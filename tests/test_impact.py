import pytest
from decimal import Decimal
from core.types import Address
from pricing.amm import UniswapV2Pair, PriceImpactAnalyzer

WETH = Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
USDC = Address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")


@pytest.fixture
def pair():
    """
    Standard Pool: 1,000 ETH / 2,000,000 USDC
    Spot Price: 2000 USDC/ETH
    """
    return UniswapV2Pair(
        address=Address("0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc"),
        token0=WETH,
        token1=USDC,
        reserve0=1000 * 10**18,
        reserve1=2_000_000 * 10**6,
    )


def test_price_impact_scaling(pair):
    """
    Requirements Covered:
    - Price impact calculation correct for various sizes
    """

    small_input = 1 * 10**17  # 0.1 ETH
    impact_small = pair.get_price_impact(small_input, WETH)

    large_input = 100 * 10**18  # 100 ETH
    impact_large = pair.get_price_impact(large_input, WETH)

    assert impact_small > Decimal("0.003")
    assert impact_small < Decimal("0.004")

    assert impact_large > Decimal("0.05")
    assert impact_large > impact_small


def test_impact_table_generation(pair):
    """Verify the impact table generates correct rows."""
    analyzer = PriceImpactAnalyzer(pair)
    sizes = [1 * 10**18, 10 * 10**18]  # 1 ETH, 10 ETH

    table = analyzer.generate_impact_table(WETH, sizes)

    assert len(table) == 2
    assert table[0]["amount_in"] == sizes[0]
    assert table[0]["price_impact_pct"] > 0
    assert table[0]["spot_price"] == table[1]["spot_price"]
