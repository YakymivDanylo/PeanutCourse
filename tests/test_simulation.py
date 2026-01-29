import pytest
from web3 import Web3

from core.types import Address
from pricing.amm import UniswapV2Pair
from pricing.simulation import ForkSimulator
from pricing.routing import Route

WETH = Address("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
USDC = Address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
ETH_USDC_POOL = Address("0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc")
WHALE_ADDRESS = Address("0x28C6c06298d514Db089934071355E5743bf21d60")


@pytest.fixture
def simulator():
    fork_url = "http://127.0.0.1:8545"
    try:
        sim = ForkSimulator(fork_url)
        if not sim.w3.is_connected():
            return None
        return sim
    except Exception:
        return None


def test_fork_connection(simulator):
    if not simulator:
        pytest.skip("No fork")
    assert simulator.w3.is_connected()
    assert simulator.w3.eth.block_number > 10_000_000


def test_impersonate_and_set_balance(simulator):
    if not simulator:
        pytest.skip("No fork")

    vitalik = Address("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
    simulator._set_balance_ether(vitalik, 100.0)

    # Check balance
    balance_wei = simulator.w3.eth.get_balance(vitalik.checksum)
    assert balance_wei == int(100.0 * 10**18)

    # Send Tx
    random_addr = Address("0x0000000000000000000000000000000000000001")
    simulator._impersonate(vitalik)

    # FIX: Add gasPrice to avoid PrecompileOOG on Anvil
    tx_hash = simulator.w3.eth.send_transaction(
        {
            "from": vitalik.checksum,
            "to": random_addr.checksum,
            "value": Web3.to_wei(1, "ether"),
            "gas": 30000,
            "gasPrice": simulator.w3.eth.gas_price + 1000000000,
        }
    )

    receipt = simulator.w3.eth.wait_for_transaction_receipt(tx_hash)
    simulator._stop_impersonating(vitalik)
    assert receipt.status == 1


def test_simulate_route_execution(simulator):
    if not simulator:
        pytest.skip("No fork")

    # Check Whale Balance
    weth_contract = simulator.w3.eth.contract(
        address=WETH.checksum,
        abi=[
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ],
    )
    weth_bal = weth_contract.functions.balanceOf(WHALE_ADDRESS.checksum).call()
    if weth_bal < 1 * 10**18:
        pytest.skip("Whale has no WETH")

    # Setup
    pair = UniswapV2Pair(ETH_USDC_POOL, WETH, USDC, 0, 0)
    route = Route([pair], [WETH, USDC])
    amount_in = 1 * 10**18

    # Approve
    simulator._impersonate(WHALE_ADDRESS)
    weth_contract = simulator.w3.eth.contract(
        address=WETH.checksum,
        abi=[
            {
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"},
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function",
            }
        ],
    )
    weth_contract.functions.approve(
        simulator.ROUTER_ADDRESS.checksum, 2**256 - 1
    ).transact({"from": WHALE_ADDRESS.checksum})

    # Simulate
    result = simulator.simulate_route(route, amount_in, WHALE_ADDRESS)
    simulator._stop_impersonating(WHALE_ADDRESS)

    assert result.success is True
    assert result.amount_out > 1000 * 10**6
    print(f"Simulated Output: {result.amount_out / 10 ** 6} USDC")


def test_compare_simulation_vs_calculation(simulator):
    if not simulator:
        pytest.skip("No fork")

    # 1. Fetch Real Reserves
    pair_contract = simulator.w3.eth.contract(
        address=ETH_USDC_POOL.checksum,
        abi=[
            {
                "constant": True,
                "inputs": [],
                "name": "getReserves",
                "outputs": [
                    {"name": "_reserve0", "type": "uint112"},
                    {"name": "_reserve1", "type": "uint112"},
                    {"name": "_blockTimestampLast", "type": "uint32"},
                ],
                "type": "function",
            }
        ],
    )
    r0, r1, _ = pair_contract.functions.getReserves().call()
    t0_addr = (
        simulator.w3.eth.contract(
            address=ETH_USDC_POOL.checksum,
            abi=[
                {"name": "token0", "outputs": [{"type": "address"}], "type": "function"}
            ],
        )
        .functions.token0()
        .call()
    )

    if t0_addr == USDC.checksum:
        pair = UniswapV2Pair(ETH_USDC_POOL, USDC, WETH, r0, r1)
    else:
        pair = UniswapV2Pair(ETH_USDC_POOL, WETH, USDC, r0, r1)

    # 2. Approve from Whale
    simulator._impersonate(WHALE_ADDRESS)
    weth_contract = simulator.w3.eth.contract(
        address=WETH.checksum,
        abi=[
            {
                "constant": False,
                "inputs": [
                    {"name": "_spender", "type": "address"},
                    {"name": "_value", "type": "uint256"},
                ],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function",
            }
        ],
    )
    weth_contract.functions.approve(
        simulator.ROUTER_ADDRESS.checksum, 2**256 - 1
    ).transact({"from": WHALE_ADDRESS.checksum})

    # 3. Compare using WHALE as sender
    comparison = simulator.compare_simulation_vs_calculation(
        pair, 1 * 10**18, WETH, sender_override=WHALE_ADDRESS  # Використовуємо кита
    )
    simulator._stop_impersonating(WHALE_ADDRESS)

    print(f"Calculated: {comparison['calculated']}")
    print(f"Simulated:  {comparison['simulated']}")

    assert (
        comparison["match"]
        or comparison["difference"] / comparison["calculated"] < 0.005
    )
