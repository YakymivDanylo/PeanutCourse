from dataclasses import dataclass
from typing import Optional
from decimal import Decimal
from eth_utils import is_address, to_checksum_address
from config import Config


@dataclass(frozen=True)
class Address:
    """Ethereum address with validation and checksumming."""

    value: str

    def __post_init__(self):
        # Validate and convert to checksum
        if not is_address(self.value):
            raise ValueError(f"Invalid address format: " f"{self.value}")
        object.__setattr__(self, "value", to_checksum_address(self.value))

    @classmethod
    def from_string(cls, s: str) -> "Address":
        return cls(s)

    @property
    def checksum(self) -> str:
        return self.value

    @property
    def lower(self) -> str:
        return self.value.lower()

    def __eq__(self, other) -> bool:
        # Case-insensitive comparison
        if isinstance(other, Address):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == to_checksum_address(other)


@dataclass(frozen=True)
class TokenAmount:
    """
    Represents a token amount with proper decimal handling.

    Internally stores raw integer (wei-equivalent).
    Provides human-readable formatting.
    """

    raw: int  # Raw amount (e.g., wei)
    decimals: int  # Token decimals (e.g., 18 for ETH, 6 for USDC)
    symbol: Optional[str] = None

    @classmethod
    def from_human(
        cls, amount: str | Decimal, decimals: int, symbol: str = None
    ) -> "TokenAmount":
        """Create from human-readable amount (e.g., '1.5' ETH)."""
        dec_amount = Decimal(str(amount))
        raw_amount = int(dec_amount * (Decimal(10) ** decimals))
        return cls(raw=raw_amount, decimals=decimals, symbol=symbol)

    @property
    def human(self) -> Decimal:
        """Returns human-readable decimal."""
        return Decimal(self.raw) / (Decimal(10) ** self.decimals)

    def __add__(self, other: "TokenAmount") -> "TokenAmount":
        # Must validate same decimals
        if self.decimals != other.decimals:
            raise ValueError("Cannot add TokenAmount with different decimals")
        return TokenAmount(
            self.raw + other.raw, self.decimals, self.symbol or other.symbol
        )

    def __mul__(self, factor: int | Decimal) -> "TokenAmount":
        factor = Decimal(str(factor))
        new_raw = int(Decimal(self.raw) * factor)
        return TokenAmount(new_raw, self.decimals, self.symbol)

    def __str__(self) -> str:
        return f"{self.human} {self.symbol or ''}"


@dataclass
class TransactionRequest:
    """A transaction ready to be signed."""

    to: Address
    value: TokenAmount
    data: bytes
    nonce: Optional[int] = None
    gas_limit: Optional[int] = None
    max_fee_per_gas: Optional[int] = None
    max_priority_fee: Optional[int] = None
    chain_id: int = Config.CHAIN_ID
    type: int = 2  # EIP-1559

    def to_dict(self) -> dict:
        """Convert to web3-compatible dict."""
        tx = {
            "to": self.to.value,
            "value": self.value.raw,
            "data": self.data,
            "chainId": self.chain_id,
            "type": self.type,
        }

        if self.nonce is not None:
            tx["nonce"] = self.nonce
        if self.gas_limit is not None:
            tx["gas"] = self.gas_limit
        if self.max_fee_per_gas is not None:
            tx["maxFeePerGas"] = self.max_fee_per_gas
        if self.max_priority_fee is not None:
            tx["maxPriorityFeePerGas"] = self.max_priority_fee
        return tx


@dataclass
class TransactionReceipt:
    """Parsed transaction receipt."""

    tx_hash: str
    block_number: int
    status: bool  # True = success
    gas_used: int
    effective_gas_price: int
    logs: list

    @property
    def tx_fee(self) -> TokenAmount:
        """Returns transaction fee as TokenAmount."""
        fee_raw = self.gas_used * self.effective_gas_price
        return TokenAmount(fee_raw, 18, "ETH")

    @classmethod
    def from_web3(cls, receipt: dict) -> "TransactionReceipt":
        """Parse from web3 receipt dict."""
        return cls(
            tx_hash=receipt["transactionHash"].hex(),
            block_number=receipt["blockNumber"],
            status=bool(receipt["status"]),
            gas_used=receipt["gasUsed"],
            effective_gas_price=receipt["effectiveGasPrice"],
            logs=receipt["logs"],
        )
