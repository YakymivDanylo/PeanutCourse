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
                "free": Decimal("1000"),
                "locked": Decimal("0"),
                "total": Decimal("1000"),
            },
        },
    )

    tracker.update_from_wallet(
        Venue.WALLET, {"ETH": Decimal("18.0"), "USDT": Decimal("12000")}
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

        status = "⚠️ NEED REBALANCE" if skew["needs_rebalance"] else "✅ OK"
        print(f"  Status: {status}")
        print("─" * 45)


def run_plan(planner: RebalancePlanner, asset: str):
    print(f"\n Rebalance Plan: {asset}")
    print("=" * 45)

    plans = planner.plan(asset)
    if not plans:
        print("No rebalance need or constraints prevent transfer ")

    cost_info = planner.estimate_cost(plans)

    for i, p in enumerate(plans, 1):
        print(f"Transfer {i}:")
        print(f"  From:     {p.from_venue.value}")
        print(f"  To:       {p.to_venue.value}")
        print(f"  Amount:   {p.amount} {p.asset}")
        print(f"  Fee:      {p.estimated_fee} {p.asset}")
        print(f"  ETA:      ~{p.estimated_time_min} min")
        print("")

        current_heavy = planner.tracker.get_available(p.from_venue, asset)
        current_light = planner.tracker.get_available(p.to_venue, asset)

        new_heavy = current_heavy - p.amount
        new_light = current_light + p.net_amount
        total = new_heavy + new_light

        h_pct = (new_heavy / total) * 100
        l_pct = (new_light / total) * 100

        print("  Result:")
        print(
            f"    {p.from_venue.value.capitalize()}:  {new_heavy} {asset} "
            f"({h_pct:.0f}%)"
        )
        print(
            f"    {p.to_venue.value.capitalize()}:  {new_light} {asset} ({l_pct:.0f}%)"
        )
        print("")

    print(f"Estimated total cost: ${cost_info['total_fees_usd']:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Inventory Rebalancer CLI")
    parser.add_argument("--check", action="store_true", help="Check inventory skew")
    parser.add_argument("--plan", type=str, help="Generate plan for asset")

    args = parser.parse_args()

    tracker = mock_tracker()
    planner = RebalancePlanner(tracker)

    if args.check:
        run_check(planner)
    elif args.plan:
        run_plan(planner, args.plan.upper())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
