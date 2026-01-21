import random
from dataclasses import dataclass
from datetime import time
from typing import Optional

from chain.exceptions import (
    InsufficientFunds,
    NonceTooLow,
    ReplacementUnderpriced,
    RPCError,
)
from core.types import Address, TokenAmount, TransactionReceipt, TransactionRequest
from web3 import Web3, HTTPProvider
from web3.middleware import ExtraDataToPOAMiddleware


@dataclass
class GasPrice:
    """Current gas price information."""

    base_fee: int
    priority_fee_low: int
    priority_fee_medium: int
    priority_fee_high: int

    def get_max_fee(self, priority: str = "medium", buffer: float = 1.2) -> int:
        """Calculate maxFeePerGas with buffer for base fee increase."""
        priority_fee = getattr(
            self, f"priority_fee_{priority}", self.priority_fee_medium
        )
        return int(self.base_fee * buffer) + priority_fee


class ChainClient:
    """
    Ethereum RPC client with reliability features.

    Features:
    - Automatic retry with exponential backoff
    - Multiple RPC endpoint fallback
    - Request timing/logging
    - Proper error classification
    """

    def __init__(self, rpc_urls: list[str], timeout: int = 30, max_retries: int = 3):
        self.rpc_urls = rpc_urls
        self.timeout = timeout
        self.max_retries = max_retries
        self._w3 = Optional[Web3] = None
        self._current_rpc_index = 0
        self._connect()

    def _connect(self):
        """Initialise Web3 with the current RPC URL"""
        url = self.rpc_urls[self._current_rpc_index]
        self._w3 = Web3(HTTPProvider(url, request_kwargs={"timeout": self.timeout}))
        self._w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    def _switch_provider(self):
        """Switches to the next available RPC URL."""
        self._current_rpc_index = (self._current_rpc_index + 1) % len(self.rpc_urls)
        print(f"Switching RPC provider to {self.rpc_urls[self._current_rpc_index]}")
        self._connect()

    def _retry(self, func, *args, **kwargs):
        """Method for retrying RPC calls."""
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_msg = str(e).lower()
                if "insufficient funds" in error_msg:
                    raise InsufficientFunds(str(e))
                if "nonce to low " in error_msg:
                    raise NonceTooLow(str(e))
                if "replacement transaction underprice" in error_msg:
                    raise ReplacementUnderpriced(str(e))
                if attempt == self.max_retries - 1:
                    raise RPCError(f"RPC call failed after {attempt} attempts: {e}")

                sleep_time = (2**attempt) + random.uniform(0, 1)
                time.sleep(sleep_time)

                if "connection" in error_msg or "timeout" in error_msg:
                    self._switch_provider()

    def get_balance(self, address: Address) -> TokenAmount:
        ...

    def get_nonce(self, address: Address, block: str = "pending") -> int:
        ...

    def get_gas_price(self) -> GasPrice:
        """Returns current gas price info (base fee, priority fee estimates)."""
        ...

    def estimate_gas(self, tx: TransactionRequest) -> int:
        ...

    def send_transaction(self, signed_tx: bytes) -> str:
        """Send and return tx hash. Does NOT wait for confirmation."""
        ...

    def wait_for_receipt(
        self, tx_hash: str, timeout: int = 120, poll_interval: float = 1.0
    ) -> TransactionReceipt:
        """Wait for transaction confirmation."""
        ...

    def get_transaction(self, tx_hash: str) -> dict:
        ...

    def get_receipt(self, tx_hash: str) -> Optional[TransactionReceipt]:
        ...

    def call(self, tx: TransactionRequest, block: str = "latest") -> bytes:
        """eth_call - simulate transaction without sending."""
        ...
