from unittest.mock import MagicMock, patch
import pytest
from chain.builder import TransactionBuilder
from chain.client import ChainClient
from core.types import Address, TokenAmount
from core.wallet import WalletManager


@pytest.fixture
def mock_client():
    client = MagicMock(spec=ChainClient)
    client.get_nonce.return_value = 5
    client.estimate_gas.return_value = 21000

    mock_gas = MagicMock()
    mock_gas.get_max_fee.return_value = 30000000000
    mock_gas.priority_fee_medium = 1000000000
    client.get_gas_price.return_value = mock_gas

    return client


@pytest.fixture
def mock_wallet():
    return WalletManager.generate()


def test_builder_fluent_interface(mock_client, mock_wallet):
    """Tests that builder methods returns self"""
    builder = TransactionBuilder(mock_client, mock_wallet)
    res = builder.to(Address("0xd8da6bf26964af9d7eed9e03e53415d37aa96045"))
    assert res is builder

    res = builder.value(TokenAmount(0, 18))
    assert res is builder


def test_builder_missing_gas_config(mock_client, mock_wallet):
    """Tests that fails if gas estimate_price wasn`t called"""
    builder = TransactionBuilder(mock_client, mock_wallet)
    builder.to(Address(mock_wallet.address))

    with pytest.raises(ValueError, match="Gas limit isn`t set"):
        builder.build()


def test_builder_full_flow(mock_client, mock_wallet):
    """Test building a valid transaction request"""
    recipient = Address("0xd8da6bf26964af9d7eed9e03e53415d37aa96045")
    amount = TokenAmount.from_human("0.1", 18)

    tx = (
        TransactionBuilder(mock_client, mock_wallet)
        .to(recipient)
        .value(amount)
        .with_gas_estimate()
        .with_gas_price()
        .build()
    )

    assert tx.to.value == recipient.checksum
    assert tx.value.raw == 100000000000000000
    assert tx.nonce == 5
    assert tx.gas_limit == int(21000 * 1.2)
    assert tx.chain_id == 11155111


def test_client_retry_logic():
    """Test that client retries on failure."""
    with patch("web3.providers.rpc.HTTPProvider.make_request"):
        client = ChainClient(["http://fake.url"], max_retries=3)

        mock_w3 = MagicMock()
        client._w3 = mock_w3

        client._connect = MagicMock()

        mock_get_balance = mock_w3.eth.get_balance
        mock_get_balance.side_effect = [
            Exception("Connection error"),
            Exception("Timeout"),
            1000,
        ]

        balance = client.get_balance(
            Address("0xd8da6bf26964af9d7eed9e03e53415d37aa96045")
        )

        assert balance.raw == 1000

        assert mock_get_balance.call_count == 3

        assert client._connect.call_count == 2


def test_analyze_transaction_success(capsys):
    """Test analyzer prints correct info for a successful transaction"""
    with patch("chain.analyzer.Web3") as MockWeb3:
        #       Configure the mock Web3 instance
        mock_w3 = MockWeb3.return_value
        mock_w3.is_connected.return_value = True

        #       Mock transaction data
        mock_w3.eth.get_transaction.return_value = {
            "hash": "0x123",
            "from": "0xSender",
            "to": "0xReceiver",
            "value": 1000000000000000000,
            "gas": 21000,
            "input": b"",
        }

        #       Mock receipt data
        mock_w3.eth.get_transaction_receipt.return_value = {
            "status": 1,
            "blockNumber": 12345,
            "gasUsed": 21000,
            "effectiveGasPrice": 20000000000,
            "logs": [],
        }

        #       Mock block data
        mock_w3.eth.get_block.return_value = {
            "timestamp": 1678886400,
        }

        from chain.analyzer import analyze_transaction

        analyze_transaction("0x123", "http://mock.rpc")

        captured = capsys.readouterr()

        assert "Transaction Analysis" in captured.out
        assert "Status:         SUCCESS" in captured.out
        assert "Value:           1 ETH" in captured.out
        assert "Function: Native ETH Transfer" in captured.out
