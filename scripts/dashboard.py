import sys
import os
import time
from decimal import Decimal
from datetime import datetime
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rich.live import Live  # noqa: E402
from rich.layout import Layout  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

from integration.arb_checker import ArbChecker  # noqa: E402
from inventory.tracker import InventoryTracker, Venue  # noqa: E402
from exchange.client import ExchangeClient  # noqa: E402
from chain.client import ChainClient  # noqa: E402
from configs.binance_config import BINANCE_CONFIG  # noqa: E402

RPC_URLS = [
    "https://eth.drpc.org",
    "https://rpc.ankr.com/eth",
    "https://cloudflare-eth.com",
    "https://1rpc.io/eth",
    "https://eth.llamarpc.com",
]


def make_layout() -> Layout:
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
        Layout(name="prices", ratio=1),
        Layout(name="inventory", ratio=2),
    )
    layout["right"].split_column(
        Layout(name="gaps", ratio=2),
        Layout(name="recent_trades", ratio=3),
    )
    return layout


def generate_inventory_table(tracker: InventoryTracker) -> Table:
    table = Table(expand=True, border_style="dim")
    table.add_column("Venue", style="cyan")
    table.add_column("Asset", style="magenta")
    table.add_column("Free", justify="right")
    table.add_column("Locked", justify="right")

    snapshot = tracker.snapshot()
    for venue, assets in snapshot["venues"].items():
        for asset, data in assets.items():
            if data["total"] > 0:
                table.add_row(
                    venue.capitalize(),
                    asset,
                    f"{data['free']:,.4f}",
                    f"{data['locked']:,.4f}",
                )
    return table


def generate_gap_table(result: dict) -> Table:
    table = Table(expand=True, border_style="dim")
    table.add_column("Metric", style="white")
    table.add_column("Value", justify="right", style="bold")

    if not result:
        return table

    gap_color = "green" if result.get("gap_usd", 0) > 0 else "red"
    pnl_color = "green" if result.get("estimated_net_pnl_bps", 0) > 0 else "red"

    table.add_row("Gap (USD)", f"[{gap_color}]${result.get('gap_usd', 0):.2f}[/]")
    table.add_row("Gap (bps)", f"[{gap_color}]{result.get('gap_bps', 0):.2f} bps[/]")
    table.add_row(
        "Est. Net PnL",
        f"[{pnl_color}]{result.get('estimated_net_pnl_bps', 0):.2f} bps[/]",
    )
    table.add_row(
        "Gas Cost", f"${result.get('details', {}).get('gas_cost_usd', 0):.2f}"
    )

    direction = result.get("direction", "N/A")
    formatted_dir = direction.replace("_", " ").title() if direction else "N/A"
    table.add_row("Direction", formatted_dir)

    return table


class Dashboard:
    def __init__(self):
        load_dotenv()

        self.tracker = InventoryTracker()

        try:
            self.exchange = ExchangeClient(BINANCE_CONFIG)
            self.exchange.exchange.fetch_time()
        except Exception:
            self.exchange = None

        self.chain = None
        for rpc in RPC_URLS:
            try:
                c = ChainClient([rpc])
                c._w3.eth.block_number
                self.chain = c
                break
            except Exception:
                continue

        if self.exchange and self.chain:
            self.checker = ArbChecker(self.exchange, self.chain, self.tracker)
        else:
            print("Failed to initialize clients (Binance or Chain)")
            sys.exit(1)

        self.tracker.update_from_wallet(
            Venue.WALLET,
            {
                "ETH": Decimal("10.0"),
                "USDT": Decimal("20000.0"),
                "USDC": Decimal("20000.0"),
            },
        )

        self.last_check_result = {}

    def update_market_data(self):
        try:
            binance_balances = self.exchange.exchange.fetch_balance()
            cex_update = {}
            for asset in ["ETH", "USDT", "USDC"]:
                if asset in binance_balances:
                    cex_update[asset] = {
                        "free": Decimal(str(binance_balances[asset]["free"])),
                        "locked": Decimal(str(binance_balances[asset]["used"])),
                        "total": Decimal(str(binance_balances[asset]["total"])),
                    }
            self.tracker.update_from_cex(Venue.BINANCE, cex_update)
        except Exception:
            pass

    def run(self):
        layout = make_layout()
        layout["header"].update(
            Panel(
                Text(
                    " TRADE BOT DASHBOARD ",
                    justify="center",
                    style="bold white on blue",
                )
            )
        )

        with Live(layout, refresh_per_second=1, screen=True):
            while True:
                self.update_market_data()

                try:
                    self.last_check_result = self.checker.check("ETH/USDT", 2.0)
                except Exception:
                    self.last_check_result = {}

                layout["inventory"].update(
                    Panel(generate_inventory_table(self.tracker), title="Inventory")
                )
                layout["gaps"].update(
                    Panel(
                        generate_gap_table(self.last_check_result),
                        title="Arb Opportunity",
                    )
                )

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

                time.sleep(5)


if __name__ == "__main__":
    app = Dashboard()
    app.run()
