"""Strict ECDSA DER and P1363 conversion behavior."""

import pytest
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from anis_partners.signing.ecdsa_signature_format import der_to_p1363, p1363_to_der


def test_der_signature_with_31_byte_r_is_left_padded() -> None:
    """A short r value still occupies exactly 32 wire bytes."""
    der = encode_dss_signature(1, (1 << 248) + 7)
    encoded = der_to_p1363(der)
    assert len(encoded) == 64
    assert encoded[:32] == b"\0" * 31 + b"\x01"


def test_der_signature_with_zero_prefixed_s_is_normalized() -> None:
    """A DER sign-protection zero is removed before the fixed-width wire form."""
    value = (1 << 255) + 3
    der = encode_dss_signature(5, value)
    encoded = der_to_p1363(der)
    assert encoded[32:] == value.to_bytes(32, "big")


def test_two_hundred_valid_signatures_round_trip() -> None:
    """Two hundred scalar pairs survive both encoding conversions."""
    for index in range(1, 201):
        der = encode_dss_signature(index, index * 7)
        assert p1363_to_der(der_to_p1363(der)) == der


@pytest.mark.parametrize("signature", [b"", b"\x30\x00", b"\x30\x06\x02\x01\x01"])
def test_malformed_der_is_refused(signature: bytes) -> None:
    """Malformed DER cannot be treated as a gateway signature."""
    with pytest.raises(ValueError, match="Malformed"):
        der_to_p1363(signature)


@pytest.mark.parametrize("signature", [b"", b"x" * 63, b"x" * 65])
def test_non_64_byte_p1363_is_refused(signature: bytes) -> None:
    """Only exact-width P1363 values can be converted for verification."""
    with pytest.raises(ValueError, match="exactly 64"):
        p1363_to_der(signature)
