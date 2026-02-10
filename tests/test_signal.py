import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from strategy.generator import SignalGenerator
from strategy.fees import FeeStructure
from strategy.signal import Direction


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
        "token_map": {"ETH": "0xBase", "USDT": "0xQuote"},
    }

    mock_inventory.get_available.return_value = Decimal("100000.0")

    generator = SignalGenerator(
        mock_exchange, mock_pricing, mock_inventory, fees, config
    )
    return generator, mock_exchange, mock_pricing


def test_generate_signal_profitable(setup_components):
    gen, exch, pricing = setup_components

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
    gen, exch, pricing = setup_components

    exch.fetch_order_book.return_value = {"bids": [[2000.0, 1]], "asks": [[2000.0, 1]]}

    # DEX Flat price (2000)
    pricing.get_quote.side_effect = [
        MockQuote(int(2000 * 10**6)),  # Sell 1 ETH -> 2000 USDT
        MockQuote(int(1.0 * 10**18)),  # Buy with 2000 USDT -> 1.0 ETH
    ]

    signal = gen.generate("ETH/USDT", 1.0)
    assert signal is None


def test_cooldown_prevents_rapid_signals(setup_components):
    gen, exch, pricing = setup_components

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
    gen, exch, pricing = setup_components

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
