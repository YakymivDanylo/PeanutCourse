import asyncio
import logging
import os
import sys
from dotenv import load_dotenv


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from configs.binance_config import BINANCE_CONFIG  # noqa: E402
from exchange.client import ExchangeClient  # noqa: E402
from inventory.tracker import InventoryTracker, Venue  # noqa: E402
from strategy.fees import FeeStructure  # noqa: E402
from strategy.generator import SignalGenerator  # noqa: E402
from strategy.scorer import SignalScorer  # noqa: E402
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

        api_config = BINANCE_CONFIG.copy()
        api_config.update(
            {
                "apiKey": config["binance_key"],
                "secret": config["binance_secret"],
            }
        )

        self.exchange = ExchangeClient(api_config)

        rpc_url = config.get("rpc_url", "http://127.0.0.1:8545")
        ws_url = config.get("ws_url", "ws://127.0.0.1:8545")

        self.chain_client = ChainClient([rpc_url])
        self.pricing_engine = PricingEngine(self.chain_client, rpc_url, ws_url)

        self.inventory = InventoryTracker()

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
            config=ExecutorConfig(simulation_mode=config.get("simulation", True)),
        )

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
                logging.info("Skipped: score below threshold")
                continue

            logging.info(f"Executing: {signal.direction.name} {self.trade_size} ETH")

            ctx = await self.executor.execute(signal)

            self.scorer.record_result(pair, ctx.state == ExecutorState.DONE)

            if ctx.state == ExecutorState.DONE:
                pnl = ctx.actual_net_pnl if ctx.actual_net_pnl else 0.0
                logging.info(f"SUCCESS: PnL=${pnl:.2f}")
            else:
                logging.warning(f"FAILED: {ctx.error}")

                failures = getattr(self.executor.circuit_breaker, "failure_count", 0)
                threshold = getattr(
                    self.executor.circuit_breaker, "failure_threshold", 3
                )
                logging.warning(f"Circuit breaker: {failures}/{threshold} failures")

            await self._sync_balances()

    async def _sync_balances(self):
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
        "binance_key": os.getenv("BINANCE_TESTNET_API_KEY"),
        "binance_secret": os.getenv("BINANCE_TESTNET_SECRET"),
        "rpc_url": "http://127.0.0.1:8545",
        "ws_url": "ws://127.0.0.1:8545",
        "pairs": ["ETH/USDT"],
        "trade_size": 0.1,
        "simulation": True,
        "signal_config": {"min_spread_bps": 5},
    }

    bot = ArbBot(config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
