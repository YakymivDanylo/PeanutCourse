import time
from dataclasses import dataclass
from strategy.risk import RiskManager, RiskLimits, PreTradeValidator


@dataclass
class MockSignal:
    size: float
    cex_price: float
    data_timestamp: float
    spread_bps: float


def test_risk_manager_allowed():
    limits = RiskLimits(
        max_trade_usd=50.0, max_daily_loss=20.0, max_consecutive_losses=3
    )
    rm = RiskManager(limits, initial_capital=100.0)
    signal = MockSignal(
        size=0.1, cex_price=100.0, data_timestamp=time.time(), spread_bps=15
    )

    is_allowed, msg = rm.check_pre_trade(signal)
    assert is_allowed is True


def test_risk_manager_trade_too_large():
    limits = RiskLimits(max_trade_usd=5.0)
    rm = RiskManager(limits)
    signal = MockSignal(
        size=0.1, cex_price=100.0, data_timestamp=time.time(), spread_bps=10
    )

    is_allowed, msg = rm.check_pre_trade(signal)
    assert is_allowed is False
    assert "Trade size" in msg


def test_risk_manager_consecutive_losses():
    limits = RiskLimits(max_consecutive_losses=2)
    rm = RiskManager(limits)
    rm.record_trade(-1.0)
    rm.record_trade(-1.0)

    signal = MockSignal(
        size=0.1, cex_price=10.0, data_timestamp=time.time(), spread_bps=10
    )
    is_allowed, msg = rm.check_pre_trade(signal)
    assert is_allowed is False
    assert "Too many consecutive losses" in msg


def test_pre_trade_validator():
    validator = PreTradeValidator(max_age_seconds=2.0)

    valid_signal = MockSignal(
        size=1.0, cex_price=1.0, data_timestamp=time.time(), spread_bps=10
    )
    is_valid, _ = validator.validate_signal(valid_signal)
    assert is_valid is True

    old_signal = MockSignal(
        size=1.0, cex_price=1.0, data_timestamp=time.time() - 5.0, spread_bps=10
    )
    is_valid, msg = validator.validate_signal(old_signal)
    assert is_valid is False
    assert "too old" in msg

    neg_spread_signal = MockSignal(
        size=1.0, cex_price=1.0, data_timestamp=time.time(), spread_bps=-5
    )
    is_valid, msg = validator.validate_signal(neg_spread_signal)
    assert is_valid is False
    assert "Negative spread" in msg
