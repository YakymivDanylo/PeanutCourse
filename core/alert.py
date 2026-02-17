import os
import logging
import requests

logger = logging.getLogger(__name__)


class TelegramAlert:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self.enabled = bool(self.token and self.chat_id)

        if not self.enabled:
            logger.warning("Telegram alerts DISABLED (missing token or chat_id)")

    def send(self, message: str):
        """Send a message to Telegram."""
        if not self.enabled:
            return

        try:
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}
            response = requests.post(self.base_url, json=payload, timeout=5)
            if response.status_code != 200:
                logger.error(f"Telegram send failed: {response.text}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    def send_trade(self, pair, side, size, pnl, venue_info=""):
        emoji = "🟢" if pnl >= 0 else "🔴"
        msg = (
            f"<b>Trade Executed</b>\n"
            f"Pair: {pair}\n"
            f"Side: {side}\n"
            f"Size: {size}\n"
            f"PnL: {emoji} ${pnl:.2f}\n"
            f"Info: {venue_info}"
        )
        self.send(msg)

    def send_error(self, error_msg):
        self.send(f"⚠️ <b>Error/Warning</b>\n{error_msg}")

    def send_critical(self, msg):
        self.send(f"☠️ <b>KILL SWITCH / CRITICAL</b>\n{msg}")

    def send_status(self, msg):
        self.send(f"ℹ️ <b>System Status</b>\n{msg}")
