import csv
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal


def generate_data(filename="trades.csv", num_trades=100):
    headers = [
        "id",
        "timestamp",
        "symbol",
        "buy_venue",
        "buy_price",
        "sell_venue",
        "sell_price",
        "amount",
        "gross_pnl",
        "gas_cost",
        "total_fees",
        "net_pnl",
        "net_pnl_bps",
    ]

    current_time = datetime.now(timezone.utc) - timedelta(days=7)

    trades = []

    print(f"Generating {num_trades} trades...")

    for i in range(1, num_trades + 1):
        current_time += timedelta(minutes=random.randint(10, 180))

        base_price = Decimal(random.uniform(1950, 2150)).quantize(Decimal("0.01"))

        spread_pct = Decimal(random.uniform(0.002, 0.015))

        is_profitable = random.random() > 0.2

        if is_profitable:
            price_diff = base_price * spread_pct
        else:
            price_diff = -base_price * (spread_pct / 2)

        buy_price = base_price
        sell_price = base_price + price_diff

        amount = Decimal("1.0")

        gross_pnl = (sell_price - buy_price) * amount

        gas_cost = Decimal(random.uniform(2.0, 8.0)).quantize(Decimal("0.01"))
        fees = (buy_price * amount * Decimal("0.001")) + (
            sell_price * amount * Decimal("0.001")
        )
        total_fees = fees + gas_cost

        net_pnl = gross_pnl - total_fees
        net_pnl_bps = (net_pnl / (buy_price * amount)) * 10000

        row = [
            i,
            current_time.isoformat(),
            "ETH/USDT",
            "binance",
            f"{buy_price:.2f}",
            "wallet",
            f"{sell_price:.2f}",
            f"{amount:.1f}",
            f"{gross_pnl:.2f}",
            f"{gas_cost:.2f}",
            f"{total_fees:.2f}",
            f"{net_pnl:.2f}",
            f"{net_pnl_bps:.2f}",
        ]
        trades.append(row)

    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(trades)

    print(f"Success! Saved to {filename}")


if __name__ == "__main__":
    generate_data()
