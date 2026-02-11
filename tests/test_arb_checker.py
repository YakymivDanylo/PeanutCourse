import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from integration.arb_checker import ArbChecker, TOKEN_MAP


@pytest.fixture
def mock_clients():
    exchange = MagicMock()
    chain = MagicMock()
    inventory = MagicMock()
    return exchange, chain, inventory


@pytest.fixture
def checker(mock_clients):
    exchange, chain, inventory = mock_clients
    return ArbChecker(exchange, chain, inventory)


def test_arb_profitable_dex_buy_cex_sell(checker, mock_clients):
    exchange, chain, inventory = mock_clients

    exchange.fetch_order_book.return_value = {
        "symbol": "ETH/USDC",
        "bids": [[Decimal("2010.0"), Decimal("10.0")]],
        "asks": [[Decimal("2020.0"), Decimal("10.0")]],
        "best_bid": [Decimal("2010.0"), Decimal("10.0")],
        "best_ask": [Decimal("2020.0"), Decimal("10.0")],
        "mid_price": Decimal("2015.0"),
    }
    exchange.get_trading_fees.return_value = {"taker": Decimal("0.001")}
    inventory.get_available.return_value = Decimal("50000.0")

    with patch("integration.arb_checker.UniswapV2Pair") as MockPair:
        mock_pool = MockPair.from_chain.return_value
        mock_pool.token0 = TOKEN_MAP["WETH"]
        mock_pool.reserve0 = 1 * 10**18
        mock_pool.reserve1 = 2000 * 10**6

        mock_pool.get_spot_price.return_value = Decimal("2000") / Decimal(10**12)
        mock_pool.get_amount_out.return_value = 2000 * 10**6
        mock_pool.get_amount_in.return_value = 2000 * 10**6

        result = checker.check("ETH/USDC", 1.0)

        assert result["direction"] == "buy_dex_sell_cex"
        assert result["gap_usd"] > 0
        assert result["dex_price"] == Decimal("2000.0")
        assert result["cex_price"] == Decimal("2010.0")


def test_arb_unprofitable_high_costs(checker, mock_clients):
    exchange, chain, inventory = mock_clients

    exchange.fetch_order_book.return_value = {
        "symbol": "ETH/USDC",
        "bids": [[Decimal("2005.0"), Decimal("10.0")]],
        "asks": [[Decimal("2010.0"), Decimal("10.0")]],
        "best_bid": [Decimal("2005.0"), Decimal("10.0")],
        "best_ask": [Decimal("2010.0"), Decimal("10.0")],
        "mid_price": Decimal("2007.5"),
    }
    exchange.get_trading_fees.return_value = {"taker": Decimal("0.001")}
    inventory.get_available.return_value = Decimal("50000.0")

    with patch("integration.arb_checker.UniswapV2Pair") as MockPair:
        mock_pool = MockPair.from_chain.return_value
        mock_pool.token0 = TOKEN_MAP["WETH"]
        mock_pool.reserve0 = 1 * 10**18
        mock_pool.reserve1 = 2004 * 10**6

        mock_pool.get_spot_price.return_value = Decimal("2004") / Decimal(10**12)
        mock_pool.get_amount_out.return_value = 2004 * 10**6
        mock_pool.get_amount_in.return_value = 2004 * 10**6

        result = checker.check("ETH/USDC", 1.0)

        assert result["gap_usd"] > 0
        assert result["estimated_net_pnl_bps"] < 0
        assert result["executable"] is False


def test_inventory_check_fails(checker, mock_clients):
    exchange, chain, inventory = mock_clients

    exchange.fetch_order_book.return_value = {
        "symbol": "ETH/USDC",
        "bids": [[Decimal("2000.0"), Decimal("10.0")]],
        "asks": [[Decimal("2010.0"), Decimal("10.0")]],
        "best_bid": [Decimal("2000.0"), Decimal("10.0")],
        "best_ask": [Decimal("2010.0"), Decimal("10.0")],
        "mid_price": Decimal("2005.0"),
    }

    exchange.get_trading_fees.return_value = {"taker": Decimal("0.001")}

    inventory.get_available.return_value = Decimal("0")

    with patch("integration.arb_checker.UniswapV2Pair") as MockPair:
        mock_pool = MockPair.from_chain.return_value
        mock_pool.token0 = TOKEN_MAP["WETH"]
        mock_pool.reserve0 = 1 * 10**18
        mock_pool.reserve1 = 2100 * 10**6

        mock_pool.get_spot_price.return_value = Decimal("2100") / Decimal(10**12)
        mock_pool.get_amount_out.return_value = 2100 * 10**6
        mock_pool.get_amount_in.return_value = 2100 * 10**6

        result = checker.check("ETH/USDC", 1.0)

        assert result["inventory_ok"] is False
        assert result["executable"] is False
