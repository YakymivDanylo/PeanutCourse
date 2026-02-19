from safety import safety_check


def test_safety_check_ok():
    """Normal conditions"""
    is_safe, msg = safety_check(
        trade_usd=10.0, daily_loss=5.0, total_capital=100.0, trades_this_hour=5
    )
    assert is_safe is True
    assert msg == "OK"


def test_safety_check_max_trade_exceeded():
    """Exceeding the limit for one trade (> $25.0)"""
    is_safe, msg = safety_check(
        trade_usd=30.0, daily_loss=0.0, total_capital=100.0, trades_this_hour=0
    )
    assert is_safe is False
    assert "exceeds absolute max" in msg


def test_safety_check_max_daily_loss_reached():
    """Exceeding daily loss limit (>= $20.0)"""
    is_safe, msg = safety_check(
        trade_usd=10.0, daily_loss=20.0, total_capital=100.0, trades_this_hour=0
    )
    assert is_safe is False
    assert "reached absolute limit" in msg


def test_safety_check_min_capital_reached():
    """Capital falls below the minimum (< $50.0)"""
    is_safe, msg = safety_check(
        trade_usd=10.0, daily_loss=0.0, total_capital=45.0, trades_this_hour=0
    )
    assert is_safe is False
    assert "below minimum" in msg


def test_safety_check_max_trades_per_hour():
    """Exceeding the limit of trades per hour (>= 30)"""
    is_safe, msg = safety_check(
        trade_usd=10.0, daily_loss=0.0, total_capital=100.0, trades_this_hour=30
    )
    assert is_safe is False
    assert "Hourly trade limit" in msg
