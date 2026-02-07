import argparse
import sys
import os
import csv
from datetime import datetime, timezone
from decimal import Decimal
from dotenv import load_dotenv

from exchange.orderbook import OrderBookAnalyzer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from configs.binance_config import BINANCE_CONFIG  # noqa: E402
from exchange.client import ExchangeClient  # noqa: E402
from chain.client import ChainClient  # noqa: E402
from core.types import Address  # noqa: E402
from pricing.amm import UniswapV2Pair  # noqa: E402
from inventory.tracker import InventoryTracker, Venue  # noqa: E402

TOKEN_MAP = {
    "ETH": Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
    "WETH": Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"),
    "USDC": Address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"),
    "USDT": Address("0xdAC17F958D2ee523a2206206994597C13D831ec7"),
}

DECIMALS = {
    "ETH": 18,
    "WETH": 18,
    "USDC": 6,
    "USDT": 6,
}

USDC_WETH_POOL = Address("0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc")
OPPORTUNITIES_FILE = "opportunities.csv"

RPC_URLS = [
    "https://eth.drpc.org",
    "https://rpc.ankr.com/eth",
    "https://cloudflare-eth.com",
    "https://1rpc.io/eth",
    "https://eth.llamarpc.com",
]


class ArbChecker:
    """
    Real-time arbitrage checker using live
    data from Binance Testnet and Ethereum Mainnet.
    Logs opportunities to CSV.
    """

    def __init__(
        self,
        exchange_client: ExchangeClient,
        chain_client: ChainClient,
        inventory_tracker: InventoryTracker,
    ):
        self.exchange = exchange_client
        self.chain = chain_client
        self.inventory = inventory_tracker
        self._init_csv()

    def _init_csv(self):
        """Initialize CSV file with headers if it doesn't exist."""
        if not os.path.exists(OPPORTUNITIES_FILE):
            with open(OPPORTUNITIES_FILE, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "timestamp",
                        "pair",
                        "direction",
                        "gap_bps",
                        "est_net_pnl_bps",
                        "gas_cost_usd",
                        "executable",
                    ]
                )

    def _log_opportunity(self, data: dict):
        """Append opportunity details to CSV."""
        try:
            with open(OPPORTUNITIES_FILE, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        datetime.now(timezone.utc).isoformat(),
                        data.get("pair"),
                        data.get("direction"),
                        f"{data.get('gap_bps', 0):.2f}",
                        f"{data.get('estimated_net_pnl_bps', 0):.2f}",
                        f"{data.get('details', {}).get('gas_cost_usd', 0):.2f}",
                        data.get("executable"),
                    ]
                )
        except IOError as e:
            print(f"Error logging opportunity: {e}")

    def check(self, pair: str, size: float) -> dict:
        """
        Analyzes arbitrage opportunity between
        Binance (Testnet) and Uniswap V2 (Mainnet).
        """
        size_dec = Decimal(str(size))
        base_sym, quote_sym = pair.split("/")

        book_data = self.exchange.fetch_order_book(pair)
        ob_analyzer = OrderBookAnalyzer(book_data)

        # Cost to buy size (Ask)
        cex_buy_sim = ob_analyzer.walk_the_book("buy", size)
        cex_ask_exec = cex_buy_sim["avg_price"]
        cex_buy_slippage = cex_buy_sim["slippage_bps"]

        # Cost to sell size(Bid)
        cex_sell_sim = ob_analyzer.walk_the_book("sell", size)
        cex_bid_exec = cex_sell_sim["avg_price"]
        cex_sell_slippage = cex_sell_sim["slippage_bps"]

        cex_fees = self.exchange.get_trading_fees(pair)
        cex_fee_bps = Decimal(cex_fees.get("taker", "0.001")) * 10000

        if not self.chain:
            raise ValueError("Chain Client is required for Arb Checker.")

        pool = UniswapV2Pair.from_chain(USDC_WETH_POOL, self.chain)

        base_addr = TOKEN_MAP.get(base_sym, TOKEN_MAP["WETH"])

        base_decimals = DECIMALS.get(base_sym, 18)
        quote_decimals = DECIMALS.get(quote_sym, 6)

        size_int = int(size_dec * (10**base_decimals))

        raw_spot_ratio = pool.get_spot_price(base_addr)  # Price of Base in Quote (Raw)
        adj_factor = Decimal(10**base_decimals) / Decimal(10**quote_decimals)
        dex_spot_price = raw_spot_ratio * adj_factor

        # Scenario A: Sell on DEX (Input Base -> Output Quote)
        # We give 'size' ETH, we get X USDT
        try:
            amount_out_quote = pool.get_amount_out(size_int, base_addr)
            dex_bid_exec = (
                Decimal(amount_out_quote) / (10**quote_decimals)
            ) / size_dec
        except ValueError:
            dex_bid_exec = Decimal("0")

        # Scenario B: Buy on DEX (Input Quote -> Output Base)
        # We want 'size' ETH, how much USDT do we need?
        try:
            amount_in_quote = pool.get_amount_in(size_int, base_addr)
            dex_ask_exec = (
                Decimal(amount_in_quote) / (10**quote_decimals)
            ) / size_dec
        except ValueError:
            dex_ask_exec = Decimal("0")

        # Calculate gaps using exec price

        # buy dex, sell cex
        gap_1 = cex_bid_exec - dex_ask_exec

        # buy cex, sell dex
        gap_2 = dex_bid_exec - cex_ask_exec

        direction = ""
        dex_price_exec = Decimal("0")
        cex_price_exec = Decimal("0")
        gap_usd = Decimal("0")

        final_dex_impact = Decimal("0")
        final_cex_slippage = Decimal("0")

        if gap_1 > gap_2:
            direction = "buy_dex_sell_cex"
            dex_price_exec = dex_ask_exec
            cex_price_exec = cex_bid_exec
            gap_usd = gap_1

            if dex_spot_price > 0:
                final_dex_impact = (
                    (dex_price_exec - dex_spot_price) / dex_spot_price
                ) * 10000

            final_cex_slippage = cex_sell_slippage

            wallet_need_asset = quote_sym
            wallet_need_amt = size_dec * dex_price_exec
            cex_need_asset = base_sym
            cex_need_amt = size_dec

        else:
            direction = "buy_cex_sell_dex"
            dex_price_exec = dex_bid_exec
            cex_price_exec = cex_ask_exec
            gap_usd = gap_2

            if dex_spot_price > 0:
                final_dex_impact = (
                    (dex_spot_price - dex_price_exec) / dex_spot_price
                ) * 10000

            final_cex_slippage = cex_buy_slippage

            wallet_need_asset = base_sym
            wallet_need_amt = size_dec
            cex_need_asset = quote_sym
            cex_need_amt = size_dec * cex_price_exec

        gas_cost_usd = Decimal("5.00")
        notional = size_dec * dex_price_exec
        gas_bps = (gas_cost_usd / notional * 10000) if notional > 0 else Decimal("0")

        dex_fee_bps = Decimal("30.0")

        total_costs_bps = cex_fee_bps + gas_bps

        gap_bps = (
            (gap_usd / dex_price_exec * 10000) if dex_price_exec > 0 else Decimal("0")
        )

        net_pnl_bps = gap_bps - total_costs_bps

        wallet_bal = self.inventory.get_available(Venue.WALLET, wallet_need_asset)
        cex_bal_data = self.inventory.get_available(Venue.BINANCE, cex_need_asset)
        cex_bal = cex_bal_data if isinstance(cex_bal_data, Decimal) else Decimal("0")

        inv_ok = (wallet_bal >= wallet_need_amt) and (cex_bal >= cex_need_amt)
        is_profitable = net_pnl_bps > 0
        executable = inv_ok and is_profitable

        if not is_profitable:
            verdict = "SKIP — not profitable"
        elif not inv_ok:
            verdict = "SKIP — insufficient inventory"
        else:
            verdict = "EXECUTE"

        result = {
            "pair": pair,
            "dex_price": dex_price_exec,
            "cex_price": cex_price_exec,
            "gap_usd": gap_usd,
            "gap_bps": gap_bps,
            "direction": direction,
            "estimated_costs_bps": total_costs_bps,  # Displaying external costs
            "estimated_net_pnl_bps": net_pnl_bps,
            "inventory_ok": inv_ok,
            "executable": executable,
            "verdict": verdict,
            "details": {
                "dex_fee_bps": dex_fee_bps,
                "dex_impact_bps": final_dex_impact,
                "cex_fee_bps": cex_fee_bps,
                "cex_slippage_bps": final_cex_slippage,
                "gas_cost_usd": gas_cost_usd,
                "gas_bps": gas_bps,
            },
            "inventory_details": {
                "wallet_asset": wallet_need_asset,
                "wallet_bal": wallet_bal,
                "wallet_need": wallet_need_amt,
                "cex_asset": cex_need_asset,
                "cex_bal": cex_bal,
                "cex_need": cex_need_amt,
            },
        }

        self._log_opportunity(result)
        return result


