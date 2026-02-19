import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from strategy.generator import SignalGenerator
from strategy.fees import FeeStructure
from strategy.signal import Direction, Signal
import time


class MockQuote:
    def __init__(self, output):
        self.expected_output = output
        self.gas_estimate = 21000


@pytest.fixture
def setup_components():
    mock_exchange = MagicMock()
    mock_pricing = MagicMock()
    mock_inventory = MagicMock()

    fees = FeeStructure()
    config = {
        "min_spread_bps": 20,
        "min_profit_usd": 1.0,
        "cooldown_seconds": 1,
        "token_map": {
            "ETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        },
    }

    mock_inventory.get_available.return_value = Decimal("100000.0")

    generator = SignalGenerator(
        mock_exchange, mock_pricing, mock_inventory, fees, config
    )
    return generator, mock_exchange, mock_pricing, mock_inventory


def test_signal_is_valid_logic():
    """Checks the signal verification logic."""
    base_signal_params = {
        "pair": "ETH/USDT",
        "direction": Direction.BUY_CEX_SELL_DEX,
        "data_timestamp": time.time(),
        "cex_price": 2000.0,
        "dex_price": 2020.0,
        "spread_bps": 100,
        "size": 1.0,
        "expected_gross_pnl": 20.0,
        "expected_fees": 5.0,
        "expected_net_pnl": 15.0,
        "score": 100,
        "expiry": time.time() + 60,
        "inventory_ok": True,
        "within_limits": True,
    }

    signal = Signal.create(**base_signal_params)
    assert signal.is_valid() is True

    expired_params = base_signal_params.copy()
    expired_params["expiry"] = time.time() - 1
    signal = Signal.create(**expired_params)
    assert signal.is_valid() is False

    no_inv_params = base_signal_params.copy()
    no_inv_params["inventory_ok"] = False
    signal = Signal.create(**no_inv_params)
    assert signal.is_valid() is False

    limits_params = base_signal_params.copy()
    limits_params["within_limits"] = False
    signal = Signal.create(**limits_params)
    assert signal.is_valid() is False

    neg_pnl_params = base_signal_params.copy()
    neg_pnl_params["expected_net_pnl"] = -5.0
    signal = Signal.create(**neg_pnl_params)
    assert signal.is_valid() is False

    zero_score_params = base_signal_params.copy()
    zero_score_params["score"] = 0
    signal = Signal.create(**zero_score_params)
    assert signal.is_valid() is False


def test_generator_inventory_check(setup_components):
    """
    Checks that Generator sets inventory_ok=False if there are insufficient funds.
    """
    gen, exch, pricing, inventory = setup_components

    exch.fetch_order_book.return_value = {
        "bids": [[2000.0, 1.0]],
        "asks": [[2000.0, 1.0]],
    }
    pricing.get_quote.side_effect = [
        MockQuote(int(2100 * 10**6)),
        MockQuote(int(0.9 * 10**18)),
    ]

    def mock_get_available(venue, asset):
        if venue == "binance" and asset == "USDT":
            return Decimal("10.0")
        return Decimal("10000.0")

    inventory.get_available.side_effect = mock_get_available

    signal = gen.generate("ETH/USDT", 1.0)

    assert signal is not None
    assert signal.direction == Direction.BUY_CEX_SELL_DEX
    assert signal.expected_net_pnl > 0
    assert signal.inventory_ok is False
    assert signal.is_valid() is False


def test_generate_signal_profitable(setup_components):
    gen, exch, pricing, _ = setup_components

    exch.fetch_order_book.return_value = {
        "bids": [[2000.0, 1.0]],
        "asks": [[2000.0, 1.0]],
    }

    pricing.get_quote.side_effect = [
        MockQuote(int(2050 * 10**6)),
        MockQuote(int(0.97 * 10**18)),
    ]

    signal = gen.generate("ETH/USDT", 1.0)

    assert signal is not None
    assert signal.direction == Direction.BUY_CEX_SELL_DEX
    assert signal.expected_net_pnl > 1.0


def test_generate_signal_no_opportunity(setup_components):
    gen, exch, pricing, _ = setup_components

    exch.fetch_order_book.return_value = {"bids": [[2000.0, 1]], "asks": [[2000.0, 1]]}

    # DEX Flat price (2000)
    pricing.get_quote.side_effect = [
        MockQuote(int(2000 * 10**6)),  # Sell 1 ETH -> 2000 USDT
        MockQuote(int(1.0 * 10**18)),  # Buy with 2000 USDT -> 1.0 ETH
    ]

    signal = gen.generate("ETH/USDT", 1.0)
    assert signal is None


def test_cooldown_prevents_rapid_signals(setup_components):
    gen, exch, pricing, _ = setup_components

    exch.fetch_order_book.return_value = {"bids": [[2000.0, 1]], "asks": [[2000.0, 1]]}
    pricing.get_quote.side_effect = [
        MockQuote(int(2050 * 10**6)),
        MockQuote(int(0.97 * 10**18)),
    ]

    signal1 = gen.generate("ETH/USDT", 1.0)
    assert signal1 is not None

    pricing.get_quote.side_effect = [
        MockQuote(int(2050 * 10**6)),
        MockQuote(int(0.97 * 10**18)),
    ]
    signal2 = gen.generate("ETH/USDT", 1.0)

    assert signal2 is None


def test_direction_selection(setup_components):
    gen, exch, pricing, _ = setup_components

    exch.fetch_order_book.return_value = {"bids": [[2100.0, 1]], "asks": [[2105.0, 1]]}

    pricing.get_quote.side_effect = [
        MockQuote(int(2000 * 10**6)),  # Sell on DEX (Low price) - bad direction
        MockQuote(
            int(1.05 * 10**18)
        ),  # Buy on DEX (Input ~2100 USDT -> Get 1.05 ETH) -> Price 2000
    ]

    signal = gen.generate("ETH/USDT", 1.0)

    assert signal is not None
    assert signal.direction == Direction.BUY_DEX_SELL_CEX
