import time
import logging
from dataclasses import dataclass
from typing import Optional
from strategy.signal import Signal
import requests
from core.alert import TelegramAlert


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 3
    window_seconds: float = 300
    cooldown_seconds: float = 600
    webhook_url: Optional[str] = None


class CircuitBreaker:
    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self.failures: list[float] = []
        self.tripped_at: Optional[float] = None

        self.telegram_alert = TelegramAlert()

    def record_failure(self, error_reason: str = "Unknown error"):
        now = time.time()
        self.failures.append(now)
        cutoff = now - self.config.window_seconds
        self.failures = [t for t in self.failures if t > cutoff]

        if len(self.failures) >= self.config.failure_threshold:
            self.trip(error_reason)

    def record_success(self):
        pass

    def trip(self, error_msg: str = "No details provided"):
        self.tripped_at = time.time()
        discord_ts = int(self.tripped_at)
        discord_time_str = f"<t:{discord_ts}:F>"

        tg_message = (
            f"<b>Circuit Breaker Tripped</b>\n"
            f"Reason: <code>{error_msg}</code>\n"
            f"Failures in window: {len(self.failures)}"
        )
        self.telegram_alert.send_critical(tg_message)

        if self.config.webhook_url:
            try:
                payload = {
                    "content": (
                        f"**ARBITRAGE BOT ALERT**\n"
                        f"**Status:**Circuit Breaker Tripped\n"
                        f"**Reason:** `{error_msg}`\n"
                        f"**Time:** {discord_time_str}\n"
                        f"**Failures in window:** `{len(self.failures)}`"
                    )
                }
                requests.post(self.config.webhook_url, json=payload, timeout=5)
            except Exception as e:
                logging.error(f"Failed to send webhook alert: {e}")

    def is_open(self) -> bool:
        if self.tripped_at is None:
            return False
        if time.time() - self.tripped_at > self.config.cooldown_seconds:
            self.tripped_at = None
            self.failures = []
            logging.info("Circuit breaker reset")
            return False
        return True

    def time_until_reset(self) -> float:
        if self.tripped_at is None:
            return 0.0
        return max(0.0, self.config.cooldown_seconds - (time.time() - self.tripped_at))


class ReplayProtection:
    def __init__(self, ttl_seconds: float = 60):
        self.executed: dict[str, float] = {}
        self.ttl = ttl_seconds

    def is_duplicate(self, signal: Signal) -> bool:
        self._cleanup()
        return signal.signal_id in self.executed

    def mark_executed(self, signal: Signal):
        self.executed[signal.signal_id] = time.time()

    def _cleanup(self):
        cutoff = time.time() - self.ttl
        self.executed = {k: v for k, v in self.executed.items() if v > cutoff}
