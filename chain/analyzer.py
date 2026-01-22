import argparse
import sys
from datetime import datetime, timezone
from web3 import Web3
from core.types import TokenAmount

KNOWN_SELECTORS = {
    #   ERC-20
    "0xa9059cbb": "transfer(address,uint256)",
    "0x095ea7b3": "approve(address,uint256)",
    "0x23b872dd": "transferFrom(address,address,uint256)",
    #   Uniswap V2
    "0x38ed1739": "swapExactTokensForTokens",
    "0x7ff36ab5": "swapExactETHForTokens",
    "0x18cbafe5": "swapExactTokensForETH",
    "0xf305d719": "addLiquidityETH",
    #   Uniswap V3
    "0x5ae401dc": "multicall",
    "0x414bf389": "exactInputSingle",
    "0xb858183f": "exactInput",
}

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def analyze_transaction(tx_hash: str, rpc_url: str):
    w3 = Web3(Web3.HTTPProvider(rpc_url))

    if not w3.is_connected():
        print("Error: Could not connect to RPC")
        sys.exit(1)

    try:
        tx = w3.eth.get_transaction(tx_hash)
        reciept = w3.eth.get_transaction_receipt(tx_hash)
        block = w3.eth.get_block(reciept["blockNumber"])
    except Exception as e:
        print(f"Error fetching transaction: {e}")
        return

    #    Base Info
    status = "SUCCESS" if reciept["status"] == 1 else "FAILED"
    block_time = datetime.fromtimestamp(block["timestamp"], tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    print("Transaction Analysis")
    print("====================")
    print(f"Hash:           {tx_hash}")
    print(f"Block:          {reciept['blockNumber']}")
    print(f"Timestamp:      {block_time}")
    print(f"Status:         {status}")
    print("")
    print(f"From:           {tx['from']}")
    print(f"To:             {tx['to']}")
    val = TokenAmount(tx["value"], 18, "ETH")
    print(f"Value:           {val.human}")
    print("")

    #   Gas Analysis
    print("Gas Analysis")
    print("------------")
    print(f"Gas Limit:          {tx['gas']}")
    print(f"Gas Used:{reciept['gasUsed']} ({reciept['gasUsed']/tx['gas']*100:.2f}%)")

    effective_price = reciept["effectiveGasPrice"]
    fee_eth = TokenAmount(reciept["gasUsed"] * effective_price, 18, "ETH")

    print(f"Effective Price: {effective_price / 10**9:.2f} gwei")
    print(f"Transaction Fee: {fee_eth.human} ETH")
    print("")

    #   Function Decode
    print("Function Called")
    print("---------------")
    input_data = tx["input"].hex()

    if not input_data.startswith("0x"):
        input_data = "0x" + input_data

    if len(input_data) < 10:
        print("Function: Native ETH Transfer")
    else:
        selector = input_data[:10]
        func_name = KNOWN_SELECTORS.get(selector, "Unknown Function")
        print(f"Selector:       {selector}")
        print(f"Function:       {func_name}")
    print("")

    print("Token Transfers")
    print("---------------")

    transfers = []

    for log in reciept["logs"]:
        if len(log["topics"]) == 3 and log["topics"][0] == TRANSFER_TOPIC:
            try:
                from_addr = Web3.to_checksum_address(
                    "0x" + log["topics"][1].hex()[-40:]
                )
                to_addr = Web3.to_checksum_address("0x" + log["topics"][2].hex()[-40:])
                token_addr = log["address"]

                raw_amount = int(log["data"], 16)

                amount_fmt = raw_amount / 10**18

                transfers.append(
                    {
                        "token": token_addr,
                        "from": from_addr,
                        "to": to_addr,
                        "amount": amount_fmt,
                        "raw": raw_amount,
                    }
                )
                print(
                    f"Token ({token_addr[:10]}...): {from_addr[:10]} ... -> "
                    f"{to_addr[:10]} | {amount_fmt:.4f}"
                )
            except Exception:
                continue
    if not transfers:
        print("No ERC-20 transfers found")

    print("")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze an Ethereum transaction")
    parser.add_argument("tx_hash", help="Transaction Hash")
    parser.add_argument(
        "--rpc", default="https://eth.llamarpc.com", help="RPC Endpoint URL"
    )

    args = parser.parse_args()
    analyze_transaction(args.tx_hash, args.rpc)
