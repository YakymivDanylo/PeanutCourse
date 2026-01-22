from typing import Optional

from eth_account.datastructures import SignedTransaction

from chain.client import ChainClient
from core.types import Address, TokenAmount, TransactionRequest, TransactionReceipt
from core.wallet import WalletManager


class TransactionBuilder:
    """
    Fluent builder for transactions.

    Usage:
        tx = (TransactionBuilder(client, wallet)
            .to(recipient)
            .value(TokenAmount.from_human("0.1", 18))
            .data(calldata)
            .with_gas_estimate()
            .with_gas_price("high")
            .build())
    """

    def __init__(self, client: ChainClient, wallet: WalletManager):
        self.client = client
        self.wallet = wallet
        self._to: Optional[Address] = None
        self._value: TokenAmount = TokenAmount(0, 18)
        self._data: bytes = b""
        self._nonce: Optional[int] = None
        self._gas_limit: Optional[int] = None
        self._max_fee_per_gas: Optional[int] = None
        self._max_priority_fee: Optional[int] = None
        self._chain_id: int = 11155111

    def to(self, address: Address) -> "TransactionBuilder":
        self._to = address
        return self

    def value(self, amount: TokenAmount) -> "TransactionBuilder":
        self._value = amount
        return self

    def data(self, calldata: bytes) -> "TransactionBuilder":
        self._data = calldata
        return self

    def nonce(self, nonce: int) -> "TransactionBuilder":
        """Explicit nonce (for replacement or batch)."""
        self._nonce = nonce
        return self

    def gas_limit(self, limit: int) -> "TransactionBuilder":
        self._gas_limit = limit
        return self

    def with_gas_estimate(self, buffer: float = 1.2) -> "TransactionBuilder":
        """Estimate gas and set limit with buffer."""
        temp_req = self._build_request()
        estimated = self.client.estimate_gas(temp_req)
        self._gas_limit = int(estimated * buffer)
        return self

    def with_gas_price(self, priority: str = "medium") -> "TransactionBuilder":
        """Set gas price based on current network conditions."""
        gas_price = self.client.get_gas_price()
        self._max_priority_fee = getattr(gas_price, f"priority_fee_{priority}")
        self._max_fee_per_gas = gas_price.get_max_fee(priority)
        return self

    def _build_request(self) -> TransactionRequest:
        if not self._to:
            raise ValueError("Recipient address is required.")

        return TransactionRequest(
            to=self._to,
            value=self._value,
            data=self._data,
            nonce=self._nonce,
            gas_limit=self._gas_limit,
            max_fee_per_gas=self._max_fee_per_gas,
            max_priority_fee=self._max_priority_fee,
            chain_id=self._chain_id,
        )

    def build(self) -> TransactionRequest:
        """Validate and return transaction request."""
        if self._nonce is None:
            self._nonce = self.client.get_nonce(Address(self.wallet.address))

        req = self._build_request()

        if self._gas_limit is None:
            raise ValueError("Gas limit isn`t set")
        if self._max_fee_per_gas is None:
            raise ValueError("Gas price isn`t set")

        return req

    def build_and_sign(self) -> SignedTransaction:
        """Build, sign, and return ready-to-send transaction."""
        req = self.build()
        tx_dict = req.to_dict()
        return self.wallet.sign_transaction(tx_dict)

    def send(self) -> str:
        """Build, sign, send, return tx hash."""
        signed_tx = self.build_and_sign()
        raw_tx = (
            signed_tx.rawTransaction
            if hasattr(signed_tx, "rawTransaction")
            else signed_tx[0]
        )
        return self.client.send_transaction(raw_tx)

    def send_and_wait(self, timeout: int = 120) -> TransactionReceipt:
        """Build, sign, send, wait for confirmation."""
        tx_hash = self.send()
        return self.client.wait_for_receipt(tx_hash, timeout)