def main():
    parser = argparse.ArgumentParser(description="Real-Time Arb Checker")
    parser.add_argument(
        "pair", nargs="?", default="ETH/USDT", help="Trading pair (default: ETH/USDT)"
    )
    parser.add_argument(
        "--size", type=float, default=2.0, help="Trade size in base asset"
    )
    args = parser.parse_args()

    load_dotenv()

    print(f"Initializing Arb Checker for {args.pair}...")
    try:
        exchange = ExchangeClient(BINANCE_CONFIG)
        exchange.exchange.fetch_time()
    except Exception as e:
        print(f"❌ Failed to connect to Binance: {e}")
        return

    chain_client = None
    for rpc in RPC_URLS:
        try:
            client = ChainClient([rpc])
            client._w3.eth.block_number
            chain_client = client
            break
        except Exception:
            continue

    if not chain_client:
        print("❌ Failed to connect to Ethereum Mainnet (all RPCs failed).")
        return

    tracker = InventoryTracker()
    try:
        binance_balances = exchange.exchange.fetch_balance()
        cex_update = {}
        for asset in ["ETH", "USDT", "USDC"]:
            if asset in binance_balances:
                cex_update[asset] = {
                    "free": Decimal(str(binance_balances[asset]["free"])),
                    "locked": Decimal(str(binance_balances[asset]["used"])),
                    "total": Decimal(str(binance_balances[asset]["total"])),
                }
        tracker.update_from_cex(Venue.BINANCE, cex_update)
    except Exception as e:
        print(f"Could not fetch real Binance balances: {e}")

    tracker.update_from_wallet(
        Venue.WALLET,
        {
            "ETH": Decimal("10.0"),
            "USDT": Decimal("20000.0"),
            "USDC": Decimal("20000.0"),
        },
    )

    checker = ArbChecker(exchange, chain_client, tracker)
    res = checker.check(args.pair, args.size)

    print("\n═══════════════════════════════════════════")
    print(f"  REAL EXECUTION CHECK: {res['pair']} (size: {args.size} ETH)")
    print("═══════════════════════════════════════════")

    if res["direction"] == "buy_dex_sell_cex":
        dir_label = "Buy Uniswap -> Sell Binance"
        dex_side = "Ask (Buy)"
        cex_side = "Bid (Sell)"
    else:
        dir_label = "Buy Binance -> Sell Uniswap"
        dex_side = "Bid (Sell)"
        cex_side = "Ask (Buy)"

    print(f"\nStrategy: {dir_label}")

    print("\nPrices (Volume-Weighted):")

    print(
        f"  Uniswap V2 {dex_side}:    ${res['dex_price']:,.2f} (Includes Impact & Fee)"
    )
    print(f"  Binance {cex_side}:       ${res['cex_price']:,.2f} (Includes Slippage)")

    print(f"\nGap: ${res['gap_usd']:,.2f} ({res['gap_bps']:.1f} bps)")

    d = res["details"]
    print("\nMetrics:")
    print("  DEX fee (30bps):   [Included in Price]")
    print(f"  DEX price impact:  {d['dex_impact_bps']:.1f} bps")
    print(f"  CEX slippage:      {d['cex_slippage_bps']:.1f} bps")
    print("\nAdditional Costs:")
    print(f"  CEX fee:           {d['cex_fee_bps']:.1f} bps")
    print(f"  Gas:               ${d['gas_cost_usd']:.2f} ({d['gas_bps']:.1f} bps)")
    print("  ────────────────────────")

    pnl_sign = "✅" if res["estimated_net_pnl_bps"] > 0 else "❌"
    label = "PROFITABLE" if res["estimated_net_pnl_bps"] > 0 else "NOT PROFITABLE"
    print(
        f"\nNet PnL estimate: {res['estimated_net_pnl_bps']:.1f} bps {pnl_sign} {label}"
    )

    print("\nInventory:")
    inv = res["inventory_details"]

    def print_inv_line(venue, asset, balance, need):
        ok = "✅" if balance >= need else "❌"
        print(f"  {venue} {asset}:  {balance:,.4f} (need {need:,.4f}) {ok}")

    print_inv_line("Wallet", inv["wallet_asset"], inv["wallet_bal"], inv["wallet_need"])
    print_inv_line("Binance", inv["cex_asset"], inv["cex_bal"], inv["cex_need"])

    print(f"\nVerdict: {res['verdict']}")
    print("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
