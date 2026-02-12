import sys
import os
import argparse
import time
from eth_abi import encode

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.types import Address  # noqa: E402
from pricing.simulation import ForkSimulator  # noqa: E402

ROUTER_ADDRESS = Address("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")
WETH_ADDRESS = Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
USDT_ADDRESS = Address("0xdAC17F958D2ee523a2206206994597C13D831ec7")
WHALE_ADDRESS = Address("0xF977814e90dA44bFA03b6295A0616a897441aceC")


def pump_eth(simulator, amount_usdt_mil):
    """Buying ETH for USDT -> Price ETH rising"""
    amount_in = int(amount_usdt_mil * 1_000_000 * 10**6)
    print(f"PUMPING ETH: Swapping {amount_usdt_mil}M USDT for ETH...")

    simulator._impersonate(WHALE_ADDRESS)
    simulator._set_balance_ether(WHALE_ADDRESS, 10.0)
    simulator._approve(USDT_ADDRESS, ROUTER_ADDRESS, WHALE_ADDRESS)

    path = [USDT_ADDRESS.checksum, WETH_ADDRESS.checksum]
    deadline = int(time.time()) + 300

    encoded_args = encode(
        ["uint256", "uint256", "address[]", "address", "uint256"],
        [amount_in, 0, path, WHALE_ADDRESS.checksum, deadline],
    )

    data = simulator.SWAP_EXACT_TOKENS_FOR_TOKENS + encoded_args

    res = simulator.simulate_swap(
        router=ROUTER_ADDRESS,
        swap_params={"data": data, "value": 0},
        sender=WHALE_ADDRESS,
    )

    if res.success:
        print("✅ Pump Successful! Transaction mined.")
    else:
        print(f"❌ Pump Failed: {res.error}")


def dump_eth(simulator, amount_eth):
    """Selling ETH for USDT -> Price ETH falling"""
    amount_in = int(amount_eth * 10**18)
    print(f"DUMPING ETH: Swapping {amount_eth} ETH for USDT...")

    simulator._impersonate(WHALE_ADDRESS)

    needed_eth = (amount_eth * 10) + 50
    simulator._set_balance_ether(WHALE_ADDRESS, float(needed_eth))

    simulator._wrap_eth(amount_in, WHALE_ADDRESS)

    simulator._approve(WETH_ADDRESS, ROUTER_ADDRESS, WHALE_ADDRESS)

    path = [WETH_ADDRESS.checksum, USDT_ADDRESS.checksum]
    deadline = int(time.time()) + 300

    encoded_args = encode(
        ["uint256", "uint256", "address[]", "address", "uint256"],
        [amount_in, 0, path, WHALE_ADDRESS.checksum, deadline],
    )

    data = simulator.SWAP_EXACT_TOKENS_FOR_TOKENS + encoded_args

    res = simulator.simulate_swap(
        router=ROUTER_ADDRESS,
        swap_params={"data": data, "value": 0},
        sender=WHALE_ADDRESS,
    )

    if res.success:
        print("✅ Dump Successful! Transaction mined.")
    else:
        print(f"❌ Dump Failed: {res.error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manipulate Fork Prices")
    parser.add_argument("action", choices=["pump", "dump"], help="Pump or Dump ETH")
    parser.add_argument("--amount", type=float, default=1000, help="Amount")
    parser.add_argument(
        "--rpc", type=str, default="http://127.0.0.1:8545", help="RPC URL"
    )

    args = parser.parse_args()
    sim = ForkSimulator(args.rpc)

    if args.action == "pump":
        pump_eth(sim, args.amount)
    elif args.action == "dump":
        dump_eth(sim, args.amount)
