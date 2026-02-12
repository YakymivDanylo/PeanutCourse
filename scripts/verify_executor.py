import asyncio
import sys
import os
import time
from unittest.mock import MagicMock, patch

sys.path.append(os.getcwd())

from executor.engine import Executor, ExecutorConfig, ExecutorState  # noqa: E402
from strategy.signal import Signal, Direction  # noqa: E402


class MockQuote:
    def __init__(self):
        self.expected_output = 2000000000  # 2000 USDT (6 decimals)
        self.route = MagicMock()
        token_in = MagicMock()
        token_in.checksum = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"  # WETH
        token_out = MagicMock()
        token_out.checksum = "0xdAC17F958D2ee523a2206206994597C13D831ec7"  # USDT
        self.route.path = [token_in, token_out]


class MockReceipt:
    def __init__(self, status=1):
        self.status = status
        self.tx_hash = "0x" + "a" * 64


async def verify_executor():
    print("Starting Executor...")

    mock_exchange = MagicMock()
    mock_exchange.create_limit_ioc_order.return_value = {
        "status": "filled",
        "avg_fill_price": 2000.0,
        "amount_filled": 1.0,
        "error": None,
    }
    mock_exchange.create_market_order.return_value = {"status": "filled"}

    mock_pricing = MagicMock()
    mock_pricing.client.get_gas_price_gwei.return_value = 20
    mock_pricing.get_quote.return_value = MockQuote()

    mock_wallet = MagicMock()
    mock_wallet.address = "0x71C7656EC7ab88b098defB751B7401B5f6d8976F"

    mock_inventory = MagicMock()

    signal = Signal.create(
        pair="ETH/USDT",
        direction=Direction.BUY_CEX_SELL_DEX,
        cex_price=2000.0,
        dex_price=2020.0,
        spread_bps=100,
        size=1.0,
        expected_gross_pnl=20.0,
        expected_fees=5.0,
        expected_net_pnl=15.0,
        score=100.0,
        expiry=time.time() + 60,
        inventory_ok=True,
        within_limits=True,
    )

    signal.is_valid = MagicMock(return_value=True)

    config = ExecutorConfig(simulation_mode=False, use_flashbots=False)

    with patch("executor.engine.TransactionBuilder") as MockBuilderClass:
        mock_builder_instance = MockBuilderClass.return_value

        print("\n--- Test 1: Happy Path ---")
        mock_builder_instance.send_and_wait.return_value = MockReceipt(status=1)

        executor = Executor(
            mock_exchange, mock_pricing, mock_inventory, mock_wallet, config
        )
        ctx = await executor.execute(signal)

        if ctx.state == ExecutorState.DONE:
            print("✅ [OK] Status DONE")
        else:
            print(f"❌ [FAIL] Waiting for DONE, got {ctx.state}. Error: {ctx.error}")

        mock_exchange.create_limit_ioc_order.assert_called()
        print("✅ [OK] CEX order was sent")
        mock_builder_instance.send_and_wait.assert_called()
        print("✅ [OK] DEX tx was sent")

        print("\n--- Test 2: Unwind ---")

        mock_exchange.reset_mock()
        mock_builder_instance.reset_mock()

        executor_fresh = Executor(
            mock_exchange, mock_pricing, mock_inventory, mock_wallet, config
        )

        mock_builder_instance.send_and_wait.return_value = MockReceipt(status=0)

        ctx_fail = await executor_fresh.execute(signal)

        if ctx_fail.state == ExecutorState.FAILED and "unwound" in str(ctx_fail.error):
            print(f"✅ [OK] Status FAILED with correct error: {ctx_fail.error}")
        else:
            print(
                f"❌ [FAIL] Waiting for Unwind,"
                f" got {ctx_fail.state}. Error: {ctx_fail.error}"
            )

        if mock_exchange.create_market_order.called:
            print("✅ [OK] CEX Unwind (market order) сфддув")
        else:
            print("❌ [FAIL] CEX Unwind WASN`T called!")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(verify_executor())
