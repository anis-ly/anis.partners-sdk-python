"""Shared response verification rules plus synchronous and asynchronous key lookup."""

import base64
import binascii
import hashlib
import hmac
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.clock import Clock, SystemClock
from anis_partners._internal.telemetry import safe_get_logger, safe_log
from anis_partners.signing.ecdsa_signature_format import p1363_to_der
from anis_partners.verification.errors import UnverifiableResponseError
from anis_partners.verification.failures import ResponseVerificationFailure as Failure
from anis_partners.verification.partner_jwk import PartnerJwk, SigningKeySet
from anis_partners.verification.partner_response_signature_base import (
    ALGORITHM,
    MAX_AGE_SECONDS,
    ResponseComponent,
    build,
    components,
)
from anis_partners.verification.signature_input_parser import ParsedSignatureInput, parse
from anis_partners.verification.signing_key_source import AsyncSigningKeySource, SigningKeySource
from anis_partners.verification.verifiable_response import VerifiableResponse

_LABEL: Final = "sig1"


def _header(response: VerifiableResponse, name: str) -> str | None:
    """Find an HTTP header without depending on mapping key casing."""
    lowered = name.lower()
    return next((value for key, value in response.headers.items() if key.lower() == lowered), None)


def _signature_bytes(value: str) -> bytes | None:
    """Read a strict RFC byte sequence rather than accepting alternate encodings."""
    if not value.startswith("sig1=:") or not value.endswith(":") or value.count(":") != 2:
        return None
    raw = value[6:-1]
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        return None
    return decoded if base64.b64encode(decoded).decode("ascii") == raw else None


def _resolve(keys: SigningKeySet, key_id: str) -> PartnerJwk | None:
    """Find the published version named by a response."""
    return next((key for key in keys.keys if key.kid == key_id and key.x and key.y), None)


@dataclass(frozen=True, slots=True)
class _PreKeyContext:
    parsed: ParsedSignatureInput
    parts: tuple[ResponseComponent, ...]
    signature: str


def _pre_key_phase(response: VerifiableResponse, now: datetime) -> tuple[_PreKeyContext | None, Failure | None]:
    """Check all response data that does not depend on the published key document."""
    content_encoding = _header(response, "Content-Encoding")
    if content_encoding and content_encoding.strip().casefold() != "identity":
        return None, Failure.CONTENT_DIGEST_MISMATCH
    signature_input = _header(response, "Signature-Input")
    signature = _header(response, "Signature")
    if not signature_input or not signature:
        return None, Failure.SIGNATURE_MISSING
    parsed: ParsedSignatureInput | None = parse(signature_input)
    if parsed is None:
        return None, Failure.SIGNATURE_MALFORMED
    if parsed.label != _LABEL or not signature.startswith(_LABEL + "="):
        return None, Failure.LABEL_UNEXPECTED
    if parsed.algorithm is not None and parsed.algorithm != ALGORITHM:
        return None, Failure.ALGORITHM_NOT_SUPPORTED
    digest = _header(response, "Content-Digest")
    if not digest:
        return None, Failure.CONTENT_DIGEST_MISMATCH
    computed = "sha-256=:" + base64.b64encode(hashlib.sha256(response.body).digest()).decode("ascii") + ":"
    if not hmac.compare_digest(computed.encode(), digest.encode()):
        return None, Failure.CONTENT_DIGEST_MISMATCH
    request_id = _header(response, "X-Request-Id")
    if not request_id:
        return None, Failure.COVERED_COMPONENTS_MISMATCH
    parts = components(
        response.status,
        digest,
        request_id,
        response.request_signature_input,
        _header(response, "Location"),
        _header(response, "Retry-After"),
        _header(response, "Idempotency-Replayed"),
        _header(response, "Cache-Control"),
    )
    expected = tuple(part.identifier.replace('"', "") for part in parts)
    if expected != parsed.identifiers:
        return None, Failure.COVERED_COMPONENTS_MISMATCH
    if any(identifier.endswith(";req") for identifier in parsed.identifiers) and not response.request_signature_input:
        return None, Failure.COVERED_COMPONENTS_MISMATCH
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The verification clock must return an aware UTC datetime.")
    age = math.floor(now.astimezone(UTC).timestamp()) - parsed.created
    if abs(age) > MAX_AGE_SECONDS:
        return None, Failure.CREATED_OUT_OF_WINDOW
    return _PreKeyContext(parsed, parts, signature), None


