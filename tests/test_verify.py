"""
Comprehensive Unit & Regression Tests for Independent Verification (PRD Section 17 & 22).
Covers all 6 defined verification states:
1. VERIFIED
2. TAMPER DETECTED
3. RECORD_NOT_FOUND
4. INSUFFICIENT_DATA
5. SOURCE_UNAVAILABLE
6. CHAIN_RPC_ERROR
"""

from unittest.mock import MagicMock
import pytest

from pipeline.canon.canonicalize import Canonicalizer, ImmutableVerifiableData
from pipeline.chain.client import BlockchainClient, ChainRPCError
from pipeline.chain.reader import BlockchainReader, OnChainRecord
from pipeline.chain.writer import BlockchainWriter
from pipeline.storage.cache import MetadataCache
from pipeline.verifier import RecordVerifier


@pytest.fixture
def deployed_env():
    """Initializes local EVM and deploys contract."""
    client = BlockchainClient(use_local_chain=True)
    contract_addr, _ = client.deploy_contract(private_key="default")
    writer = BlockchainWriter(client=client, contract_address=contract_addr)
    reader = BlockchainReader(client=client, contract_address=contract_addr)
    cache = MetadataCache(db_path=":memory:")
    return client, contract_addr, writer, reader, cache


def test_outcome_1_verified(deployed_env):
    """Outcome 1: Valid recordId + unmodified data -> VERIFIED."""
    client, contract_addr, writer, reader, cache = deployed_env
    verifier = RecordVerifier(reader=reader, cache=cache, check_live_source=False)

    data = ImmutableVerifiableData(
        normalized_source_url="https://example.com/authentic",
        platform="twitter",
        public_post_id="post_1",
        post_text_normalized="Authentic post text",
        image_sha256="1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        schema_version="1.0",
    )
    content_hash, _ = Canonicalizer.create_fingerprint(data)

    receipt = writer.submit_record(content_hash, "https://example.com/authentic")
    record_id = receipt.record_id

    # Cache original
    cache.save_record(record_id, receipt.tx_hash, content_hash, data.to_dict(), {})

    res = verifier.verify(record_id, data.to_dict())
    assert res.status == "VERIFIED"
    assert res.is_hash_match is True
    assert res.record_id == record_id


def test_outcome_2_tamper_detected(deployed_env):
    """Outcome 2: Valid recordId + altered field -> TAMPER DETECTED."""
    client, contract_addr, writer, reader, cache = deployed_env
    verifier = RecordVerifier(reader=reader, cache=cache, check_live_source=False)

    original_data = ImmutableVerifiableData(
        normalized_source_url="https://example.com/authentic",
        platform="twitter",
        public_post_id="post_1",
        post_text_normalized="Authentic post text",
        image_sha256="1111111111111111111111111111111111111111111111111111111111111111",
        schema_version="1.0",
    )
    content_hash, _ = Canonicalizer.create_fingerprint(original_data)

    receipt = writer.submit_record(content_hash, "https://example.com/authentic")
    record_id = receipt.record_id

    cache.save_record(record_id, receipt.tx_hash, content_hash, original_data.to_dict(), {})

    # Create tampered copy (changed post text)
    tampered_data = original_data.to_dict()
    tampered_data["post_text_normalized"] = "TAMPERED FAKE TEXT"

    res = verifier.verify(record_id, tampered_data)
    assert res.status == "TAMPER DETECTED"
    assert res.is_hash_match is False
    assert len(res.field_diffs) > 0
    assert res.field_diffs[0].field_name == "post_text_normalized"


def test_outcome_3_record_not_found(deployed_env):
    """
    Outcome 3: Fabricated/unused recordId -> RECORD_NOT_FOUND.
    CRITICAL: Must NOT return TAMPER DETECTED (PRD Correction 2).
    """
    client, contract_addr, writer, reader, cache = deployed_env
    verifier = RecordVerifier(reader=reader, cache=cache, check_live_source=False)

    data = {
        "image_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
        "normalized_source_url": "https://example.com/random",
        "platform": "generic_web",
        "post_text_normalized": "Any text",
        "public_post_id": None,
        "schema_version": "1.0",
    }

    # Record 999 was never submitted
    res = verifier.verify(999, data)
    assert res.status == "RECORD_NOT_FOUND"
    assert res.status != "TAMPER DETECTED"
    assert res.on_chain_record is not None
    assert res.on_chain_record.exists is False


def test_outcome_4_insufficient_data(deployed_env):
    """Outcome 4: Missing mandatory schema fields -> INSUFFICIENT_DATA."""
    client, contract_addr, writer, reader, cache = deployed_env
    verifier = RecordVerifier(reader=reader, cache=cache, check_live_source=False)

    invalid_data = {
        "platform": "twitter",
        # Missing normalized_source_url and image_sha256
    }

    res = verifier.verify(0, invalid_data)
    assert res.status == "INSUFFICIENT_DATA"


def test_outcome_5_source_unavailable(deployed_env):
    """Outcome 5: Hash integrity verified, but live source URL unreachable -> SOURCE_UNAVAILABLE."""
    client, contract_addr, writer, reader, cache = deployed_env
    # Enable live check but mock _check_source_url to False
    verifier = RecordVerifier(reader=reader, cache=cache, check_live_source=True)
    verifier._check_source_url = MagicMock(return_value=False)

    data = ImmutableVerifiableData(
        normalized_source_url="https://offline-server.fake/post/404",
        platform="twitter",
        public_post_id="404",
        post_text_normalized="Offline post",
        image_sha256="9999999999999999999999999999999999999999999999999999999999999999",
        schema_version="1.0",
    )
    content_hash, _ = Canonicalizer.create_fingerprint(data)

    receipt = writer.submit_record(content_hash, "https://offline-server.fake/post/404")
    record_id = receipt.record_id

    res = verifier.verify(record_id, data.to_dict())
    assert res.status == "SOURCE_UNAVAILABLE"
    assert res.is_hash_match is True
    assert res.source_url_reachable is False


def test_outcome_6_chain_rpc_error(deployed_env):
    """
    Outcome 6: Blockchain RPC unreachable -> CHAIN_RPC_ERROR.
    CRITICAL: Must NOT silently fall back to local SQLite cache (PRD Correction 4).
    """
    client, contract_addr, writer, reader, cache = deployed_env
    # Mock reader to raise ChainRPCError
    mock_reader = MagicMock()
    mock_reader.get_record.side_effect = ChainRPCError("Connection refused by RPC")

    verifier = RecordVerifier(reader=mock_reader, cache=cache, check_live_source=False)

    data = {
        "image_sha256": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        "normalized_source_url": "https://example.com/test",
        "platform": "twitter",
        "post_text_normalized": "Post text",
        "public_post_id": "1",
        "schema_version": "1.0",
    }

    res = verifier.verify(0, data)
    assert res.status == "CHAIN_RPC_ERROR"
    assert "unreachable" in res.message.lower()
