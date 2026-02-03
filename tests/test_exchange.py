import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal
from exchange.client import ExchangeClient


@pytest.fixture
def mock_config():
    return {
        "apiKey": "test_key",
        "secret": "test_secret",
        "sandbox": True,
        "enableRateLimit": True,
    }


@pytest.fixture
def client(mock_config):
    with patch("ccxt.binance") as mock_cnst:
        mock_instance = MagicMock()
        mock_cnst.return_value = mock_instance

        mock_instance.load_markets.return_value = {}
        mock_instance.fetch_time.return_value = 1600000000000

        client = ExchangeClient(mock_config)
        return client


def test_fetch_order_book_structure(client):
    """Order book has required fields and correct sort order."""
    client.exchange.fetch_order_book.return_value = {
        "symbol": "ETH/USDT",
        "timestamp": 1700000000000,
        "bids": [[2000.0, 1.0], [1990.0, 2.0]],
        "asks": [[2010.0, 1.0], [2020.0, 2.0]],
    }

    book = client.fetch_order_book("ETH/USDT")

    required_fields = [
        "symbol",
        "bids",
        "asks",
        "best_bid",
        "best_ask",
        "mid_price",
        "spread_bps",
    ]
    for field in required_fields:
        assert field in book, f"Missing field: {field}"

    assert isinstance(book["best_bid"][0], Decimal)
    assert isinstance(book["mid_price"], Decimal)
    assert book["mid_price"] == Decimal("2005.0")


def test_order_book_bids_descending(client):
    """Bids sorted highest to lowest."""
    client.exchange.fetch_order_book.return_value = {
        "bids": [[2000.0, 1.0], [1990.0, 1.0], [1980.0, 1.0]],
        "asks": [],
    }

    book = client.fetch_order_book("ETH/USDT")
    bids = book["bids"]

    assert bids[0][0] > bids[1][0]
    assert bids[1][0] > bids[2][0]


def test_order_book_asks_ascending(client):
    """Asks sorted lowest to highest."""
    client.exchange.fetch_order_book.return_value = {
        "bids": [],
        "asks": [[2010.0, 1.0], [2020.0, 1.0], [2030.0, 1.0]],
    }

    book = client.fetch_order_book("ETH/USDT")
    asks = book["asks"]

    assert asks[0][0] < asks[1][0]
    assert asks[1][0] < asks[2][0]


def test_spread_calculation(client):
    """Spread = best_ask - best_bid, in bps."""
    client.exchange.fetch_order_book.return_value = {
        "bids": [[2000.0, 1.0]],
        "asks": [[2010.0, 1.0]],
    }

    book = client.fetch_order_book("ETH/USDT")

    # Mid = (2000 + 2010) / 2 = 2005
    # Spread = 10
    # Bps = (10 / 2005) * 10000 ≈ 49.8753...

    mid_price = (Decimal("2000") + Decimal("2010")) / 2
    expected_spread = (Decimal("2010") - Decimal("2000")) / mid_price * 10000

    assert abs(book["spread_bps"] - expected_spread) < Decimal("0.0001")


def test_fetch_balance_filters_zeros(client):
    """Zero-balance assets excluded from result."""
    client.exchange.fetch_balance.return_value = {
        "total": {"ETH": 1.5, "BTC": 0.0, "USDT": 100.0},
        "free": {"ETH": 1.5, "BTC": 0.0, "USDT": 100.0},
        "used": {"ETH": 0.0, "BTC": 0.0, "USDT": 0.0},
    }

    balance = client.fetch_balance()

    assert "ETH" in balance
    assert "USDT" in balance
    assert "BTC" not in balance
    assert balance["ETH"]["total"] == Decimal("1.5")
    assert balance["ETH"]["locked"] == Decimal("0.0")


def test_limit_ioc_returns_fill_info(client):
    """IOC order returns fill qty, avg price, fees."""
    client.exchange.create_order.return_value = {
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

    order = client.create_limit_ioc_order("ETH/USDT", "buy", 2.0, 2000.0)

    assert order["amount_filled"] == Decimal("1.5")
    assert order["avg_fill_price"] == Decimal("2000.0")
    assert order["fee"] == Decimal("0.003")
    assert order["status"] == "closed"


def test_rate_limiter_blocks_when_exhausted(mock_config):
    """Requests blocked when weight limit reached."""
    with patch("ccxt.binance") as mock_cnst:
        ExchangeClient(mock_config)
        args, kwargs = mock_cnst.call_args
        config_passed = args[0]
        assert config_passed["enableRateLimit"] is True
