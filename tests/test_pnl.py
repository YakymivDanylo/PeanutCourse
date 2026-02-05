import csv
from datetime import datetime
from decimal import Decimal

import pytest

from inventory.pnl import TradeLeg, ArbRecord, PnLEngine
from inventory.tracker import Venue


@pytest.fixture
def mock_trade_legs():
    """Returns basic Buy/Sell legs for testing."""
    ts = datetime.now()
    buy = TradeLeg(
        id="leg1",
        timestamp=ts,
        venue=Venue.BINANCE,
        symbol="ETH/USDT",
        side="buy",
        amount=Decimal("1.0"),
        price=Decimal("2000.0"),
        fee=Decimal("2.0"),
        fee_asset="USDT",
    )
    sell = TradeLeg(
        id="leg2",
        timestamp=ts,
        venue=Venue.WALLET,
        symbol="ETH/USDT",
        side="sell",
        amount=Decimal("1.0"),
        price=Decimal("2010.0"),
        fee=Decimal("1.5"),
        fee_asset="USDT",
    )
    return buy, sell


def test_gross_pnl_calculation(mock_trade_legs):
    """Gross PnL = sell revenue - buy cost."""
    buy, sell = mock_trade_legs
    arb = ArbRecord(
        id="tx1",
        timestamp=buy.timestamp,
        buy_leg=buy,
        sell_leg=sell,
        gas_cost_usd=Decimal("0"),
    )

    assert arb.gross_pnl == Decimal("10")


def test_net_pnl_includes_all_fees(mock_trade_legs):
    """Net PnL = gross - buy fee - sell fee - gas."""
    buy, sell = mock_trade_legs
    gas = Decimal("3.0")
    arb = ArbRecord(
        id="tx1", timestamp=buy.timestamp, buy_leg=buy, sell_leg=sell, gas_cost_usd=gas
    )

    assert arb.total_fees == Decimal("6.5")
    assert arb.net_pnl == Decimal("3.5")


def test_pnl_bps_calculation(mock_trade_legs):
    """PnL bps = net_pnl / notional * 10000."""
    buy, sell = mock_trade_legs
    gas = Decimal("3.0")
    arb = ArbRecord(
        id="tx1", timestamp=buy.timestamp, buy_leg=buy, sell_leg=sell, gas_cost_usd=gas
    )

    # Net PnL: 3.5
    # Notional: 2000.0
    # Ratio: 3.5 / 2000 = 0.00175
    # Bps: 0.00175 * 10000 = 17.5
    assert arb.notional == Decimal("2000.0")
    assert arb.net_pnl_bps == Decimal("17.5")


def test_summary_win_rate(mock_trade_legs):
    """Win rate = profitable trades / total trades."""
    buy, sell = mock_trade_legs
    engine = PnLEngine()

    # Trade 1: Winner (Net +3.5 see previous test)
    t1 = ArbRecord(
        id="1",
        timestamp=buy.timestamp,
        buy_leg=buy,
        sell_leg=sell,
        gas_cost_usd=Decimal("3.0"),
    )
    engine.record(t1)

    # Trade 2: Loser
    # Sell price 1990 (Loss 10 gross), Fees 6.5 -> Net -16.5
    loss_sell = TradeLeg(
        id="leg3",
        timestamp=datetime.now(),
        venue=Venue.WALLET,
        symbol="ETH/USDT",
        side="sell",
        amount=Decimal("1.0"),
        price=Decimal("1990.0"),
        fee=Decimal("1.5"),
        fee_asset="USDT",
    )
    t2 = ArbRecord(
        id="2",
        timestamp=buy.timestamp,
        buy_leg=buy,
        sell_leg=loss_sell,
        gas_cost_usd=Decimal("3.0"),
    )
    engine.record(t2)

    stats = engine.summary()
    assert stats["total_trades"] == 2
    assert stats["win_rate"] == 50.0
    assert stats["total_pnl_usd"] == t1.net_pnl + t2.net_pnl


def test_summary_with_no_trades(mock_trade_legs):
    """Summary returns zeros, no division errors."""
    engine = PnLEngine()
    stats = engine.summary()

    assert stats["total_trades"] == 0
    assert stats["total_pnl_usd"] == Decimal("0")
    assert stats["win_rate"] == 0.0
    assert stats["sharpe_estimate"] == 0.0


def test_export_csv_format(mock_trade_legs, tmp_path):
    """CSV has expected columns and correct values."""
    buy, sell = mock_trade_legs
    engine = PnLEngine()
    t1 = ArbRecord(
        id="csv_test",
        timestamp=buy.timestamp,
        buy_leg=buy,
        sell_leg=sell,
        gas_cost_usd=Decimal("1.0"),
    )
    engine.record(t1)

    csv_file = tmp_path / "test_export.csv"
    engine.export_csv(str(csv_file))

    assert csv_file.exists()

    with open(csv_file, "r") as f:
        reader = csv.reader(f)
        rows = list(reader)

    assert rows[0] == [
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

    data_row = rows[1]
    assert data_row[0] == "csv_test"
    assert data_row[3] == "binance"
    assert data_row[5] == "wallet"
    assert data_row[9] == "1.0"
