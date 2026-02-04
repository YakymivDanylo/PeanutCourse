from dataclasses import dataclass
from decimal import Decimal

from inventory.tracker import Venue, InventoryTracker


@dataclass
class TransferPlan:
    """A planned transfer between venues."""

    from_venue: Venue
    to_venue: Venue
    asset: str
    amount: Decimal
    estimated_fee: Decimal  # Withdrawal/gas fee
    estimated_time_min: int  # Minutes to complete

    @property
    def net_amount(self) -> Decimal:
        """Amount received after fees."""
        return self.amount - self.estimated_fee


# Hardcoded for testnet / estimation purposes
TRANSFER_FEES = {
    "ETH": {
        "withdrawal_fee": Decimal("0.005"),  # ETH network
        "min_withdrawal": Decimal("0.01"),
        "confirmations": 12,
        "estimated_time_min": 15,
    },
    "USDT": {
        "withdrawal_fee": Decimal("1.0"),  # ERC-20
        "min_withdrawal": Decimal("10.0"),
        "confirmations": 12,
        "estimated_time_min": 15,
    },
    "USDC": {
        "withdrawal_fee": Decimal("1.0"),
        "min_withdrawal": Decimal("10.0"),
        "confirmations": 12,
        "estimated_time_min": 15,
    },
}

MIN_OPERATING_BALANCE = {
    # Keep at least this much at each venue to continue trading
    "ETH": Decimal("0.5"),
    "USDT": Decimal("500"),
    "USDC": Decimal("500"),
}


class RebalancePlanner:
    """
    Generates rebalancing plans when inventory skew exceeds threshold.
    Plans only — does NOT execute transfers.
    """

    def __init__(
        self,
        tracker: InventoryTracker,
        threshold_pct: float = 30.0,  # Rebalance when deviation > 30%
        target_ratio: dict[Venue, float] = None,  # Default: equal split
    ):
        self.tracker = tracker
        self.threshold_pct = threshold_pct

    def check_all(self) -> list[dict]:
        """
        Check all tracked assets for skew.
        Returns list of assets that need rebalancing.

        Returns:
        [
            {'asset': 'ETH', 'max_deviation_pct': 42.5, 'needs_rebalance': True},
            {'asset': 'USDT', 'max_deviation_pct': 15.2, 'needs_rebalance': False},
        ]
        """
        results = []
        assets = set()
        snapshot = self.tracker.snapshot()
        for v_data in snapshot["venues"].values():
            assets.update(v_data.keys())

        for asset in assets:
            skew_data = self.tracker.skew(asset)

            if skew_data["needs_rebalance"]:
                results.append(
                    {
                        "asset": asset,
                        "max_deviation_pct": skew_data["max_deviation_pct"],
                        "needs_rebalance": skew_data["needs_rebalance"],
                    }
                )

        return results

    def plan(self, asset: str) -> list[TransferPlan]:
        """
        Generate transfer plan to rebalance a specific asset.

        Rules:
        - Only generate transfers that reduce skew
        - Respect minimum transfer amounts (e.g., Binance min withdrawal)
        - Account for transfer fees in the plan
        - Never plan a transfer that would leave a venue below minimum operating balance

        Returns list of TransferPlan objects.
        Empty list if no rebalance needed.
        """
        skew_data = self.tracker.skew(asset)

        if not skew_data["needs_rebalance"]:
            return []

        total = skew_data["total"]
        target_amount = total / Decimal("2")

        heavy_venue = None
        heavy_amt = Decimal("0")

        for v_name, data in skew_data["venues"].items():
            if data["pct"] > 50:
                heavy_venue = Venue(v_name)
                heavy_amt = data["amount"]
                break

        if not heavy_venue:
            return []

        light_venue = Venue.WALLET if heavy_venue == Venue.BINANCE else Venue.BINANCE

        transfer_amt = heavy_amt - target_amount

        min_op = MIN_OPERATING_BALANCE.get(asset, Decimal("0"))
        max_transferable = heavy_amt - min_op

        actual_transfer = min(transfer_amt, max_transferable)

        fees_cfg = TRANSFER_FEES.get(asset, Decimal("0"))

        if not fees_cfg:
            return []

        if actual_transfer < fees_cfg["min_withdrawal"]:
            return []

        return [
            TransferPlan(
                from_venue=heavy_venue,
                to_venue=light_venue,
                asset=asset,
                amount=actual_transfer,
                estimated_fee=fees_cfg["withdrawal_fee"],
                estimated_time_min=fees_cfg["estimated_time_min"],
            )
        ]

    def plan_all(self) -> dict[str, list[TransferPlan]]:
        """
        Generate rebalancing plans for ALL skewed assets.
        Returns {asset: [TransferPlan, ...]}
        """
        plans_map = {}
        skewed_assets = self.check_all()

        for item in skewed_assets:
            asset = item["asset"]
            plans = self.plan(asset)
            if plans:
                plans_map[asset] = plans

        return plans_map

    def estimate_cost(self, plans: list[TransferPlan]) -> dict:
        """
        Estimate total cost of executing rebalance plans.

        Returns:
        {
            'total_transfers': int,
            'total_fees_usd': Decimal,
            'total_time_min': int,  # Max of all transfer times (parallel)
            'assets_affected': list[str],
        }
        """
        total_fees = Decimal("0")
        prices = {"ETH": Decimal("2000"), "USDT": Decimal("1"), "USDC": Decimal("1")}
        max_time = 0
        assets = set()

        for p in plans:
            price = prices.get(p.asset, Decimal("0"))
            usd_fee = p.estimated_fee * price
            total_fees += usd_fee

            if p.estimated_time_min > max_time:
                max_time = p.estimated_time_min
            assets.add(p.asset)

        return {
            "total_transfers": len(plans),
            "total_fees_usd": total_fees,
            "total_time_min": max_time,
            "assets_affected": list(assets),
        }
