import sys
from datetime import datetime

from web3 import Web3

from core.types import TokenAmount

KNOWN_SELECTORS = {
    "0xa9059cbb": "transfer(address,uint256)",
    "0x095ea7b3": "approve(address,uint256)",
    "0x23b872dd": "transferFrom(address,address,uint256)",
}


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
    block_time = datetime.datetime.fromtimestamp(block["timestamp"]).strftime(
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
