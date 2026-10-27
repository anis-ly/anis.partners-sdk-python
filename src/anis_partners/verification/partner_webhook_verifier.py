"""Shared notification verification rules plus synchronous and asynchronous key lookup."""

import base64
import binascii
import hashlib
import hmac
import json
import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners._internal.clock import Clock, SystemClock
from anis_partners._internal.telemetry import safe_get_logger, safe_log
from anis_partners.models._json import timestamp
from anis_partners.models.webhooks import WebhookEnvelope
from anis_partners.signing.ecdsa_signature_format import p1363_to_der
from anis_partners.verification.partner_jwk import PublishedSigningKey, SigningKeySet
from anis_partners.verification.partner_webhook_signature_base import (
    ALGORITHM,
    COMPONENTS,
    LABEL,
    LIFETIME_SECONDS,
    MAX_SKEW_SECONDS,
    TAG,
    build,
)
from anis_partners.verification.signing_key_source import AsyncSigningKeySource, SigningKeySource
from anis_partners.verification.verifiable_webhook import VerifiableWebhook
from anis_partners.verification.webhook_errors import UnverifiableWebhookError
from anis_partners.verification.webhook_failures import WebhookVerificationFailure as Failure
from anis_partners.verification.webhook_signature_input_parser import ParsedWebhookSignatureInput, parse

_SIGNATURE: Final = re.compile(r"([a-z][a-z0-9_*.-]*)=:([A-Za-z0-9+/]*={0,2}):")
_UUID: Final = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_MAX_ATTEMPT: Final = 2_147_483_647
_COVERED: Final = "(" + " ".join(f'"{name}"' for name in COMPONENTS) + ")"
_PURPOSE: Final = "webhook"


def _uuid(value: object) -> UUID | None:
    """Read only canonical UUID text so alternate spellings cannot slip past equality checks."""
    if isinstance(value, str) and _UUID.fullmatch(value):
        return UUID(value)
    return None


def _header_groups(headers: Mapping[str, str]) -> dict[str, list[str]]:
    """Group received values by lower-case name so case variants of one header are visible as duplicates."""
    groups: dict[str, list[str]] = {}
    for name, value in headers.items():
        groups.setdefault(name.lower(), []).append(value)
    return groups


@dataclass(frozen=True, slots=True)
class _PreKeyContext:
    parsed: ParsedWebhookSignatureInput
    signature: str
    webhook_id: str
    attempt: str
    application_id: str
    content_digest: str
    expires: int


def _pre_key_phase(
    webhook: VerifiableWebhook, configured_url: str, application: UUID, now: datetime
) -> tuple[_PreKeyContext | None, Failure | None]:
    """Check everything that does not depend on the published key document, in the corpus order."""
    groups = _header_groups(webhook.headers)
    inputs, signatures = groups.get("signature-input", []), groups.get("signature", [])
    if not inputs or not signatures:
        return None, Failure.SIGNATURE_MISSING
    if len(inputs) != 1 or len(signatures) != 1:
        return None, Failure.SIGNATURE_MALFORMED
    parsed = parse(inputs[0])
    signature_match = _SIGNATURE.fullmatch(signatures[0])
    if parsed is None or signature_match is None:
        return None, Failure.SIGNATURE_MALFORMED
    if parsed.label != LABEL or signature_match.group(1) != LABEL:
        return None, Failure.LABEL_UNEXPECTED
    if parsed.algorithm != ALGORITHM:
        return None, Failure.ALGORITHM_NOT_SUPPORTED
    if parsed.tag != TAG:
        return None, Failure.PROFILE_UNEXPECTED
    digests = groups.get("content-digest", [])
    computed = "sha-256=:" + base64.b64encode(hashlib.sha256(webhook.body).digest()).decode("ascii") + ":"
    if len(digests) != 1 or not hmac.compare_digest(computed.encode(), digests[0].encode()):
        return None, Failure.CONTENT_DIGEST_MISMATCH
    if parsed.covered != _COVERED or any(len(values) != 1 for values in groups.values()):
        return None, Failure.COVERED_COMPONENTS_MISMATCH
    webhook_id = groups.get("webhook-id", [""])[0]
    application_header = groups.get("anis-application-id", [""])[0]
    attempt = groups.get("anis-webhook-attempt", [""])[0]
    if (
        _uuid(webhook_id) is None
        or _uuid(application_header) is None
        or not re.fullmatch(r"[0-9]+", attempt)
        or len(attempt) > len(str(_MAX_ATTEMPT))
        or not 0 < int(attempt) <= _MAX_ATTEMPT
    ):
        return None, Failure.COVERED_COMPONENTS_MISMATCH
    if parsed.expires is None or len(parsed.expires) > 19 or not re.fullmatch(r"[0-9]+", parsed.expires):
        return None, Failure.VALIDITY_WINDOW_INVALID
    expires = int(parsed.expires)
    if expires - parsed.created != LIFETIME_SECONDS:
        return None, Failure.VALIDITY_WINDOW_INVALID
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The verification clock must return an aware UTC datetime.")
    instant = math.floor(now.astimezone(UTC).timestamp())
    if instant > expires:
        return None, Failure.SIGNATURE_EXPIRED
    if abs(instant - parsed.created) > MAX_SKEW_SECONDS:
        return None, Failure.CREATED_OUT_OF_WINDOW
    if webhook.method != "POST":
        return None, Failure.METHOD_UNEXPECTED
    if not webhook.target_uri.startswith("https://") or webhook.target_uri != configured_url:
        return None, Failure.TARGET_URI_MISMATCH
    if _uuid(application_header) != application:
        return None, Failure.APPLICATION_ID_MISMATCH
    return _PreKeyContext(
        parsed, signature_match.group(2), webhook_id, attempt, application_header, digests[0], expires
    ), None


