"""
Blockchain Record Writer Module.
Submits cryptographic content fingerprints to FaceMatchRegistry on-chain
and parses the newly created sequential recordId.
"""

from dataclasses import dataclass
import logging
import os
from typing import Optional, Tuple

from eth_account import Account
from hexbytes import HexBytes
from web3 import Web3

from .abi import CONTRACT_ABI
from .client import BlockchainClient, ChainRPCError, InsufficientFundsError

logger = logging.getLogger("pipeline.chain.writer")


@dataclass
class WriteReceipt:
    """Detailed result of an on-chain record submission."""
    record_id: int
    tx_hash: str
    block_number: int
    submitter: str
    content_hash: str
    metadata_uri: str
    explorer_url: str
    gas_used: int


class BlockchainWriter:
    """
    Handles transaction building, gas pricing, signing, and submission
    to FaceMatchRegistry.submitRecord(bytes32, string).
    """

    def __init__(
        self,
        client: Optional[BlockchainClient] = None,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None,
    ):
        self.client = client or BlockchainClient()
        self.private_key = private_key or os.getenv("WALLET_PRIVATE_KEY")
        self.contract_address = contract_address or self.client.contract_address

    def _get_explorer_url(self, tx_hash: str) -> str:
        """Returns explorer link for transaction hash."""
        if self.client.chain_id == 80002:
            return f"https://amoy.polygonscan.com/tx/{tx_hash}"
        elif self.client.chain_id == 137:
            return f"https://polygonscan.com/tx/{tx_hash}"
        return f"https://etherscan.io/tx/{tx_hash}"

    def submit_record(
        self,
        content_hash: str,
        metadata_uri: str = "",
    ) -> WriteReceipt:
        """
        Submits content hash and metadata URI to FaceMatchRegistry on-chain.
        Returns WriteReceipt containing recordId and tx_hash.
        """
        self.client.check_connection_or_raise()
        checksum_contract_addr = self.client.validate_contract(self.contract_address)
        contract = self.client.w3.eth.contract(address=checksum_contract_addr, abi=CONTRACT_ABI)

        # Normalize content hash to bytes32 format (0x prefixed 64 hex chars)
        if not content_hash.startswith("0x"):
            content_hash_hex = f"0x{content_hash}"
        else:
            content_hash_hex = content_hash

        # Convert to HexBytes / bytes32
        content_hash_bytes = HexBytes(content_hash_hex)
        if len(content_hash_bytes) != 32:
            raise ValueError(f"Content hash must be 32 bytes (64 hex characters), got {len(content_hash_bytes)} bytes.")

        logger.info(
            f"Submitting record to contract at {checksum_contract_addr} (hash={content_hash_hex[:12]}...)..."
        )

        # 1. Local Chain execution path (no private key needed if using default account)
        if self.client.use_local_chain:
            sender = self.client.w3.eth.accounts[0]
            tx_hash_bytes = contract.functions.submitRecord(
                content_hash_bytes,
                metadata_uri,
            ).transact({"from": sender})
            receipt = self.client.w3.eth.wait_for_transaction_receipt(tx_hash_bytes)
            tx_hash_str = tx_hash_bytes.hex()
            submitter_addr = sender

        # 2. Public / Dedicated RPC Private Key transaction path
        else:
            # Validate wallet and ensure sufficient POL for gas
            submitter_addr, balance = self.client.validate_wallet(self.private_key, min_balance_eth=0.0001)

            pk = (self.private_key or os.getenv("WALLET_PRIVATE_KEY", "")).strip()
            if pk.startswith("0x"):
                pk = pk[2:]

            nonce = self.client.w3.eth.get_transaction_count(submitter_addr)
            gas_price = int(self.client.w3.eth.gas_price * 1.25)  # 25% buffer for Amoy

            tx_data = contract.functions.submitRecord(
                content_hash_bytes,
                metadata_uri,
            ).build_transaction({
                "from": submitter_addr,
                "nonce": nonce,
                "gasPrice": gas_price,
                "chainId": self.client.chain_id,
            })

            try:
                gas_est = self.client.w3.eth.estimate_gas(tx_data)
                tx_data["gas"] = int(gas_est * 1.25)
            except Exception as e:
                logger.warning(f"Gas estimation failed ({e}), using safe fallback 250000 gas.")
                tx_data["gas"] = 250000

            signed = self.client.w3.eth.account.sign_transaction(tx_data, private_key=pk)
            try:
                tx_hash = self.client.w3.eth.send_raw_transaction(signed.raw_transaction)
            except Exception as e:
                err_msg = str(e)
                if "insufficient funds" in err_msg.lower():
                    raise InsufficientFundsError(
                        f"Wallet '{submitter_addr}' has insufficient POL balance for live Polygon gas fees. "
                        f"Please fund wallet from faucet or set USE_LOCAL_CHAIN=true for offline testing. ({e})"
                    )
                raise
            tx_hash_str = tx_hash.hex()
            logger.info(f"Transaction broadcast: {tx_hash_str}. Waiting for receipt...")

            receipt = self.client.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

        if not tx_hash_str.startswith("0x"):
            tx_hash_str = f"0x{tx_hash_str}"

        if receipt["status"] != 1:
            raise RuntimeError(f"Transaction failed on-chain with status 0 (tx: {tx_hash_str}).")

        # Parse RecordSubmitted event to extract assigned recordId
        logs = contract.events.RecordSubmitted().process_receipt(receipt)
        if logs:
            record_id = int(logs[0]["args"]["recordId"])
        else:
            # Fallback: nextRecordId - 1
            next_id = contract.functions.nextRecordId().call()
            record_id = int(next_id) - 1

        explorer_url = self._get_explorer_url(tx_hash_str)
        logger.info(
            f"==> Record #{record_id} successfully created on-chain! Tx: {tx_hash_str}"
        )

        return WriteReceipt(
            record_id=record_id,
            tx_hash=tx_hash_str,
            block_number=receipt["blockNumber"],
            submitter=submitter_addr,
            content_hash=content_hash_hex,
            metadata_uri=metadata_uri,
            explorer_url=explorer_url,
            gas_used=receipt["gasUsed"],
        )
