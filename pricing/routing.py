import collections
from decimal import Decimal
from typing import Optional, Any

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

    def _build_graph(self) -> dict[Address, list[tuple[UniswapV2Pair, Address]]]:
        """
        Build adjacency graph: token → [(pool, other_token), ...]
        """
        graph = collections.defaultdict(list)
        for pool in self.pools:
            graph[pool.token0].append((pool, pool.token1))
            graph[pool.token1].append((pool, pool.token0))
        return graph

    def find_all_routes(
        self, token_in: Address, token_out: Address, max_hops: int = 3
    ) -> list[Route]:
        """
        Find all possible routes up to max_hops.
        """
        routes = []
        # Stack  that stores (current token, visited tokens, pools path list)
        stack = [(token_in, [token_in], [])]

        while stack:
            current_token, visited, pools_path = stack.pop()

            if current_token == token_out:
                if len(pools_path) > 0:
                    routes.append(Route(pools_path, visited))
                continue

            if len(pools_path) >= max_hops:
                continue

            for pool, neighbor in self.graph[current_token]:
                if neighbor not in visited:
                    new_visited = visited + [neighbor]
                    new_pools = pools_path + [pool]
                    stack.append((neighbor, new_visited, new_pools))

        return routes

    def find_best_route(
        self,
        token_in: Address,
        token_out: Address,
        amount_in: int,
        gas_price_gwei: int,
        max_hops: int = 3,
    ) -> tuple[Optional[Route], int]:
        """
        Find route that maximizes NET output (after gas).
        Returns (best_route, net_output).
        """
        comparison = self.compare_routes(
            token_in, token_out, amount_in, gas_price_gwei, max_hops
        )

        if not comparison:
            return None, 0

        best = comparison[0]
        return best["route"], best["net_output"]

    def compare_routes(
        self,
        token_in: Address,
        token_out: Address,
        amount_in: int,
        gas_price_gwei: int,
        max_hops: int = 3,
    ) -> list[dict[str, Any]]:
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
        all_routes = self.find_all_routes(token_in, token_out, max_hops)
        results = []

        eth_price_in_out = self._get_token_eth_price(token_out)

        for route in all_routes:
            try:
                gross_output = route.get_output(amount_in)
                gas_used = route.estimate_gas()
                gas_cost_eth = Decimal(gas_used * gas_price_gwei) / Decimal(10**9)

                if eth_price_in_out:
                    gas_cost_out = int(
                        gas_cost_eth * eth_price_in_out * Decimal(10**18)
                    )
                else:
                    gas_cost_out = 0

                net_output = gross_output - gas_cost_out
                results.append(
                    {
                        "route": route,
                        "gross_output": gross_output,
                        "gas_estimate": gas_used,
                        "gas_cost": gas_cost_out,
                        "net_output": net_output,
                    }
                )

            except ValueError:
                continue

        return sorted(results, key=lambda x: x["net_output"], reverse=True)

    def _get_token_eth_price(self, token: Address) -> Optional[Decimal]:
        """
        Helper to find the price of 1 ETH in token_out
        """
        if token == WETH_ADDRESS:
            return Decimal(1)

        for pool, neighbor in self.graph[token]:
            if neighbor == WETH_ADDRESS:
                return pool.get_spot_price(WETH_ADDRESS)

        return None
