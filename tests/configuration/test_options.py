"""Settings binding tests that fail before client creation or order submission."""

from typing import cast

import pytest

from anis_partners.options import AcceptLanguage, ClientOptions


def test_options_bind_from_the_anis_partners_section() -> None:
    """Bind conventional settings once so an invalid deployment fails at startup."""
    options = ClientOptions.from_mapping(
        {
            "AnisPartners": {
                "Authority": "https://partners.example",
                "SignatureLifetime": "00:00:45",
                "AcceptLanguage": "English",
                "SigningKeyCacheDuration": "00:05:00",
                "Timeout": "00:00:45",
            }
        }
    )
    assert options.authority == "https://partners.example"
    assert options.signature_lifetime_seconds == 45
    assert options.accept_language is AcceptLanguage.ENGLISH
    assert options.signing_key_cache_seconds == 300
    assert options.timeout_seconds == 45


def test_options_bind_snake_case_without_a_section_wrapper() -> None:
    """Support native Python settings without requiring a cross-runtime configuration container."""
    options = ClientOptions.from_mapping(
        {
            "authority": "http://localhost:8080",
            "signature_lifetime_seconds": 12,
            "accept_language": "ar",
            "signing_key_cache_seconds": 25,
            "timeout_seconds": 4.5,
        }
    )
    assert options.authority == "http://localhost:8080"
    assert options.accept_language is AcceptLanguage.ARABIC
    assert options.timeout_seconds == 4.5


def test_options_bind_camel_case_from_a_shared_settings_section() -> None:
    """Accept shared camelCase settings while keeping Python's snake_case form available."""
    options = ClientOptions.from_mapping(
        {
            "AnisPartners": {
                "authority": "https://partners.example",
                "signatureLifetime": 15,
                "acceptLanguage": "en",
                "signingKeyCacheDuration": 300,
                "timeout": 12,
            }
        }
    )
    assert options.signature_lifetime_seconds == 15
    assert options.accept_language is AcceptLanguage.ENGLISH
    assert options.signing_key_cache_seconds == 300
    assert options.timeout_seconds == 12


@pytest.mark.parametrize(
    ("authority", "lifetime", "message"),
    [
        ("", 60, r"ClientOptions\.authority"),
        ("partners.example", 60, r"ClientOptions\.authority"),
        ("ftp://partners.example", 60, r"ClientOptions\.authority"),
        ("https://partners.example", 61, r"ClientOptions\.signature_lifetime_seconds"),
        ("https://partners.example", 0, r"ClientOptions\.signature_lifetime_seconds"),
    ],
)
def test_invalid_authority_or_lifetime_is_rejected_at_construction(authority: str, lifetime: int, message: str) -> None:
    """Prevent unusable settings from surviving until the first paid request."""
    with pytest.raises(ValueError, match=message):
        ClientOptions(authority, signature_lifetime_seconds=lifetime)


def test_nonpositive_timeouts_and_cache_lifetimes_are_refused() -> None:
    """Avoid immediate timeouts and unbounded stale signing-key documents."""
    with pytest.raises(ValueError, match=r"ClientOptions.timeout_seconds must be positive"):
        ClientOptions("https://partners.example", timeout_seconds=0)
    with pytest.raises(ValueError, match=r"ClientOptions.signing_key_cache_seconds must be positive"):
        ClientOptions("https://partners.example", signing_key_cache_seconds=0)


def test_invalid_mapping_duration_names_the_python_attribute() -> None:
    """Identify the Python setting that must be corrected when a mapping value cannot be parsed."""
    with pytest.raises(ValueError, match=r"ClientOptions.timeout_seconds"):
        ClientOptions.from_mapping({"authority": "https://partners.example", "timeout_seconds": "soon"})


@pytest.mark.parametrize("value", [True, 30.0])
def test_signature_lifetime_requires_an_actual_integer(value: object) -> None:
    """Reject bool and fractional settings before they can create malformed signature parameters."""
    with pytest.raises(ValueError, match=r"ClientOptions\.signature_lifetime_seconds"):
        ClientOptions("https://partners.example", signature_lifetime_seconds=cast(int, value))


@pytest.mark.parametrize("value", [True, 600.0])
def test_cache_lifetime_requires_an_actual_integer(value: object) -> None:
    """Keep host-cache TTL arguments integral and avoid bool-as-int configuration mistakes."""
    with pytest.raises(ValueError, match=r"ClientOptions\.signing_key_cache_seconds"):
        ClientOptions("https://partners.example", signing_key_cache_seconds=cast(int, value))


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), True, "30"])
def test_timeout_requires_finite_numeric_seconds(timeout: object) -> None:
    """Reject timeout values that cannot safely bound an HTTP request."""
    with pytest.raises(ValueError, match=r"ClientOptions\.timeout_seconds"):
        ClientOptions("https://partners.example", timeout_seconds=cast(float, timeout))


@pytest.mark.parametrize(
    "authority",
    [
        "https://user:password@partners.example",
        "https://partners.example:99999",
        "https://partners.example/path",
        "https://bücher.example",
    ],
)
def test_authority_rejects_userinfo_bad_ports_paths_and_unicode_hosts(authority: str) -> None:
    """Prevent HTTP Basic credentials, invalid Host forms, and mismatched canonical authorities."""
    with pytest.raises(ValueError, match=r"ClientOptions\.authority"):
        ClientOptions(authority)


def test_options_require_accept_language_enum_at_construction() -> None:
    """Refuse strings that would fail later while building a signed request."""
    with pytest.raises(ValueError, match=r"ClientOptions\.accept_language"):
        ClientOptions("https://partners.example", accept_language=cast(AcceptLanguage, "en"))


def test_shared_duration_binding_reads_day_prefixed_and_negative_forms() -> None:
    """Parse shared settings durations without dropping days or the sign."""
    options = ClientOptions.from_mapping(
        {
            "authority": "https://partners.example",
            "signing_key_cache_seconds": "1.00:00:00",
        }
    )
    assert options.signing_key_cache_seconds == 86_400
    with pytest.raises(ValueError, match="timeout_seconds"):
        ClientOptions.from_mapping({"authority": "https://partners.example", "timeout_seconds": "-00:00:05"})


@pytest.mark.parametrize("value", ["00:61:00", "1.24:00:00", "999999999999999999999.00:00:00"])
def test_shared_duration_binding_rejects_out_of_range_time_components(value: str) -> None:
    """Refuse duration strings that cannot be represented by the shared settings format."""
    with pytest.raises(ValueError, match=r"ClientOptions\.timeout_seconds"):
        ClientOptions.from_mapping({"authority": "https://partners.example", "timeout_seconds": value})
