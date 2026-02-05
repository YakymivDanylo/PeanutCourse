import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from decimal import Decimal  # noqa: E402

from inventory.pnl import PnLEngine, ArbRecord, TradeLeg  # noqa: E402
from inventory.tracker import Venue  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="PnL Engine Reporting")
    parser.add_argument(
        "--summary", action="store_true", help="Show PnL summary and recent trades"
    )
    parser.add_argument(
        "--export",
        type=str,
        help="Export PnL summary to CSV file (provide filename)",
        default=None,
    )
    args = parser.parse_args()

    engine = PnLEngine()
    base_time = datetime.now(timezone.utc)

    t1 = ArbRecord(
        id="1",
        timestamp=base_time,
        buy_leg=TradeLeg(
            "L1",
            base_time,
            Venue.BINANCE,
            "ETH/USDT",
            "buy",
            Decimal("1.0"),
            Decimal("2000"),
            Decimal("1.0"),
            "USDT",
        ),
        sell_leg=TradeLeg(
            "L2",
            base_time,
            Venue.WALLET,
            "ETH/USDT",
            "sell",
            Decimal("1.0"),
            Decimal("2010"),
            Decimal("2.0"),
            "USDT",
        ),
        gas_cost_usd=Decimal("2.0"),
    )

    engine.record(t1)

    t2 = ArbRecord(
        id="2",
        timestamp=base_time,
        buy_leg=TradeLeg(
            "L3",
            base_time,
            Venue.WALLET,
            "ETH/USDT",
            "buy",
            Decimal("1.0"),
            Decimal("2005"),
            Decimal("2.0"),
            "USDT",
        ),
        sell_leg=TradeLeg(
            "L4",
            base_time,
            Venue.BINANCE,
            "ETH/USDT",
            "sell",
            Decimal("1.0"),
            Decimal("2006"),
            Decimal("1.0"),
            "USDT",
        ),
        gas_cost_usd=Decimal("1.5"),
    )
    engine.record(t2)

    if args.summary:
        stats = engine.summary()

        print("\nPnL Summary (last 24h)")
        print("═" * 45)
        print(f"Total Trades:        {stats['total_trades']}")
        print(f"Win Rate:            {stats['win_rate']:.1f}%")
        print(f"Total PnL:           ${stats['total_pnl_usd']:.2f}")
        print(f"Total Fees:          ${stats['total_fees_usd']:.2f}")
        print(f"Avg PnL/Trade:       ${stats['avg_pnl_per_trade']:.2f}")
        print(f"Avg PnL (bps):       {stats['avg_pnl_bps']:.1f} bps")
        print(f"Best Trade:          ${stats['best_trade_pnl']:.2f}")
        print(f"Worst Trade:         ${stats['worst_trade_pnl']:.2f}")
        print(f"Total Notional:      ${stats['total_notional']:,.0f}")
        print("")

        print("Recent Trades:")
        for t in engine.recent(5):
            print(
                f"  {t['time_str']}  {t['pair']:<8} {t['desc']:<30} "
                f"{t['pnl_str']:<20} {t['icon']}"
            )

    if args.export:
        filename = args.export
        if not filename.endswith(".csv"):
            filename += ".csv"

        print("\nExporting data to csv file")
        engine.export_csv(filename)
        print("Done!")


if __name__ == "__main__":
    main()
