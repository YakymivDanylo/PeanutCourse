import pytest
from decimal import Decimal
from exchange.orderbook import OrderBookAnalyzer


# Створюємо тестовий стакан для всіх тестів
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
    # Купуємо 1.0 ETH. Це рівно стільки, скільки є на першому рівні Asks (2010)
    result = analyzer.walk_the_book("buy", 1.0)

    assert result["fully_filled"] is True
    assert result["levels_consumed"] == 1
    assert result["avg_price"] == Decimal("2010")
    assert result["total_cost"] == Decimal("2010")


def test_walk_the_book_multiple_levels(analyzer):
    """Fill across multiple price levels, avg price correct."""
    # Купуємо 2.0 ETH.
    # 1.0 @ 2010 = 2010
    # 1.0 @ 2020 = 2020
    # Total = 4030. Avg = 2015
    result = analyzer.walk_the_book("buy", 2.0)

    assert result["levels_consumed"] == 2
    assert result["total_cost"] == Decimal("4030")
    assert result["avg_price"] == Decimal("2015")
    assert result["fully_filled"] is True


def test_walk_the_book_insufficient_liquidity(analyzer):
    """Returns fully_filled=False when book is too thin."""
    # Купуємо 100 ETH. У стакані всього 1.0 + 2.0 = 3.0 ETH
    result = analyzer.walk_the_book("buy", 100.0)

    assert result["fully_filled"] is False
    # Перевіряємо, що купили все, що було (3.0 ETH)
    fills_qty = sum(f["qty"] for f in result["fills"])
    assert fills_qty == Decimal("3.0")


def test_depth_at_bps_correct(analyzer):
    """Depth at 10 bps matches manual calculation."""
    # 100 bps = 1%.
    # Для Bids (2000): 1% вниз = 1980.
    # Обидва біди (2000 і 1990) вищі за 1980.
    # Тож глибина має бути 1.0 + 2.0 = 3.0

    depth = analyzer.depth_at_bps("bid", 100)  # 100 bps
    assert depth == Decimal("3.0")

    # Для дуже малого bps (наприклад 2 bps ~ 0.02%)
    # Поріг: 2000 * (1 - 0.0002) = 1999.6
    # Тільки перший бід (2000) потрапляє. Другий (1990) - ні.
    depth_tight = analyzer.depth_at_bps("bid", 2)
    assert depth_tight == Decimal("1.0")


def test_imbalance_range(analyzer):
    """Imbalance always in [-1.0, +1.0]."""
    imb = analyzer.imbalance()

    assert isinstance(imb, float)
    assert -1.0 <= imb <= 1.0

    # У нашому прикладі: Bids Vol = 3.0, Asks Vol = 3.0
    # Imbalance = (3 - 3) / 6 = 0
    assert imb == 0.0


def test_effective_spread_greater_than_quoted(analyzer, sample_orderbook):
    """Effective spread >= quoted spread for any qty > 0."""
    # Quoted spread (звичайний) базується на найкращих цінах (2000 vs 2010)
    quoted_spread = sample_orderbook["spread_bps"]

    # Effective spread для об'єму 3.0 ETH
    # Середня ціна купівлі буде вищою за 2010
    # Середня ціна продажу буде нижчою за 2000
    # Отже, effective spread має бути ширшим (більшим)
    eff_spread = analyzer.effective_spread(3.0)

    assert eff_spread > quoted_spread
    assert eff_spread > 0
