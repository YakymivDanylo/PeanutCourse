from decimal import Decimal

import pytest

from inventory.tracker import InventoryTracker, Venue


@pytest.fixture
def tracker() -> InventoryTracker:
    return InventoryTracker()


def test_snapshot_aggregates_across_venues(tracker: InventoryTracker):
    """Total ETH = Binance ETH + Wallet ETH."""

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "ETH": {"free": Decimal("2.0"), "locked": Decimal("1.0")},
            "USDT": {"free": Decimal("100.0"), "locked": Decimal("0")},
        },
    )
    tracker.update_from_wallet(
        Venue.WALLET, {"ETH": Decimal("5.0"), "USDC": Decimal("200.0")}
    )

    prices = {"ETH": Decimal("2000.0"), "USDT": Decimal("1.0"), "USDC": Decimal("1.0")}

    snap = tracker.snapshot(prices=prices)

    assert snap["totals"]["ETH"] == Decimal("8.0")
    assert snap["totals"]["USDT"] == Decimal("100.0")
    assert snap["totals"]["USDC"] == Decimal("200.0")

    assert snap["venues"]["binance"]["ETH"]["total"] == Decimal("3.0")
    assert snap["venues"]["wallet"]["ETH"]["free"] == Decimal("5.0")

    assert snap["total_usd"] == 16300


def test_can_execute_passes_when_sufficient(tracker: InventoryTracker):
    """Returns can_execute=True with enough balance on both sides."""

    tracker.update_from_cex(
        Venue.BINANCE, {"USDT": {"free": Decimal("100.0"), "locked": Decimal("0")}}
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("1.0")})

    # Check if we can Spend 50 USDT on Binance and Spend 0.5 ETH on Wallet
    result = tracker.can_execute(
        buy_venue=Venue.BINANCE,
        buy_asset="USDT",
        buy_amount=Decimal("50.0"),
        sell_venue=Venue.WALLET,
        sell_asset="ETH",
        sell_amount=Decimal("0.5"),
    )

    assert result["can_execute"] is True

    assert result["reason"] is None


def test_can_execute_fails_insufficient_buy(tracker: InventoryTracker):
    """Returns can_execute=False when buy venue lacks funds."""

    # Have only 10 USDT on Binance
    tracker.update_from_cex(
        Venue.BINANCE, {"USDT": {"free": Decimal("10.0"), "locked": Decimal("0")}}
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("1.0")})

    result = tracker.can_execute(
        buy_venue=Venue.BINANCE,
        buy_asset="USDT",
        buy_amount=Decimal("50.0"),
        sell_venue=Venue.WALLET,
        sell_asset="ETH",
        sell_amount=Decimal("0.5"),
    )

    assert result["can_execute"] is False
    assert "Insufficient USDT on binance" in result["reason"]


def test_can_execute_fails_insufficient_sell(tracker: InventoryTracker):
    """Returns can_execute=False when sell venue lacks asset."""

    # Have 100 USDT on Binance, but 0 ETH on Wallet
    tracker.update_from_cex(
        Venue.BINANCE, {"USDT": {"free": Decimal("100.0"), "locked": Decimal("0")}}
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("0.0")})

    result = tracker.can_execute(
        buy_venue=Venue.BINANCE,
        buy_asset="USDT",
        buy_amount=Decimal("50.0"),
        sell_venue=Venue.WALLET,
        sell_asset="ETH",
        sell_amount=Decimal("0.5"),
    )

    assert result["can_execute"] is False
    assert "Insufficient ETH on wallet" in result["reason"]


def test_record_trade_updates_balances(tracker: InventoryTracker):
    """After buy trade: base increases, quote decreases, fee deducted."""

    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "USDT": {"free": Decimal("1000.0"), "locked": Decimal("0")},
            "ETH": {"free": Decimal("0.0"), "locked": Decimal("0")},
            "BNB": {"free": Decimal("1.0"), "locked": Decimal("0")},
        },
    )

    tracker.record_trade(
        venue=Venue.BINANCE,
        side="buy",
        base_asset="ETH",
        quote_asset="USDT",
        base_amount=Decimal("0.1"),
        quote_amount=Decimal("200.0"),
        fee=Decimal("0.01"),
        fee_asset="BNB",
    )

    assert tracker.get_available(Venue.BINANCE, "ETH") == Decimal("0.1")
    assert tracker.get_available(Venue.BINANCE, "USDT") == Decimal("800.0")
    assert tracker.get_available(Venue.BINANCE, "BNB") == Decimal("0.99")


def test_skew_detects_imbalance(tracker: InventoryTracker):
    """80/20 split shows >30% deviation."""
    tracker.update_from_cex(
        Venue.BINANCE,
        {
            "ETH": {"free": Decimal("85.0"), "locked": Decimal("0")},
        },
    )

    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("15.0")})

    skew = tracker.skew("ETH")

    assert skew["total"] == Decimal("100.0")
    assert skew["needs_rebalance"] is True
    assert skew["max_deviation_pct"] == 35.0


def test_skew_balanced(tracker: InventoryTracker):
    """50/50 split shows ~0% deviation."""
    tracker.update_from_cex(
        Venue.BINANCE, {"ETH": {"free": Decimal("50.0"), "locked": Decimal("0")}}
    )
    tracker.update_from_wallet(Venue.WALLET, {"ETH": Decimal("50.0")})

    skew = tracker.skew("ETH")

    assert skew["needs_rebalance"] is False
    assert skew["max_deviation_pct"] == 0.0
