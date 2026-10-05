"""Settings binding tests that fail before client creation or order submission."""

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
    """Support native Python settings without requiring a .NET-style configuration container."""
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
