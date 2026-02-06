import argparse
import sys
import os
import csv
from datetime import datetime, timezone
from decimal import Decimal
from dotenv import load_dotenv

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

        book = self.exchange.fetch_order_book(pair)
        best_bid = Decimal(book["best_bid"][0])
        best_ask = Decimal(book["best_ask"][0])

        cex_fees = self.exchange.get_trading_fees(pair)
        cex_fee_bps = Decimal(cex_fees.get("taker", "0.001")) * 10000

        if not self.chain:
            raise ValueError("ChainClient is required for Real Arb Check")

        pool = UniswapV2Pair.from_chain(USDC_WETH_POOL, self.chain)

        weth_addr = TOKEN_MAP["WETH"]

        if pool.token0 == weth_addr:
            weth_res = Decimal(pool.reserve0) / Decimal(10 ** DECIMALS["WETH"])
            usdc_res = Decimal(pool.reserve1) / Decimal(10 ** DECIMALS["USDC"])
        else:
            usdc_res = Decimal(pool.reserve0) / Decimal(10 ** DECIMALS["USDC"])
            weth_res = Decimal(pool.reserve1) / Decimal(10 ** DECIMALS["WETH"])

        dex_spot_price = usdc_res / weth_res

        gap_1 = best_bid - dex_spot_price
        gap_2 = dex_spot_price - best_ask

        direction = ""
        dex_price = Decimal("0")
        cex_price = Decimal("0")
        gap_usd = Decimal("0")
        dex_impact_bps = Decimal("0")

        impact_est = (size_dec / weth_res) * 100

        if gap_1 > gap_2:
            direction = "buy_dex_sell_cex"
            dex_price = dex_spot_price
            cex_price = best_bid
            gap_usd = gap_1
            dex_impact_bps = impact_est

            wallet_need_asset = quote_sym
            wallet_need_amt = size_dec * dex_price
            cex_need_asset = base_sym
            cex_need_amt = size_dec

        else:
            direction = "buy_cex_sell_dex"
            dex_price = dex_spot_price
            cex_price = best_ask
            gap_usd = gap_2
            dex_impact_bps = impact_est

            wallet_need_asset = base_sym
            wallet_need_amt = size_dec
            cex_need_asset = quote_sym
            cex_need_amt = size_dec * cex_price

        gas_cost_usd = Decimal("5.00")
        notional = size_dec * dex_price
        gas_bps = (gas_cost_usd / notional * 10000) if notional > 0 else Decimal("0")
        dex_fee_bps = Decimal("30.0")
        cex_slippage_bps = Decimal("0.0")

        total_costs_bps = (
            dex_fee_bps + dex_impact_bps + cex_fee_bps + cex_slippage_bps + gas_bps
        )

        gap_bps = (gap_usd / dex_price * 10000) if dex_price > 0 else Decimal("0")
        net_pnl_bps = gap_bps - total_costs_bps

        wallet_bal = self.inventory.get_available(Venue.WALLET, wallet_need_asset)
        cex_bal_data = self.inventory.get_available(Venue.BINANCE, cex_need_asset)
        cex_bal = cex_bal_data if isinstance(cex_bal_data, Decimal) else Decimal("0")

        inv_ok = (wallet_bal >= wallet_need_amt) and (cex_bal >= cex_need_amt)
        executable = inv_ok and (net_pnl_bps > 0)

        result = {
            "pair": pair,
            "dex_price": dex_price,
            "cex_price": cex_price,
            "gap_usd": gap_usd,
            "gap_bps": gap_bps,
            "direction": direction,
            "estimated_costs_bps": total_costs_bps,
            "estimated_net_pnl_bps": net_pnl_bps,
            "inventory_ok": inv_ok,
            "executable": executable,
            "details": {
                "dex_fee_bps": dex_fee_bps,
                "dex_impact_bps": dex_impact_bps,
                "cex_fee_bps": cex_fee_bps,
                "cex_slippage_bps": cex_slippage_bps,
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
    print(f"  ARB CHECK: {res['pair']} (size: {args.size} ETH)")
    print("═══════════════════════════════════════════")

    dex_lbl = "buy" if res["direction"] == "buy_dex_sell_cex" else "sell"
    cex_lbl = "bid" if res["direction"] == "buy_dex_sell_cex" else "ask"

    print("\nPrices:")
    print(f"  Uniswap V2:      ${res['dex_price']:,.2f} ({dex_lbl} {args.size:g} ETH)")
    print(f"  Binance {cex_lbl}:      ${res['cex_price']:,.2f}")

    print(f"\nGap: ${res['gap_usd']:,.2f} ({res['gap_bps']:.1f} bps)")

    d = res["details"]
    print("\nCosts:")
    print(f"  DEX fee:           {d['dex_fee_bps']:.1f} bps")
    print(f"  DEX price impact:   {d['dex_impact_bps']:.1f} bps")
    print(f"  CEX fee:           {d['cex_fee_bps']:.1f} bps")
    print(f"  CEX slippage:       {d['cex_slippage_bps']:.1f} bps")
    print(f"  Gas:               ${d['gas_cost_usd']:.2f} ({d['gas_bps']:.1f} bps)")
    print("  ────────────────────────")
    print(f"  Total costs:       {res['estimated_costs_bps']:.1f} bps")

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

    verdict = "EXECUTE" if res["executable"] else "SKIP — costs exceed gap"
    print(f"\nVerdict: {verdict}")
    print("═══════════════════════════════════════════")


if __name__ == "__main__":
    main()
