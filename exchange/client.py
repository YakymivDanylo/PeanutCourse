# exchange/client.py
import logging
import ccxt
from decimal import Decimal
import time
from config import Config
import math

logger = logging.Logger(__name__)


class ExchangeClient:
    """
    Wrapper around ccxt for Binance testnet.
    Handles rate limiting, error handling, and response normalization.
    """

    def __init__(self, config: dict):
        """
        Initialize with config dict containing apiKey, secret, sandbox flag.
        Must validate connection on init (fetch server time or status).
        """
        try:
            self.exchange = ccxt.binance(config)
            self.exchange.load_markets()
            logger.info("Connected to Binance Testnet successfully")
        except ccxt.AuthenticationError:
            logger.error("Authentication failed. Check API keys.")
            raise
        except ccxt.NetworkError:
            logger.error("Network error connecting to Binance.")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize exchange: {e}")
            raise

    def _to_decimal(self, value: float | str | None) -> Decimal:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))

    def fetch_order_book(
        self, symbol: str, limit: int = 20  # "ETH/USDT"  # Number of price levels
    ) -> dict:
        """
        Fetch L2 order book snapshot.

        Returns normalized dict:
        {
            'symbol': 'ETH/USDT',
            'timestamp': 1706000000000,
            'bids': [(price, qty), ...],  # Sorted best→worst
            'asks': [(price, qty), ...],  # Sorted best→worst
            'best_bid': (price, qty),
            'best_ask': (price, qty),
            'mid_price': Decimal,
            'spread_bps': Decimal,
        }
        """
        try:
            book = self.exchange.fetch_order_book(symbol, limit)

            bids = [(self._to_decimal(p), self._to_decimal(q)) for p, q in book["bids"]]
            asks = [(self._to_decimal(p), self._to_decimal(q)) for p, q in book["asks"]]

            best_bid = bids[0] if bids else (Decimal("0"), Decimal("0"))
            best_ask = asks[0] if asks else (Decimal("0"), Decimal("0"))

            mid_price = Decimal("0")
            spread_bps = Decimal("0")

            if best_bid[0] > 0 and best_ask[0] > 0:
                mid_price = (best_bid[0] + best_ask[0]) / 2
                spread = best_ask[0] - best_bid[0]
                spread_bps = (spread / mid_price) * 10000

            return {
                "symbol": symbol,
                "timestamp": book.get("timestamp") or int(time.time() * 1000),
                "bids": bids,
                "asks": asks,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid_price": mid_price,
                "spread_bps": spread_bps,
            }
        except ccxt.BaseError as e:
            logger.error(f"Error fetching odre book data for {symbol}: {e}")

    def fetch_balance(self) -> dict[str, dict]:
        """
        Fetch account balances.

        Returns:
        {
            'ETH':  {'free': Decimal('10.5'),
            'locked': Decimal('0'), 'total': Decimal('10.5')},
            'USDT': {'free': Decimal('20000'),
            'locked': Decimal('500'), 'total': Decimal('20500')},
        }
        Must filter out zero-balance assets.
        """
        try:
            raw_balance = self.exchange.fetch_balance()
            result = {}

            for currency, total_val in raw_balance.get("total", {}).items():
                if total_val > 0:
                    result[currency] = {
                        "free": self._to_decimal(raw_balance["free"].get(currency, 0)),
                        "locked": self._to_decimal(
                            raw_balance["used"].get(currency, 0)
                        ),
                        "total": self._to_decimal(total_val),
                    }

            return result
        except ccxt.BaseError as e:
            logger.error(f"Error fetching balance data: {e}")
            raise

    def _normalize_order(self, order: dict) -> dict:
        """Convert ccxt order dict to unified decimal-based format"""
        return {
            "id": str(order["id"]),
            "symbol": order["symbol"],
            "side": order["side"],
            "type": order["type"],
            "time_in_force": order["info"].get("timeInForce", "GTC"),
            "amount_requested": self._to_decimal(order["amount"]),
            "amount_filled": self._to_decimal(order["filled"]),
            "avg_fill_price": self._to_decimal(
                order.get("average") or order.get("price")
            ),
            "fee": self._to_decimal((order.get("fee") or {}).get("cost", 0)),
            "fee_asset": (order.get("fee") or {}).get("currency", ""),
            "status": order["status"],
            "timestamp": order["timestamp"],
        }

    def round_quantity(self, qty: float, step: float) -> float:
        """Rounding the quantity down to the nearest lot step."""
        if step <= 0:
            return qty
        return math.floor(qty / step) * step

    def round_price(self, price: float, tick: float) -> float:
        """Rounding the price to the nearest price step."""
        if tick <= 0:
            return price
        return round(price / tick) * tick

    def _get_market_filters(self, symbol: str) -> tuple[float, float]:
        """Dynamically retrieve step and tick from loaded ccxt markets."""
        try:
            market = self.exchange.market(symbol)
            step = float(market["precision"]["amount"])
            tick = float(market["precision"]["price"])
            return step, tick
        except Exception:
            return Config.ETH_LOT_SIZE_STEP, Config.ETH_PRICE_TICK

    def create_limit_ioc_order(
        self,
        symbol: str,  # "ETH/USDT"
        side: str,  # "buy" or "sell"
        amount: float,  # Quantity of base asset
        price: float,  # Limit price
    ) -> dict:
        """
        Place a LIMIT IOC (Immediate Or Cancel) order.

        Returns normalized order result:
        {
            'id': str,
            'symbol': str,
            'side': str,
            'type': 'limit',
            'time_in_force': 'IOC',
            'amount_requested': Decimal,
            'amount_filled': Decimal,
            'avg_fill_price': Decimal,
            'fee': Decimal,
            'fee_asset': str,
            'status': str,  # 'filled', 'partially_filled', 'expired'
            'timestamp': int,
        }

        Must handle: partial fills, rejection, and exchange errors.
        """
        try:
            params = {"timeInForce": "IOC"}
            order = self.exchange.create_order(
                symbol=symbol,
                type="limit",
                side=side,
                amount=amount,
                price=price,
                params=params,
            )
            return self._normalize_order(order)
        except ccxt.BaseError as e:
            logger.error(f"Error creating limit IOC: {e}")
            raise

    def create_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
    ) -> dict:
        """
        Place a market order. Same return format as create_limit_ioc_order.
        Use sparingly — LIMIT IOC is preferred for arb.
        """
        try:
            order = self.exchange.create_order(
                symbol=symbol, type="market", side=side, amount=amount
            )

            return self._normalize_order(order)
        except ccxt.BaseError as e:
            logger.error(f"Error creating market order: {e}")
            raise

    def cancel_order(self, order_id: str, symbol: str) -> dict:
        """Cancel an open order. Returns order status after cancel."""
        try:
            result = self.exchange.cancel_order(order_id, symbol)
            return self._normalize_order(result)
        except ccxt.BaseError as e:
            logger.error(f"Error cancel order: {e}")
            raise

    def fetch_order_status(self, order_id: str, symbol: str) -> dict:
        """Check current status of an order."""
        try:
            result = self.exchange.fetch_order_status(order_id, symbol)
            return self._normalize_order(result)
        except ccxt.BaseError as e:
            logger.error(f"Error fetching order status: {e}")
            raise

    def get_trading_fees(self, symbol: str) -> dict:
        """
        Returns fee structure:
        {'maker': Decimal('0.001'), 'taker': Decimal('0.001')}
        """
        try:
            fees = self.exchange.fetch_trading_fees([symbol])
            symbol_fees = fees.get(symbol, {})
            return {
                "maker": self._to_decimal(symbol_fees.get("maker", 0.001)),
                "taker": self._to_decimal(symbol_fees.get("taker", 0.001)),
            }
        except Exception:
            return {"maker": Decimal("0.001"), "taker": Decimal("0.001")}
