import pytest
from unittest.mock import MagicMock, patch
import time

from core.types import Address
from pricing.engine import PricingEngine, Quote, QuoteError, ParsedSwap
from pricing.amm import UniswapV2Pair
from pricing.routing import Route
from pricing.simulation import SimulationResult

WETH = Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
USDC = Address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")


@pytest.fixture
def mock_engine():
    """
    Creates a PricingEngine with a mocked ForkSimulator.
    This prevents the engine from trying to connect to a real RPC during tests.
    """
    with patch("pricing.engine.ForkSimulator") as MockSimulatorClass:
        mock_sim_instance = MockSimulatorClass.return_value

        client = MagicMock()
        client.rpc_urls = ["http://mock"]

        engine = PricingEngine(client, "http://mock-fork", "ws://mock-ws")

        engine.simulator = mock_sim_instance
        engine.monitor = MagicMock()
        engine.router = MagicMock()

        yield engine


def test_quote_validity():
    """Test Quote.is_valid property logic."""
    mock_route = MagicMock()
    ts = time.time()

    q1 = Quote(mock_route, 100, 1000, 1000, 21000, ts)
    assert q1.is_valid

    q2 = Quote(mock_route, 100, 2000, 1999, 21000, ts)
    assert q2.is_valid

    q3 = Quote(mock_route, 100, 1000, 900, 21000, ts)
    assert not q3.is_valid


def test_get_quote_flow(mock_engine):
    """Test the full flow of get_quote."""
    engine = mock_engine

    mock_route = MagicMock(spec=Route)
    engine.router.find_best_route.return_value = (mock_route, 1000)

    engine.simulator.simulate_route.return_value = SimulationResult(
        success=True, amount_out=999, gas_used=50000, error=None, logs=[]
    )

    quote = engine.get_quote(WETH, USDC, 100, 10)

    engine.router.find_best_route.assert_called_once()
    engine.simulator.simulate_route.assert_called_once()

    assert quote.expected_output == 1000
    assert quote.simulated_output == 999
    assert quote.gas_estimate == 50000
    assert not quote.is_valid


def test_get_quote_simulation_failure(mock_engine):
    """Test get_quote raises error if simulation fails."""
    engine = mock_engine
    engine.router.find_best_route.return_value = (MagicMock(), 1000)

    engine.simulator.simulate_route.return_value = SimulationResult(
        success=False, amount_out=0, gas_used=0, error="Revert", logs=[]
    )

    with pytest.raises(QuoteError, match="Simulation failed"):
        engine.get_quote(WETH, USDC, 100, 10)


@pytest.mark.asyncio
async def test_mempool_callback(mock_engine):
    """Test _on_mempool_swap logic."""
    engine = mock_engine

    mock_pair = MagicMock(spec=UniswapV2Pair)
    mock_pair.token0 = WETH
    mock_pair.token1 = USDC
    mock_pair.symbol = "ETH-USDC"
    mock_pair.get_amount_out.return_value = 2000

    engine.pools = {"checksum_addr": mock_pair}

    valid_sender = Address("0x" + "1" * 40)

    swap = ParsedSwap(
        tx_hash="0x123",
        router="0xR",
        dex="Uni",
        method="swap",
        token_in=WETH,
        token_out=USDC,  # Matches pool
        amount_in=100,
        min_amount_out=1900,  # 5% slippage (2000 vs 1900)
        deadline=0,
        sender=valid_sender,
        gas_price=0,
        value=0,
    )

    await engine._on_mempool_swap(swap)

    mock_pair.get_amount_out.assert_called_with(100, WETH)
