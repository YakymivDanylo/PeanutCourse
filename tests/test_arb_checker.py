import pytest
from decimal import Decimal
from unittest.mock import MagicMock
from integration.arb_checker import ArbChecker, TOKEN_MAP


@pytest.fixture
def mock_components():
    pricing = MagicMock()
    exchange = MagicMock()
    inventory = MagicMock()
    pnl = MagicMock()

    gas_struct = MagicMock()
    gas_struct.priority_fee_medium = 20_000_000_000
    gas_struct.base_fee = 20_000_000_000
    pricing.client.get_gas_price.return_value = gas_struct

    return pricing, exchange, inventory, pnl


@pytest.fixture
def checker(mock_components):
    pricing, exchange, inventory, pnl = mock_components
    return ArbChecker(pricing, exchange, inventory, pnl)


def test_arb_profitable_dex_buy_cex_sell(checker, mock_components):
    pricing, exchange, inventory, _ = mock_components

    exchange.fetch_order_book.return_value = {
        "symbol": "ETH/USDC",
        "bids": [[Decimal("2010.0"), Decimal("10.0")]],
        "asks": [[Decimal("2020.0"), Decimal("10.0")]],
        "best_bid": (Decimal("2010.0"), Decimal("10.0")),
        "best_ask": (Decimal("2020.0"), Decimal("10.0")),
        "mid_price": Decimal("2015.0"),
    }
    exchange.get_trading_fees.return_value = {"taker": Decimal("0.001")}

    quote_buy = MagicMock()
    quote_buy.expected_output = int(1.01 * 10**18)
    quote_buy.gas_estimate = 100_000

    quote_sell = MagicMock()
    quote_sell.expected_output = 0
    quote_sell.gas_estimate = 100_000

    def get_quote_side_effect(token_in, token_out, amount_in, gas):
        if str(token_in) == str(TOKEN_MAP["USDC"]):
            return quote_buy
        return quote_sell

    pricing.get_quote.side_effect = get_quote_side_effect
    inventory.get_available.return_value = Decimal("50000.0")

    result = checker.check("ETH/USDC", 1.0)

    assert result["direction"] == "buy_dex_sell_cex"
    assert result["cex_price"] == Decimal("2010.0")
    assert result["dex_price"] < Decimal("2010.0")
    assert result["gap_usd"] > 0
    assert result["executable"] is True


def test_arb_unprofitable_high_costs(checker, mock_components):
    pricing, exchange, inventory, _ = mock_components

    exchange.fetch_order_book.return_value = {
        "symbol": "ETH/USDC",
        "bids": [[Decimal("2005.0"), Decimal("10.0")]],
        "asks": [[Decimal("2010.0"), Decimal("10.0")]],
        "best_bid": (Decimal("2005.0"), Decimal("10.0")),
        "best_ask": (Decimal("2010.0"), Decimal("10.0")),
        "mid_price": Decimal("2007.5"),
    }
    exchange.get_trading_fees.return_value = {"taker": Decimal("0.001")}

    quote_buy = MagicMock()
    quote_buy.expected_output = int(1.0025 * 10**18)
    quote_buy.gas_estimate = 500_000

    quote_bad = MagicMock()
    quote_bad.expected_output = 0
    quote_bad.gas_estimate = 0

    def get_quote_side_effect(token_in, token_out, amount_in, gas):
        if str(token_in) == str(TOKEN_MAP["USDC"]):
            return quote_buy
        return quote_bad

    pricing.get_quote.side_effect = get_quote_side_effect
    inventory.get_available.return_value = Decimal("50000.0")

    result = checker.check("ETH/USDC", 1.0)

    assert result["gap_usd"] > 0
    assert result["estimated_net_pnl_bps"] < 0
    assert result["executable"] is False


def test_inventory_check_fails(checker, mock_components):
    pricing, exchange, inventory, _ = mock_components

    exchange.fetch_order_book.return_value = {
        "symbol": "ETH/USDC",
        "bids": [[Decimal("2000.0"), Decimal("10.0")]],
        "asks": [[Decimal("2010.0"), Decimal("10.0")]],
        "best_bid": (Decimal("2000.0"), Decimal("10.0")),
        "best_ask": (Decimal("2010.0"), Decimal("10.0")),
        "mid_price": Decimal("2005.0"),
    }

    quote_sell = MagicMock()
    quote_sell.expected_output = 2100 * 10**6
    quote_sell.gas_estimate = 100_000

    quote_bad = MagicMock()
    quote_bad.expected_output = 0
    quote_bad.gas_estimate = 0

    def get_quote_side_effect(token_in, token_out, amount_in, gas):
        if str(token_in) == str(TOKEN_MAP["ETH"]):
            return quote_sell
        return quote_bad

    pricing.get_quote.side_effect = get_quote_side_effect

    inventory.get_available.side_effect = lambda venue, asset: Decimal("0")

    result = checker.check("ETH/USDC", 1.0)

    assert result["direction"] == "buy_cex_sell_dex"
    assert result["gap_usd"] > 0
    assert result["inventory_ok"] is False
    assert result["executable"] is False
