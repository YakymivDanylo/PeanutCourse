import sys
import os
import time
import random
from decimal import Decimal
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.live import Live  # noqa: E402
from rich.layout import Layout  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

from integration.arb_checker import ArbChecker, TOKEN_MAP  # noqa: E402
from inventory.tracker import InventoryTracker, Venue  # noqa: E402
from inventory.pnl import PnLEngine  # noqa: E402
from exchange.client import ExchangeClient  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402


def make_layout() -> Layout:
    """Define the grid layout."""
    layout = Layout(name="root")

    layout.split(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer", size=3),
    )

    layout["main"].split_row(
        Layout(name="left", ratio=2),
        Layout(name="right", ratio=3),
    )

    layout["left"].split_column(
        Layout(name="inventory", ratio=1),
        Layout(name="recent_trades", ratio=1),
    )

    layout["right"].split_column(
        Layout(name="prices", ratio=1),
        Layout(name="gaps", ratio=2),
    )

    return layout


def generate_inventory_table(tracker: InventoryTracker) -> Table:
    table = Table(title="Wallet & Exchange Balances", expand=True)
    table.add_column("Venue", style="cyan")
    table.add_column("Asset", style="magenta")
    table.add_column("Free", justify="right")
    table.add_column("Total", justify="right")

    snapshot = tracker.snapshot()

    for venue_name, assets in snapshot["venues"].items():
        for asset, data in assets.items():
            if data["total"] > 0:
                table.add_row(
                    venue_name.capitalize(),
                    asset,
                    f"{data['free']:.4f}",
                    f"{data['total']:.4f}",
                )
    return table


def generate_gap_table(last_check: dict) -> Table:
    table = Table(title="Live Arbitrage Check", expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    if not last_check:
        table.add_row("Status", "Waiting for data...")
        return table

    pair = last_check.get("pair", "N/A")
    gap_bps = last_check.get("gap_bps", 0)
    net_pnl = last_check.get("estimated_net_pnl_bps", 0)
    executable = last_check.get("executable", False)

    color = "green" if executable else "red"

    table.add_row("Pair", pair)
    table.add_row("DEX Price", f"${last_check.get('dex_price', 0):,.2f}")
    table.add_row("CEX Price", f"${last_check.get('cex_price', 0):,.2f}")
    table.add_row("Gap", f"{gap_bps:.2f} bps")
    table.add_row("Est. Net PnL", Text(f"{net_pnl:.2f} bps", style=color))
    table.add_row("Inventory OK", "✅" if last_check.get("inventory_ok") else "❌")
    table.add_row(
        "Verdict", Text("EXECUTE" if executable else "SKIP", style=f"bold {color}")
    )

    return table


class DashboardApp:
    def __init__(self):
        self.current_dex_price = Decimal("2000.00")

        self.pricing = MagicMock()
        self.pricing.client.get_gas_price.return_value = MagicMock(
            priority_fee_medium=1000000000, base_fee=1000000000
        )

        def dynamic_quote(token_in, token_out, amount_in, gas_price):
            q = MagicMock()
            q.gas_estimate = 120000

            amount_in_dec = Decimal(amount_in)
            PRICE = self.current_dex_price

            t_in = str(token_in).lower()
            eth_addrs = [str(TOKEN_MAP["ETH"]).lower(), str(TOKEN_MAP["WETH"]).lower()]
            stable_addrs = [
                str(TOKEN_MAP["USDT"]).lower(),
                str(TOKEN_MAP["USDC"]).lower(),
            ]

            if t_in in stable_addrs:
                usd_amount = amount_in_dec / Decimal("1000000")
                eth_out = usd_amount / PRICE
                q.expected_output = int(eth_out * Decimal("10") ** 18)

            elif t_in in eth_addrs:
                eth_amount = amount_in_dec / Decimal("10") ** 18
                usd_out = eth_amount * PRICE
                q.expected_output = int(usd_out * Decimal("1000000"))

            else:
                q.expected_output = 0

            return q

        self.pricing.get_quote.side_effect = dynamic_quote

        self.exchange = MagicMock(spec=ExchangeClient)
        self.exchange.get_trading_fees.return_value = {"taker": Decimal("0.001")}

        self.tracker = InventoryTracker()

        self.tracker.update_from_wallet(
            Venue.WALLET, {"ETH": Decimal("10.0"), "USDT": Decimal("50000")}
        )
        self.tracker.update_from_cex(
            Venue.BINANCE,
            {
                "ETH": {"free": Decimal("2.0"), "locked": Decimal("0")},
                "USDT": {"free": Decimal("10000"), "locked": Decimal("0")},
            },
        )

        self.pnl_engine = PnLEngine()

        self.checker = ArbChecker(
            self.pricing, self.exchange, self.tracker, self.pnl_engine
        )
        self.last_check_result = {}

    def update_market_data(self):
        """Simulate changing market conditions."""
        trend = random.uniform(-2, 2)
        base_price = Decimal("2000") + Decimal(trend)

        self.current_dex_price = base_price + Decimal(random.uniform(-1, 1))

        spread = Decimal(random.uniform(-5, 15))
        cex_price = self.current_dex_price + spread

        self.exchange.fetch_order_book.return_value = {
            "symbol": "ETH/USDT",
            "bids": [[cex_price, Decimal("10")]],
            "asks": [[cex_price + Decimal("0.5"), Decimal("10")]],
            "best_bid": (cex_price, Decimal("10")),
            "best_ask": (cex_price + Decimal("0.5"), Decimal("10")),
            "mid_price": cex_price,
            "spread_bps": Decimal("5"),
        }

    def run(self):
        layout = make_layout()
        layout["header"].update(
            Panel(
                Text(
                    "🥜 PeanutCourse Arbitrage Bot Dashboard",
                    justify="center",
                    style="bold white on blue",
                )
            )
        )

        with Live(layout, refresh_per_second=4, screen=True):
            while True:
                self.update_market_data()

                self.last_check_result = self.checker.check("ETH/USDT", 1.0)

                layout["inventory"].update(
                    Panel(generate_inventory_table(self.tracker))
                )
                layout["gaps"].update(Panel(generate_gap_table(self.last_check_result)))

                dex_p = self.last_check_result.get("dex_price", 0)
                cex_p = self.last_check_result.get("cex_price", 0)

                prices_text = Text()
                prices_text.append(f"Uniswap: ${dex_p:,.2f}\n", style="yellow")
                prices_text.append(f"Binance: ${cex_p:,.2f}\n", style="cyan")
                layout["prices"].update(Panel(prices_text, title="Live Prices"))

                trades_text = Text("No executed trades yet...", style="dim")
                layout["recent_trades"].update(
                    Panel(trades_text, title="Recent Trades")
                )

                t = datetime.now().strftime("%H:%M:%S")
                layout["footer"].update(
                    Panel(Text(f"Last Update: {t} | Status: RUNNING", justify="right"))
                )

                time.sleep(1)


if __name__ == "__main__":
    try:
        app = DashboardApp()
        app.run()
    except KeyboardInterrupt:
        print("Dashboard stopped.")