def _resolve(keys: SigningKeySet, key_id: str) -> PublishedSigningKey | None:
    """Find the published version named by a notification, matching the opaque id exactly."""
    return next((key for key in keys.keys if key.kid == key_id), None)


def _instant(value: object) -> float | None:
    """Require an aware, parseable, finite lifecycle instant even for host-provided key sources."""
    try:
        parsed = timestamp(value)
        if parsed is None:
            return None
        seconds = parsed.timestamp()
        return seconds if math.isfinite(seconds) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _usable_metadata(key: PublishedSigningKey) -> bool:
    """Accept only a public P-256 key with a known status and a readable activation time."""
    if key.status not in {"active", "next", "retired"} or _instant(key.not_before) is None or key.d is not None:
        return False
    if key.status == "retired" and _instant(key.retired_at) is None:
        return False
    try:
        key.public_key()
    except ValueError:
        return False
    return True


def _with_keys_phase(context: _PreKeyContext, configured_url: str, keys: SigningKeySet) -> Failure | None:
    """Apply key-document, key lifecycle, purpose and cryptographic checks."""
    key_id = context.parsed.key_id
    selected = [key for key in keys.keys if key.kid == key_id]
    compromised = any(item.kid == key_id for item in keys.revoked)
    if not selected:
        return Failure.KEY_COMPROMISED if compromised else Failure.UNKNOWN_KEY
    kids = [key.kid for key in keys.keys]
    if len(selected) != 1 or len(set(kids)) != len(kids) or not all(_usable_metadata(key) for key in keys.keys):
        return Failure.KEY_REJECTED
    key = selected[0]
    if compromised:
        return Failure.KEY_COMPROMISED
    if key.status == "retired":
        return Failure.KEY_RETIRED
    not_before = _instant(key.not_before)
    # Signature creation uses whole seconds, so a fractional activation starts at the following second.
    if not_before is None or context.parsed.created < math.ceil(not_before):
        return Failure.KEY_NOT_YET_VALID
    if key.purpose != _PURPOSE:
        return Failure.KEY_PURPOSE_MISMATCH
    try:
        raw = base64.b64decode(context.signature, validate=True)
    except (ValueError, binascii.Error):
        return Failure.SIGNATURE_MALFORMED
    if len(raw) != 64:
        return Failure.SIGNATURE_MALFORMED
    base = build(
        configured_url,
        context.content_digest,
        context.webhook_id,
        context.attempt,
        context.application_id,
        context.parsed.created,
        context.expires,
        key_id,
    )
    try:
        key.public_key().verify(p1363_to_der(raw), base, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return Failure.SIGNATURE_INVALID
    except ValueError:
        return Failure.KEY_REJECTED
    return None


def verify_webhook(
    webhook: VerifiableWebhook,
    keys: SigningKeySet,
    now: datetime,
    *,
    configured_url: str,
    application_id: UUID | str,
) -> Failure | None:
    """Verify notification rules against a key document without performing refresh I/O."""
    application = _application(application_id)
    context, failure = _pre_key_phase(webhook, configured_url, application, now)
    if failure is not None or context is None:
        return failure
    return _with_keys_phase(context, configured_url, keys)


def _application(value: UUID | str) -> UUID:
    """Read the receiver's own application id once so a malformed configuration fails loudly at construction."""
    return value if isinstance(value, UUID) else UUID(value)


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Refuse duplicate members so two readers cannot disagree about which value the sender meant."""
    result: dict[str, object] = {}
    for name, item in pairs:
        if name in result:
            raise ValueError("Duplicate JSON member.")
        result[name] = item
    return result


def _invalid_constant(value: str) -> object:
    """Refuse non-JSON numeric constants that Python would otherwise accept."""
    raise ValueError(f"Non-JSON constant: {value}")


def parse_envelope(webhook: VerifiableWebhook, application: UUID) -> WebhookEnvelope:
    """Read a verified delivery, binding the signed body to the verified headers.

    Callers reach this only after cryptographic verification, so a refusal here
    describes a correctly signed but unusable or misdirected envelope.
    """
    groups = _header_groups(webhook.headers)
    header_id = _uuid(groups["webhook-id"][0])
    try:
        value = json.loads(
            webhook.body.decode("utf-8"), object_pairs_hook=_object_pairs, parse_constant=_invalid_constant
        )
        if (
            not isinstance(value, dict)
            or _uuid(value.get("id")) is None
            or _uuid(value.get("applicationId")) is None
            or not isinstance(value.get("type"), str)
            or not value["type"].strip()
            or not isinstance(value.get("data"), dict)
            or timestamp(value.get("occurredAt")) is None
        ):
            raise ValueError("Invalid envelope.")
    except (ValueError, TypeError, UnicodeDecodeError, OverflowError):
        raise UnverifiableWebhookError(Failure.ENVELOPE_INVALID) from None
    if _uuid(value["id"]) != header_id:
        raise UnverifiableWebhookError(Failure.EVENT_ID_MISMATCH)
    if _uuid(value["applicationId"]) != application:
        raise UnverifiableWebhookError(Failure.APPLICATION_ID_MISMATCH)
    try:
        return WebhookEnvelope.from_json(value)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise UnverifiableWebhookError(Failure.ENVELOPE_INVALID) from None


class PartnerWebhookVerifier:
    """Verify notifications so receivers never act on content whose origin or integrity is uncertain."""

    def __init__(
        self, keys: SigningKeySource, *, configured_url: str, application_id: UUID | str, clock: Clock | None = None
    ) -> None:
        """Bind key retrieval, the receiver's own URL and application, and time.

        The expected URL and application come only from this configuration, never from request headers.
        """
        self._keys = keys
        self._url = configured_url
        self._application = _application(application_id)
        self._clock = clock or SystemClock()
        self._logger = safe_get_logger("anis_partners")

    def verify(self, webhook: VerifiableWebhook) -> None:
        """Reject an unverifiable delivery before its contents can be used."""
        context, failure = _pre_key_phase(webhook, self._url, self._application, self._clock.now())
        if failure is not None or context is None:
            raise UnverifiableWebhookError(failure or Failure.SIGNATURE_MALFORMED)
        document = self._keys.get()
        known = {item.kid for item in document.keys} | {item.kid for item in document.revoked}
        if context.parsed.key_id not in known:
            safe_log(
                self._logger,
                logging.WARNING,
                "Unknown webhook signing key %s; requesting a key-document refresh (at most once per 30 seconds).",
                context.parsed.key_id,
                event_id=1006,
                key_id=context.parsed.key_id,
            )
            document = self._keys.refresh(document)
        failure = _with_keys_phase(context, self._url, document)
        if failure is not None:
            raise UnverifiableWebhookError(failure)

    def verify_and_parse(self, webhook: VerifiableWebhook) -> WebhookEnvelope:
        """Verify first and return the typed envelope; no content is read from an unverified delivery."""
        self.verify(webhook)
        return parse_envelope(webhook, self._application)


class AsyncPartnerWebhookVerifier:
    """Verify notifications asynchronously without weakening integrity or freshness checks."""

    def __init__(
        self,
        keys: AsyncSigningKeySource,
        *,
        configured_url: str,
        application_id: UUID | str,
        clock: Clock | None = None,
    ) -> None:
        """Bind asynchronous key retrieval, the receiver's own URL and application, and time."""
        self._keys = keys
        self._url = configured_url
        self._application = _application(application_id)
        self._clock = clock or SystemClock()
        self._logger = safe_get_logger("anis_partners")

    async def verify(self, webhook: VerifiableWebhook) -> None:
        """Reject an unverifiable delivery before its contents can be used."""
        context, failure = _pre_key_phase(webhook, self._url, self._application, self._clock.now())
        if failure is not None or context is None:
            raise UnverifiableWebhookError(failure or Failure.SIGNATURE_MALFORMED)
        document = await self._keys.get()
        known = {item.kid for item in document.keys} | {item.kid for item in document.revoked}
        if context.parsed.key_id not in known:
            safe_log(
                self._logger,
                logging.WARNING,
                "Unknown webhook signing key %s; requesting a key-document refresh (at most once per 30 seconds).",
                context.parsed.key_id,
                event_id=1006,
                key_id=context.parsed.key_id,
            )
            document = await self._keys.refresh(document)
        failure = _with_keys_phase(context, self._url, document)
        if failure is not None:
            raise UnverifiableWebhookError(failure)

    async def verify_and_parse(self, webhook: VerifiableWebhook) -> WebhookEnvelope:
        """Verify first and return the typed envelope; no content is read from an unverified delivery."""
        await self.verify(webhook)
        return parse_envelope(webhook, self._application)
