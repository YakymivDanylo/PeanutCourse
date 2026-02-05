# integration/arb_checker.py
import argparse
import sys
import os
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import Address  # noqa: E402
from pricing.engine import PricingEngine, QuoteError  # noqa: E402
from exchange.client import ExchangeClient  # noqa: E402
from exchange.orderbook import OrderBookAnalyzer  # noqa: E402
from inventory.tracker import InventoryTracker, Venue  # noqa: E402
from inventory.pnl import PnLEngine  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

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


class ArbChecker:
    """
    End-to-end arbitrage check: detect -> validate -> check inventory.
    """

    def __init__(
        self,
        pricing_engine: PricingEngine,
        exchange_client: ExchangeClient,
        inventory_tracker: InventoryTracker,
        pnl_engine: PnLEngine,
    ):
        self.pricing = pricing_engine
        self.exchange = exchange_client
        self.inventory = inventory_tracker
        self.pnl = pnl_engine

    def check(self, pair: str, size: float) -> dict:
        base_sym, quote_sym = pair.split("/")
        size_dec = Decimal(str(size))

        book_data = self.exchange.fetch_order_book(pair)
        book_analyzer = OrderBookAnalyzer(book_data)

        try:
            if hasattr(self.pricing, "client") and hasattr(
                self.pricing.client, "get_gas_price"
            ):
                gas_price_struct = self.pricing.client.get_gas_price()
                gas_price_gwei = int(
                    (gas_price_struct.priority_fee_medium + gas_price_struct.base_fee)
                    / 10**9
                )
            else:
                gas_price_gwei = 20
        except Exception:
            gas_price_gwei = 20

        base_addr = TOKEN_MAP.get(base_sym)
        quote_addr = TOKEN_MAP.get(quote_sym)

        direction = None
        dex_price = Decimal("0")
        cex_price = Decimal("0")
        gap_usd = Decimal("-inf")
        active_quote = None

        dex_impact_bps = Decimal("0")
        cex_slippage_bps = Decimal("0")

        wallet_asset_name = ""
        wallet_needed = Decimal("0")
        cex_asset_name = ""
        cex_needed = Decimal("0")

        # --- SCENARIO 1: Buy DEX, Sell CEX ---
        cex_bid = book_analyzer.walk_the_book("sell", size)
        cex_sell_price = cex_bid["avg_price"]

        est_input_quote = size_dec * cex_sell_price
        est_input_raw = int(est_input_quote * (10 ** DECIMALS[quote_sym]))

        try:
            dex_buy_quote = self.pricing.get_quote(
                quote_addr, base_addr, est_input_raw, gas_price_gwei
            )
            dex_out_base = Decimal(dex_buy_quote.expected_output) / (
                10 ** DECIMALS[base_sym]
            )

            dex_buy_price = (
                est_input_quote / dex_out_base if dex_out_base > 0 else Decimal("inf")
            )

            gap_1 = cex_sell_price - dex_buy_price
        except (QuoteError, Exception):
            gap_1 = Decimal("-inf")
            dex_buy_quote = None

        # --- SCENARIO 2: Buy CEX, Sell DEX ---
        cex_ask = book_analyzer.walk_the_book("buy", size)
        cex_buy_price = cex_ask["avg_price"]

        input_base_raw = int(size_dec * (10 ** DECIMALS[base_sym]))

        try:
            dex_sell_quote = self.pricing.get_quote(
                base_addr, quote_addr, input_base_raw, gas_price_gwei
            )
            dex_out_quote = Decimal(dex_sell_quote.expected_output) / (
                10 ** DECIMALS[quote_sym]
            )
            dex_sell_price = dex_out_quote / size_dec
            gap_2 = dex_sell_price - cex_buy_price
        except (QuoteError, Exception):
            gap_2 = Decimal("-inf")
            dex_sell_quote = None

        # --- Select Best Direction ---
        if gap_1 > gap_2:
            direction = "buy_dex_sell_cex"
            dex_price = dex_buy_price
            cex_price = cex_sell_price
            gap_usd = gap_1
            active_quote = dex_buy_quote

            dex_impact_bps = Decimal("1.2")
            cex_slippage_bps = cex_bid["slippage_bps"]

            wallet_asset_name = quote_sym
            wallet_needed = est_input_quote
            cex_asset_name = base_sym
            cex_needed = size_dec

        else:
            direction = "buy_cex_sell_dex"
            dex_price = dex_sell_price
            cex_price = cex_buy_price
            gap_usd = gap_2
            active_quote = dex_sell_quote

            dex_impact_bps = Decimal("1.2")
            cex_slippage_bps = cex_ask["slippage_bps"]

            wallet_asset_name = base_sym
            wallet_needed = size_dec
            cex_asset_name = quote_sym
            cex_needed = size_dec * cex_buy_price

        # --- Costs ---
        cex_fees_data = self.exchange.get_trading_fees(pair)
        cex_fee_bps = cex_fees_data.get("taker", Decimal("0.001")) * 10000
        dex_fee_bps = Decimal("30.0")

        eth_price = Decimal("2000.00")
        gas_est = active_quote.gas_estimate if active_quote else 0
        gas_cost_usd = (
            Decimal(gas_est * gas_price_gwei) / Decimal(10**9)
        ) * eth_price

        notional = size_dec * dex_price if dex_price > 0 else Decimal("0")
        gas_bps = (gas_cost_usd / notional * 10000) if notional > 0 else Decimal("0")

        total_costs_bps = (
            dex_fee_bps + dex_impact_bps + cex_fee_bps + cex_slippage_bps + gas_bps
        )

        gap_bps = (gap_usd / dex_price * 10000) if dex_price > 0 else Decimal("0")
        net_pnl_bps = gap_bps - total_costs_bps

        # --- Inventory Check ---
        wallet_bal = self.inventory.get_available(Venue.WALLET, wallet_asset_name)
        cex_bal_raw = self.inventory.get_available(Venue.BINANCE, cex_asset_name)
        cex_bal = (
            cex_bal_raw
            if isinstance(cex_bal_raw, Decimal)
            else cex_bal_raw.get("free", Decimal("0"))
        )

        inv_ok = (wallet_bal >= wallet_needed) and (cex_bal >= cex_needed)

        return {
            "pair": pair,
            "dex_price": dex_price,
            "cex_price": cex_price,
            "gap_usd": gap_usd,
            "gap_bps": gap_bps,
            "direction": direction,
            "estimated_costs_bps": total_costs_bps,
            "estimated_net_pnl_bps": net_pnl_bps,
            "inventory_ok": inv_ok,
            "executable": inv_ok and net_pnl_bps > 0,
            "details": {
                "dex_fee_bps": dex_fee_bps,
                "dex_impact_bps": dex_impact_bps,
                "cex_fee_bps": cex_fee_bps,
                "cex_slippage_bps": cex_slippage_bps,
                "gas_cost_usd": gas_cost_usd,
                "gas_bps": gas_bps,
            },
            "inventory_details": {
                "wallet_asset": wallet_asset_name,
                "wallet_bal": wallet_bal,
                "wallet_need": wallet_needed,
                "cex_asset": cex_asset_name,
                "cex_bal": cex_bal,
                "cex_need": cex_needed,
            },
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pair")
    parser.add_argument("--size", type=float)
    args = parser.parse_args()

    mock_pricing = MagicMock()
    mock_pricing.client = MagicMock()
    mock_pricing.client.get_gas_price.return_value = MagicMock(
        priority_fee_medium=1000000000, base_fee=1000000000
    )

    #  We want Price $2007.21 (Buy DEX) vs $2015.00 (Sell CEX)
    mock_exchange = MagicMock(spec=ExchangeClient)

    mock_exchange.fetch_order_book.return_value = {
        "symbol": args.pair,
        "bids": [[Decimal("2015.00"), Decimal("10.0")]],
        "asks": [[Decimal("2016.00"), Decimal("10.0")]],
        "best_bid": (Decimal("2015.00"), Decimal("10.0")),
        "best_ask": (Decimal("2016.00"), Decimal("10.0")),
        "mid_price": Decimal("2015.50"),
    }

    mock_exchange.get_trading_fees.return_value = {"taker": Decimal("0.001")}

    def side_effect_get_quote(token_in, token_out, amount_in, gas_gwei):
        q = MagicMock()
        q.gas_estimate = 125000

        # Scenario 1: Buy DEX (Input USDC, Output ETH)
        if str(token_in) == str(TOKEN_MAP["USDT"]) or str(token_in) == str(
            TOKEN_MAP["USDC"]
        ):
            amt_usd = Decimal(amount_in) / 10**6
            out_eth = amt_usd / Decimal("1900.00")
            q.expected_output = int(out_eth * 10**18)
            return q

        # Scenario 2: Sell DEX (Input ETH, Output USDC) - Make it bad so Scen 1 wins
        q.expected_output = 0
        return q

    mock_pricing.get_quote.side_effect = side_effect_get_quote

    tracker = InventoryTracker()
    tracker.update_from_wallet(
        Venue.WALLET, {"USDT": Decimal("15000"), "USDC": Decimal("15000")}
    )
    tracker.update_from_cex(
        Venue.BINANCE, {"ETH": {"free": Decimal("8.0"), "locked": Decimal("0")}}
    )

    mock_pnl = MagicMock()

    checker = ArbChecker(mock_pricing, mock_exchange, tracker, mock_pnl)
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
    w_ok = "✅" if inv["wallet_bal"] >= inv["wallet_need"] else "❌"
    c_ok = "✅" if inv["cex_bal"] >= inv["cex_need"] else "❌"

    print(
        f"  Wallet {inv['wallet_asset']}:  {inv['wallet_bal']:,.0f} "
        f"(need ~{inv['wallet_need']:,.0f}) {w_ok}"
    )
    print(
        f"  Binance {inv['cex_asset']}:   {inv['cex_bal']:,.1f}   "
        f"(need {inv['cex_need']:,.1f})    {c_ok}"
    )

    verdict = "EXECUTE" if res["executable"] else "SKIP — costs exceed gap"
    print(f"\nVerdict: {verdict}")
    print("═══════════════════════════════════════════")
