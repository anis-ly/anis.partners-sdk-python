"""Unknown order logs tell operators to resume the durable intent with its existing id."""

from __future__ import annotations

import logging
from typing import cast

from anis_partners.operations.transport import RequestCore, record_unknown_order


class _Core:
    client_name = "sample"

    def __init__(self) -> None:
        self.logged: tuple[int, int, str, dict[str, object]] | None = None

    def _log(self, event_id: int, level: int, message: str, **fields: object) -> None:
        self.logged = (event_id, level, message, fields)


def test_package_installs_a_null_handler_for_silent_library_logging() -> None:
    logger = logging.getLogger("anis_partners")

    assert any(isinstance(handler, logging.NullHandler) for handler in logger.handlers)


def test_unknown_order_event_names_same_id_recovery() -> None:
    core = _Core()

    record_unknown_order(cast(RequestCore, core), "operation-17", "timeout")

    assert core.logged is not None
    event_id, level, message, fields = core.logged
    assert event_id == 1008
    assert level == logging.WARNING
    assert "resume it with the same operation id, never a new one" in message
    assert "operation-17" in message
    assert fields["operation_id"] == "operation-17"
