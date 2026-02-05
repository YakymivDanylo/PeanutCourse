import sys
import os
import matplotlib.pyplot as plt
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    csv_file = "trade.csv"

    if len(sys.argv) > 1:
        csv_file = sys.argv[1]

    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found. Run bot or pnl_engine to generate data.")
        return

    try:
        df = pd.read_csv(csv_file)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")

        df["cumulative_pnl"] = df["net_pnl"].cumsum()

        plt.figure(figsize=(10, 6))
        plt.plot(
            df["timestamp"],
            df["cumulative_pnl"],
            label="Cumulative Net PnL (USD)",
            color="green",
            linewidth=2,
        )

        plt.title("Historical PnL Performance", fontsize=16)
        plt.xlabel("Time", fontsize=12)
        plt.ylabel("Net PnL (USD)", fontsize=12)
        plt.grid(True, linestyle="--", alpha=0.7)
        plt.legend()
        plt.xticks(rotation=45)

        output_file = "pnl_chart.png"
        plt.tight_layout()
        plt.savefig(output_file)
        print(f"Chart saved to {output_file}")

    except Exception as e:
        print(f"Failed to plot PnL: {e}")


if __name__ == "__main__":
    main()
