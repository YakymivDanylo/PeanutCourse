import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from decimal import Decimal
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from configs.binance_config import BINANCE_CONFIG  # noqa: E402
from config import Config  # noqa: E402
from exchange.client import ExchangeClient  # noqa: E402
from inventory.tracker import InventoryTracker, Venue  # noqa: E402
from strategy.fees import FeeStructure  # noqa: E402
from strategy.generator import SignalGenerator  # noqa: E402
from strategy.scorer import SignalScorer  # noqa: E402
from executor.engine import Executor, ExecutorConfig, ExecutorState  # noqa: E402
from pricing.engine import PricingEngine  # noqa: E402
from chain.client import ChainClient  # noqa: E402
from core.types import Address  # noqa: E402
import safety  # noqa: E402
from strategy.risk import RiskManager, RiskLimits, PreTradeValidator  # noqa: E402
from core.alert import TelegramAlert  # noqa: E402
from core.wallet import WalletManager  # noqa: E402

load_dotenv()

if not os.path.exists("logs"):
    os.makedirs("logs")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s |%(levelname)s |%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
    handlers=[
        logging.FileHandler(f"logs/bot_{datetime.now():%Y%m%d}.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

KILL_SWITCH_FILE = "/tmp/arb_bot_kill"


class ArbBot:
    def __init__(self, config: dict):
        self.config = config
        self.pairs = config.get("pairs", ["ETH/USDC"])
        self.trade_size = float(config.get("trade_size", 0.01))
        self.running = False
        self.dry_run = config.get("dry_run", True)
        self.telegram = TelegramAlert()
        self.telegram.send_status(
            f" Bot was initialized at {datetime.now()}"
            f' in {"DRY RUN" if self.dry_run else "PRODUCTION"}'
        )

        api_config = BINANCE_CONFIG.copy()
        if config.get("binance_key"):
            api_config["apiKey"] = config["binance_key"]
            api_config["secret"] = config["binance_secret"]

        self.exchange = ExchangeClient(api_config)

        rpc_url = config.get("rpc_url", Config.RPC_URL)

        self.chain_client = ChainClient([rpc_url])

        self.pricing_engine = PricingEngine(
            self.chain_client, rpc_url, Config.CHAIN_WS_URL
        )

        self.inventory = InventoryTracker()

        self.fees = FeeStructure(
            cex_taker_bps=Config.CEX_FEE_BPS,
            dex_swap_bps=Config.DEX_FEE_BPS,
            gas_cost_usd=Config.GAS_COST_USD,
        )

        self.generator = SignalGenerator(
            exchange_client=self.exchange,
            pricing_engine=self.pricing_engine,
            inventory_tracker=self.inventory,
            fee_structure=self.fees,
            config=config.get("signal_config", {}),
        )

        self.scorer = SignalScorer()

        self.private_key = os.getenv("PRIVATE_KEY")
        if not self.private_key and not self.dry_run:
            logger.critical("PRIVATE_KEY not found in env! Cannot run in production.")
            sys.exit(1)

        self.wallet_manager = (
            WalletManager(self.private_key) if self.private_key else None
        )

        self.executor = Executor(
            exchange_client=self.exchange,
            pricing_module=self.pricing_engine,
            inventory_tracker=self.inventory,
            wallet_manager=self.wallet_manager,
            config=ExecutorConfig(simulation_mode=self.dry_run),
        )

        self.risk_limits = RiskLimits(
            max_trade_usd=5.0, max_daily_loss=10.0, max_drawdown_pct=0.15
        )
        self.risk_manager = RiskManager(self.risk_limits, initial_capital=100.0)

        self.session_trade_count = 0
        self.max_session_trades = 5
        self.pre_trade_validator = PreTradeValidator()
        self.trades_this_hour = 0
        self.last_hour_reset = time.time()

        if self.dry_run:
            logger.info(
                "Bot initialized in DRY RUN mode. No real trades will be executed."
            )
            self._init_mock_balances()
        else:
            logger.warning("Bot initialized in PRODUCTION mode. REAL FUNDS AT RISK.")

    def _init_mock_balances(self):
        """
        Initializing fake balances for
        DRY RUN mode so that InventoryTracker allows signal generation.
        """
        logger.info("Initializing MOCK balances for DRY RUN...")

        mock_balances = {
            "ETH": {"free": Decimal("10.0"), "total": Decimal("10.0")},
            "USDC": {"free": Decimal("20000.0"), "total": Decimal("20000.0")},
            "USDT": {"free": Decimal("20000.0"), "total": Decimal("20000.0")},
        }

        try:
            if hasattr(self.inventory, "update_from_cex"):
                self.inventory.update_from_cex(Venue.BINANCE, mock_balances)
                logger.info(f"Mock CEX balances set: {mock_balances.keys()}")

            if hasattr(self.inventory, "update_from_chain"):
                chain_balances = {
                    "ETH": Decimal("10.0"),
                    "USDC": Decimal("20000.0"),
                    "USDT": Decimal("20000.0"),
                }
                self.inventory.update_from_chain(chain_balances)
                logger.info(f"Mock Chain balances set: {chain_balances.keys()}")

        except Exception as e:
            logger.error(f"Failed to set mock balances: {e}")

    async def run(self):
        self.running = True
        logger.info(f"Bot starting... ChainID: {Config.CHAIN_ID}")

        if os.path.exists(KILL_SWITCH_FILE):
            logger.critical("KILL SWITCH FOUND ON STARTUP. STOPPING.")
            return

        try:
            pool_addr = Config.POOL_ADDRESS
            if pool_addr:
                self.pricing_engine.load_pools([Address(pool_addr)])

            asyncio.create_task(self.pricing_engine.start())
        except Exception as e:
            logger.error(f"Failed to initialize pricing engine: {e}")

        await self._sync_balances()
        try:
            while self.running:
                try:
                    await self._tick()
                    await asyncio.sleep(1)
                except Exception as e:
                    error_msg = f"Tick error: {e}"
                    logger.error(error_msg, exc_info=True)
                    self.telegram.send_error(error_msg)
                    await asyncio.sleep(5)
        finally:
            self.telegram.send_status("Bot was fully stopped.")

    def _update_internal_inventory(self, ctx):
        """Manually updates internal state based on execution results."""
        signal = ctx.signal
        from decimal import Decimal

        leg1_size = ctx.leg1_fill_size or 0
        leg2_size = ctx.leg2_fill_size or 0

        def get_venue(v_str):
            return Venue.BINANCE if v_str == "cex" else Venue.WALLET

        to_decimal = getattr(self.inventory, "_to_decimal", lambda x: Decimal(str(x)))

        if ctx.leg1_venue and leg1_size > 0:
            is_buy = (
                signal.direction.name == "BUY_CEX_SELL_DEX" and ctx.leg1_venue == "cex"
            ) or (
                signal.direction.name == "BUY_DEX_SELL_CEX" and ctx.leg1_venue == "dex"
            )

            side = "buy" if is_buy else "sell"
            price = ctx.leg1_fill_price

            base, quote = signal.pair.split("/")
            quote_qty = leg1_size * price

            fee = (
                quote_qty * 0.001
                if ctx.leg1_venue == "cex"
                else leg1_size * price * 0.003
            )

            self.inventory.record_trade(
                venue=get_venue(ctx.leg1_venue),
                side=side,
                base_asset=base,
                quote_asset=quote,
                base_amount=to_decimal(leg1_size),
                quote_amount=to_decimal(quote_qty),
                fee=to_decimal(fee),
                fee_asset=quote,
            )

        if ctx.leg2_venue and leg2_size > 0:
            is_buy = (
                signal.direction.name == "BUY_CEX_SELL_DEX" and ctx.leg2_venue == "cex"
            ) or (
                signal.direction.name == "BUY_DEX_SELL_CEX" and ctx.leg2_venue == "dex"
            )

            side = "buy" if is_buy else "sell"
            price = ctx.leg2_fill_price

            base, quote = signal.pair.split("/")
            quote_qty = leg2_size * price

            fee = (
                quote_qty * 0.001
                if ctx.leg2_venue == "cex"
                else leg2_size * price * 0.003
            )

            self.inventory.record_trade(
                venue=get_venue(ctx.leg2_venue),
                side=side,
                base_asset=base,
                quote_asset=quote,
                base_amount=to_decimal(leg2_size),
                quote_amount=to_decimal(quote_qty),
                fee=to_decimal(fee),
                fee_asset=quote,
            )

    async def _tick(self):
        if os.path.exists(KILL_SWITCH_FILE):
            msg = "KILL SWITCH ACTIVE - STOPPING"
            logger.critical(msg)
            self.telegram.send_critical(msg)
            self.stop()
            return

        if (
            hasattr(self.executor, "circuit_breaker")
            and self.executor.circuit_breaker.is_open()
        ):
            logger.warning("Circuit breaker is OPEN. Skipping tick.")
            return

        if time.time() - self.last_hour_reset > 3600:
            self.trades_this_hour = 0
            self.last_hour_reset = time.time()

        for pair in self.pairs:
            signal = self.generator.generate(pair, self.trade_size)
            if signal is None:
                continue

            if signal:
                logger.info(
                    f"DEBUG: Found signal."
                    f" Spread: {signal.spread_bps} bps. "
                    f"Net PnL: {signal.expected_net_pnl}"
                )
            else:
                logger.info("DEBUG: No signal generated (Spread too low or negative?)")

            current_skews = (
                self.inventory.get_skews()
                if hasattr(self.inventory, "get_skews")
                else {}
            )
            signal.score = self.scorer.score(signal, current_skews)

            if signal.score < 60:
                continue

            valid, reason = self.pre_trade_validator.validate_signal(signal)
            if not valid:
                logger.warning(f"Validation failed: {reason}")
                continue

            allowed, reason = self.risk_manager.check_pre_trade(signal)
            if not allowed:
                logger.warning(f"Risk check failed: {reason}")
                continue

            trade_val_usd = signal.size * signal.cex_price

            is_safe, reason = safety.safety_check(
                trade_usd=trade_val_usd,
                daily_loss=abs(min(0, self.risk_manager.daily_pnl)),
                total_capital=self.risk_manager.current_capital,
                trades_this_hour=self.trades_this_hour,
            )

            if not is_safe:
                msg = f"SAFETY VIOLATION: {reason}. STOPPING BOT."
                logger.critical(msg)
                self.telegram.send_critical(msg)
                self.stop()
                return

            if self.dry_run:
                logger.info(
                    f"DRY RUN | Would trade: {pair} {signal.direction.name} "
                    f"size={signal.size:.4f} spread={signal.spread_bps:.1f}bps "
                    f"expected_pnl=${signal.expected_net_pnl:.2f}"
                )
                self.trades_this_hour += 1
                continue

            logger.info(f"Executing: {signal.direction.name} {signal.size} {pair}")
            ctx = await self.executor.execute(signal)
            self.trades_this_hour += 1

            self.scorer.record_result(pair, ctx.state == ExecutorState.DONE)

            if ctx.state == ExecutorState.DONE:
                pnl = ctx.actual_net_pnl if ctx.actual_net_pnl else 0.0
                logger.info(f"SUCCESS: PnL=${pnl:.2f}")
                self.telegram.send_trade(
                    pair=pair, side=signal.direction.name, size=signal.size, pnl=pnl
                )
                self.risk_manager.record_trade(pnl)
                self._update_internal_inventory(ctx)

                await self._sync_balances()

                is_valid = await self.verify_balances()
                if not is_valid:
                    return

            else:
                logger.warning(f"FAILED: {ctx.error}")
                self.telegram.send_error(f"Trade was failed: {ctx.error}")
                await self._sync_balances()

            await self._sync_balances()

    async def _sync_balances(self):
        try:
            balances = self.exchange.fetch_balance()
            if hasattr(self.inventory, "update_from_cex"):
                self.inventory.update_from_cex(Venue.BINANCE, balances)
        except Exception as e:
            logger.error(f"Balance sync error: {e}")

    async def _fetch_token_balance_on_chain(
        self, symbol: str, address: Address
    ) -> float:
        """Отримує баланс токена з мережі та повертає як float."""
        try:
            token_address = self.config.get_token_address(symbol)
            decimals = self.config.get_token_decimals(symbol)
        except AttributeError:
            token_address = getattr(self.config, symbol.upper())
            decimals = 6 if symbol.upper() == "USDC" else 18

        token_amount = self.chain_client.get_token_balance(
            token_address, address.checksum, symbol, decimals
        )

        return float(token_amount.human)

    async def verify_balances(self):
        """
        Compares internal Inventory state vs Actual Exchange/Chain state.
        Stops bot if mismatch > 0.001 ETH detected.
        """
        logger.info("Running post-trade balance verification...")

        try:
            # CEX
            actual_cex_all = self.exchange.fetch_balance()
            actual_cex_eth = float(actual_cex_all.get("ETH", {}).get("free", 0.0))

            # DEX (Fetch from Chain)
            my_address = Address(self.wallet_manager.address)
            actual_dex_eth = await self._fetch_token_balance_on_chain("ETH", my_address)

            snapshot = self.inventory.snapshot()

            expected_cex_eth = float(
                snapshot["venues"]["binance"].get("ETH", {}).get("total", 0.0)
            )
            expected_dex_eth = float(
                snapshot["venues"]["wallet"].get("ETH", {}).get("total", 0.0)
            )

            cex_diff = abs(actual_cex_eth - expected_cex_eth)
            dex_diff = abs(actual_dex_eth - expected_dex_eth)

            logger.info(f"VERIFY: CEX Diff={cex_diff:.6f} | DEX Diff={dex_diff:.6f}")

            THRESHOLD = 0.001  # Tolerance
            if cex_diff > THRESHOLD or dex_diff > THRESHOLD:
                msg = (
                    f"BALANCE MISMATCH DETECTED!\n"
                    f"CEX: Exp={expected_cex_eth:.4f}, "
                    f"Act={actual_cex_eth:.4f}, Diff={cex_diff:.6f}\n"
                    f"DEX: Exp={expected_dex_eth:.4f}, "
                    f"Act={actual_dex_eth:.4f}, Diff={dex_diff:.6f}\n"
                    f"STOPPING BOT IMMEDIATELY."
                )
                logger.critical(msg)
                self.telegram.send_critical(msg)
                self.stop()
                return False

            return True

        except Exception as e:
            logger.error(f"Balance verification failed: {e}")
            return True

    def stop(self):
        self.running = False
        logger.info("Bot stopping...")


if __name__ == "__main__":
    bot_config = {
        "rpc_url": Config.RPC_URL,
        "pairs": ["ETH/USDC"] if Config.PRODUCTION else ["ETH/USDC"],
        "trade_size": 0.001 if Config.PRODUCTION else 0.1,
        "dry_run": Config.DRY_RUN,
        "signal_config": {"min_spread_bps": 5},
    }

    print("--- STARTING ARB BOT ---")
    print(f"MODE: {'DRY RUN' if bot_config['dry_run'] else 'LIVE TRADING'}")
    print(f"NETWORK: {'ARBITRUM ONE' if Config.PRODUCTION else 'TESTNET'}")
    print("------------------------")

    bot = ArbBot(bot_config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
