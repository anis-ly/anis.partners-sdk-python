"""Conversions between cryptography's DER signatures and the wire's P1363 form."""

from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature


def der_to_p1363(signature: bytes) -> bytes:
    """Convert cryptography's DER signature because Anis accepts only fixed-width 64-byte P1363."""
    try:
        r, s = decode_dss_signature(signature)
        if r < 0 or s < 0 or r.bit_length() > 256 or s.bit_length() > 256:
            raise ValueError("ECDSA values must each fit in 32 bytes.")
        return r.to_bytes(32, "big") + s.to_bytes(32, "big")
    except (ValueError, TypeError) as exc:
        raise ValueError("Malformed P-256 DER signature.") from exc


def p1363_to_der(signature: bytes) -> bytes:
    """Convert P1363 to DER because cryptography's ECDSA verifier does not consume the wire encoding."""
    if len(signature) != 64:
        raise ValueError("A P-256 P1363 signature must be exactly 64 bytes.")
    return encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
