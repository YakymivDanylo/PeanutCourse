# inventory/pnl.py
import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from inventory.tracker import Venue


@dataclass
class TradeLeg:
    """Single execution leg."""

    id: str
    timestamp: datetime
    venue: Venue
    symbol: str  # "ETH/USDT"
    side: str  # "buy" or "sell"
    amount: Decimal  # Base asset qty
    price: Decimal  # Execution price
    fee: Decimal
    fee_asset: str


@dataclass
class ArbRecord:
    """Complete arb trade with both legs."""

    id: str
    timestamp: datetime
    buy_leg: TradeLeg
    sell_leg: TradeLeg
    gas_cost_usd: Decimal = Decimal("0")

    @property
    def gross_pnl(self) -> Decimal:
        """Price difference revenue.
        (Sell Price * Sell Amount) - (Buy Price * Buy Amount)
        """
        sell_revenue = self.sell_leg.price * self.sell_leg.amount
        buy_cost = self.buy_leg.price * self.buy_leg.amount
        return sell_revenue - buy_cost

    @property
    def total_fees(self) -> Decimal:
        """All fees: both legs + gas."""
        return self.buy_leg.fee + self.sell_leg.fee + self.gas_cost_usd

    @property
    def net_pnl(self) -> Decimal:
        """Gross - fees."""
        return self.gross_pnl - self.total_fees

    @property
    def notional(self) -> Decimal:
        """Trade size in quote currency."""
        return self.buy_leg.price * self.buy_leg.amount

    @property
    def net_pnl_bps(self) -> Decimal:
        """Net PnL in basis points of notional."""
        cost = self.notional
        if cost == 0:
            return Decimal("0")
        return (self.net_pnl / cost) * Decimal("10000")


class PnLEngine:
    """
    Tracks all arb trades and produces PnL reports.
    """

    def __init__(self):
        self.trades: list[ArbRecord] = []

    def record(self, trade: ArbRecord):
        """Record a completed arb trade."""
        self.trades.append(trade)

    def summary(self) -> dict:
        """
        Aggregate PnL summary.

        Returns:
        {
            'total_trades': int,
            'total_pnl_usd': Decimal,
            'total_fees_usd': Decimal,
            'avg_pnl_per_trade': Decimal,
            'avg_pnl_bps': Decimal,
            'win_rate': float,           # % of trades with positive PnL
            'best_trade_pnl': Decimal,
            'worst_trade_pnl': Decimal,
            'total_notional': Decimal,
            'sharpe_estimate': float,    # PnL / stddev(PnL) — rough estimate
            'pnl_by_hour': dict,         # {hour: total_pnl}
        }
        """
        if not self.trades:
            return {
                "total_trades": 0,
                "total_pnl_usd": Decimal("0"),
                "total_fees_usd": Decimal("0"),
                "avg_pnl_per_trade": Decimal("0"),
                "avg_pnl_bps": Decimal("0"),
                "win_rate": 0.0,
                "best_trade_pnl": Decimal("0"),
                "worst_trade_pnl": Decimal("0"),
                "total_notional": Decimal("0"),
                "sharpe_estimate": 0.0,
                "pnl_by_hour": {},
            }

        pnls = [t.net_pnl for t in self.trades]
        bps_values = [t.net_pnl_bps for t in self.trades]
        wins = [p for p in pnls if p > 0]

        total_pnl = sum(pnls)
        total_fees = sum(t.total_fees for t in self.trades)
        total_notional = sum(t.notional for t in self.trades)

        count = len(self.trades)
        win_rate = (len(wins) / count) * 100 if count > 0 else 0.0

        # Sharpe Estimate: Mean PnL / StdDev PnL
        mean_pnl = total_pnl / count
        if count > 1:
            stdev_pnl = statistics.stdev([float(p) for p in pnls])
            sharpe = float(mean_pnl) / stdev_pnl if stdev_pnl != 0 else 0.0
        else:
            sharpe = 0.0

        pnl_by_hour = defaultdict(Decimal)
        for t in self.trades:
            pnl_by_hour[t.timestamp.hour] += t.net_pnl

        return {
            "total_trades": count,
            "total_pnl_usd": total_pnl,
            "total_fees_usd": total_fees,
            "avg_pnl_per_trade": mean_pnl,
            "avg_pnl_bps": sum(bps_values) / count,
            "win_rate": win_rate,
            "best_trade_pnl": max(pnls),
            "worst_trade_pnl": min(pnls),
            "total_notional": total_notional,
            "sharpe_estimate": sharpe,
            "pnl_by_hour": dict(pnl_by_hour),
        }

    def recent(self, n: int = 10) -> list[dict]:
        """
        Last N trades as summary dicts.
        For display in CLI dashboard.
        """
        recent_trades = self.trades[-n:]
        results = []
        for t in recent_trades:
            time_str = t.timestamp.strftime("%H:%M")
            desc = (
                f"Buy {t.buy_leg.venue.value.capitalize()} /"
                f"Sell {t.sell_leg.venue.value.capitalize()} "
            )
            sign = "+" if t.net_pnl > 0 else ""
            pnl_str = f"{sign}${t.net_pnl:.2f} ({t.net_pnl_bps:.1f} bps)"
            icon = "✅" if t.net_pnl > 0 else "❌"

            results.append(
                {
                    "time_str": time_str,
                    "pair": t.buy_leg.symbol,
                    "desc": desc,
                    "pnl_str": pnl_str,
                    "icon": icon,
                }
            )
        return results

    def export_csv(self, filepath: str):
        """Export all trades to CSV for analysis."""
        headers = [
            "id",
            "timestamp",
            "symbol",
            "buy_venue",
            "buy_price",
            "sell_venue",
            "sell_price",
            "amount",
            "gross_pnl",
            "gas_cost",
            "total_fees",
            "net_pnl",
            "net_pnl_bps",
        ]

        try:
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)

                for t in self.trades:
                    writer.writerow(
                        [
                            t.id,
                            t.timestamp.isoformat(),
                            t.buy_leg.symbol,
                            t.buy_leg.venue.value,
                            t.buy_leg.price,
                            t.sell_leg.venue.value,
                            t.sell_leg.price,
                            t.buy_leg.amount,
                            t.gross_pnl,
                            t.gas_cost_usd,
                            t.total_fees,
                            t.net_pnl,
                            t.net_pnl_bps,
                        ]
                    )
        except IOError as e:
            print(f"Error writing CSV: {e}")

    def load_from_csv(self, filepath: str):
        """
        Load trades from a CSV file into memory.
        Note: This is a simplified loader for visualization purposes.
        """
        try:
            with open(filepath, "r") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ts = datetime.fromisoformat(row["timestamp"])
                    except ValueError:
                        continue

                    mock_leg = TradeLeg(
                        id="load",
                        timestamp=ts,
                        venue=Venue.BINANCE,
                        symbol=row["symbol"],
                        side="buy",
                        amount=Decimal(row["amount"]),
                        price=Decimal(row["buy_price"]),
                        fee=Decimal("0"),
                        fee_asset="USDT",
                    )

                    record = ArbRecord(
                        id=row["id"],
                        timestamp=ts,
                        buy_leg=mock_leg,
                        sell_leg=mock_leg,
                        gas_cost_usd=Decimal(row["gas_cost"]),
                    )

                    record.stored_net_pnl = Decimal(row["net_pnl"])

                    self.trades.append(record)

        except FileNotFoundError:
            print(f"File {filepath} not found.")
