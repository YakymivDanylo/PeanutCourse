import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from eth_abi import encode
from eth_utils import function_signature_to_4byte_selector

from exchange.client import ExchangeClient
from inventory.tracker import InventoryTracker
from pricing.engine import PricingEngine
from strategy.signal import Signal, Direction
from executor.recovery import CircuitBreaker, ReplayProtection
from chain.builder import TransactionBuilder
from core.wallet import WalletManager
from core.types import Address, TokenAmount

ROUTER_ADDRESS = Address("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")
SWAP_EXACT_TOKENS_FOR_TOKENS = function_signature_to_4byte_selector(
    "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)"
)
SWAP_EXACT_ETH_FOR_TOKENS = function_signature_to_4byte_selector(
    "swapExactETHForTokens(uint256,address[],address,uint256)"
)
SWAP_EXACT_TOKENS_FOR_ETH = function_signature_to_4byte_selector(
    "swapExactTokensForETH(uint256,uint256,address[],address,uint256)"
)

TOKEN_MAP = {
    "ETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
}
DECIMALS = {"ETH": 18, "WETH": 18, "USDT": 6, "USDC": 6}


class ExecutorState(Enum):
    IDLE = auto()
    VALIDATING = auto()
    LEG1_PENDING = auto()
    LEG1_FILLED = auto()
    LEG2_PENDING = auto()
    DONE = auto()
    FAILED = auto()
    UNWINDING = auto()


@dataclass
class ExecutionContext:
    signal: Signal
    state: ExecutorState = ExecutorState.IDLE

    leg1_venue: str = ""
    leg1_order_id: Optional[str] = None
    leg1_fill_price: Optional[float] = None
    leg1_fill_size: Optional[float] = None

    leg2_venue: str = ""
    leg2_tx_hash: Optional[str] = None
    leg2_fill_price: Optional[float] = None
    leg2_fill_size: Optional[float] = None

    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    actual_net_pnl: Optional[float] = None
    error: Optional[str] = None


@dataclass
class ExecutorConfig:
    leg1_timeout: float = 5.0
    leg2_timeout: float = 60.0
    min_fill_ratio: float = 0.8
    use_flashbots: bool = True
    simulation_mode: bool = True


