"""Closed response refusal reasons shared with the gateway conformance corpus."""

from enum import StrEnum


class ResponseVerificationFailure(StrEnum):
    """Give partners stable refusal reasons so untrusted response content is never mistaken for an API result."""

    #: One or both required signature headers were absent.
    SIGNATURE_MISSING = "signature_missing"
    #: A header could not be parsed or did not contain a 64-byte P1363 value.
    SIGNATURE_MALFORMED = "signature_malformed"
    #: The response signature failed against the rebuilt component base.
    SIGNATURE_INVALID = "signature_invalid"
    #: The advertised digest did not describe the body received.
    CONTENT_DIGEST_MISMATCH = "content_digest_mismatch"
    #: Advertised components differed from the gateway's frozen response profile.
    COVERED_COMPONENTS_MISMATCH = "covered_components_mismatch"
    #: The published document did not contain the response's key version.
    UNKNOWN_KEY = "unknown_key"
    #: The key document exposed private material or an invalid P-256 point.
    KEY_REJECTED = "key_rejected"
    #: The response named an algorithm this SDK does not support.
    ALGORITHM_NOT_SUPPORTED = "algorithm_not_supported"
    #: The required signature label was not sig1 on both headers.
    LABEL_UNEXPECTED = "label_unexpected"
    #: The signed creation time fell outside the client's freshness window.
    CREATED_OUT_OF_WINDOW = "created_out_of_window"
