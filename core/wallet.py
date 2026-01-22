import os
import json
from eth_account import Account
from eth_account.datastructures import SignedMessage, SignedTransaction
from eth_account.messages import encode_defunct, encode_typed_data
from eth_account.signers.local import LocalAccount

Account.enable_unaudited_hdwallet_features()


class WalletManager:
    """Manages wallet operations: key loading, signing, verification."""

    def __init__(self, private_key: str):
        self._account: LocalAccount = Account.from_key(private_key)
        """
        Local account has an
        access to private key and can
        execute sign_message sign_transaction without network
        """

    @classmethod
    def from_env(cls, env_var: str = "PRIVATE_KEY") -> "WalletManager":
        key = os.getenv(env_var)
        if not key:
            raise ValueError(f"Environment variable {env_var} not set")
        return cls(key)

    @classmethod
    def generate(cls) -> "WalletManager":
        account = Account.create()
        print(f"SAVE THIS PRIVATE KEY: {account.key.hex()} !!!")
        return cls(account.key.hex())

    @classmethod
    def from_keyfile(cls, path: str, password: str) -> "WalletManager":
        """Load from encrypted keyfile."""
        try:
            with open(path, "r") as f:
                encrypted_key = json.load(f)

            private_key = Account.decrypt(encrypted_key, password)
            return cls(private_key.hex())
        except FileNotFoundError:
            raise ValueError(f"Keyfile not found at {path}")
        except ValueError as e:
            raise ValueError("Invalid password or corrupted keyfile") from e

    def to_keyfile(self, path: str, password: str) -> None:
        """Export to encrypted keyfile."""
        encrypted_key = Account.encrypt(self._account.key, password)

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        with open(path, "w") as f:
            json.dump(encrypted_key, f)

    @property
    def address(self) -> str:
        return self._account.address

    def sign_message(self, message: str) -> SignedMessage:
        if not message:
            raise ValueError("Message cannot be empty")
        signable_msg = encode_defunct(text=message)
        return self._account.sign_message(signable_msg)

    def sign_typed_data(
        self, domain: dict, types: dict, value: dict
    ) -> SignedMessage:  # noqa: E501
        if not domain or not types or not value:
            raise ValueError("Domain and types cannot be empty")

        signable_msg = encode_typed_data(
            domain_data=domain, message_types=types, message_data=value
        )
        return self._account.sign_message(signable_msg)

    def sign_transaction(self, tx: dict) -> SignedTransaction:
        return self._account.sign_transaction(tx)

    def __repr__(self) -> str:
        return f"WalletManager({self.address}"

    def __str__(self) -> str:
        return self.__repr__()
