from dataclasses import dataclass
from typing import Optional
from core.types import Address, TokenAmount, TransactionReceipt, TransactionRequest


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
        ...

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
