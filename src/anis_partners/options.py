"""Validated client settings for one Anis authority."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import ip_address
from urllib.parse import urlsplit

import httpx

_MAX_TIMESPAN_SECONDS = 922_337_203_685.4775807


class AcceptLanguage(StrEnum):
    """Choose presentation language while leaving machine-readable contract values unchanged."""

    UNSPECIFIED = ""
    ARABIC = "ar"
    ENGLISH = "en"


@dataclass(frozen=True, slots=True)
class ClientOptions:
    """Keep authority and bounded timeouts explicit so one client cannot silently target another deployment."""

    authority: str
    signature_lifetime_seconds: int = field(default=60, kw_only=True)
    accept_language: AcceptLanguage = field(default=AcceptLanguage.UNSPECIFIED, kw_only=True)
    signing_key_cache_seconds: int = field(default=600, kw_only=True)
    timeout_seconds: float = field(default=30, kw_only=True)

    def __post_init__(self) -> None:
        """Validate before requests can be sent, since invalid settings must not fail after an order starts."""
        if not isinstance(self.authority, str):
            raise ValueError("ClientOptions.authority must be an absolute HTTPS authority issued by Anis.")
        parsed = urlsplit(self.authority)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(
                "ClientOptions.authority must be the absolute authority Anis issued, e.g. https://partners.example."
            )
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("ClientOptions.authority must be an http or https URI.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("ClientOptions.authority must not include user information.")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("ClientOptions.authority must not include a path, query, or fragment.")
        try:
            _ = parsed.port
        except ValueError:
            raise ValueError("ClientOptions.authority must use a valid port.") from None
        if parsed.hostname is None or not parsed.hostname.isascii():
            raise ValueError("ClientOptions.authority must use an ASCII host name (use its punycode form).")
        if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
            raise ValueError(
                "ClientOptions.authority must use HTTPS because the unsigned key document can otherwise "
                "be replaced in transit and card codes can be read. HTTP is allowed only for loopback testing."
            )
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            raise ValueError("ClientOptions.timeout_seconds must be a finite positive number of seconds.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("ClientOptions.timeout_seconds must be positive.")
        if type(self.signing_key_cache_seconds) is not int:
            raise ValueError("ClientOptions.signing_key_cache_seconds must be a positive integer number of seconds.")
        if self.signing_key_cache_seconds <= 0:
            raise ValueError("ClientOptions.signing_key_cache_seconds must be positive.")
        if type(self.signature_lifetime_seconds) is not int:
            raise ValueError("ClientOptions.signature_lifetime_seconds must be an integer from 1 to 60 seconds.")
        if not 1 <= self.signature_lifetime_seconds <= 60:
            raise ValueError(
                "ClientOptions.signature_lifetime_seconds must be between 1 and 60 seconds. Anis would admit up "
                "to 300, but this SDK accepts answers only within 60 seconds: with a longer signature and a slow "
                "clock an order can complete and its answer — with the card codes — be discarded."
            )
        if not isinstance(self.accept_language, AcceptLanguage):
            raise ValueError("ClientOptions.accept_language must be an AcceptLanguage value.")
        normalized = httpx.URL(self.authority)
        object.__setattr__(self, "authority", str(normalized.copy_with(path="", query=None, fragment=None)).rstrip("/"))

    @classmethod
    def from_mapping(cls, settings: Mapping[str, object]) -> "ClientOptions":
        """Read Python or shared settings-file names so invalid values fail before first use."""
        source: Mapping[str, object] = settings
        section = settings.get("AnisPartners")
        if isinstance(section, Mapping):
            source = section

        def read(dotnet: str, snake: str, default: object) -> object:
            """Prefer Python spelling while accepting shared camelCase and PascalCase keys."""
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
        return cls(
            authority,
            signature_lifetime_seconds=lifetime,
            accept_language=language,
            signing_key_cache_seconds=cache,
            timeout_seconds=timeout,
        )


def _seconds(value: object, attribute: str) -> int | float:
    """Accept seconds or the shared settings-file duration form without adding a parser dependency."""
    if isinstance(value, bool):
        raise ValueError(f"ClientOptions.{attribute} must be seconds or an hh:mm:ss string.")
    if type(value) is int:
        if abs(value) <= _MAX_TIMESPAN_SECONDS:
            return value
        raise ValueError(f"ClientOptions.{attribute} must be a finite supported duration.")
    if isinstance(value, float):
        if math.isfinite(value) and abs(value) <= _MAX_TIMESPAN_SECONDS:
            return value
        raise ValueError(f"ClientOptions.{attribute} must be a finite supported duration.")
    if isinstance(value, str):
        pattern = (
            r"(?P<sign>-?)(?:(?P<days>[0-9]+)\.)?"
            r"(?P<hours>[0-9]{1,2}):(?P<minutes>[0-9]{2}):"
            r"(?P<seconds>[0-9]{2}(?:\.[0-9]+)?)"
        )
        match = re.fullmatch(pattern, value)
        if match is not None:
            sign = -1 if value.startswith("-") else 1
            try:
                days = int(match.group("days") or "0")
                hours = int(match.group("hours"))
                minutes = int(match.group("minutes"))
                seconds = float(match.group("seconds"))
                if minutes > 59 or seconds >= 60 or (match.group("days") is not None and hours > 23):
                    raise ValueError
                result = sign * (days * 86400 + hours * 3600 + minutes * 60 + seconds)
                if math.isfinite(result) and abs(result) <= _MAX_TIMESPAN_SECONDS:
                    return result
            except (OverflowError, ValueError):
                pass
        try:
            numeric = float(value)
            if math.isfinite(numeric) and abs(numeric) <= _MAX_TIMESPAN_SECONDS:
                return numeric
        except (OverflowError, ValueError):
            pass
    raise ValueError(f"ClientOptions.{attribute} must be seconds or an hh:mm:ss string.")


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
        language = {
            "": AcceptLanguage.UNSPECIFIED,
            "arabic": AcceptLanguage.ARABIC,
            "ar": AcceptLanguage.ARABIC,
            "english": AcceptLanguage.ENGLISH,
            "en": AcceptLanguage.ENGLISH,
        }.get(value.casefold())
        if language is not None:
            return language
    raise ValueError("ClientOptions.accept_language must be 'ar', 'en', or an empty string.")


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
