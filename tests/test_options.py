"""Authority validation prevents credentials and unsigned key documents crossing a plain network path."""

import pytest

from anis_partners import ClientOptions


@pytest.mark.parametrize("authority", ["http://example.test", "http://192.0.2.10"])
def test_non_loopback_http_authority_is_refused(authority: str) -> None:
    """Reject cleartext network authorities because keys can be replaced and card codes exposed in transit."""
    with pytest.raises(ValueError, match=r"unsigned key document.*card codes"):
        ClientOptions(authority)


@pytest.mark.parametrize("authority", ["http://localhost", "http://127.0.0.1", "http://[::1]"])
def test_loopback_http_authority_is_allowed_for_local_testing(authority: str) -> None:
    """Allow cleartext only on loopback for local fake gateways and test servers."""
    assert ClientOptions(authority).authority == authority
