import time
import logging
from typing import Optional

from web3 import Web3

from strategy.signal import Signal, Direction
from strategy.fees import FeeStructure
from core.types import Address
from pricing.engine import PricingEngine

TOKEN_MAP = {
    "ETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
    "USDT": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
    "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
    "ARB": "0x912CE59144191C1204E64559FE8253a0e49E6548",
}
DECIMALS = {"ETH": 18, "WETH": 18, "USDT": 6, "USDC": 6, "ARB": 18}

logger = logging.getLogger(__name__)


class SignalGenerator:
    def __init__(
        self,
        exchange_client,
        pricing_engine: PricingEngine,
        inventory_tracker,
        fee_structure: FeeStructure,
        config: dict,
    ):
        self.exchange = exchange_client
        self.pricing = pricing_engine
        self.inventory = inventory_tracker
        self.fees = fee_structure

        self.min_spread_bps = config.get("min_spread_bps", 50)
        self.min_profit_usd = config.get("min_profit_usd", 0.005)
        self.max_position_usd = config.get("max_position_usd", 10_000)
        self.signal_ttl = config.get("signal_ttl_seconds", 5)
        self.cooldown = config.get("cooldown_seconds", 2)

        self.token_map = config.get("token_map", TOKEN_MAP)
        self.last_signal_time: dict[str, float] = {}

    def generate(self, pair: str, size: float) -> Optional[Signal]:
        if self._in_cooldown(pair):
            return None

        prices = self._fetch_prices(pair, size)
        if prices is None:
            logger.warning(f"DEBUG: Could not fetch prices for {pair}")
            return None

        # Spread A: Buy CEX (Ask) -> Sell DEX (Bid/Exit)
        spread_a = (prices["dex_sell"] - prices["cex_ask"]) / prices["cex_ask"] * 10_000

        # Spread B: Buy DEX (Ask/Entry) -> Sell CEX (Bid)
        spread_b = (prices["cex_bid"] - prices["dex_buy"]) / prices["dex_buy"] * 10_000

        logger.info(
            f"DEBUG PRICE: {pair} | Size: {size} | "
            f"CEX {prices['cex_bid']:.2f}/{prices['cex_ask']:.2f} | "
            f"DEX Buy:{prices['dex_buy']:.2f} Sell:{prices['dex_sell']:.2f} | "
            f"Sprd A (C->D): {spread_a:.2f}bps | Sprd B (D->C): {spread_b:.2f}bps"
        )

        if spread_a > spread_b and spread_a >= self.min_spread_bps:
            direction = Direction.BUY_CEX_SELL_DEX
            spread = spread_a
            cex_price = prices["cex_ask"]
            dex_price = prices["dex_sell"]
        elif spread_b >= self.min_spread_bps:
            direction = Direction.BUY_DEX_SELL_CEX
            spread = spread_b
            cex_price = prices["cex_bid"]
            dex_price = prices["dex_buy"]
        else:
            return None

        trade_value_usd = size * cex_price
        fees_bps = self.fees.total_fee_bps(trade_value_usd)
        gross_pnl = (spread / 10_000) * trade_value_usd
        fees = (fees_bps / 10_000) * trade_value_usd
        net_pnl = gross_pnl - fees

        if net_pnl < self.min_profit_usd:
            logger.info(
                f"DEBUG: Signal rejected."
                f" Net PnL ${net_pnl:.4f} < Min ${self.min_profit_usd}"
            )
            return None

        inventory_ok = self._check_inventory(pair, direction, size, cex_price)
        within_limits = trade_value_usd <= self.max_position_usd

        signal = Signal.create(
            pair=pair,
            direction=direction,
            data_timestamp=prices["timestamp"],
            cex_price=cex_price,
            dex_price=dex_price,
            spread_bps=spread,
            size=size,
            expected_gross_pnl=gross_pnl,
            expected_fees=fees,
            expected_net_pnl=net_pnl,
            score=0,
            expiry=time.time() + self.signal_ttl,
            inventory_ok=inventory_ok,
            within_limits=within_limits,
        )

        self.last_signal_time[pair] = time.time()
        return signal

    def _in_cooldown(self, pair: str) -> bool:
        return time.time() - self.last_signal_time.get(pair, 0) < self.cooldown

    def _fetch_prices(self, pair: str, size: float) -> Optional[dict]:
        fetch_start_time = time.time()  # Фіксуємо час початку запитів
        try:
            ob = self.exchange.fetch_order_book(pair)
            cex_bid = float(ob["bids"][0][0])
            cex_ask = float(ob["asks"][0][0])

            base_symbol, quote_symbol = pair.split("/")

            base_addr = Address(Web3.to_checksum_address(self.token_map[base_symbol]))
            quote_addr = Address(Web3.to_checksum_address(self.token_map[quote_symbol]))

            base_decimals = DECIMALS.get(base_symbol, 18)
            quote_decimals = DECIMALS.get(quote_symbol, 18)

            amount_in_wei = int(size * (10**base_decimals))
            current_gas_gwei = self.pricing.client.get_gas_price_gwei()

            quote_sell = self.pricing.get_quote(
                token_in=base_addr,
                token_out=quote_addr,
                amount_in=amount_in_wei,
                gas_price_gwei=current_gas_gwei,
            )

            if not quote_sell or quote_sell.expected_output == 0:
                logger.warning(f"DEBUG: Quote Sell failed for {pair}")
                return None

            amount_out_human = quote_sell.expected_output / (10**quote_decimals)
            dex_sell_price = amount_out_human / size

            approx_usdt_in = size * cex_ask
            amount_in_usdt_wei = int(approx_usdt_in * (10**quote_decimals))

            quote_buy = self.pricing.get_quote(
                token_in=quote_addr,
                token_out=base_addr,
                amount_in=amount_in_usdt_wei,
                gas_price_gwei=current_gas_gwei,
            )

            if not quote_buy or quote_buy.expected_output == 0:
                logger.warning(f"DEBUG: Quote Buy failed for {pair}")
                return None

            amount_out_base_human = quote_buy.expected_output / (10**base_decimals)

            if amount_out_base_human == 0:
                return None

            dex_buy_price = approx_usdt_in / amount_out_base_human

            return {
                "cex_bid": cex_bid,
                "cex_ask": cex_ask,
                "dex_buy": dex_buy_price,
                "dex_sell": dex_sell_price,
                "timestamp": fetch_start_time,
            }

        except Exception as e:
            logging.error(f"Error fetching prices: {e}")
            return None

    def _check_inventory(
        self, pair: str, direction: Direction, size: float, price: float
    ) -> bool:
        base, quote = pair.split("/")
        try:
            if direction == Direction.BUY_CEX_SELL_DEX:
                # Check CEX Quote (USDT) & Wallet Base (ETH)
                cex_bal = float(self.inventory.get_available("binance", quote))
                dex_bal = float(self.inventory.get_available("wallet", base))

                # Check logic
                has_cex = cex_bal >= size * price
                has_dex = dex_bal >= size
                if not (has_cex and has_dex):
                    logger.warning(
                        f"Inventory Low for {direction.name}: CEX_USDC={cex_bal:.2f}"
                        f" (Need {size * price:.2f}),"
                        f" DEX_ETH={dex_bal:.4f} (Need {size:.4f})"
                    )
                return has_cex and has_dex
            else:
                # Check CEX Base (ETH) & Wallet Quote (USDT)
                cex_bal = float(self.inventory.get_available("binance", base))
                dex_bal = float(self.inventory.get_available("wallet", quote))

                has_cex = cex_bal >= size
                has_dex = dex_bal >= size * price
                if not (has_cex and has_dex):
                    logger.warning(
                        f"Inventory Low for {direction.name}:"
                        f" CEX_ETH={cex_bal:.4f} (Need {size:.4f}),"
                        f" DEX_USDC={dex_bal:.2f} (Need {size * price:.2f})"
                    )
                return has_cex and has_dex
        except Exception as e:
            logger.error(f"Inventory check error: {e}")
            return False
