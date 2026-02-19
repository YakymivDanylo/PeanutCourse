import os
from unittest.mock import patch
from core.alert import TelegramAlert


@patch.dict(
    os.environ, {"TELEGRAM_BOT_TOKEN": "mock_token", "TELEGRAM_CHAT_ID": "123456789"}
)
@patch("core.alert.requests.post")
def test_telegram_alert_send(mock_post):
    mock_post.return_value.status_code = 200

    alert = TelegramAlert()
    assert alert.enabled is True

    alert.send("Test Alert")

    mock_post.assert_called_once()

    args, kwargs = mock_post.call_args
    assert "botmock_token/sendMessage" in args[0]
    assert kwargs["json"]["text"] == "Test Alert"
    assert kwargs["json"]["chat_id"] == "123456789"


@patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""})
@patch("core.alert.requests.post")
def test_telegram_alert_disabled(mock_post):
    alert = TelegramAlert()
    assert alert.enabled is False

    alert.send("Test Alert")
    mock_post.assert_not_called()


@patch.dict(
    os.environ, {"TELEGRAM_BOT_TOKEN": "mock_token", "TELEGRAM_CHAT_ID": "123456789"}
)
@patch("core.alert.requests.post")
def test_telegram_alert_daily_summary(mock_post):
    mock_post.return_value.status_code = 200

    alert = TelegramAlert()
    assert alert.enabled is True

    summary_data = {
        "trades": 0,
        "pnl": 0.0,
        "starting_capital": 100.0,
        "ending_capital": 100.0,
    }

    summary_message = (
        f"📊 *Daily Summary*\n"
        f"Trades Executed: {summary_data['trades']}\n"
        f"Total PnL: ${summary_data['pnl']:.2f}\n"
        f"Ending Capital: ${summary_data['ending_capital']:.2f}"
    )

    alert.send(summary_message)

    mock_post.assert_called_once()

    args, kwargs = mock_post.call_args
    assert "botmock_token/sendMessage" in args[0]
    assert kwargs["json"]["text"] == summary_message
    assert kwargs["json"]["chat_id"] == "123456789"
