from decimal import Decimal

import pytest

from core.serializer import CanonicalSerializer
from core.types import Address, TokenAmount
from core.wallet import WalletManager


# core/types


def test_address_validation():
    """Test that invalid address raises ValueError"""
    with pytest.raises(ValueError):
        Address("0xInvalidAddress")
    with pytest.raises(ValueError):
        Address("NotAnAddress")


def test_address_checksum_conversion():
    """Test that checksum_address function works correctly"""
    addr_str = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
    addr = Address(addr_str)
    assert addr.value == "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


def test_address_equality():
    """Test that equality works correctly"""
    addr1 = Address("0xd8da6bf26964af9d7eed9e03e53415d37aa96045")
    addr2 = Address("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
    assert addr1 == addr2
    assert addr1 == "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


def test_token_amount_from_human():
    """Test creating TokenAmount from human-readable string"""
    amount = TokenAmount.from_human("1.5", 18)
    assert amount.raw == 1500000000000000000
    assert amount.decimals == 18


def test_token_amount_math_addition():
    """Test adding two TokenAmount"""
    tkn1 = TokenAmount.from_human("1.0", 18)
    tkn2 = TokenAmount.from_human("0.5", 18)
    result = tkn1 + tkn2
    assert result.human == Decimal("1.5")
    assert result.raw == 1500000000000000000


def test_token_amount_add_mismatch_decimals():
    """Test adding two TokenAmount with different decimals fails"""
    tkn1 = TokenAmount.from_human("1.0", 18)
    tkn2 = TokenAmount.from_human("0.5", 9)
    with pytest.raises(
        ValueError, match="Cannot add TokenAmount with different decimals"
    ):
        tkn1 + tkn2


def test_token_multiplication():
    """Test multiplication TokenAmount by a factor"""
    tkn = TokenAmount.from_human("10.0", 18)
    result = tkn * 2
    assert result.human == Decimal("20.0")
    result_float = tkn * 0.5
    assert result_float.human == Decimal("5.0")


# core/wallet


def test_wallet_security_repr():
    """Test that repr doesn`t show the private key"""
    wallet = WalletManager.generate()
    output = repr(wallet)

    assert wallet._account.key.hex() not in output
    assert "WalletManager" in output
    assert wallet.address in output


def test_wallet_signing_message():
    """Test sign a basic message"""
    wallet = WalletManager.generate()
    msg = "Hellow, World"
    signed = wallet.sign_message(msg)

    assert hasattr(signed, "signature")
    assert len(signed.signature) > 0


# core/serializer


def test_serializer_determinism():
    """Test that serialization is deterministic"""
    data = {"a": 1, "b": 2, "c": [3, 4, 5]}
    first = CanonicalSerializer.serialize(data)

    for _ in range(50):
        assert CanonicalSerializer.serialize(data) == first


def test_serializater_sorting():
    """Test that keys are sorted alphabetically"""
    data = {"z": 1, "a": 2}
    first = CanonicalSerializer.serialize(data)

    assert first == b'{"a":2,"z":1}'


def test_serializater_types():
    """Test serializer of different data types"""
    assert CanonicalSerializer.serialize(None) == b"null"
    assert CanonicalSerializer.serialize(True) == b"true"

    with pytest.raises(ValueError):
        CanonicalSerializer.serialize(1.5)
