"""
Blockchain Record Reader Module.
Reads on-chain records from FaceMatchRegistry by sequential recordId.
Read-only, zero gas, does not require wallet private keys.
"""

from dataclasses import dataclass
import logging
import os
from typing import Optional

from hexbytes import HexBytes
from web3 import Web3

from .abi import CONTRACT_ABI
from .client import BlockchainClient, ChainRPCError

logger = logging.getLogger("pipeline.chain.reader")


@dataclass
class OnChainRecord:
    """Represents a record retrieved directly from FaceMatchRegistry smart contract."""
    record_id: int
    content_hash: str
    submitter: str
    timestamp: int
    metadata_uri: str
    exists: bool


class BlockchainReader:
    """
    Direct on-chain reader for FaceMatchRegistry.
    Used during independent verification to fetch original ground-truth contentHash.
    """

    def __init__(
        self,
        client: Optional[BlockchainClient] = None,
        contract_address: Optional[str] = None,
    ):
        self.client = client or BlockchainClient()
        self.contract_address = contract_address or self.client.contract_address

    def get_record(self, record_id: int) -> OnChainRecord:
        """
        Calls getRecord(uint256 recordId) on-chain.
        Raises ChainRPCError if blockchain RPC is unreachable or contract error occurs.
        """
        self.client.check_connection_or_raise()
        checksum_contract_addr = self.client.validate_contract(self.contract_address)
        contract = self.client.w3.eth.contract(address=checksum_contract_addr, abi=CONTRACT_ABI)

        try:
            logger.info(
                f"[Blockchain Reader] Querying getRecord({record_id}) on contract {checksum_contract_addr}..."
            )
            # Contract returns: (bytes32 contentHash, address submitter, uint256 timestamp, string metadataURI, bool exists)
            raw_hash, submitter, timestamp, metadata_uri, exists = contract.functions.getRecord(
                int(record_id)
            ).call()

            # Normalize raw_hash bytes to 0x-prefixed hex string
            if isinstance(raw_hash, (bytes, bytearray)):
                content_hash_hex = f"0x{raw_hash.hex()}"
            else:
                content_hash_hex = str(raw_hash)

            record = OnChainRecord(
                record_id=int(record_id),
                content_hash=content_hash_hex,
                submitter=str(submitter),
                timestamp=int(timestamp),
                metadata_uri=str(metadata_uri),
                exists=bool(exists),
            )

            logger.info(
                f"[Blockchain Reader] Result for record #{record_id}: exists={record.exists}, hash={record.content_hash[:12]}..."
            )
            return record

        except ChainRPCError:
            raise
        except Exception as e:
            # Check if this was a network / connection error
            if not self.client.is_connected():
                raise ChainRPCError(f"Blockchain RPC unreachable while reading record #{record_id}: {e}")
            raise RuntimeError(f"Error reading record #{record_id} from contract: {e}")
