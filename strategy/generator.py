import time
import logging
from typing import Optional

from web3 import Web3

from strategy.signal import Signal, Direction
from strategy.fees import FeeStructure
from core.types import Address
from pricing.engine import PricingEngine

TOKEN_MAP = {
    "ETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
}
DECIMALS = {"ETH": 18, "WETH": 18, "USDT": 6, "USDC": 6}


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
        self.min_profit_usd = config.get("min_profit_usd", 5.0)
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
            return None

        # Spread A: Buy CEX (Ask) -> Sell DEX (Bid/Exit)
        spread_a = (prices["dex_sell"] - prices["cex_ask"]) / prices["cex_ask"] * 10_000

        # Spread B: Buy DEX (Ask/Entry) -> Sell CEX (Bid)
        spread_b = (prices["cex_bid"] - prices["dex_buy"]) / prices["dex_buy"] * 10_000

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
            return None

        inventory_ok = self._check_inventory(pair, direction, size, cex_price)
        within_limits = trade_value_usd <= self.max_position_usd

        signal = Signal.create(
            pair=pair,
            direction=direction,
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
                return None

            amount_out_base_human = quote_buy.expected_output / (10**base_decimals)

            dex_buy_price = approx_usdt_in / amount_out_base_human

            return {
                "cex_bid": cex_bid,
                "cex_ask": cex_ask,
                "dex_buy": dex_buy_price,
                "dex_sell": dex_sell_price,
            }

        except Exception as e:
            logging.error(f"Error fetching prices: {e}")
            return None

    def _check_inventory(
        self, pair: str, direction: Direction, size: float, price: float
    ) -> bool:
        base, quote = pair.split("/")
        if direction == Direction.BUY_CEX_SELL_DEX:
            # Check CEX Quote (USDT) & Wallet Base (ETH)
            cex_bal = float(self.inventory.get_available("binance", quote))
            dex_bal = float(self.inventory.get_available("wallet", base))
            return cex_bal >= size * price and dex_bal >= size
        else:
            # Check CEX Base (ETH) & Wallet Quote (USDT)
            cex_bal = float(self.inventory.get_available("binance", base))
            dex_bal = float(self.inventory.get_available("wallet", quote))
            return cex_bal >= size and dex_bal >= size * price
