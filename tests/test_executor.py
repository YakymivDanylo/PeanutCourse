import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from executor.engine import Executor, ExecutorConfig, ExecutorState
from strategy.signal import Signal, Direction
import time
import os
from dotenv import load_dotenv
from executor.recovery import CircuitBreaker, CircuitBreakerConfig

load_dotenv()


@pytest.fixture
def mock_deps():
    return MagicMock(), MagicMock(), MagicMock(), MagicMock()


@pytest.fixture
def executor(mock_deps):
    exchange, pricing, inventory, wallet = mock_deps
    config = ExecutorConfig(simulation_mode=False, use_flashbots=False)
    return Executor(exchange, pricing, inventory, wallet, config)


@pytest.fixture
def signal():
    return Signal.create(
        pair="ETH/USDT",
        direction=Direction.BUY_CEX_SELL_DEX,
        cex_price=2000.0,
        dex_price=2020.0,
        spread_bps=100,
        size=1.0,
        expected_gross_pnl=20,
        expected_fees=5,
        expected_net_pnl=15,
        score=100,
        expiry=time.time() + 60,
        inventory_ok=True,
        within_limits=True,
    )


@pytest.mark.asyncio
async def test_execute_success(executor, signal):
    """Both legs fill, state ends at DONE."""
    executor._execute_cex_leg = AsyncMock(
        return_value={"success": True, "price": 2000.0, "filled": 1.0}
    )
    executor._execute_dex_leg = AsyncMock(
        return_value={"success": True, "price": 2020.0, "filled": 1.0}
    )

    ctx = await executor.execute(signal)

    assert ctx.state == ExecutorState.DONE
    assert ctx.leg1_venue == "cex"
    assert ctx.leg2_venue == "dex"
    assert ctx.actual_net_pnl is not None


@pytest.mark.asyncio
async def test_execute_cex_timeout(executor, signal):
    """CEX timeout results in FAILED state."""
    executor.config.leg1_timeout = 0.01

    async def slow_leg(*args, **kwargs):
        await asyncio.sleep(0.1)
        return {}

    executor._execute_cex_leg = slow_leg

    ctx = await executor.execute(signal)
    assert ctx.state == ExecutorState.FAILED
    assert ctx.error == "CEX timeout"


@pytest.mark.asyncio
async def test_execute_dex_failure_unwinds(executor, signal):
    """DEX failure after CEX fill triggers unwind."""
    executor._execute_cex_leg = AsyncMock(
        return_value={"success": True, "price": 2000.0, "filled": 1.0}
    )
    executor._execute_dex_leg = AsyncMock(return_value={"success": False})
    executor._unwind = AsyncMock()

    ctx = await executor.execute(signal)

    assert ctx.state == ExecutorState.FAILED
    assert "DEX failed - unwound" in ctx.error


@pytest.mark.asyncio
async def test_partial_fill_rejected(executor, signal):
    """Fill below min_fill_ratio is rejected."""
    executor.config.min_fill_ratio = 0.9
    executor._execute_cex_leg = AsyncMock(
        return_value={"success": True, "filled": 0.5, "price": 2000}  # 50% fill
    )

    ctx = await executor.execute(signal)
    assert ctx.state == ExecutorState.FAILED
    assert "Partial fill" in ctx.error


@pytest.mark.asyncio
async def test_circuit_breaker_blocks(executor, signal):
    """Open circuit breaker prevents execution."""
    executor.circuit_breaker.is_open = MagicMock(return_value=True)

    ctx = await executor.execute(signal)
    assert ctx.state == ExecutorState.FAILED
    assert ctx.error == "Circuit breaker open"


@pytest.mark.asyncio
async def test_replay_protection(executor, signal):
    """Same signal can't execute twice."""
    executor._execute_cex_leg = AsyncMock(
        return_value={"success": True, "price": 2000.0, "filled": 1.0}
    )
    executor._execute_dex_leg = AsyncMock(
        return_value={"success": True, "price": 2020.0, "filled": 1.0}
    )

    await executor.execute(signal)

    ctx = await executor.execute(signal)
    assert ctx.state == ExecutorState.FAILED
    assert ctx.error == "Duplicate signal"


def test_real_webhook_notification():
    webhook_url = os.getenv("WEBHOOK_URL")
    if not webhook_url:
        pytest.skip("Webhook URL not set")

    config = CircuitBreakerConfig(
        failure_threshold=1,
        webhook_url=webhook_url,
    )
    cb = CircuitBreaker(config=config)

    error_text = "API Key Invalid or Insufficient Balance"

    try:
        cb.record_failure(error_reason=error_text)
        print("Notification sent. Check Discord for the error message!")
    except Exception as e:
        pytest.fail(f"Execution failed: {e}")

    assert cb.is_open() is True
