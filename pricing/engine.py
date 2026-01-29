from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
import time
from chain.client import ChainClient
from core.types import Address
from pricing.amm import UniswapV2Pair
from pricing.mempool import MempoolMonitor, ParsedSwap
from pricing.routing import Route, RouteFinder
from pricing.simulation import ForkSimulator
import logging

logger = logging.getLogger(__name__)


class QuoteError(Exception):
    """Raised when a quote can not be simulated or generated"""

    pass


@dataclass
class Quote:
    route: Route
    amount_in: int
    expected_output: int
    simulated_output: int
    gas_estimate: int
    timestamp: float

    @property
    def is_valid(self) -> bool:
        """Quote valid if simulation matches expectation within tolerance."""
        if self.expected_output == 0:
            return False

        diff = abs(self.expected_output - self.simulated_output)

        return diff * 1000 < self.expected_output


class PricingEngine:
    """
    Main interface for the pricing module.
    Integrates AMM math, routing, simulation, and mempool monitoring.
    """

    def __init__(self, chain_client: ChainClient, fork_url: str, ws_url: str):
        self.client = chain_client
        self.simulator = ForkSimulator(fork_url)

        http_rpc = self.client.rpc_urls[0] if self.client.rpc_urls else fork_url

        self.monitor = MempoolMonitor(
            ws_url=ws_url,
            callback=self._on_mempool_swap,
            http_rpc_url=http_rpc,
        )
        self.pools: dict[str, UniswapV2Pair] = {}
        self.router: Optional[RouteFinder] = None

    def load_pools(self, pool_addresses: list[Address]):
        """Load pool data from chain."""
        logger.info(f"Loading {len(pool_addresses)} pools ")
        pairs = []
        for addr in pool_addresses:
            try:
                pair = UniswapV2Pair.from_chain(addr, self.client)
                self.pools[addr.checksum] = pair
                pairs.append(pair)
            except Exception as e:
                logger.error(f"Failed to load pool {addr.value}: {e}")

    def refresh_pool(self, address: Address):
        """Refresh single pool's reserves."""
        checksum = address.checksum
        if checksum in self.pools:
            try:
                updated_pair = UniswapV2Pair.from_chain(address, self.client)
                self.pools[checksum] = updated_pair

                if self.router:
                    self.router = RouteFinder(list(self.pools.values()))
            except Exception as e:
                logger.error(f"Failed to refresh pool {checksum}: {e}")

    def get_quote(
        self, token_in: Address, token_out: Address, amount_in: int, gas_price_gwei: int
    ) -> Quote:
        """
        Get best quote for a swap.
        """
        if not self.router:
            raise QuoteError("Router not initialized. Call load_pools first")

        route, net_output = self.router.find_best_route(
            token_in, token_out, amount_in, gas_price_gwei
        )

        if not route:
            raise QuoteError("No route found")

        sim_sender = Address("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")

        sim_result = self.simulator.simulate_route(route, amount_in, sim_sender)

        if not sim_result.success:
            raise QuoteError(f"Simulation failed: {sim_result.error}")

        return Quote(
            route=route,
            amount_in=amount_in,
            expected_output=net_output,
            simulated_output=sim_result.amount_out,
            gas_estimate=sim_result.gas_used,
            timestamp=time.time(),
        )

    async def start(self):
        """Starts the engine's background tasks (mempool monitoring)"""
        logger.info("Starting pricing engine...")
        await self.monitor.start()

    async def _on_mempool_swap(self, swap: ParsedSwap):
        """Handle detected mempool swap."""
        relevant_pair = None
        if swap.token_in and swap.token_out:
            for pair in self.pools.values():
                is_token0 = pair.token0 == swap.token_in
                is_token1 = pair.token1 == swap.token_out

                if (is_token0 and pair.token1 == swap.token_out) or (
                    is_token1 and pair.token0 == swap.token_in
                ):
                    relevant_pair = pair
                    break

        if relevant_pair:
            try:
                expected_out = relevant_pair.get_amount_out(
                    swap.amount_in, swap.token_in
                )

                if expected_out > 0:
                    diff = expected_out - swap.min_amount_out
                    slippage_pct = (Decimal(diff) / Decimal(expected_out)) * 100

                    log_msg = (
                        f"Detected Swap on {relevant_pair.symbol}:\n"
                        f"  Tx: {swap.tx_hash[:10]}...\n"
                        f"  Amount: {swap.amount_in} -> Min: {swap.min_amount_out}\n"
                        f"  Expected (Local): {expected_out}\n"
                        f"  Implied Slippage: {slippage_pct:.2f}%"
                    )

                    if slippage_pct > 2.0:
                        logger.warning(log_msg + "[HIGH SLIPPAGE - ARB OPPORTUNITY]")
                    else:
                        logger.info(log_msg)
            except ValueError:
                pass
