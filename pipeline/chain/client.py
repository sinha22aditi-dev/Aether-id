"""
Web3 Blockchain Client Manager.
Handles connections to Polygon Amoy Testnet, Local EVM (eth-tester), or custom dedicated RPCs (Alchemy/Infura).
Provides comprehensive diagnostic health checks and granular error categorization.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from eth_account import Account
from web3 import Web3
from web3.exceptions import Web3Exception
from web3.middleware import ExtraDataToPOAMiddleware

from .abi import CONTRACT_ABI, CONTRACT_BYTECODE

logger = logging.getLogger("pipeline.chain.client")


# ==============================================================================
# Granular Blockchain Exceptions (PRD & Production Robustness)
# ==============================================================================

class BlockchainError(Exception):
    """Base exception for all blockchain subsystem errors."""
    pass


class ChainRPCError(BlockchainError):
    """Base exception for blockchain RPC communication failures."""
    pass


class ChainRPCUnreachableError(ChainRPCError):
    """Raised when the configured RPC endpoint is unreachable, timed out, or DNS failed."""
    pass


class ChainIDMismatchError(ChainRPCError):
    """Raised when the connected RPC chain ID does not match the expected network chain ID."""
    pass


class WalletError(BlockchainError, ValueError):
    """Base exception for wallet configuration and signing errors."""
    pass


class WalletNotConfiguredError(WalletError):
    """Raised when WALLET_PRIVATE_KEY is missing or contains a placeholder."""
    pass


class InvalidWalletKeyError(WalletError):
    """Raised when WALLET_PRIVATE_KEY is malformed (not 32 bytes / 64 hex characters)."""
    pass


class InsufficientFundsError(BlockchainError, RuntimeError):
    """Raised when the wallet balance is insufficient to pay for transaction gas."""
    pass


class ContractError(BlockchainError, ValueError):
    """Base exception for smart contract validation errors."""
    pass


class ContractNotConfiguredError(ContractError):
    """Raised when CONTRACT_ADDRESS is missing or zero address."""
    pass


class InvalidContractAddressError(ContractError):
    """Raised when CONTRACT_ADDRESS is not a valid 20-byte Ethereum checksum address."""
    pass


class ContractNotDeployedError(ContractError, RuntimeError):
    """Raised when CONTRACT_ADDRESS has no deployed bytecode on the target chain."""
    pass


# Default verified public RPC endpoints for Polygon Amoy (Chain ID: 80002)
AMOY_FALLBACK_RPCS = [
    "https://polygon-amoy.drpc.org",
    "https://polygon-amoy-bor-rpc.publicnode.com",
    "https://rpc.ankr.com/polygon_amoy",
]


# Module-level singletons for Local EVM Test Chain (eth-tester)
_LOCAL_WEB3_SINGLETON: Optional[Web3] = None
_LOCAL_CONTRACT_ADDRESS: Optional[str] = None


class BlockchainClient:
    """
    Manages Web3 provider connection, account funding status, contract initialization,
    and runtime diagnostic verification for Polygon Amoy / Local EVM.
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        chain_id: Optional[int] = None,
        contract_address: Optional[str] = None,
        use_local_chain: bool = False,
        allow_rpc_fallback: bool = True,
    ):
        self.use_local_chain = use_local_chain or os.getenv("USE_LOCAL_CHAIN", "false").lower() == "true"
        self.configured_rpc_url = rpc_url or os.getenv("BLOCKCHAIN_RPC_URL", "https://polygon-amoy.drpc.org")
        self.rpc_url = self.configured_rpc_url
        self.chain_id = chain_id or int(os.getenv("CHAIN_ID", "80002"))
        self.allow_rpc_fallback = allow_rpc_fallback
        self._w3: Optional[Web3] = None

        if self.use_local_chain:
            local_override = contract_address or os.getenv("LOCAL_CONTRACT_ADDRESS")
            global _LOCAL_CONTRACT_ADDRESS
            self.contract_address = local_override or _LOCAL_CONTRACT_ADDRESS
        else:
            self.contract_address = contract_address or os.getenv("CONTRACT_ADDRESS")

        self._init_web3()

    def _deploy_local_contract(self) -> Tuple[str, str]:
        """Auto-deploys FaceMatchRegistry onto the local EVM chain."""
        deployer_account = self.w3.eth.accounts[0]
        factory = self.w3.eth.contract(abi=CONTRACT_ABI, bytecode=CONTRACT_BYTECODE)
        tx_hash = factory.constructor().transact({"from": deployer_account})
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        contract_address = receipt.contractAddress
        logger.info(f"FaceMatchRegistry auto-deployed to Local EVM at: {contract_address}")
        return contract_address, tx_hash.hex()

    def _init_web3(self):
        """Initializes Web3 with HTTPProvider or Local EthereumTesterProvider."""
        if self.use_local_chain:
            global _LOCAL_WEB3_SINGLETON, _LOCAL_CONTRACT_ADDRESS
            if _LOCAL_WEB3_SINGLETON is None or not _LOCAL_WEB3_SINGLETON.is_connected():
                logger.info("Initializing Shared Local EVM Test Chain (eth-tester)...")
                try:
                    from eth_tester import EthereumTester, PyEVMBackend
                    from web3.providers.eth_tester import EthereumTesterProvider

                    eth_tester = EthereumTester(backend=PyEVMBackend())
                    _LOCAL_WEB3_SINGLETON = Web3(EthereumTesterProvider(eth_tester))
                    logger.info(f"Shared Local EVM Initialized. Default accounts: {len(_LOCAL_WEB3_SINGLETON.eth.accounts)}")
                except Exception as e:
                    logger.error(f"Failed to initialize local eth-tester: {e}")
                    raise RuntimeError(f"USE_LOCAL_CHAIN=true requested but eth-tester failed: {e}")

            self._w3 = _LOCAL_WEB3_SINGLETON
            self.chain_id = self._w3.eth.chain_id
            self.rpc_url = "in-process eth-tester (Local EVM)"

            # Auto-deploy contract if not already deployed on this local EVM
            if not self.contract_address or not self._has_local_bytecode(self.contract_address):
                if _LOCAL_CONTRACT_ADDRESS and self._has_local_bytecode(_LOCAL_CONTRACT_ADDRESS):
                    self.contract_address = _LOCAL_CONTRACT_ADDRESS
                else:
                    addr, _ = self._deploy_local_contract()
                    _LOCAL_CONTRACT_ADDRESS = addr
                    self.contract_address = addr
            return

        # Remote / Public / Dedicated RPC path
        urls_to_try = [self.configured_rpc_url]
        if self.allow_rpc_fallback and self.chain_id == 80002:
            for fallback in AMOY_FALLBACK_RPCS:
                if fallback not in urls_to_try:
                    urls_to_try.append(fallback)

        connected = False
        last_error = None

        for url in urls_to_try:
            logger.info(f"Connecting to Blockchain RPC: {url}...")
            try:
                provider = Web3.HTTPProvider(url, request_kwargs={"timeout": 10.0})
                test_w3 = Web3(provider)
                # Inject POA middleware for Polygon networks
                try:
                    test_w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
                except Exception:
                    pass

                if test_w3.is_connected():
                    self._w3 = test_w3
                    self.rpc_url = url
                    connected = True
                    if url != self.configured_rpc_url:
                        logger.warning(
                            f"Primary RPC '{self.configured_rpc_url}' was unreachable. "
                            f"Successfully connected via fallback RPC '{url}'."
                        )
                    else:
                        logger.info(f"Successfully connected to RPC '{url}'.")
                    break
                else:
                    logger.warning(f"RPC endpoint '{url}' did not respond to is_connected ping.")
            except Exception as e:
                last_error = e
                logger.warning(f"Failed connecting to RPC '{url}': {e}")

        if not connected:
            self._w3 = Web3(Web3.HTTPProvider(self.configured_rpc_url, request_kwargs={"timeout": 10.0}))
            try:
                self._w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            except Exception:
                pass
            logger.error(
                f"Unable to connect to any blockchain RPC. Configured URL: {self.configured_rpc_url}. "
                f"Last error: {last_error}"
            )

    def _has_local_bytecode(self, address: Optional[str]) -> bool:
        """Helper to check if address has bytecode on active Web3 instance."""
        if not address or not Web3.is_address(address):
            return False
        try:
            checksum_addr = Web3.to_checksum_address(address)
            code = self.w3.eth.get_code(checksum_addr)
            return bool(code and code != b"" and code.hex() not in ("", "0x"))
        except Exception:
            return False

    @property
    def w3(self) -> Web3:
        if self._w3 is None:
            self._init_web3()
        return self._w3

    def is_connected(self) -> bool:
        """Checks if RPC endpoint is responding."""
        try:
            return bool(self.w3 and self.w3.is_connected())
        except Exception:
            return False

    def check_connection_or_raise(self):
        """Verifies active connection and chain ID match or raises specific ChainRPCError."""
        if self.use_local_chain:
            return

        if not self.is_connected():
            raise ChainRPCUnreachableError(
                f"Unable to connect to blockchain RPC at '{self.rpc_url}'. "
                "Verify your internet connection or configure a dedicated authenticated RPC in "
                "BLOCKCHAIN_RPC_URL (e.g., Alchemy https://polygon-amoy.g.alchemy.com/v2/KEY "
                "or Infura https://polygon-amoy.infura.io/v3/KEY)."
            )

        try:
            actual_chain_id = self.w3.eth.chain_id
            if self.chain_id and actual_chain_id != self.chain_id:
                raise ChainIDMismatchError(
                    f"Chain ID mismatch: Connected RPC '{self.rpc_url}' returned Chain ID {actual_chain_id}, "
                    f"but expected {self.chain_id}. Check BLOCKCHAIN_RPC_URL and CHAIN_ID in .env."
                )
        except ChainIDMismatchError:
            raise
        except Exception as e:
            raise ChainRPCUnreachableError(f"RPC endpoint '{self.rpc_url}' failed chain ID query: {e}")

    def get_block_number(self) -> int:
        self.check_connection_or_raise()
        return self.w3.eth.block_number

    def get_balance(self, address: str) -> float:
        """Returns balance in POL / ETH."""
        self.check_connection_or_raise()
        checksum_addr = Web3.to_checksum_address(address)
        wei = self.w3.eth.get_balance(checksum_addr)
        return float(self.w3.from_wei(wei, "ether"))

    def validate_contract(self, address: Optional[str] = None) -> str:
        """
        Validates contract address format and verifies deployed bytecode on-chain.
        Returns checksummed address or raises specific ContractError.
        """
        target_addr = self.contract_address if address is None else address
        if not target_addr or target_addr.strip() in ("", "0x0000000000000000000000000000000000000000"):
            if address is None and self.use_local_chain:
                global _LOCAL_CONTRACT_ADDRESS
                checksum_addr, _ = self._deploy_local_contract()
                _LOCAL_CONTRACT_ADDRESS = checksum_addr
                self.contract_address = checksum_addr
                return checksum_addr
            else:
                raise ContractNotConfiguredError(
                    "CONTRACT_ADDRESS is not configured in .env. "
                    "Deploy the FaceMatchRegistry smart contract using 'python scripts/deploy_contract.py' "
                    "and paste the resulting address into CONTRACT_ADDRESS."
                )

        target_addr = target_addr.strip()
        if not Web3.is_address(target_addr):
            raise InvalidContractAddressError(
                f"'{target_addr}' is not a valid 20-byte Ethereum contract address."
            )

        checksum_addr = Web3.to_checksum_address(target_addr)

        code = self.w3.eth.get_code(checksum_addr)
        if not code or code == b"" or code.hex() in ("", "0x"):
            if self.use_local_chain and address is None:
                logger.warning(
                    f"No deployed bytecode found at '{checksum_addr}' on Local EVM. "
                    "Auto-deploying FaceMatchRegistry to local EVM..."
                )
                checksum_addr, _ = self._deploy_local_contract()
                _LOCAL_CONTRACT_ADDRESS = checksum_addr
                self.contract_address = checksum_addr
            else:
                if not self.use_local_chain:
                    self.check_connection_or_raise()
                raise ContractNotDeployedError(
                    f"No deployed bytecode found at contract address '{checksum_addr}' on chain {self.chain_id}. "
                    "Make sure the contract is deployed on Polygon Amoy using 'python scripts/deploy_contract.py'."
                )

        return checksum_addr

    def validate_wallet(
        self,
        private_key: Optional[str] = None,
        min_balance_eth: float = 0.0005,
    ) -> Tuple[str, float]:
        """
        Validates wallet private key format and checks balance on-chain.
        Returns (wallet_address, balance_pol) or raises specific WalletError / InsufficientFundsError.
        """
        if self.use_local_chain:
            addr = self.w3.eth.accounts[0]
            balance = self.get_balance(addr)
            return addr, balance

        pk = private_key or os.getenv("WALLET_PRIVATE_KEY")
        if not pk or pk.strip() == "" or pk.strip().startswith("your_"):
            raise WalletNotConfiguredError(
                "WALLET_PRIVATE_KEY is not set or contains a placeholder in .env. "
                "Provide a funded Polygon Amoy private key or set USE_LOCAL_CHAIN=true for offline testing."
            )

        pk = pk.strip()
        if pk.startswith("0x"):
            pk = pk[2:]

        if len(pk) != 64:
            raise InvalidWalletKeyError(
                f"WALLET_PRIVATE_KEY is invalid: expected 64 hex characters (32 bytes), got {len(pk)} chars."
            )

        try:
            account = Account.from_key(pk)
        except Exception as e:
            raise InvalidWalletKeyError(f"Failed to parse WALLET_PRIVATE_KEY: {e}")

        wallet_addr = account.address
        self.check_connection_or_raise()
        balance = self.get_balance(wallet_addr)

        if min_balance_eth > 0 and balance < min_balance_eth:
            raise InsufficientFundsError(
                f"Wallet '{wallet_addr}' has {balance:.6f} POL, which is insufficient for gas "
                f"(minimum required: {min_balance_eth:.6f} POL). "
                "Fund your wallet with testnet POL from https://faucet.polygon.technology/ "
                "or the Alchemy Polygon Amoy faucet (https://www.alchemy.com/faucets/polygon-amoy)."
            )

        return wallet_addr, balance

    def get_contract(self, address: Optional[str] = None):
        """Returns Contract instance for FaceMatchRegistry after validation."""
        checksum_addr = self.validate_contract(address)
        return self.w3.eth.contract(address=checksum_addr, abi=CONTRACT_ABI)

    def get_diagnostics(self) -> Dict[str, Any]:
        """
        Performs end-to-end startup diagnostics across RPC, Chain ID, Wallet, and Contract.
        Returns detailed telemetry report.
        """
        diag: Dict[str, Any] = {
            "timestamp": time.time(),
            "mode": "LOCAL_EVM" if self.use_local_chain else "POLYGON_AMOY",
            "use_local_chain": self.use_local_chain,
            "configured_rpc_url": self.configured_rpc_url,
            "active_rpc_url": self.rpc_url,
            "expected_chain_id": self.chain_id,
            "rpc_connected": False,
            "rpc_latency_ms": None,
            "actual_chain_id": None,
            "chain_id_match": False,
            "block_number": None,
            "gas_price_gwei": None,
            "wallet": {
                "configured": False,
                "address": None,
                "balance_pol": None,
                "status": "NOT_CHECKED",
                "message": "",
            },
            "contract": {
                "configured": False,
                "address": self.contract_address,
                "deployed": False,
                "bytecode_length": 0,
                "status": "NOT_CHECKED",
                "message": "",
            },
            "status": "ERROR",
            "summary": "",
            "errors": [],
            "warnings": [],
        }

        # 1. Test RPC Connection & Latency
        t0 = time.time()
        connected = self.is_connected()
        diag["rpc_latency_ms"] = int((time.time() - t0) * 1000)
        diag["rpc_connected"] = connected

        if not connected:
            msg = f"RPC endpoint '{self.rpc_url}' is unreachable."
            diag["errors"].append(msg)
            diag["summary"] = f"RPC Connection Failed ({self.rpc_url})"
            return diag

        # 2. Test Chain ID
        try:
            actual_cid = self.w3.eth.chain_id
            diag["actual_chain_id"] = actual_cid
            diag["chain_id_match"] = (actual_cid == self.chain_id)
            if not diag["chain_id_match"] and not self.use_local_chain:
                diag["errors"].append(
                    f"Chain ID mismatch: Expected {self.chain_id}, got {actual_cid} from RPC."
                )
        except Exception as e:
            diag["errors"].append(f"Failed to query chain ID: {e}")

        # 3. Test Block Number & Gas Price
        try:
            diag["block_number"] = self.w3.eth.block_number
            gas_wei = self.w3.eth.gas_price
            diag["gas_price_gwei"] = round(float(self.w3.from_wei(gas_wei, "gwei")), 2)
        except Exception as e:
            diag["warnings"].append(f"Could not fetch block/gas price: {e}")

        # 4. Test Wallet Status
        try:
            wallet_addr, balance = self.validate_wallet(min_balance_eth=0.0)
            diag["wallet"]["configured"] = True
            diag["wallet"]["address"] = wallet_addr
            diag["wallet"]["balance_pol"] = balance
            if balance < 0.0005 and not self.use_local_chain:
                diag["wallet"]["status"] = "INSUFFICIENT_FUNDS"
                diag["wallet"]["message"] = f"Balance is {balance:.6f} POL (low gas warning)."
                diag["warnings"].append(diag["wallet"]["message"])
            else:
                diag["wallet"]["status"] = "OK"
                diag["wallet"]["message"] = f"Funded with {balance:.4f} POL."
        except WalletNotConfiguredError as e:
            diag["wallet"]["status"] = "NOT_CONFIGURED"
            diag["wallet"]["message"] = str(e)
            diag["warnings"].append("WALLET_PRIVATE_KEY is not configured.")
        except Exception as e:
            diag["wallet"]["status"] = "ERROR"
            diag["wallet"]["message"] = str(e)
            diag["errors"].append(f"Wallet validation failed: {e}")

        # 5. Test Contract Status
        try:
            checksum_addr = self.validate_contract()
            diag["contract"]["configured"] = True
            diag["contract"]["address"] = checksum_addr
            code = self.w3.eth.get_code(checksum_addr)
            diag["contract"]["bytecode_length"] = len(code)
            diag["contract"]["deployed"] = len(code) > 0
            diag["contract"]["status"] = "OK"
            diag["contract"]["message"] = f"Deployed bytecode verified at {checksum_addr}."
        except ContractNotConfiguredError as e:
            diag["contract"]["status"] = "NOT_CONFIGURED"
            diag["contract"]["message"] = str(e)
            diag["warnings"].append("CONTRACT_ADDRESS is not configured.")
        except Exception as e:
            diag["contract"]["status"] = "ERROR"
            diag["contract"]["message"] = str(e)
            diag["errors"].append(f"Contract validation failed: {e}")

        # Overall Status Summary
        if diag["errors"]:
            diag["status"] = "ERROR"
            diag["summary"] = f"Blockchain Errors: {'; '.join(diag['errors'])}"
        elif diag["warnings"]:
            diag["status"] = "DEGRADED"
            diag["summary"] = f"Blockchain Connected with Warnings: {'; '.join(diag['warnings'])}"
        else:
            diag["status"] = "HEALTHY"
            diag["summary"] = f"Blockchain Healthy (Chain {diag['actual_chain_id']}, Block #{diag['block_number']})"

        return diag

    def deploy_contract(self, private_key: Optional[str] = None) -> Tuple[str, str]:
        """
        Deploys FaceMatchRegistry contract to the active chain.
        Returns (contract_address, tx_hash).
        """
        self.check_connection_or_raise()

        if self.use_local_chain and (not private_key or private_key == "default"):
            deployer_account = self.w3.eth.accounts[0]
            logger.info(f"Deploying with local pre-funded account: {deployer_account}")

            factory = self.w3.eth.contract(abi=CONTRACT_ABI, bytecode=CONTRACT_BYTECODE)
            tx_hash = factory.constructor().transact({"from": deployer_account})
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            contract_address = receipt.contractAddress
            self.contract_address = contract_address
            logger.info(f"Contract deployed locally at: {contract_address}")
            return contract_address, tx_hash.hex()

        # Remote chain deployment with private key validation
        deployer_addr, balance = self.validate_wallet(private_key, min_balance_eth=0.005)
        pk = (private_key or os.getenv("WALLET_PRIVATE_KEY", "")).strip()
        if pk.startswith("0x"):
            pk = pk[2:]

        logger.info(f"Deploying from wallet {deployer_addr} (balance: {balance:.4f} POL)...")

        factory = self.w3.eth.contract(abi=CONTRACT_ABI, bytecode=CONTRACT_BYTECODE)
        nonce = self.w3.eth.get_transaction_count(deployer_addr)
        gas_price = int(self.w3.eth.gas_price * 1.25)  # 25% gas buffer

        construct_txn = factory.constructor().build_transaction({
            "from": deployer_addr,
            "nonce": nonce,
            "gasPrice": gas_price,
            "chainId": self.chain_id,
        })

        try:
            gas_est = self.w3.eth.estimate_gas(construct_txn)
            construct_txn["gas"] = int(gas_est * 1.25)
        except Exception:
            construct_txn["gas"] = 1500000

        signed = self.w3.eth.account.sign_transaction(construct_txn, private_key=pk)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        logger.info(f"Deployment tx broadcast: {tx_hash.hex()}. Waiting for confirmation...")

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt["status"] != 1:
            raise RuntimeError(f"Contract deployment transaction reverted on-chain (tx: {tx_hash.hex()}).")

        contract_address = receipt.contractAddress
        self.contract_address = contract_address

        logger.info(f"==> Contract successfully deployed at: {contract_address}")
        return contract_address, tx_hash.hex()

