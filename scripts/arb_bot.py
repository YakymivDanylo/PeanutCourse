import asyncio
import logging
import os
import sys
from decimal import Decimal
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from configs.binance_config import BINANCE_CONFIG  # noqa: E402
from exchange.client import ExchangeClient  # noqa: E402
from inventory.tracker import InventoryTracker, Venue  # noqa: E402
from strategy.fees import FeeStructure  # noqa: E402
from strategy.generator import SignalGenerator  # noqa: E402
from strategy.scorer import SignalScorer  # noqa: E402
from strategy.signal import Direction  # noqa: E402
from executor.engine import Executor, ExecutorConfig, ExecutorState  # noqa: E402
from pricing.engine import PricingEngine  # noqa: E402
from chain.client import ChainClient  # noqa: E402
from core.types import Address  # noqa: E402

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

WETH_USDT_POOL = "0x0d4a11d5EEaaC28EC3F61d100daF4d40471f1852"


class ArbBot:
    def __init__(self, config: dict):
        self.config = config
        self.pairs = config.get("pairs", ["ETH/USDT"])
        self.trade_size = float(config.get("trade_size", 0.1))
        self.running = False

        self.paper_trading = config.get("paper_trading", False)
        if self.paper_trading:
            logger.info("PAPER TRADING MODE ENABLED")
            self.config["simulation"] = True
            self.initial_capital_usd = Decimal("0")

        api_config = BINANCE_CONFIG.copy()
        api_config.update(
            {
                "apiKey": config.get("binance_key", ""),
                "secret": config.get("binance_secret", ""),
            }
        )

        self.exchange = ExchangeClient(api_config)

        rpc_url = config.get("rpc_url", "http://127.0.0.1:8545")
        ws_url = config.get("ws_url", "ws://127.0.0.1:8545")

        self.chain_client = ChainClient([rpc_url])
        self.pricing_engine = PricingEngine(self.chain_client, rpc_url, ws_url)

        self.inventory = InventoryTracker()

        if self.paper_trading:
            self._init_paper_balances()

        self.fees = FeeStructure()

        self.generator = SignalGenerator(
            exchange_client=self.exchange,
            pricing_engine=self.pricing_engine,
            inventory_tracker=self.inventory,
            fee_structure=self.fees,
            config=config.get("signal_config", {}),
        )

        self.scorer = SignalScorer()

        self.executor = Executor(
            exchange_client=self.exchange,
            pricing_module=self.pricing_engine,
            inventory_tracker=self.inventory,
            wallet_manager=None,
            config=ExecutorConfig(simulation_mode=config.get("simulation", True)),
        )

        if self.paper_trading:
            initial_snapshot = self.inventory.snapshot(
                prices={"ETH": Decimal("2000"), "USDT": Decimal("1")}
            )
            self.initial_capital_usd = initial_snapshot["total_usd"]

    def _init_paper_balances(self):
        """Sets up fake balances for testing."""
        logger.info("Initializing Paper Balances: 10 ETH, 20,000 USDT per venue")

        binance_eth = self.inventory._get_balance(Venue.BINANCE, "ETH")
        binance_eth.free = Decimal("10.0")
        binance_usdt = self.inventory._get_balance(Venue.BINANCE, "USDT")
        binance_usdt.free = Decimal("20000.0")

        wallet_eth = self.inventory._get_balance(Venue.WALLET, "ETH")
        wallet_eth.free = Decimal("10.0")
        wallet_usdt = self.inventory._get_balance(Venue.WALLET, "USDT")
        wallet_usdt.free = Decimal("20000.0")

    async def run(self):
        self.running = True
        logger.info("Bot starting...")

        try:
            pool_address = Address(WETH_USDT_POOL)
            self.pricing_engine.load_pools([pool_address])
            asyncio.create_task(self.pricing_engine.start())
        except Exception as e:
            logger.error(f"Failed to initialize pricing engine: {e}")

        await self._sync_balances()

        while self.running:
            try:
                await self._tick()
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Tick error: {e}")
                await asyncio.sleep(5)

    async def _tick(self):
        if (
            hasattr(self.executor, "circuit_breaker")
            and self.executor.circuit_breaker.is_open()
        ):
            failures = getattr(self.executor.circuit_breaker, "failure_count", 0)
            threshold = getattr(self.executor.circuit_breaker, "failure_threshold", 3)
            logging.warning(f"Circuit breaker: {failures}/{threshold} failures")
            return

        for pair in self.pairs:
            signal = self.generator.generate(pair, self.trade_size)
            if signal is None:
                continue

            current_skews = (
                self.inventory.get_skews()
                if hasattr(self.inventory, "get_skews")
                else {}
            )
            signal.score = self.scorer.score(signal, current_skews)

            logging.info(
                f"Signal: {pair} spread={signal.spread_bps:.1f}bps score={signal.score}"
            )

            if signal.score < 60:
                continue

            logging.info(f"Executing: {signal.direction.name} {self.trade_size} ETH")

            ctx = await self.executor.execute(signal)

            self.scorer.record_result(pair, ctx.state == ExecutorState.DONE)

            if ctx.state == ExecutorState.DONE:
                pnl = ctx.actual_net_pnl if ctx.actual_net_pnl else 0.0
                logging.info(f"SUCCESS: PnL=${pnl:.2f}")

                if self.paper_trading:
                    self._update_paper_balances_after_trade(ctx)
                    self._log_paper_status(signal)

            else:
                logging.warning(f"FAILED: {ctx.error}")

                failures = getattr(self.executor.circuit_breaker, "failure_count", 0)
                threshold = getattr(
                    self.executor.circuit_breaker, "failure_threshold", 3
                )
                logging.warning(f"Circuit breaker: {failures}/{threshold} failures")

            if not self.paper_trading:
                await self._sync_balances()

    def _update_paper_balances_after_trade(self, ctx):
        """Manually updates InventoryTracker based
        on execution context with correct side logic."""
        signal = ctx.signal
        base, quote = signal.pair.split("/")

        def get_venue_enum(v_str):
            return Venue.BINANCE if v_str == "cex" else Venue.WALLET

        if signal.direction == Direction.BUY_CEX_SELL_DEX:
            cex_action = "buy"
            dex_action = "sell"
        else:
            cex_action = "sell"
            dex_action = "buy"

        if ctx.leg1_venue == "cex":
            leg1_side = cex_action
            leg2_side = dex_action
        else:
            leg1_side = dex_action
            leg2_side = cex_action

        leg1_venue_enum = get_venue_enum(ctx.leg1_venue)
        leg1_price = Decimal(str(ctx.leg1_fill_price))
        leg1_size = Decimal(str(ctx.leg1_fill_size))
        leg1_quote_qty = leg1_size * leg1_price
        leg1_fee = leg1_quote_qty * Decimal("0.001")

        self.inventory.record_trade(
            venue=leg1_venue_enum,
            side=leg1_side,
            base_asset=base,
            quote_asset=quote,
            base_amount=leg1_size,
            quote_amount=leg1_quote_qty,
            fee=leg1_fee,
            fee_asset=quote,
        )

        leg2_venue_enum = get_venue_enum(ctx.leg2_venue)
        leg2_price = Decimal(str(ctx.leg2_fill_price))
        leg2_size = Decimal(str(ctx.leg2_fill_size))
        leg2_quote_qty = leg2_size * leg2_price
        leg2_fee = leg2_quote_qty * Decimal("0.001")

        self.inventory.record_trade(
            venue=leg2_venue_enum,
            side=leg2_side,
            base_asset=base,
            quote_asset=quote,
            base_amount=leg2_size,
            quote_amount=leg2_quote_qty,
            fee=leg2_fee,
            fee_asset=quote,
        )

    def _log_paper_status(self, signal):
        """Logs current portfolio value and total PnL."""
        prices = {
            "ETH": Decimal(str(signal.cex_price)),
            "USDT": Decimal("1.0"),
            "USDC": Decimal("1.0"),
        }
        snapshot = self.inventory.snapshot(prices)
        current_usd = snapshot["total_usd"]
        total_pnl = current_usd - self.initial_capital_usd

        logger.info("-" * 40)
        logger.info("PAPER TRADING REPORT")
        logger.info(f"Total Value: ${current_usd:,.2f}")
        logger.info(f"Total PnL:   ${total_pnl:,.2f}")
        logger.info(f"Holdings:    {snapshot['totals']}")
        logger.info("-" * 40)

    async def _sync_balances(self):
        if self.paper_trading:
            return

        try:
            balances = self.exchange.fetch_balance()

            if hasattr(self.inventory, "update_from_cex"):
                self.inventory.update_from_cex(Venue.BINANCE, balances)
        except Exception as e:
            logger.error(f"Balance sync error: {e}")

    def stop(self):
        self.running = False


if __name__ == "__main__":
    config = {
        "binance_key": os.getenv("BINANCE_TESTNET_API_KEY", ""),
        "binance_secret": os.getenv("BINANCE_TESTNET_SECRET", ""),
        "rpc_url": "http://127.0.0.1:8545",
        "ws_url": "ws://127.0.0.1:8545",
        "pairs": ["ETH/USDT"],
        "trade_size": 0.1,
        "simulation": True,
        "paper_trading": True,
        "signal_config": {"min_spread_bps": 5},
    }

    bot = ArbBot(config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
