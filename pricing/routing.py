from core.types import Address
from pricing.amm import UniswapV2Pair

GAS_BASE_SWAP = 100_000
GAS_PER_HOP = 50_000
WETH_ADDRESS = Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")


class Route:
    """Represents a swap route through one or more pools."""

    def __init__(self, pools: list[UniswapV2Pair], path: list[Address]):
        if len(pools) != len(path) - 1:
            raise ValueError("Path length must be pools length + 1")

        self.pools = pools  # List of pairs to swap through
        self.path = path  # token_in → intermediate... → token_out

    @property
    def num_hops(self) -> int:
        return len(self.pools)

    @property
    def token_in(self) -> Address:
        return self.path[0]

    @property
    def token_out(self) -> Address:
        return self.path[-1]

    def get_output(self, amount_in: int) -> int:
        """Simulate full route, return final output."""
        current_amount = amount_in
        for i, pair in enumerate(self.pools):
            current_amount = pair.get_amount_out(current_amount, self.path[i])

        return current_amount

    def get_intermediate_amounts(self, amount_in: int) -> list[int]:
        """Return amount at each step: [input, after_hop1, after_hop2, ...]"""
        amounts = [amount_in]

        current_amount = amount_in
        for i, pair in enumerate(self.pools):
            current_amount = pair.get_amount_out(current_amount, self.path[i])
            amounts.append(current_amount)
        return amounts

    def estimate_gas(self) -> int:
        """Estimate gas: ~150k base + ~100k per hop."""
        # hop = BASE
        # hops = BASE + Per_Hop
        extra_hops = max(0, self.num_hops - 1)

        return GAS_BASE_SWAP + GAS_PER_HOP * extra_hops


class RouteFinder:
    """
    Finds optimal routes between tokens.
    """

    def __init__(self, pools: list[UniswapV2Pair]):
        self.pools = pools
        self.graph = self._build_graph()

    def _build_graph(self) -> dict:
        """
        Build adjacency graph: token → [(pool, other_token), ...]
        """
        ...

    def find_all_routes(
        self, token_in: Address, token_out: Address, max_hops: int = 3
    ) -> list[Route]:
        """
        Find all possible routes up to max_hops.
        """
        ...

    def find_best_route(
        self,
        token_in: Address,
        token_out: Address,
        amount_in: int,
        gas_price_gwei: int,
        max_hops: int = 3,
    ) -> tuple[Route, int]:
        """
        Find route that maximizes NET output (after gas).
        Returns (best_route, net_output).
        """
        ...

    def compare_routes(
        self, token_in: Address, token_out: Address, amount_in: int, gas_price_gwei: int
    ) -> list[dict]:
        """
        Compare all routes with detailed breakdown:
        {
            'route': Route,
            'gross_output': int,
            'gas_estimate': int,
            'gas_cost': int,
            'net_output': int,
        }
        """
        ...
