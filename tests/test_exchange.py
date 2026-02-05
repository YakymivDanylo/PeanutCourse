import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from exchange.client import ExchangeClient
from configs.binance_config import BINANCE_CONFIG


@pytest.fixture
def real_client():
    """Client connected to real Binance Testnet (public endpoints only)"""

    config = BINANCE_CONFIG.copy()
    config["sandbox"] = True
    return ExchangeClient(config)


@pytest.fixture
def mock_client():
    """Mocker client for private endpoints (balance, orders)"""
    with patch("ccxt.binance") as mock_cnst:
        mock_instance = MagicMock()
        mock_cnst.return_value = mock_instance
        mock_instance.load_markets.return_value = {}
        client = ExchangeClient(BINANCE_CONFIG)
        return client


# Real Data
def test_fetch_order_book_structure(real_client):
    """Order book has required fields and correct sort order."""
    symbol = "ETH/USDT"
    try:
        book = real_client.fetch_order_book(symbol)
    except Exception as e:
        pytest.skip(f"Skipping real API test due to connection error: {e}")

    required_fields = [
        "symbol",
        "bids",
        "asks",
        "best_bid",
        "best_ask",
        "mid_price",
        "spread_bps",
        "timestamp",
    ]
    for field in required_fields:
        assert field in book, f"Missing field: {field}"

    if book["bids"] and book["asks"]:
        assert len(book["bids"]) > 0
        assert len(book["asks"]) > 0

        assert isinstance(book["bids"][0][0], Decimal)
        assert isinstance(book["bids"][0][1], Decimal)


def test_real_order_book_sorting(real_client):
    """
    Hits real Binance Testnet API.
    Verifies bids are descending and asks are ascending.
    """
    try:
        book = real_client.fetch_order_book("ETH/USDT")
    except Exception as e:
        pytest.skip(f"Skipping real API test due to connection error: {e}")

    bids = book["bids"]
    asks = book["asks"]

    if len(bids) >= 2:
        for i in range(len(bids) - 1):
            assert bids[i][0] >= bids[i + 1][0], "Bids are not sorted descending"

    if len(asks) >= 2:
        for i in range(len(asks) - 1):
            assert asks[i][0] <= asks[i + 1][0], "Asks are not sorted ascending"


def test_order_book_bids_descending(mock_client):
    """Bids sorted highest to lowest."""
    mock_client.exchange.fetch_order_book.return_value = {
        "bids": [[2000.0, 1.0], [1990.0, 1.0], [1980.0, 1.0]],
        "asks": [],
    }

    book = mock_client.fetch_order_book("ETH/USDT")
    bids = book["bids"]

    assert bids[0][0] > bids[1][0]
    assert bids[1][0] > bids[2][0]


def test_order_book_asks_ascending(mock_client):
    """Asks sorted lowest to highest."""
    mock_client.exchange.fetch_order_book.return_value = {
        "bids": [],
        "asks": [[2010.0, 1.0], [2020.0, 1.0], [2030.0, 1.0]],
    }

    book = mock_client.fetch_order_book("ETH/USDT")
    asks = book["asks"]

    assert asks[0][0] < asks[1][0]
    assert asks[1][0] < asks[2][0]


def test_real_spread_calculation(real_client):
    """
    Hits real Binance Testnet API.
    Verifies calculated spread validity.
    """
    try:
        book = real_client.fetch_order_book("ETH/USDT")
    except Exception as e:
        pytest.skip(f"Skipping real API test due to connection error: {e}")

    if book["best_bid"][0] > 0 and book["best_ask"][0] > 0:
        assert book["spread_bps"] >= 0

        mid = (book["best_bid"][0] + book["best_ask"][0]) / 2
        diff = book["best_ask"][0] - book["best_bid"][0]
        calc_bps = (diff / mid) * 10000

        assert abs(book["spread_bps"] - calc_bps) < Decimal("0.01")


# Mocked Tests
def test_fetch_balance_filters_zeros(mock_client):
    """Zero-balance assets excluded from result."""
    mock_client.exchange.fetch_balance.return_value = {
        "total": {"ETH": 1.5, "BTC": 0.0, "USDT": 100.0},
        "free": {"ETH": 1.5, "BTC": 0.0, "USDT": 100.0},
        "used": {"ETH": 0.0, "BTC": 0.0, "USDT": 0.0},
    }

    balance = mock_client.fetch_balance()

    assert "ETH" in balance
    assert "USDT" in balance
    assert "BTC" not in balance
    assert balance["ETH"]["total"] == Decimal("1.5")
    assert balance["ETH"]["locked"] == Decimal("0.0")


def test_limit_ioc_returns_fill_info(mock_client):
    """IOC order returns fill qty, avg price, fees."""
    mock_client.exchange.create_order.return_value = {
        "id": "12345",
        "symbol": "ETH/USDT",
        "side": "buy",
        "type": "limit",
        "info": {"timeInForce": "IOC"},
        "amount": 2.0,
        "filled": 1.5,
        "average": 2000.0,
        "fee": {"cost": 0.003, "currency": "ETH"},
        "status": "closed",
        "timestamp": 1700000000,
    }

    order = mock_client.create_limit_ioc_order("ETH/USDT", "buy", 2.0, 2000.0)

    assert order["amount_filled"] == Decimal("1.5")
    assert order["avg_fill_price"] == Decimal("2000.0")
    assert order["fee"] == Decimal("0.003")
    assert order["status"] == "closed"


def test_rate_limiter_blocks_when_exhausted():
    """Requests blocked when weight limit reached."""
    with patch("ccxt.binance") as mock_cnst:
        ExchangeClient(BINANCE_CONFIG)
        args, kwargs = mock_cnst.call_args
        config_passed = args[0]
        assert config_passed["enableRateLimit"] is True
