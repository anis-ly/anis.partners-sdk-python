"""Validated client settings for one Anis authority."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address
from urllib.parse import urlsplit


class AcceptLanguage(StrEnum):
    """Choose presentation language while leaving machine-readable contract values unchanged."""

    UNSPECIFIED = ""
    ARABIC = "ar"
    ENGLISH = "en"


@dataclass(frozen=True, slots=True)
class ClientOptions:
    """Keep authority and bounded timeouts explicit so one client cannot silently target another deployment."""

    authority: str
    signature_lifetime_seconds: int = 60
    accept_language: AcceptLanguage = AcceptLanguage.UNSPECIFIED
    signing_key_cache_seconds: int = 600
    timeout_seconds: float = 30

    def __post_init__(self) -> None:
        """Validate before requests can be sent, since invalid settings must not fail after an order starts."""
        parsed = urlsplit(self.authority)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(
                "ClientOptions.authority must be the absolute authority Anis issued, e.g. https://partners.example."
            )
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("ClientOptions.authority must be an http or https URI.")
        if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
            raise ValueError(
                "ClientOptions.authority must use HTTPS because the unsigned key document can otherwise "
                "be replaced in transit and card codes can be read. HTTP is allowed only for loopback testing."
            )
        if self.timeout_seconds <= 0:
            raise ValueError("ClientOptions.timeout_seconds must be positive.")
        if self.signing_key_cache_seconds <= 0:
            raise ValueError("ClientOptions.signing_key_cache_seconds must be positive.")
        if not 1 <= self.signature_lifetime_seconds <= 60:
            raise ValueError(
                "ClientOptions.signature_lifetime_seconds must be between 1 and 60 seconds. Anis would admit up "
                "to 300, but this SDK accepts answers only within 60 seconds: with a longer signature and a slow "
                "clock an order can complete and its answer — with the card codes — be discarded."
            )
        object.__setattr__(self, "authority", self.authority.rstrip("/"))

    @classmethod
    def from_mapping(cls, settings: Mapping[str, object]) -> "ClientOptions":
        """Read Python, camelCase, or .NET setting names so file-based settings fail before first use."""
        source: Mapping[str, object] = settings
        section = settings.get("AnisPartners")
        if isinstance(section, Mapping):
            source = section

        def read(dotnet: str, snake: str, default: object) -> object:
            """Prefer Python spelling while accepting shared camelCase and .NET PascalCase keys."""
            camel = dotnet[:1].lower() + dotnet[1:]
            for key in (snake, camel, dotnet):
                if key in source:
                    return source[key]
            return default

        authority = read("Authority", "authority", "")
        if not isinstance(authority, str):
            raise ValueError(
                "ClientOptions.authority must be the absolute authority Anis issued, e.g. https://partners.example."
            )
        lifetime = _whole_seconds(
            read("SignatureLifetime", "signature_lifetime_seconds", 60), "signature_lifetime_seconds"
        )
        cache = _whole_seconds(
            read("SigningKeyCacheDuration", "signing_key_cache_seconds", 600), "signing_key_cache_seconds"
        )
        timeout = _seconds(read("Timeout", "timeout_seconds", 30), "timeout_seconds")
        language_value = read("AcceptLanguage", "accept_language", "")
        language = _language(language_value)
        return cls(authority, lifetime, language, cache, timeout)


def _seconds(value: object, attribute: str) -> int | float:
    """Accept numeric seconds and .NET-style duration strings without adding a configuration dependency."""
    if isinstance(value, bool):
        raise ValueError(f"ClientOptions.{attribute} must be seconds or a .NET time span.")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        pieces = value.split(":")
        try:
            if len(pieces) == 3:
                hours, minutes, seconds = (float(piece) for piece in pieces)
                return hours * 3600 + minutes * 60 + seconds
            return float(value)
        except ValueError as exc:
            raise ValueError(f"ClientOptions.{attribute} must be seconds or a .NET time span.") from exc
    raise ValueError(f"ClientOptions.{attribute} must be seconds or a .NET time span.")


def _whole_seconds(value: object, attribute: str) -> int:
    """Keep protocol windows integral because created and expires are whole Unix seconds."""
    result = _seconds(value, attribute)
    if int(result) != result:
        raise ValueError(f"ClientOptions.{attribute} must use whole seconds.")
    return int(result)


def _language(value: object) -> AcceptLanguage:
    """Use only declared language preferences so an unknown config value cannot alter wire presentation."""
    if isinstance(value, AcceptLanguage):
        return value
    if isinstance(value, str):
        return {
            "arabic": AcceptLanguage.ARABIC,
            "ar": AcceptLanguage.ARABIC,
            "english": AcceptLanguage.ENGLISH,
            "en": AcceptLanguage.ENGLISH,
        }.get(value.casefold(), AcceptLanguage.UNSPECIFIED)
    return AcceptLanguage.UNSPECIFIED


def _is_loopback(hostname: str | None) -> bool:
    """Allow plain HTTP only for local test authorities that cannot be reached from the network path."""
    if hostname is None:
        return False
    if hostname.casefold() == "localhost":
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False
