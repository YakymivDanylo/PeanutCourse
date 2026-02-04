from decimal import Decimal

import pytest

from inventory.rebalancer import RebalancePlanner, TransferPlan
from inventory.tracker import InventoryTracker, Venue


@pytest.fixture
def tracker() -> InventoryTracker:
    return InventoryTracker()


@pytest.fixture
def planner(tracker: InventoryTracker) -> RebalancePlanner:
    return RebalancePlanner(tracker)


def test_check_detects_skewed_asset(
    tracker: InventoryTracker, planner: RebalancePlanner
):
    """Asset with 85/15 split flagged for rebalance."""

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "ETH": {
                "free": Decimal("85.0"),
                "locked": Decimal("0"),
                "total": Decimal("85.0"),
            }
        },
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("15.0")})

    results = planner.check_all()
    eth_result = next((r for r in results if r["asset"] == "ETH"), None)
    assert eth_result is not None
    assert eth_result["needs_rebalance"] is True
    assert eth_result["max_deviation_pct"] == 35.0


def test_check_passes_balanced_asset(
    tracker: InventoryTracker, planner: RebalancePlanner
):
    """Asset with 55/45 split not flagged."""

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "ETH": {
                "free": Decimal("55.0"),
                "locked": Decimal("0"),
                "total": Decimal("55.0"),
            }
        },
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("45.0")})

    results = planner.check_all()

    assert len(results) == 0


def test_plan_generates_correct_transfer(
    tracker: InventoryTracker, planner: RebalancePlanner
):
    """Plan moves the right amount in the right direction."""

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "ETH": {
                "free": Decimal("90.0"),
                "locked": Decimal("0"),
                "total": Decimal("90.0"),
            }
        },
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("10.0")})

    plans = planner.plan("ETH")

    assert len(plans) == 1
    plan = plans[0]

    assert plan.from_venue == Venue.BINANCE
    assert plan.to_venue == Venue.WALLET
    assert plan.amount == Decimal("40.0")
    assert plan.asset == "ETH"


def test_plan_respects_min_operating_balance(
    tracker: InventoryTracker, planner: RebalancePlanner
):
    """Never plans transfer that leaves venue below minimum."""

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "ETH": {
                "free": Decimal("0.6"),
                "locked": Decimal("0"),
                "total": Decimal("0.6"),
            }
        },
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("0.0")})

    plans = planner.plan("ETH")

    assert len(plans) == 1
    assert plans[0].amount == Decimal("0.1")


def test_plan_accounts_for_fees(tracker: InventoryTracker, planner: RebalancePlanner):
    """Net amount received = amount - fee."""

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "USDT": {
                "free": Decimal("1000.0"),
                "locked": Decimal("0"),
                "total": Decimal("1000.0"),
            }
        },
    )
    tracker.update_from_wallet(Venue.WALLET, {"USDT": Decimal("0.0")})

    plans = planner.plan("USDT")
    assert len(plans) == 1

    plan = plans[0]
    expected_fee = Decimal("1.0")

    assert plan.estimated_fee == expected_fee
    assert plan.net_amount == plan.amount - expected_fee


def test_plan_empty_when_balanced(tracker: InventoryTracker, planner: RebalancePlanner):
    """No plans generated for balanced assets."""

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "ETH": {
                "free": Decimal("50.0"),
                "locked": Decimal("0"),
                "total": Decimal("50.0"),
            }
        },
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("50.0")})

    plans = planner.plan("ETH")
    assert plans == []


def test_estimate_cost_sums_correctly(
    tracker: InventoryTracker, planner: RebalancePlanner
):
    """Total fees and time calculated correctly."""

    plan_eth = TransferPlan(
        from_venue=Venue.BINANCE,
        to_venue=Venue.WALLET,
        asset="ETH",
        amount=Decimal("1.0"),
        estimated_fee=Decimal("0.005"),
        estimated_time_min=15,
    )

    plan_usdt = TransferPlan(
        from_venue=Venue.WALLET,
        to_venue=Venue.BINANCE,
        asset="USDT",
        amount=Decimal("100.0"),
        estimated_fee=Decimal("1.0"),
        estimated_time_min=10,
    )

    cost_report = planner.estimate_cost([plan_eth, plan_usdt])

    assert cost_report["total_fees_usd"] == Decimal("11.0")

    assert cost_report["total_time_min"] == 15

    assert cost_report["total_transfers"] == 2
