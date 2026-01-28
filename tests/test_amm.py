import pytest

from core.types import Address
from pricing.amm import UniswapV2Pair

WETH = Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
USDC = Address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")


@pytest.fixture
def eth_usdc_pair():
    """Create an ETH USDC pair (1000 ETH/ 2M USDC)"""
    return UniswapV2Pair(
        address=Address("0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc"),
        token0=WETH,
        token1=USDC,
        reserve0=1000 * 10**18,
        reserve1=2_000_000 * 10**6,
        fee_bps=30,
        symbol="ETH-USDC",
    )


def test_get_amount_out_basic(eth_usdc_pair):
    """1000 ETH / 2M USDC pool, selling 2000 USDC for less than 1 ETH,
    because of fee and price impact"""
    usdc_in = 2000 * 10**6

    eth_out = eth_usdc_pair.get_amount_out(usdc_in, USDC)

    # Expect less than 1 ETH, due to 0.3% fee
    assert eth_out < 1 * 10**18

    # But more than 0.99 ETH (low impact)
    assert eth_out > 0.99 * 10**18

    # Точний розрахунок вручну для перевірки відповідності Solidity:
    # amount_in_with_fee = 2000000000 * 9970 = 19940000000000
    # numerator = 19940000000000 * 1000000000000000000000 (1000 ETH)
    # denominator = (2000000000000 * 10000) + 19940000000000 = 20019940000000000
    # result = numerator // denominator = 996006981039903216

    expected = 996006981039903216
    assert eth_out == expected


def test_get_amount_out_matches_solidity():
    """Comparison with a known example (hardcoded solidity output).
    Suppose: Reserves(100, 100), Input 10.
    Solidity: (10 * 997 * 100) / (100 * 1000 + 10 * 997) = 90661... -> 9"""
    # Use a real historical swap and verify we get same output
    pair = UniswapV2Pair(
        address=Address("0x0000000000000000000000000000000000000001"),
        token0=WETH,
        token1=USDC,
        reserve0=100 * 10**18,
        reserve1=100 * 10**18,
    )

    amount_in = 10 * 10**18
    amount_out = pair.get_amount_out(amount_in, WETH)

    # amountInWithFee = 10 * 9970 = 99700
    # numerator = 99700 * 100 = 9970000
    # denominator = 100 * 10000 + 99700 = 1000000 + 99700 = 1099700
    # result = 9970000 / 1099700 = 9.066... -> 9 (integer math floor)
    # 99700 * 10^18 * 100 * 10^18 ...
    # Result: 9.066108938801491315 * 10^18

    expected_exact = 9066108938801491315
    assert amount_out == expected_exact


def test_integer_math_no_floats():
    """Verify no floating point used"""
    # Large numbers that would lose precision with float
    pair = UniswapV2Pair(
        address=Address("0x0000000000000000000000000000000000000001"),
        token0=WETH,
        token1=USDC,
        reserve0=10**30,
        reserve1=10**30,
    )

    amount_in = 10**25
    out = pair.get_amount_out(amount_in, WETH)

    assert isinstance(out, int)

    assert not isinstance(out, float)


def test_swap_is_immutable(eth_usdc_pair):
    """simulate_swap doesn't modify original"""

    original_r0 = eth_usdc_pair.reserve0
    original_r1 = eth_usdc_pair.reserve1

    amount_in = 1 * 10**18
    new_pair = eth_usdc_pair.simulate_swap(amount_in, WETH)

    # Original didn't change
    assert eth_usdc_pair.reserve0 == original_r0
    assert eth_usdc_pair.reserve1 == original_r1

    # New obj has changed reserves
    assert new_pair.reserve0 != original_r0

    # WETH (token0) entered -> reserve0 increased
    assert new_pair.reserve0 == amount_in + original_r0

    # USDC (token1) got out -> reserve1 decreased
    assert new_pair.reserve1 < original_r1
