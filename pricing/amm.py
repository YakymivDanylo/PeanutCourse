from decimal import Decimal
from eth_utils import function_signature_to_4byte_selector
from eth_abi import decode
from chain.client import ChainClient
from core.types import Address, TransactionRequest, TokenAmount

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
        """Helper to get (reserve_in, reserve_out) from input token."""

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
        reserve_in, reserve_out = self._get_reserve(token_in)
        if reserve_in == 0:
            return Decimal(0)
        return Decimal(reserve_out) / Decimal(reserve_in)

    def get_execution_price(self, amount_in: int, token_in: Address) -> Decimal:
        """
        Returns actual execution price for given trade size.
        """
        if amount_in == 0:
            return self.get_spot_price(token_in)

        amount_out = self.get_amount_out(amount_in, token_in)
        return Decimal(amount_out) / Decimal(amount_in)

    def get_price_impact(self, amount_in: int, token_in: Address) -> Decimal:
        """
        Returns price impact as a decimal (0.01 = 1%).
        """
        spot = self.get_spot_price(token_in)
        if spot == 0:
            return Decimal(0)

        exec_price = self.get_execution_price(amount_in, token_in)
        return (spot - exec_price) / spot

    def simulate_swap(self, amount_in: int, token_in: Address) -> "UniswapV2Pair":
        """
        Returns a NEW pair with updated reserves after the swap.
        (Useful for multi-hop simulation)
        """
        amount_out = self.get_amount_out(amount_in, token_in)
        new_reserve0 = self.reserve0
        new_reserve1 = self.reserve1

        if token_in == self.token0:
            new_reserve0 += amount_in
            new_reserve1 -= amount_out
        else:
            new_reserve1 += amount_in
            new_reserve0 -= amount_out

        return UniswapV2Pair(
            address=self.address,
            token0=self.token0,
            token1=self.token1,
            reserve0=new_reserve0,
            reserve1=new_reserve1,
            fee_bps=self.fee_bps,
            symbol=self.symbol,
        )

    @classmethod
    def from_chain(cls, address: Address, client: ChainClient) -> "UniswapV2Pair":
        """
        Fetch pair data from on-chain.
        """

        # Selectors
        sel_token0 = function_signature_to_4byte_selector("token0()")
        sel_token1 = function_signature_to_4byte_selector("token1()")
        sel_reserve = function_signature_to_4byte_selector("getReserve()")

        # Creation of requests
        req_t0 = TransactionRequest(
            to=address, value=TokenAmount(0, 18), data=sel_token0
        )
        req_t1 = TransactionRequest(
            to=address, value=TokenAmount(0, 18), data=sel_token1
        )
        req_res = TransactionRequest(
            to=address, value=TokenAmount(0, 18), data=sel_reserve
        )

        # Call RPC
        raw_t0 = client.call(req_t0)
        raw_t1 = client.call(req_t1)
        raw_res = client.call(req_res)

        # Decode
        token0_addr = decode(["address"], raw_t0)[0]
        token1_addr = decode(["address"], raw_t1)[0]
        reserves = decode(["uint112", "uint112", "uint32"], raw_res)

        return cls(
            address=address,
            token0=token0_addr,
            token1=token1_addr,
            reserve0=reserves[0],
            reserve1=reserves[1],
        )

    def __repr__(self):
        return (
            f"<UniswapV2Pair {self.symbol}" f"R0={self.reserve0}, R1={self.reserve1}>"
        )
