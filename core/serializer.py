import json
from typing import Any
from eth_utils import keccak


class CanonicalSerializer:
    """
    Produces deterministic JSON for signing.

    Rules:
    - Keys sorted alphabetically (recursive)
    - No whitespace
    - Numbers as-is (but prefer string amounts in trading data)
    - Consistent unicode handling
    """

    @staticmethod
    def _validate_no_floats(obj: Any):
        """Recursively check for float types."""
        if isinstance(obj, float):
            raise ValueError(
                "Floating point aren`t allowed in canonical serialization."
            )

        if isinstance(obj, dict):
            for k, v in obj.items():
                CanonicalSerializer._validate_no_floats(k)
                CanonicalSerializer._validate_no_floats(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                CanonicalSerializer._validate_no_floats(v)

    @staticmethod
    def _default_encoder(obj):
        """For bytes serializing"""
        if isinstance(obj, bytes):
            return obj.hex()
        if isinstance(obj, float):
            raise ValueError(
                "Floating point aren`t allowed in canonical serialization."
            )
        raise TypeError(
            f"Object of type " f"{type(obj).__name__} is not JSON serializable"
        )

    @staticmethod
    def serialize(obj: Any) -> bytes:
        """Returns canonical bytes representation."""
        CanonicalSerializer._validate_no_floats(obj)
        return json.dumps(
            obj,
            sort_keys=True,
            separators=(",", ":"),
            default=CanonicalSerializer._default_encoder,
        ).encode("utf-8")

    @staticmethod
    def hash(obj: Any) -> bytes:
        """Returns keccak256 of canonical serialization."""
        return keccak(CanonicalSerializer.serialize(obj))

    @staticmethod
    def verify_determinism(obj: Any, iterations: int = 100) -> bool:
        """Verifies serialization is deterministic over N iterations."""
        first = CanonicalSerializer.serialize(obj)

        for _ in range(iterations):
            if CanonicalSerializer.serialize(obj) != first:
                return False
        return True
