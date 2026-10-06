"""Shared partner identity and signing fixtures for in-memory HTTP tests."""

from decimal import Decimal
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners import CreateOrderRequest, Money
from anis_partners.signing.ecdsa_signature_format import der_to_p1363

WALLET = UUID("2f1c8a94-6d37-4e52-b8a1-0c9e5d3f7b26")
OPERATION = UUID("9b2e4f17-3c6a-4d58-b0e1-7a5c8d2f6b34")
CARD = UUID("8d4b1e73-9a25-4c60-8f37-6b2e9d5a1c48")
CARD_SOLD = UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046")


class TestSigner:
    """Supply the same P-256 identity to signed-wire tests without importing another test module."""

    key_id = "9e96dc41-c715-4cc4-b1aa-836fe42ad0bb"

    def __init__(self) -> None:
        self._key = ec.generate_private_key(ec.SECP256R1())

    def sign(self, data: bytes) -> bytes:
        """Produce the fixed-width signature encoding accepted by the request contract."""
        return der_to_p1363(self._key.sign(data, ec.ECDSA(hashes.SHA256())))


SIGNER = TestSigner()


def order(unit: str = "10.500", total: str = "21.000", quantity: int = 2) -> CreateOrderRequest:
    """Construct one exact purchase intent for transport conformance tests."""
    return CreateOrderRequest(CARD, quantity, Money(Decimal(unit), "LYD"), Money(Decimal(total), "LYD"))
