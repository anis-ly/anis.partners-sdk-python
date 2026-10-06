"""Share the supported AnyIO backend across asynchronous conformance and client tests."""

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run async SDK tests on the asyncio runtime used by the supported host APIs."""
    return "asyncio"
