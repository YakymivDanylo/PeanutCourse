# safety.py — DO NOT MODIFY THESE VALUES

ABSOLUTE_MAX_TRADE_USD = 25.0  # Hard ceiling on any single trade
ABSOLUTE_MAX_DAILY_LOSS = 20.0  # Hard ceiling on daily loss
ABSOLUTE_MIN_CAPITAL = 50.0  # Auto-stop if total capital < $50
ABSOLUTE_MAX_TRADES_PER_HOUR = 30  # Prevent runaway loops


def safety_check(
    trade_usd: float, daily_loss: float, total_capital: float, trades_this_hour: int
) -> tuple[bool, str]:
    """Final safety gate — runs AFTER all other checks."""

    if trade_usd > ABSOLUTE_MAX_TRADE_USD:
        return (
            False,
            f"SAFETY: Trade ${trade_usd:.2f} "
            f"exceeds absolute max ${ABSOLUTE_MAX_TRADE_USD}",
        )

    if daily_loss >= ABSOLUTE_MAX_DAILY_LOSS:  # Note: passed as positive loss amount
        return (
            False,
            f"SAFETY: Daily loss ${daily_loss:.2f}"
            f" reached absolute limit ${ABSOLUTE_MAX_DAILY_LOSS}",
        )

    if total_capital < ABSOLUTE_MIN_CAPITAL:
        return (
            False,
            f"SAFETY: Capital ${total_capital:.2f} "
            f"below minimum ${ABSOLUTE_MIN_CAPITAL}",
        )

    if trades_this_hour >= ABSOLUTE_MAX_TRADES_PER_HOUR:
        return (
            False,
            f"SAFETY: Hourly trade limit {ABSOLUTE_MAX_TRADES_PER_HOUR} reached",
        )

    return True, "OK"
