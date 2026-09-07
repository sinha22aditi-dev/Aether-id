"""
Unit tests for Blockchain Subsystem (Deployment, Write, Read, RecordId Keying).
Uses real in-memory EVM execution via eth-tester / py-evm.
"""

import pytest

from pipeline.chain.client import BlockchainClient
from pipeline.chain.reader import BlockchainReader
from pipeline.chain.writer import BlockchainWriter


@pytest.fixture
def local_chain():
    """Initializes a real in-memory EVM chain and deploys FaceMatchRegistry."""
    client = BlockchainClient(use_local_chain=True)
    contract_addr, tx_hash = client.deploy_contract(private_key="default")
    assert contract_addr is not None
    assert contract_addr.startswith("0x")
    return client, contract_addr


def test_contract_deployment_and_properties(local_chain):
    client, contract_addr = local_chain
    contract = client.get_contract(contract_addr)
    next_id = contract.functions.nextRecordId().call()
    assert next_id == 0


def test_submit_record_and_get_record(local_chain):
    client, contract_addr = local_chain
    writer = BlockchainWriter(client=client, contract_address=contract_addr)
    reader = BlockchainReader(client=client, contract_address=contract_addr)

    test_hash = "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    test_uri = "https://example.com/post/100"

    # 1. Submit Record 0
    receipt0 = writer.submit_record(test_hash, test_uri)
    assert receipt0.record_id == 0
    assert receipt0.tx_hash.startswith("0x")
    assert receipt0.content_hash.lower() == test_hash.lower()

    # 2. Read Record 0
    rec0 = reader.get_record(0)
    assert rec0.exists is True
    assert rec0.content_hash.lower() == test_hash.lower()
    assert rec0.metadata_uri == test_uri
    assert rec0.record_id == 0
    assert rec0.timestamp > 0


def test_sequential_record_id_assignment(local_chain):
    client, contract_addr = local_chain
    writer = BlockchainWriter(client=client, contract_address=contract_addr)
    reader = BlockchainReader(client=client, contract_address=contract_addr)

    hash_a = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    hash_b = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    receipt1 = writer.submit_record(hash_a, "uri_a")
    receipt2 = writer.submit_record(hash_b, "uri_b")

    assert receipt1.record_id == 0
    assert receipt2.record_id == 1

    rec1 = reader.get_record(0)
    rec2 = reader.get_record(1)

    assert rec1.content_hash.lower() == hash_a.lower()
    assert rec2.content_hash.lower() == hash_b.lower()


def test_nonexistent_record_returns_exists_false(local_chain):
    client, contract_addr = local_chain
    reader = BlockchainReader(client=client, contract_address=contract_addr)

    # Record 999 has never been written
    rec999 = reader.get_record(999)
    assert rec999.exists is False
    assert rec999.record_id == 999


def test_diagnostics_reporting_local_chain(local_chain):
    client, contract_addr = local_chain
    diag = client.get_diagnostics()
    assert diag["rpc_connected"] is True
    assert diag["use_local_chain"] is True
    assert diag["wallet"]["configured"] is True
    assert diag["wallet"]["status"] == "OK"
    assert diag["contract"]["configured"] is True
    assert diag["contract"]["deployed"] is True
    assert diag["status"] == "HEALTHY"


def test_contract_validation_errors(local_chain):
    client, _ = local_chain
    from pipeline.chain.client import (
        ContractNotConfiguredError,
        InvalidContractAddressError,
    )

    # Missing / empty address
    with pytest.raises(ContractNotConfiguredError):
        client.validate_contract("")

    with pytest.raises(ContractNotConfiguredError):
        client.validate_contract("0x0000000000000000000000000000000000000000")

    # Invalid format address
    with pytest.raises(InvalidContractAddressError):
        client.validate_contract("not_an_eth_address")


def test_wallet_validation_errors(monkeypatch):
    from pipeline.chain.client import (
        BlockchainClient,
        InvalidWalletKeyError,
        WalletNotConfiguredError,
    )
    # Test on a remote-mode client instance without connecting
    client = BlockchainClient.__new__(BlockchainClient)
    client.use_local_chain = False
    client.chain_id = 80002

    # 1. Missing / placeholder key
    with pytest.raises(WalletNotConfiguredError):
        client.validate_wallet("your_wallet_key_here")

    with pytest.raises(WalletNotConfiguredError):
        client.validate_wallet("")

    # 2. Invalid length key
    with pytest.raises(InvalidWalletKeyError):
        client.validate_wallet("0x1234abcd")  # Too short

    with pytest.raises(InvalidWalletKeyError):
        client.validate_wallet("zzzz" * 16)   # Non-hex characters


def test_insufficient_funds_error():
    from unittest.mock import MagicMock
    from pipeline.chain.client import BlockchainClient, InsufficientFundsError

    client = BlockchainClient.__new__(BlockchainClient)
    client.use_local_chain = False
    client.chain_id = 80002
    client.check_connection_or_raise = MagicMock()
    client.get_balance = MagicMock(return_value=0.000000)

    # Valid 64-hex private key (funded with 0 POL)
    valid_key = "0x" + "1" * 64
    with pytest.raises(InsufficientFundsError):
        client.validate_wallet(valid_key, min_balance_eth=0.005)


def test_chain_id_mismatch_error():
    from unittest.mock import MagicMock
    from pipeline.chain.client import BlockchainClient, ChainIDMismatchError

    client = BlockchainClient.__new__(BlockchainClient)
    client.use_local_chain = False
    client.chain_id = 80002  # Expects Amoy
    client.rpc_url = "https://mock.rpc"
    client._w3 = MagicMock()
    client._w3.is_connected.return_value = True
    client._w3.eth.chain_id = 1  # Returns Ethereum Mainnet

    with pytest.raises(ChainIDMismatchError):
        client.check_connection_or_raise()


def test_contract_not_deployed_error():
    from unittest.mock import MagicMock
    from pipeline.chain.client import BlockchainClient, ContractNotDeployedError

    client = BlockchainClient.__new__(BlockchainClient)
    client.use_local_chain = False
    client.chain_id = 80002
    client.rpc_url = "https://mock.rpc"
    client.check_connection_or_raise = MagicMock()
    client._w3 = MagicMock()
    client._w3.eth.get_code.return_value = b""  # Empty bytecode

    dummy_addr = "0x1111111111111111111111111111111111111111"
    with pytest.raises(ContractNotDeployedError):
        client.validate_contract(dummy_addr)


