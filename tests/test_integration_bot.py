import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from scripts.arb_bot import ArbBot
from strategy.signal import Signal, Direction
from executor.engine import ExecutorState
import time


@pytest.mark.asyncio
async def test_arb_bot_single_tick_integration():
    """
    Integration test for ArbBot._tick().
    We test Exchange, Chain and Generator to verify the signal passes to the Executor.
    """

    mock_config = {
        "binance_key": "test",
        "binance_secret": "test",
        "rpc_url": "http://mock",
        "pairs": ["ETH/USDT"],
        "trade_size": 0.1,
        "simulation": True,
        "paper_trading": True,
        "signal_config": {"min_spread_bps": 10},
    }

    with patch("scripts.arb_bot.ExchangeClient"), patch(
        "scripts.arb_bot.ChainClient"
    ), patch("scripts.arb_bot.PricingEngine"):
        bot = ArbBot(mock_config)

        valid_signal = Signal.create(
            pair="ETH/USDT",
            direction=Direction.BUY_CEX_SELL_DEX,
            cex_price=2000.0,
            dex_price=2050.0,
            spread_bps=250.0,
            size=0.1,
            expected_gross_pnl=5.0,
            expected_fees=1.0,
            expected_net_pnl=4.0,
            score=80,
            expiry=time.time() + 10,
            inventory_ok=True,
            within_limits=True,
        )
        bot.generator.generate = MagicMock(return_value=valid_signal)

        bot.scorer.score = MagicMock(return_value=80)

        mock_ctx = MagicMock()
        mock_ctx.state = ExecutorState.DONE
        mock_ctx.actual_net_pnl = 3.8

        mock_ctx.signal = valid_signal
        mock_ctx.leg1_venue = "cex"
        mock_ctx.leg1_fill_price = 2000.0
        mock_ctx.leg1_fill_size = 0.1
        mock_ctx.leg2_venue = "dex"
        mock_ctx.leg2_fill_price = 2050.0
        mock_ctx.leg2_fill_size = 0.1

        bot.executor.execute = AsyncMock(return_value=mock_ctx)

        await bot._tick()

        bot.generator.generate.assert_called_with("ETH/USDT", 0.1)

        bot.executor.execute.assert_awaited_once()
        args, _ = bot.executor.execute.call_args
        assert args[0].pair == "ETH/USDT"
