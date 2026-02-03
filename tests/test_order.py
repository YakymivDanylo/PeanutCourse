import pytest
from decimal import Decimal
from exchange.orderbook import OrderBookAnalyzer


@pytest.fixture
def sample_orderbook():
    return {
        "symbol": "ETH/USDT",
        "timestamp": 1700000000000,
        "bids": [(Decimal("2000"), Decimal("1.0")), (Decimal("1990"), Decimal("2.0"))],
        "asks": [(Decimal("2010"), Decimal("1.0")), (Decimal("2020"), Decimal("2.0"))],
        "best_bid": (Decimal("2000"), Decimal("1.0")),
        "best_ask": (Decimal("2010"), Decimal("1.0")),
        "mid_price": Decimal("2005"),
        "spread_bps": Decimal("49.75"),
    }


@pytest.fixture
def analyzer(sample_orderbook):
    return OrderBookAnalyzer(sample_orderbook)


def test_walk_the_book_exact_fill(analyzer):
    """Fill exactly at one price level."""
    result = analyzer.walk_the_book("buy", 1.0)

    assert result["fully_filled"] is True
    assert result["levels_consumed"] == 1
    assert result["avg_price"] == Decimal("2010")
    assert result["total_cost"] == Decimal("2010")


def test_walk_the_book_multiple_levels(analyzer):
    """Fill across multiple price levels, avg price correct."""

    result = analyzer.walk_the_book("buy", 2.0)

    assert result["levels_consumed"] == 2
    assert result["total_cost"] == Decimal("4030")
    assert result["avg_price"] == Decimal("2015")
    assert result["fully_filled"] is True


def test_walk_the_book_insufficient_liquidity(analyzer):
    """Returns fully_filled=False when book is too thin."""
    result = analyzer.walk_the_book("buy", 100.0)

    assert result["fully_filled"] is False
    fills_qty = sum(f["qty"] for f in result["fills"])
    assert fills_qty == Decimal("3.0")


def test_depth_at_bps_correct(analyzer):
    """Depth at 10 bps matches manual calculation."""

    depth = analyzer.depth_at_bps("bid", 100)
    assert depth == Decimal("3.0")

    depth_tight = analyzer.depth_at_bps("bid", 2)
    assert depth_tight == Decimal("1.0")


def test_imbalance_range(analyzer):
    """Imbalance always in [-1.0, +1.0]."""
    imb = analyzer.imbalance()

    assert isinstance(imb, float)
    assert -1.0 <= imb <= 1.0

    assert imb == 0.0


def test_effective_spread_greater_than_quoted(analyzer, sample_orderbook):
    """Effective spread >= quoted spread for any qty > 0."""
    quoted_spread = sample_orderbook["spread_bps"]

    eff_spread = analyzer.effective_spread(3.0)

    assert eff_spread > quoted_spread
    assert eff_spread > 0
