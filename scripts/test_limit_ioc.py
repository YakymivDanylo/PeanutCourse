import os
import sys
from decimal import Decimal
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from configs.binance_config import BINANCE_CONFIG  # noqa: E402
from exchange.client import ExchangeClient  # noqa: E402


def main():
    load_dotenv()

    if not os.getenv("BINANCE_TESTNET_API_KEY"):
        print("WARNING: BINANCE_TESTNET_API_KEY not found in .env")

    print("1. Initializing ExchangeClient (Testnet)")
    client = ExchangeClient(BINANCE_CONFIG)

    symbol = "ETH/USDT"

    try:
        print(f"\n2. Fetching Order Book for {symbol}")
        order_book = client.fetch_order_book(symbol)
        best_bid = order_book["bids"][0][0]
        best_ask = order_book["asks"][0][0]
        print(f"Best Bid: {best_bid}")
        print(f"Best Ask: {best_ask}")

        target_price = best_bid - Decimal("50.0")
        amount = Decimal("0.02")

        print("\n3. Placing LIMIT IOC Buy Order")
        print(f"Params: {symbol}, Side: BUY, Amount: {amount}, Price: {target_price}")
        print(
            "Expectation: Order should be "
            "CANCELED/EXPIRED immediately because price < best_ask"
        )

        order = client.create_limit_ioc_order(
            symbol=symbol, side="buy", amount=amount, price=target_price
        )

        print("\nOrder Response:")
        print(order)

        status = order.get("status")

        print(f"\nResult Status: {status}")

        if status in ["canceled", "expired"]:
            print("✅ SUCCESS: LIMIT IOC order was automatically cancelled as expected.")
        elif status == "filled":
            print("NOTE: Order was filled. Check if price passed was market-able.")
        else:
            print(
                f"❌ FAILURE: Unexpected status '{status}' for IOC order. "
                "Should be 'canceled' or 'expired'."
            )

        print("\n 4. (Optional) Placing Standard Limit Order & Cancelling Manually")

    except Exception as e:
        print(f"\n ERROR: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
