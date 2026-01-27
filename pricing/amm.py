from decimal import Decimal

from chain.client import ChainClient
from core.types import Address

FEE_BPS = 30
BPS_DENOMINATOR = 10000


class UniswapV2Pair:
    """
    Represents a Uniswap V2 liquidity pair.
    All math uses integers only — no floats anywhere.
    """

    def __init__(
        self,
        address: Address,
        token0: Address,
        token1: Address,
        reserve0: int,
        reserve1: int,
        fee_bps: int = FEE_BPS,  # 0.30% = 30 basis points
        symbol: str = "UNI-V2",
    ):
        self.address = address
        self.token0 = token0
        self.token1 = token1
        self.reserve0 = reserve0
        self.reserve1 = reserve1
        self.fee_bps = fee_bps
        self.symbol = symbol

    def _get_reserve(self, token_in: Address) -> tuple[int, int]:
        """Helper to get (reserve_in, reserve_out) from input token.)"""

        if token_in == self.token0:
            return self.reserve0, self.reserve1
        elif token_in == self.token1:
            return self.reserve1, self.reserve0
        else:
            raise ValueError(f"Token {token_in.value} not in pair {self.address.value}")

    def get_amount_out(self, amount_in: int, token_in: Address) -> int:
        """
        Calculate output amount for a given input.
        Must match Solidity exactly:

        amount_in_with_fee = amount_in * (10000 - fee_bps)
        numerator = amount_in_with_fee * reserve_out
        denominator = reserve_in * 10000 + amount_in_with_fee
        amount_out = numerator // denominator
        """
        if amount_in < 0:
            raise ValueError("Insufficient input amount")

        reserve_in, reserve_out = self._get_reserve(token_in)

        if reserve_in < 0 or reserve_out < 0:
            raise ValueError("Insufficient liquidity")

        amount_in_with_fee = amount_in * (BPS_DENOMINATOR - self.fee_bps)
        numerator = reserve_out * amount_in_with_fee
        denominator = reserve_in * BPS_DENOMINATOR + amount_in_with_fee

        return numerator // denominator

    def get_amount_in(self, amount_out: int, token_out: Address) -> int:
        """
        Calculate required input for desired output.
        (Inverse of get_amount_out)
        """
        if amount_out < 0:
            raise ValueError("Insufficient output amount")

        if token_out == self.token0:
            reserve_in, reserve_out = self.reserve0, self.reserve1
        elif token_out == self.token1:
            reserve_in, reserve_out = self.reserve1, self.reserve0
        else:
            raise ValueError(f"Token {token_out.value} not in pair")

        if reserve_in < 0 or reserve_out < 0:
            raise ValueError("Insufficient liquidity")
        if amount_out >= reserve_out:
            raise ValueError("Insufficient liquidity for output token")

        numerator = reserve_in * FEE_BPS * amount_out
        denominator = (reserve_out - amount_out) * (BPS_DENOMINATOR - self.fee_bps)

        return (numerator // denominator) + 1

    def get_spot_price(self, token_in: Address) -> Decimal:
        """
        Returns spot price (for display only, not calculations).
        """
        ...

    def get_execution_price(self, amount_in: int, token_in: Address) -> Decimal:
        """
        Returns actual execution price for given trade size.
        """
        ...

    def get_price_impact(self, amount_in: int, token_in: Address) -> Decimal:
        """
        Returns price impact as a decimal (0.01 = 1%).
        """
        ...

    def simulate_swap(self, amount_in: int, token_in: Address) -> "UniswapV2Pair":
        """
        Returns a NEW pair with updated reserves after the swap.
        (Useful for multi-hop simulation)
        """
        ...

    @classmethod
    def from_chain(cls, address: Address, client: ChainClient) -> "UniswapV2Pair":
        """
        Fetch pair data from on-chain.
        """
        ...
