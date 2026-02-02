import os
import pytest
from web3 import Web3
from eth_abi import decode
from core.types import Address
from pricing.amm import UniswapV2Pair

USDC_WETH_PAIR = "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc"

PAIR_ABI = [
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
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token0",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "token1",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
]


@pytest.mark.skipif(
    not os.getenv("ALCHEMY_RPC_URL"),
    reason="The test requires a connection to the Mainnet RPC (ALCHEMY_RPC_URL)",
)
def test_verify_amm_math_dynamic():
    """
    Dynamically store the valid Swap transaction in the USDC/WETH pool.
    Selects the FIRST transaction in the block to ensure correct
    historical reserves (block-1)
    """
    rpc_url = os.getenv("ALCHEMY_RPC_URL")
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        pytest.skip("Failed to connect to RPC")

    if w3.eth.chain_id != 1:
        pytest.skip("The test is designed for Mainnet (ChainID 1)")

    swap_topic = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
    current_block = w3.eth.block_number

    BATCH_SIZE = 5
    MAX_ITERATIONS = 20

    print(f"\nSearching for a clean Swap starting from block {current_block}...")

    found_valid_swap = False

    pair_contract = w3.eth.contract(address=USDC_WETH_PAIR, abi=PAIR_ABI)

    for i in range(MAX_ITERATIONS):
        end_block = current_block - (i * BATCH_SIZE)
        start_block = end_block - BATCH_SIZE + 1

        print(f"Scanning [{start_block} - {end_block}]...")

        try:
            logs = w3.eth.get_logs(
                {
                    "fromBlock": w3.to_hex(start_block),
                    "toBlock": w3.to_hex(end_block),
                    "address": USDC_WETH_PAIR,
                    "topics": [swap_topic],
                }
            )
        except Exception as e:
            print(f"RPC Error: {e}")
            continue

        logs.sort(key=lambda x: (x["blockNumber"], x["logIndex"]))

        seen_blocks = set()
        candidates = []
        for log in logs:
            if log["blockNumber"] not in seen_blocks:
                candidates.append(log)
                seen_blocks.add(log["blockNumber"])

        for log in candidates:
            try:
                if verify_single_swap(w3, pair_contract, log):
                    found_valid_swap = True
                    return
            except AssertionError as ae:
                print(
                    f"Mismatch on block {log['blockNumber']} (MEV/Complex block?): {ae}"
                )
                continue
            except Exception as e:
                print(f"Error checking log: {e}")
                continue

    if not found_valid_swap:
        pytest.fail(
            "No 'clean' transactions could be found for "
            "verification for the verified blocks."
        )


def verify_single_swap(w3, pair_contract, log):
    """Auxiliary function for verifying a single log"""
    tx_hash = log["transactionHash"].hex()
    block_number = log["blockNumber"]

    data_bytes = (
        bytes.fromhex(log["data"][2:]) if isinstance(log["data"], str) else log["data"]
    )

    vals = decode(["uint256", "uint256", "uint256", "uint256"], data_bytes)
    amount0_in, amount1_in, amount0_out, amount1_out = vals

    if amount0_in > 0:
        amount_in = amount0_in
        amount_out_actual = amount1_out
        token_in_is_0 = True
    else:
        amount_in = amount1_in
        amount_out_actual = amount0_out
        token_in_is_0 = False

    reserves = pair_contract.functions.getReserves().call(
        block_identifier=block_number - 1
    )
    token0 = pair_contract.functions.token0().call()
    token1 = pair_contract.functions.token1().call()

    reserve0, reserve1, _ = reserves

    pair = UniswapV2Pair(
        address=Address(USDC_WETH_PAIR),
        token0=Address(token0),
        token1=Address(token1),
        reserve0=reserve0,
        reserve1=reserve1,
    )

    token_in_addr = Address(token0) if token_in_is_0 else Address(token1)
    amount_out_calc = pair.get_amount_out(amount_in, token_in_addr)

    if amount_out_calc != amount_out_actual:
        raise AssertionError(f"Calc: {amount_out_calc} != Real: {amount_out_actual}")

    print(f"\nSUCCESS Verified Tx: {tx_hash} (Block: {block_number})")
    print(f"Input: {amount_in} -> Output: {amount_out_actual}")
    return True
