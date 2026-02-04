import argparse
import sys
from decimal import Decimal

import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inventory.tracker import InventoryTracker, Venue  # noqa: E402
from inventory.rebalancer import RebalancePlanner  # noqa: E402


def mock_tracker():
    """Create a tracker with dummy data for CLI demo"""
    tracker = InventoryTracker()

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "ETH": {
                "free": Decimal("2.0"),
                "locked": Decimal("0"),
                "total": Decimal("2.0"),
            },
            "USDT": {
                "free": Decimal("18000"),
                "locked": Decimal("0"),
                "total": Decimal("18000"),
            },
        },
    )

    tracker.update_from_wallet(
        Venue.WALLET, {"ETH": Decimal("8.0"), "USDT": Decimal("12000")}
    )

    return tracker


def run_check(planner: RebalancePlanner):
    print("\n Inventory Skew Report")
    print("=" * 45)

    assets = ["ETH", "USDT"]
    for asset in assets:
        skew = planner.tracker.skew(asset)
        print(f"Asset {asset}")

        for v_name, data in skew["venues"].items():
            venue_label = v_name.capitalize()
            amt = data["amount"]
            pct = data["pct"]
            dev = data["deviation"]

            dev_str = f"{dev:+.0f}"
            print(
                f"  {venue_label:<8}: {amt:,.4f} {asset:<4} ({pct:.0f}%)"
                f" ← deviation: {dev_str}"
            )

        status = "⚠️ NEED REBALANCE" if skew["needs_rebalance"] else "✅ OK )"
        print(f"  Status: {status}")
        print("─" * 45)


# def run_plan(planner: RebalancePlanner, asset: str):
#     tracker = InventoryTracker()


def main():
    parser = argparse.ArgumentParser(description="Inventory Rebalancer CLI")
    parser.add_argument("--check", action="store_true", help="Check inventory skew")
    parser.add_argument("--plan", type=str, help="Generate plan for asset")

    args = parser.parse_args()

    tracker = mock_tracker()
    planner = RebalancePlanner(tracker)

    if args.check:
        run_check(planner)
    # elif args.plan:
    #     run_plan(planner, args.plan.upper())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
