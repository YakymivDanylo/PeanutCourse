import pytest
from core.types import Address
from pricing.amm import UniswapV2Pair
from pricing.routing import Route, RouteFinder

SHIB = Address("0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE")
ETH = Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
USDC = Address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
WBTC = Address("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599")


def get_pool_addr(i):
    return Address("0x" + str(i).zfill(40))


@pytest.fixture
def shib_eth_usdc_pools():
    """
    Setup pools where SHIB -> ETH -> USDC is better than SHIB -> USDC direct.
    index 0: SHIB-USDC (Direct, Bad Price)
    index 1: SHIB-ETH (Hop 1)
    index 2: ETH-USDC (Hop 2)
    """
    pair_direct = UniswapV2Pair(
        get_pool_addr(1),
        SHIB,
        USDC,
        reserve0=10_000_000_000 * 10**18,
        reserve1=10_000 * 10**6,
        symbol="SHIB-USDC",
    )

    pair_shib_eth = UniswapV2Pair(
        get_pool_addr(2),
        SHIB,
        ETH,
        reserve0=10_000_000_000 * 10**18,
        reserve1=10 * 10**18,
        symbol="SHIB-ETH",
    )

    pair_eth_usdc = UniswapV2Pair(
        get_pool_addr(3),
        ETH,
        USDC,
        reserve0=10 * 10**18,
        reserve1=20_000 * 10**6,
        symbol="ETH-USDC",
    )

    return [pair_direct, pair_shib_eth, pair_eth_usdc]


def test_route_output_matches_sequential_swaps(shib_eth_usdc_pools):
    """Route simulation equals doing swaps one by one"""
    # Route: SHIB -> ETH -> USDC
    pools = [shib_eth_usdc_pools[1], shib_eth_usdc_pools[2]]
    route = Route(pools, [SHIB, ETH, USDC])

    amount_in = 1_000_000 * 10**18  # 1M SHIB

    # 1. Calculate via Route
    route_output = route.get_output(amount_in)

    # 2. Calculate Sequentially
    eth_out = shib_eth_usdc_pools[1].get_amount_out(amount_in, SHIB)
    usdc_out = shib_eth_usdc_pools[2].get_amount_out(eth_out, ETH)

    assert route_output == usdc_out
    assert route.num_hops == 2


def test_direct_vs_multihop(shib_eth_usdc_pools):
    """Sometimes multi-hop is better despite gas"""
    finder = RouteFinder(shib_eth_usdc_pools)
    amount_in = 1_000_000_000 * 10**18  # 1B SHIB

    best_route, net_output = finder.find_best_route(
        SHIB, USDC, amount_in, gas_price_gwei=10
    )

    # Expect multi-hop (SHIB->ETH->USDC)
    assert best_route.num_hops == 2
    assert len(best_route.pools) == 2
    assert best_route.path == [SHIB, ETH, USDC]


def test_gas_makes_direct_better(shib_eth_usdc_pools):
    """At high gas prices, fewer hops win"""
    finder = RouteFinder(shib_eth_usdc_pools)
    amount_in = 1_000_000_000 * 10**18  # 1B SHIB

    best_route, net_output = finder.find_best_route(
        SHIB, USDC, amount_in, gas_price_gwei=50000
    )

    # Expect direct route because gas cost of extra hop is too high
    assert best_route.num_hops == 1
    assert best_route.path == [SHIB, USDC]


def test_no_route_exists():
    """Handle disconnected tokens gracefully"""
    # Pool A-B
    pair_ab = UniswapV2Pair(get_pool_addr(10), SHIB, ETH, 100, 100)
    # Pool C-D (USDC-WBTC) - disconnected from SHIB/ETH
    pair_cd = UniswapV2Pair(get_pool_addr(11), USDC, WBTC, 100, 100)

    finder = RouteFinder([pair_ab, pair_cd])

    # Try to find route from SHIB to WBTC (impossible)
    route, output = finder.find_best_route(SHIB, WBTC, 10, gas_price_gwei=10)

    assert route is None
    assert output == 0