class Executor:
    """Execute arbitrage trades across CEX and DEX."""

    def __init__(
        self,
        exchange_client: ExchangeClient,
        pricing_module: PricingEngine,
        inventory_tracker: InventoryTracker,
        wallet_manager: WalletManager,
        config: Optional[ExecutorConfig] = None,
    ):
        self.exchange = exchange_client
        self.pricing = pricing_module
        self.inventory = inventory_tracker
        self.wallet = wallet_manager
        self.config = config or ExecutorConfig()

        self.circuit_breaker = CircuitBreaker()
        self.replay_protection = ReplayProtection()

    async def execute(self, signal: Signal) -> ExecutionContext:
        ctx = ExecutionContext(signal=signal)

        # Pre-flight checks
        if self.circuit_breaker.is_open():
            ctx.state = ExecutorState.FAILED
            ctx.error = "Circuit breaker open"
            return ctx

        if self.replay_protection.is_duplicate(signal):
            ctx.state = ExecutorState.FAILED
            ctx.error = "Duplicate signal"
            return ctx

        ctx.state = ExecutorState.VALIDATING
        if not signal.is_valid():
            ctx.state = ExecutorState.FAILED
            ctx.error = "Signal invalid"
            return ctx

        # Execute based on leg order strategy
        if self.config.use_flashbots:
            ctx = await self._execute_dex_first(ctx)
        else:
            ctx = await self._execute_cex_first(ctx)

        # Record result
        if ctx.state == ExecutorState.DONE:
            self.replay_protection.mark_executed(signal)
            self.circuit_breaker.record_success()
        else:
            self.circuit_breaker.record_failure()

        ctx.finished_at = time.time()
        return ctx

    async def _execute_cex_first(self, ctx: ExecutionContext) -> ExecutionContext:
        """CEX leg first (default for non-Flashbots)."""
        signal = ctx.signal

        # Leg 1: CEX
        ctx.state = ExecutorState.LEG1_PENDING
        ctx.leg1_venue = "cex"

        try:
            leg1 = await asyncio.wait_for(
                self._execute_cex_leg(signal), timeout=self.config.leg1_timeout
            )
        except asyncio.TimeoutError:
            ctx.state = ExecutorState.FAILED
            ctx.error = "CEX timeout"
            return ctx

        if not leg1["success"]:
            ctx.state = ExecutorState.FAILED
            ctx.error = leg1.get("error", "CEX rejected")
            return ctx

        if leg1["filled"] / signal.size < self.config.min_fill_ratio:
            ctx.state = ExecutorState.FAILED
            ctx.error = "Partial fill below threshold"
            return ctx

        ctx.leg1_fill_price = leg1["price"]
        ctx.leg1_fill_size = leg1["filled"]
        ctx.state = ExecutorState.LEG1_FILLED

        # Leg 2: DEX
        ctx.state = ExecutorState.LEG2_PENDING
        ctx.leg2_venue = "dex"

        try:
            leg2 = await asyncio.wait_for(
                self._execute_dex_leg(signal, ctx.leg1_fill_size),
                timeout=self.config.leg2_timeout,
            )
        except asyncio.TimeoutError:
            ctx.state = ExecutorState.UNWINDING
            await self._unwind(ctx)
            ctx.state = ExecutorState.FAILED
            ctx.error = "DEX timeout - unwound"
            return ctx

        if not leg2["success"]:
            ctx.state = ExecutorState.UNWINDING
            await self._unwind(ctx)
            ctx.state = ExecutorState.FAILED
            ctx.error = "DEX failed - unwound"
            return ctx

        ctx.leg2_fill_price = leg2["price"]
        ctx.leg2_fill_size = leg2["filled"]
        ctx.actual_net_pnl = self._calculate_pnl(ctx)
        ctx.state = ExecutorState.DONE
        return ctx

    async def _execute_dex_first(self, ctx: ExecutionContext) -> ExecutionContext:
        """DEX leg first (when using Flashbots - failed tx = no cost)."""
        signal = ctx.signal

        # Leg 1: DEX
        ctx.state = ExecutorState.LEG1_PENDING
        ctx.leg1_venue = "dex"

        try:
            leg1 = await asyncio.wait_for(
                self._execute_dex_leg(signal, signal.size),
                timeout=self.config.leg2_timeout,
            )
        except asyncio.TimeoutError:
            ctx.state = ExecutorState.FAILED
            ctx.error = "DEX timeout"
            return ctx

        if not leg1["success"]:
            ctx.state = ExecutorState.FAILED
            ctx.error = "DEX failed (no cost via Flashbots)"
            return ctx

        ctx.leg1_fill_price = leg1["price"]
        ctx.leg1_fill_size = leg1["filled"]
        ctx.state = ExecutorState.LEG1_FILLED

        # Leg 2: CEX
        ctx.state = ExecutorState.LEG2_PENDING
        ctx.leg2_venue = "cex"

        try:
            leg2 = await asyncio.wait_for(
                self._execute_cex_leg(signal, ctx.leg1_fill_size),
                timeout=self.config.leg1_timeout,
            )
        except asyncio.TimeoutError:
            ctx.state = ExecutorState.UNWINDING
            await self._unwind(ctx)
            ctx.state = ExecutorState.FAILED
            ctx.error = "CEX timeout after DEX - unwound"
            return ctx

        if not leg2["success"]:
            ctx.state = ExecutorState.UNWINDING
            await self._unwind(ctx)
            ctx.state = ExecutorState.FAILED
            ctx.error = "CEX failed after DEX - unwound"
            return ctx

        ctx.leg2_fill_price = leg2["price"]
        ctx.leg2_fill_size = leg2["filled"]
        ctx.actual_net_pnl = self._calculate_pnl(ctx)
        ctx.state = ExecutorState.DONE
        return ctx

    async def _execute_cex_leg(self, signal: Signal, size: float = None) -> dict:
        actual_size = size or signal.size
        if self.config.simulation_mode:
            await asyncio.sleep(0.1)
            return {
                "success": True,
                "price": signal.cex_price * 1.0001,
                "filled": actual_size,
            }

        side = "buy" if signal.direction == Direction.BUY_CEX_SELL_DEX else "sell"
        try:
            result = self.exchange.create_limit_ioc_order(
                symbol=signal.pair,
                side=side,
                amount=actual_size,
                price=signal.cex_price * 1.001,  # Slightly aggressive limit for IOC
            )
            is_filled = result["status"] == "filled" or (
                result["status"] == "closed" and result["amount_filled"] > 0
            )
            return {
                "success": is_filled,
                "price": float(result["avg_fill_price"]),
                "filled": float(result["amount_filled"]),
                "error": result["status"],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_dex_leg(self, signal: Signal, size: float) -> dict:
        if self.config.simulation_mode:
            await asyncio.sleep(0.5)
            return {"success": True, "price": signal.dex_price * 0.9998, "filled": size}

        base_sym, quote_sym = signal.pair.split("/")

        if signal.direction == Direction.BUY_CEX_SELL_DEX:
            token_in_sym = base_sym
            token_out_sym = quote_sym
            amount_in_human = size
        else:
            token_in_sym = quote_sym
            token_out_sym = base_sym
            amount_in_human = size * signal.dex_price

        decimals_in = DECIMALS.get(token_in_sym, 18)
        amount_in_raw = int(amount_in_human * (10**decimals_in))

        token_in_addr = Address(TOKEN_MAP[token_in_sym])
        token_out_addr = Address(TOKEN_MAP[token_out_sym])

        try:
            gas_price_gwei = self.pricing.client.get_gas_price_gwei()
            quote = self.pricing.get_quote(
                token_in_addr, token_out_addr, amount_in_raw, gas_price_gwei
            )

            min_amount_out = int(quote.expected_output * 0.99)
            deadline = int(time.time()) + 120
            path = [t.checksum for t in quote.route.path]
            to = self.wallet.address

            is_native_in = token_in_sym == "ETH"
            is_native_out = token_out_sym == "ETH"

            data = b""
            value_raw = TokenAmount(0, 18)

            if is_native_in:
                # swapExactETHForTokens
                args = encode(
                    ["uint256", "address[]", "address", "uint256"],
                    [min_amount_out, path, to, deadline],
                )
                data = SWAP_EXACT_ETH_FOR_TOKENS + args
                value_raw = TokenAmount(amount_in_raw, 18)

            elif is_native_out:
                # swapExactTokensForETH
                args = encode(
                    ["uint256", "uint256", "address[]", "address", "uint256"],
                    [amount_in_raw, min_amount_out, path, to, deadline],
                )
                data = SWAP_EXACT_TOKENS_FOR_ETH + args
            else:
                # swapExactTokensForTokens
                args = encode(
                    ["uint256", "uint256", "address[]", "address", "uint256"],
                    [amount_in_raw, min_amount_out, path, to, deadline],
                )
                data = SWAP_EXACT_TOKENS_FOR_TOKENS + args

            builder = TransactionBuilder(self.pricing.client, self.wallet)
            builder.to(ROUTER_ADDRESS)
            builder.value(value_raw)
            builder.data(data)
            builder.with_gas_estimate()
            builder.with_gas_price()

            receipt = builder.send_and_wait(timeout=60)

            if receipt.status:
                amount_out_human = float(quote.expected_output) / (
                    10 ** DECIMALS[token_out_sym]
                )
                fill_price = amount_out_human / size if size else 0
                return {
                    "success": True,
                    "price": fill_price,
                    "filled": size,
                    "tx_hash": receipt.tx_hash,
                }
            else:
                return {
                    "success": False,
                    "error": "TX Reverted",
                    "tx_hash": receipt.tx_hash,
                }

        except Exception as e:
            return {"success": False, "error": f"DEX Execution failed: {e}"}

    async def _unwind(self, ctx: ExecutionContext):
        """Market sell to flatten stuck position."""
        if self.config.simulation_mode:
            await asyncio.sleep(0.1)
            return

        if ctx.leg1_venue == "cex":
            side = (
                "sell" if ctx.signal.direction == Direction.BUY_CEX_SELL_DEX else "buy"
            )
            try:
                self.exchange.create_market_order(
                    symbol=ctx.signal.pair, side=side, amount=ctx.leg1_fill_size
                )
            except Exception as e:
                print(f"CRITICAL: CEX Unwind failed: {e}")

        elif ctx.leg1_venue == "dex":
            reverse_dir = (
                Direction.BUY_CEX_SELL_DEX
                if ctx.signal.direction == Direction.BUY_DEX_SELL_CEX
                else Direction.BUY_DEX_SELL_CEX
            )

            unwind_signal = Signal.create(
                pair=ctx.signal.pair,
                direction=reverse_dir,
                cex_price=0,
                dex_price=0,
                spread_bps=0,
                size=ctx.leg1_fill_size,
                expected_gross_pnl=0,
                expected_fees=0,
                expected_net_pnl=0,
                score=0,
                expiry=0,
                inventory_ok=True,
                within_limits=True,
            )

            await self._execute_dex_leg(unwind_signal, ctx.leg1_fill_size)

    def _calculate_pnl(self, ctx: ExecutionContext) -> float:
        signal = ctx.signal
        if signal.direction == Direction.BUY_CEX_SELL_DEX:
            # Buy CEX (Leg1), Sell DEX (Leg2)
            buy_price = (
                ctx.leg1_fill_price if ctx.leg1_venue == "cex" else ctx.leg2_fill_price
            )
            sell_price = (
                ctx.leg2_fill_price if ctx.leg2_venue == "dex" else ctx.leg1_fill_price
            )
            size = ctx.leg2_fill_size
        else:
            # Buy DEX, Sell CEX
            buy_price = (
                ctx.leg1_fill_price if ctx.leg1_venue == "dex" else ctx.leg2_fill_price
            )
            sell_price = (
                ctx.leg2_fill_price if ctx.leg2_venue == "cex" else ctx.leg1_fill_price
            )
            size = ctx.leg2_fill_size

        gross = (sell_price - buy_price) * size
        fees = size * buy_price * 0.004  # ~40 bps estimate
        return gross - fees
