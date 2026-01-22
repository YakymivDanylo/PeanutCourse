import os
import sys
from dotenv import load_dotenv
from chain.client import ChainClient
from chain.builder import TransactionBuilder
from core.wallet import WalletManager
from core.types import Address, TokenAmount

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_integration_test():
    load_dotenv()

    # 1. Setup
    print("--- Starting Integration Test (Sepolia) ---")
    rpc_url = os.getenv("SEPOLIA_RPC_URL", "https://rpc.sepolia.org")
    private_key = os.getenv("PRIVATE_KEY")

    if not private_key:
        print("Error: PRIVATE_KEY not found in .env")
        return

    wallet = WalletManager(private_key)
    client = ChainClient([rpc_url])

    print(f"Wallet: {wallet.address}")

    # 2. Check Balance
    balance = client.get_balance(Address(wallet.address))
    print(f"Balance: {balance.human} ETH")

    if balance.human < 0.001:
        print("Error: Insufficient balance for test. Get ETH from Sepolia faucet.")
        return

    # 3. Build Transaction (Self-transfer for test)
    recipient = Address(wallet.address)
    amount = TokenAmount.from_human("0.0001", 18)

    print("\nBuilding transaction...")
    builder = TransactionBuilder(client, wallet)
    tx_req = (
        builder.to(recipient)
        .value(amount)
        .with_gas_price("medium")
        .with_gas_estimate()
        .build()
    )

    print(f"  To: {tx_req.to.value}")
    print(f"  Value: {tx_req.value.human} ETH")
    print(f"  Gas Limit: {tx_req.gas_limit}")
    print(f"  Max Fee: {tx_req.max_fee_per_gas / 10 ** 9:.2f} gwei")

    # 4. Sign and Send
    print("\nSigning and Sending...")
    try:
        signed_tx = builder.build_and_sign()

        try:
            raw_tx = signed_tx.rawTransaction
        except AttributeError:
            raw_tx = signed_tx[0]

        from eth_account import Account

        recovered_address = Account.recover_transaction(raw_tx)

        print(f"  Signer: {wallet.address}")
        print(f"  Recovered: {recovered_address}")

        if recovered_address.lower() == wallet.address.lower():
            print("  Signature valid: ✓")
        else:
            print("  ERROR: Signature verification failed!")
            return

        print("\nSending...")
        tx_hash = client.send_transaction(raw_tx)
        print(f"  TX Hash: {tx_hash}")
    except Exception as e:
        print(f"Error sending transaction: {e}")
        import traceback

        traceback.print_exc()
        return

    # 5. Wait for Receipt
    print("\nWaiting for confirmation...")
    try:
        receipt = client.wait_for_receipt(tx_hash)
        print(f"  Block: {receipt.block_number}")
        print(f"  Status: {'SUCCESS' if receipt.status else 'FAILED'}")
        print(f"  Gas Used: {receipt.gas_used}")
        print(f"  Fee: {receipt.tx_fee.human} ETH")

        if receipt.status:
            print("\nIntegration test PASSED")
        else:
            print("\nIntegration test FAILED (Transaction reverted)")

    except Exception as e:
        print(f"Error waiting for receipt: {e}")


if __name__ == "__main__":
    run_integration_test()