def _with_keys_phase(context: _PreKeyContext, keys: SigningKeySet, key: PartnerJwk | None) -> Failure | None:
    """Apply key-document, signature encoding, key import, and cryptographic checks."""
    if any(candidate.d for candidate in keys.keys):
        return Failure.KEY_REJECTED
    if key is None:
        return Failure.UNKNOWN_KEY
    raw_signature = _signature_bytes(context.signature)
    if raw_signature is None or len(raw_signature) != 64:
        return Failure.SIGNATURE_MALFORMED
    try:
        public_key = key.public_key()
    except ValueError:
        return Failure.KEY_REJECTED
    try:
        public_key.verify(
            p1363_to_der(raw_signature),
            build(context.parts, context.parsed.created, context.parsed.key_id),
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature:
        return Failure.SIGNATURE_INVALID
    except ValueError:
        return Failure.KEY_REJECTED
    return None


def verify_response(response: VerifiableResponse, keys: SigningKeySet, now: datetime) -> Failure | None:
    """Verify response rules against a key document without performing refresh I/O.

    The synchronous and asynchronous verifiers use these same pure phases so their
    refusal order remains identical when key rotation requires a refresh.
    """
    context, failure = _pre_key_phase(response, now)
    if failure is not None or context is None:
        return failure
    key = _resolve(keys, context.parsed.key_id)
    return _with_keys_phase(context, keys, key)


class PartnerResponseVerifier:
    """Verify signed responses so callers never consume data whose origin or integrity is uncertain."""

    def __init__(self, keys: SigningKeySource, clock: Clock | None = None) -> None:
        """Bind key retrieval and time so hosts can keep rotation and freshness checks reliable."""
        self._keys = keys
        self._clock = clock or SystemClock()
        self._logger = safe_get_logger("anis_partners")

    def verify(self, response: VerifiableResponse) -> None:
        """Reject invalid responses before their contents can be used by the host application."""
        context, failure = _pre_key_phase(response, self._clock.now())
        if failure is not None or context is None:
            raise UnverifiableResponseError(failure or Failure.SIGNATURE_MALFORMED)
        document = self._keys.get()
        key = _resolve(document, context.parsed.key_id)
        if key is None:
            safe_log(
                self._logger,
                logging.WARNING,
                "Unknown signing key %s; refreshing the key document once.",
                context.parsed.key_id,
                event_id=1006,
                key_id=context.parsed.key_id,
            )
            document = self._keys.refresh(document)
            key = _resolve(document, context.parsed.key_id)
        failure = _with_keys_phase(context, document, key)
        if failure is not None:
            raise UnverifiableResponseError(failure)


class AsyncPartnerResponseVerifier:
    """Verify signed responses asynchronously without weakening integrity or freshness checks."""

    def __init__(self, keys: AsyncSigningKeySource, clock: Clock | None = None) -> None:
        """Bind asynchronous key retrieval and time so hosts can preserve reliable rotation checks."""
        self._keys = keys
        self._clock = clock or SystemClock()
        self._logger = safe_get_logger("anis_partners")

    async def verify(self, response: VerifiableResponse) -> None:
        """Reject invalid responses before their contents can be used by the host application."""
        context, failure = _pre_key_phase(response, self._clock.now())
        if failure is not None or context is None:
            raise UnverifiableResponseError(failure or Failure.SIGNATURE_MALFORMED)
        document = await self._keys.get()
        key = _resolve(document, context.parsed.key_id)
        if key is None:
            safe_log(
                self._logger,
                logging.WARNING,
                "Unknown signing key %s; refreshing the key document once.",
                context.parsed.key_id,
                event_id=1006,
                key_id=context.parsed.key_id,
            )
            document = await self._keys.refresh(document)
            key = _resolve(document, context.parsed.key_id)
        failure = _with_keys_phase(context, document, key)
        if failure is not None:
            raise UnverifiableResponseError(failure)
