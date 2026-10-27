"""Closed webhook refusal reasons shared with the webhook conformance corpus."""

from enum import StrEnum


class WebhookVerificationFailure(StrEnum):
    """Give receivers stable refusal reasons so an unverified notification is never mistaken for an Anis event."""

    #: One or both required signature headers were absent.
    SIGNATURE_MISSING = "signature_missing"
    #: A signature header could not be parsed, was ambiguous, or did not hold a 64-byte P1363 value.
    SIGNATURE_MALFORMED = "signature_malformed"
    #: The signature failed against the rebuilt component base.
    SIGNATURE_INVALID = "signature_invalid"
    #: The advertised digest was absent or did not describe the raw body received.
    CONTENT_DIGEST_MISMATCH = "content_digest_mismatch"
    #: Covered components or required binding headers differed from the webhook profile.
    COVERED_COMPONENTS_MISMATCH = "covered_components_mismatch"
    #: The published document did not contain the signature's key version.
    UNKNOWN_KEY = "unknown_key"
    #: The key document exposed private material, or the matched key was unusable.
    KEY_REJECTED = "key_rejected"
    #: The signature named an algorithm this SDK does not support.
    ALGORITHM_NOT_SUPPORTED = "algorithm_not_supported"
    #: The required signature label was not sig1 on both headers.
    LABEL_UNEXPECTED = "label_unexpected"
    #: The signed creation time was more than 300 seconds from the receiver's clock.
    CREATED_OUT_OF_WINDOW = "created_out_of_window"
    #: The signature did not use the anis-partner-webhook-v1 profile tag.
    PROFILE_UNEXPECTED = "profile_unexpected"
    #: The key version is compromised, whenever the signature was created.
    KEY_COMPROMISED = "key_compromised"
    #: The key version no longer signs notifications, even before its retirement time.
    KEY_RETIRED = "key_retired"
    #: The signature was created before the key version activated.
    KEY_NOT_YET_VALID = "key_not_yet_valid"
    #: The signature expiry had passed.
    SIGNATURE_EXPIRED = "signature_expired"
    #: The signature lifetime was absent or was not exactly 300 seconds.
    VALIDITY_WINDOW_INVALID = "validity_window_invalid"
    #: The signed target is not the receiver's configured URL.
    TARGET_URI_MISMATCH = "target_uri_mismatch"
    #: The application is not the receiver's configured application.
    APPLICATION_ID_MISMATCH = "application_id_mismatch"
    #: The matched key was not published for webhook signing.
    KEY_PURPOSE_MISMATCH = "key_purpose_mismatch"
    #: The request method was not POST.
    METHOD_UNEXPECTED = "method_unexpected"
    #: The signed envelope id differs from the webhook-id header.
    EVENT_ID_MISMATCH = "event_id_mismatch"
    #: The body is not a valid notification envelope.
    ENVELOPE_INVALID = "envelope_invalid"
