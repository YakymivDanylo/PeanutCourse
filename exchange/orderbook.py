from decimal import Decimal


class OrderBookAnalyzer:
    """
    Analyze order book snapshots for trading decisions.
    """

    def __init__(self, orderbook: dict):
        """
        Initialize with order book from ExchangeClient.fetch_order_book().
        """
        self.bids = orderbook["bids"]
        self.asks = orderbook["asks"]
        self.best_bid = orderbook["best_bid"]
        self.best_ask = orderbook["best_ask"]
        self.mid_price = orderbook["mid_price"]
        self.symbol = orderbook.get("symbol", "Unknown")
        self.spread_bps = orderbook.get("spread_bps", Decimal(0))
        self.timestamp = orderbook.get("timestamp")

    def walk_the_book(
        self,
        side: str,  # "buy" (walk asks) or "sell" (walk bids)
        qty: float,  # Amount of base asset
    ) -> dict:
        """
        Simulate filling `qty` against the order book.
        """
        target_qty = Decimal(str(qty))
        remaining_qty = target_qty
        total_cost = Decimal("0")
        levels_consumed = 0
        fills = []
        fully_filled = True

        # Select side
        book_side = self.asks if side == "buy" else self.bids

        best_price = self.best_ask[0] if side == "buy" else self.best_bid[0]

        for price, available_qty in book_side:
            if remaining_qty <= 0:
                break

            levels_consumed += 1
            fill_qty = min(available_qty, remaining_qty)
            cost = fill_qty * price

            fills.append(
                {
                    "price": price,
                    "qty": fill_qty,
                    "cost": cost,
                }
            )

            total_cost += cost
            remaining_qty -= fill_qty

        if remaining_qty > 0:
            fully_filled = False

        filled_qty = target_qty - remaining_qty
        avg_price = Decimal("0")
        slippage_bps = Decimal("0")

        if filled_qty > 0:
            avg_price = total_cost / filled_qty
            if best_price > 0:
                diff = abs(avg_price - best_price)
                slippage_bps = (diff / best_price) * 10000

        return {
            "avg_price": avg_price,
            "total_cost": total_cost,
            "slippage_bps": slippage_bps,
            "levels_consumed": levels_consumed,
            "fully_filled": fully_filled,
            "fills": fills,
        }

    def depth_at_bps(
        self,
        side: str,  # "bid" or "ask"
        bps: float,  # How deep (e.g., 10 = within 10 bps of best)
    ) -> Decimal:
        """
        Total quantity available within `bps` basis points of best price.
        """
        threshold_bps = Decimal(str(bps))
        total_qty = Decimal("0")

        if side == "bid":
            best = self.best_bid[0]
            if best == 0:
                return Decimal("0")
            cutoff = best * (1 - threshold_bps / 10000)

            for price, qty in self.bids:
                if price >= cutoff:
                    total_qty += qty
                else:
                    break

        else:
            best = self.best_ask[0]
            if best == 0:
                return Decimal(0)
            cutoff = best * (1 + threshold_bps / 10000)

            for price, qty in self.asks:
                if price <= cutoff:
                    total_qty += qty
                else:
                    break

        return total_qty

    def imbalance(self, levels: int = 10) -> float:
        """
        Order book imbalance ratio.
        """
        bid_vol = sum(q for p, q in self.bids[:levels])
        ask_vol = sum(q for p, q in self.asks[:levels])

        total = bid_vol + ask_vol

        if total == 0:
            return 0.0

        return float((bid_vol - ask_vol) / total)

    def effective_spread(self, qty: float) -> Decimal:
        """
        Effective spread for a round-trip of size `qty`.
        """
        buy_sim = self.walk_the_book("buy", qty)
        sell_sim = self.walk_the_book("sell", qty)

        if not buy_sim["fully_filled"] or not sell_sim["fully_filled"]:
            return Decimal("0")

        avg_ask = buy_sim["avg_price"]
        avg_bid = sell_sim["avg_price"]

        if self.mid_price == 0:
            return Decimal("0")

        spread = avg_ask - avg_bid
        return (spread / self.mid_price) * 10000
