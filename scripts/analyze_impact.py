import sys
import os
import argparse
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import Address  # noqa: E402
from pricing.amm import UniswapV2Pair, PriceImpactAnalyzer  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Price Impact Analysis Tool")
    parser.add_argument(
        "--token-in", type=str, default="USDC", help="Symbol of input token"
    )
    parser.add_argument(
        "--sizes",
        type=str,
        default="1000,10000,100000,1000000",
        help="Comma separated list of amounts",
    )
    args = parser.parse_args()

    print("Fetching pool data... (Using Mock for Demo)")

    # Example: ETH/USDC Pool
    # Reserve: 1000 ETH / 2,000,000 USDC
    # Price: ~2000 USDC/ETH

    token_eth = Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
    token_usdc = Address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")

    pair = UniswapV2Pair(
        address=Address("0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc"),
        token0=token_eth,
        token1=token_usdc,
        reserve0=1000 * 10**18,
        reserve1=2_000_000 * 10**6,
        symbol="ETH-USDC",
    )

    analyzer = PriceImpactAnalyzer(pair)

    if args.token_in.upper() == "USDC":
        token_in_addr = token_usdc
        token_out_symbol = "ETH"
        decimals_in = 6
        decimals_out = 18
    else:
        token_in_addr = token_eth
        token_out_symbol = "USDC"
        decimals_in = 18
        decimals_out = 6

    sizes_human = [float(x.strip()) for x in args.sizes.split(",")]
    sizes_raw = [int(x * (10**decimals_in)) for x in sizes_human]

    print(f"\nPrice Impact Analysis for {args.token_in} -> {token_out_symbol}")
    print(f"Pool: {pair.address.value}")
    spot = pair.get_spot_price(token_in_addr)

    adj_factor = Decimal(10**decimals_in) / Decimal(10**decimals_out)
    real_spot = spot * adj_factor

    print(f"Reserves: {pair.reserve0} (raw) / {pair.reserve1} (raw)")
    print(f"Spot Price: {real_spot:.2f} {token_out_symbol}/{args.token_in}")

    results = analyzer.generate_impact_table(token_in_addr, sizes_raw)

    print("\n" + "─" * 65)
    print(
        f"{args.token_in.center(12)} | {token_out_symbol.center(12)} "
        f"| {'Exec Price'.center(12)} | {'Impact'.center(10)}"
    )
    print("─" * 65)

    for res, input_human in zip(results, sizes_human):
        if "error" in res:
            print(
                f"{str(input_human).center(12)} | {'ERROR'.center(12)} | {res['error']}"
            )
            continue

        amount_out_human = Decimal(res["amount_out"]) / Decimal(10**decimals_out)

        # Exec price human readable
        exec_price_fmt = res["execution_price"] * adj_factor

        impact_pct = res["price_impact_pct"]

        print(
            f"{f'{input_human:,.0f}'.center(12)} | "
            f"{f'{amount_out_human:,.4f}'.center(12)} | "
            f"{f'{exec_price_fmt:,.6f}'.center(12)} | "
            f"{f'{impact_pct:.2f}%'.center(10)}"
        )
    print("─" * 65)

    # Max trade for 1% impact
    print("\nCalculating max trade for 1% impact...")
    max_size_raw = analyzer.find_max_size_for_impact(token_in_addr, Decimal("1.0"))
    max_size_human = Decimal(max_size_raw) / Decimal(10**decimals_in)
    print(f"Max trade for 1% impact: {max_size_human:,.2f} {args.token_in}")


if __name__ == "__main__":
    main()
