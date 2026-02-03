import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse  # noqa: E402
from exchange.orderbook import OrderBookAnalyzer  # noqa: E402

try:
    from exchange.client import ExchangeClient  # noqa: E402
    from configs.binance_config import BINANCE_CONFIG  # noqa: E402
except ImportError:
    pass


def run_cli():
    """CLI Entrypoint"""
    parser = argparse.ArgumentParser(description="Analyze Order Book")
    parser.add_argument("symbol", type=str, help="Trading pair (e.g., ETH/USDT)")
    parser.add_argument(
        "--depth", type=int, default=20, help="Order book depth to fetch"
    )
    args = parser.parse_args()

    try:
        client = ExchangeClient(BINANCE_CONFIG)
        print(f"Fetching order book for {args.symbol}...")

        book_data = client.fetch_order_book(args.symbol, args.depth)
        analyzer = OrderBookAnalyzer(book_data)

        imbalance = analyzer.imbalance()

        price = book_data["mid_price"]
        if price > 1000:
            qty_small = 0.1
            qty_large = 1.0
        else:
            qty_small = 10
            qty_large = 100

        sim_small_buy = analyzer.walk_the_book("buy", qty_small)
        sim_large_buy = analyzer.walk_the_book("buy", qty_large)
        eff_spread = analyzer.effective_spread(qty_small)

        depth_bids = analyzer.depth_at_bps("bid", 10)
        depth_asks = analyzer.depth_at_bps("ask", 10)

        print("\n" + "╔" + "═" * 54 + "╗")
        print(f"║  {args.symbol} Order Book Analysis".ljust(55) + "║")
        print(f"║  Timestamp: {book_data.get('timestamp')}".ljust(55) + "║")
        print("╠" + "═" * 54 + "╣")

        bb_price, bb_qty = book_data["best_bid"]
        ba_price, ba_qty = book_data["best_ask"]

        print(f"║  Best Bid:    ${bb_price:,.2f} x {bb_qty:.4f}".ljust(55) + "║")
        print(f"║  Best Ask:    ${ba_price:,.2f} x {ba_qty:.4f}".ljust(55) + "║")
        print(f"║  Mid Price:   ${book_data['mid_price']:,.2f}".ljust(55) + "║")
        print(f"║  Spread:      {book_data['spread_bps']:.2f} bps".ljust(55) + "║")
        print("╠" + "═" * 54 + "╣")
        print("║  Depth (within 10 bps):".ljust(55) + "║")
        print(f"║    Bids: {depth_bids:,.4f}".ljust(55) + "║")
        print(f"║    Asks: {depth_asks:,.4f}".ljust(55) + "║")

        imb_desc = "Neutral"
        if imbalance > 0.1:
            imb_desc = "Buy Pressure"
        if imbalance < -0.1:
            imb_desc = "Sell Pressure"
        print(f"║  Imbalance:   {imbalance:+.2f} ({imb_desc})".ljust(55) + "║")
        print("╠" + "═" * 54 + "╣")

        print(f"║  Walk-the-book ({qty_small} buy):".ljust(55) + "║")
        print(f"║    Avg Price: ${sim_small_buy['avg_price']:,.2f}".ljust(55) + "║")
        print(
            f"║    Slippage:  {sim_small_buy['slippage_bps']:.2f} bps".ljust(55) + "║"
        )

        print(f"║  Walk-the-book ({qty_large} buy):".ljust(55) + "║")
        print(f"║    Avg Price: ${sim_large_buy['avg_price']:,.2f}".ljust(55) + "║")
        print(
            f"║    Slippage:  {sim_large_buy['slippage_bps']:.2f} bps".ljust(55) + "║"
        )
        print("╠" + "═" * 54 + "╣")
        print(
            f"║  Effective Spread ({qty_small} round-trip): {eff_spread:.2f} bps".ljust(
                55
            )
            + "║"
        )
        print("╚" + "═" * 54 + "╝")

    except Exception as e:
        print(f"Error running analysis: {e}")


if __name__ == "__main__":
    run_cli()
