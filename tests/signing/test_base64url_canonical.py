"""Canonical base64url decoding prevents alternate strings from naming identical signed bytes."""

from anis_partners._internal.base64url import decode


def test_base64url_accepts_canonical_zero_byte_encoding() -> None:
    """Accept the canonical spelling of one zero byte."""
    assert decode("AA") == b"\x00"


def test_base64url_refuses_nonzero_unused_padding_bits() -> None:
    """Refuse alternate padding bits even when a permissive decoder yields the same byte."""
    assert decode("AB") is None
