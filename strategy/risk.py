# strategy/risk.py
from dataclasses import dataclass


@dataclass
class RiskLimits:
    max_trade_usd: float = 5.0
    max_trade_pct: float = 0.05
    max_daily_loss: float = 10.0
    max_drawdown_pct: float = 0.20
    max_consecutive_losses: int = 3


class RiskManager:
    def __init__(self, limits: RiskLimits, initial_capital: float = 100.0):
        self.limits = limits
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.trades_today = 0

    def check_pre_trade(self, signal) -> tuple[bool, str]:
        expected_trade_usd = signal.size * signal.cex_price
        if expected_trade_usd > self.limits.max_trade_usd:
            return (
                False,
                f"Trade size ${expected_trade_usd:.2f}"
                f" > limit ${self.limits.max_trade_usd}",
            )

        if self.daily_pnl <= -self.limits.max_daily_loss:
            return False, f"Daily loss limit hit: ${self.daily_pnl:.2f}"

        if self.consecutive_losses >= self.limits.max_consecutive_losses:
            return False, f"Too many consecutive losses: {self.consecutive_losses}"

        return True, "OK"

    def record_trade(self, pnl: float):
        self.daily_pnl += pnl
        self.current_capital += pnl
        self.trades_today += 1

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0


class PreTradeValidator:
    def validate_signal(self, signal) -> tuple[bool, str]:
        if not signal:
            return False, "Empty signal"

        if signal.spread_bps < 0:
            return False, f"Negative spread: {signal.spread_bps}"

        if signal.spread_bps > 5000:  # 50% spread sanity check
            return False, "Spread too high (sanity check)"

        return True, "OK"
