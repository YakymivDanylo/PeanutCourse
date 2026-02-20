import sys
import os
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


os.environ["PRODUCTION"] = "true"
os.environ["DRY_RUN"] = "true"

try:
    from config import Config
    from exchange.client import ExchangeClient
    from chain.client import ChainClient
    from strategy.fees import FeeStructure
    from safety import ABSOLUTE_MAX_TRADE_USD, ABSOLUTE_MAX_DAILY_LOSS, safety_check
    import safety
    from pricing.amm import UniswapV2Pair
    from core.types import Address
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)


def print_status(check_name, status, details=""):
    icon = "✅" if status else "❌"
    print(f"{icon} {check_name}: {details}")


def test_readiness():
    print(" Starting Code Readiness Verification...\n")

    print("--- 1. Binance Connection ---")
    try:
        exch_config = {
            "apiKey": os.getenv("BINANCE_API_KEY_PROD", ""),
            "secret": os.getenv("BINANCE_SECRET_KEY_PROD", ""),
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }
        Config.BINANCE_BASE_URL = "https://api.binance.com"

        client = ExchangeClient(exch_config)
        book = client.fetch_order_book("ARB/USDC", limit=5)

        if book and book["bids"] and book["asks"]:
            binance_price = book["bids"][0][0]
            print_status(
                "Binance Read Orderbook",
                True,
                f"Top Bid: {book['bids'][0][0]} Top Ask {book['asks'][0][0]}",
            )
        else:
            binance_price = None
            print_status("Binance Read Orderbook", False, "Empty orderbook")
    except Exception as e:
        binance_price = None
        print_status("Binance Connection", False, str(e))

    print("\n--- 2. Arbitrum Connection ---")
    try:
        if not Config.POOL_ADDRESS:
            print_status(
                "Arbitrum Pool Config", False, "POOL_ADDRESS is empty in config.py!"
            )
        else:
            rpc_url = Config.RPC_URL
            chain_client = ChainClient([rpc_url])

            gas_price = chain_client.get_gas_price_gwei()
            print_status(
                "Arbitrum RPC Connection", True, f"Current Gas: {gas_price:.4f} Gwei"
            )

            pool_addr = Address(Config.POOL_ADDRESS)
            pair = UniswapV2Pair.from_chain(pool_addr, chain_client)

            res_in, res_out = pair._get_reserve(Address(Config.ARB))

            normalized_in = Decimal(res_in) / Decimal(10**18)
            normalized_out = Decimal(res_out) / Decimal(10**6)

            if normalized_in > 0:
                dex_price = normalized_out / normalized_in
                print_status(
                    "Arbitrum Read Price", True, f"DEX Spot Price: {dex_price:.4f}"
                )
            else:
                print_status("Arbitrum Read Price", False, "No liquidity")

            if binance_price:
                diff = abs(float(dex_price) - float(binance_price))
                print(f"   ℹ️  Price Diff: {diff:.4f} USDC")

    except Exception as e:
        print_status("Arbitrum Connection", False, str(e))

    # 3. Fee calculation checks
    print("\n--- 3. Fee Configuration ---")
    fees = FeeStructure()
    if Config.CEX_FEE_BPS == 10.0 and Config.DEX_FEE_BPS == 30.0:
        print_status(
            "Fee Constants",
            True,
            f"CEX: {Config.CEX_FEE_BPS}bps, DEX: {Config.DEX_FEE_BPS}bps",
        )
    else:
        print_status(
            "Fee Constants",
            False,
            f"Expected 10/30, got {Config.CEX_FEE_BPS}/{Config.DEX_FEE_BPS}",
        )

    if fees.cex_taker_bps == 10.0 and fees.dex_swap_bps == 30.0:
        print_status(
            "Fee Calculation Logic", True, "FeeStructure defaults match requirements"
        )
    else:
        print_status(
            "Fee Calculation Logic", False, "Check defaults in strategy/fees.py"
        )

    print("\n--- 4. Risk & Safety Checks ---")

    is_safe_capital = safety.ABSOLUTE_MIN_CAPITAL == 50.0
    is_safe_trade = safety.ABSOLUTE_MAX_TRADE_USD == 25.0
    is_safe_loss = safety.ABSOLUTE_MAX_DAILY_LOSS == 20.0

    print_status(
        "Safety Constants Hardcoded",
        is_safe_capital and is_safe_trade and is_safe_loss,
        f"Max Trade: ${ABSOLUTE_MAX_TRADE_USD}, Max Loss: ${ABSOLUTE_MAX_DAILY_LOSS}",
    )

    can_trade, msg = safety_check(
        trade_usd=1000.0, daily_loss=0, total_capital=100, trades_this_hour=0
    )
    if not can_trade and "exceeds absolute max" in msg:
        print_status(
            "Circuit Breaker (Max Trade)", True, "Blocked large trade successfully"
        )
    else:
        print_status(
            "Circuit Breaker (Max Trade)", False, "Failed to block large trade"
        )

    can_trade_loss, msg_loss = safety_check(
        trade_usd=10.0,
        daily_loss=ABSOLUTE_MAX_DAILY_LOSS + 1,
        total_capital=100,
        trades_this_hour=0,
    )
    if not can_trade_loss and "reached absolute limit" in msg_loss:
        print_status(
            "Circuit Breaker (Max Loss)", True, "Blocked due to daily loss limit"
        )
    else:
        print_status("Circuit Breaker (Max Loss)", False, "Failed to block loss limit")

    print("\nDone.")


if __name__ == "__main__":
    test_readiness()
