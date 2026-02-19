import time
import pytest
from executor.recovery import CircuitBreaker, CircuitBreakerConfig, ReplayProtection
from strategy.signal import Signal, Direction


@pytest.fixture
def signal():
    return Signal.create(
        pair="ETH/USDT",
        direction=Direction.BUY_CEX_SELL_DEX,
        data_timestamp=time.time(),
        cex_price=2000,
        dex_price=2010,
        spread_bps=50,
        size=1.0,
        expected_gross_pnl=10,
        expected_fees=2,
        expected_net_pnl=8,
        score=100,
        expiry=time.time() + 60,
        inventory_ok=True,
        within_limits=True,
    )


def test_circuit_breaker_trips():
    """3 failures in window trips breaker."""
    cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3, window_seconds=10))

    assert not cb.is_open()

    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()

    cb.record_failure()
    assert cb.is_open()


def test_circuit_breaker_resets():
    """Breaker resets after cooldown."""
    cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=1, cooldown_seconds=0.1))

    cb.record_failure()
    assert cb.is_open()

    time.sleep(0.2)
    assert not cb.is_open()


def test_replay_blocks_duplicate(signal):
    """Same signal_id blocked."""
    rp = ReplayProtection()

    assert not rp.is_duplicate(signal)
    rp.mark_executed(signal)

    assert rp.is_duplicate(signal)


def test_replay_allows_new(signal):
    """Different signal_id allowed."""
    rp = ReplayProtection()
    rp.mark_executed(signal)

    new_signal = Signal.create(
        pair="ETH/USDT",
        direction=Direction.BUY_CEX_SELL_DEX,
        data_timestamp=time.time(),
        cex_price=2000,
        dex_price=2010,
        spread_bps=50,
        size=1.0,
        expected_gross_pnl=10,
        expected_fees=2,
        expected_net_pnl=8,
        score=100,
        expiry=time.time() + 60,
        inventory_ok=True,
        within_limits=True,
    )

    assert not rp.is_duplicate(new_signal)
