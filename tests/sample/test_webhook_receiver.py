"""Deliver signed HTTP requests to the sample and inspect its durable inbox."""

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

import httpx
import pytest

from anis_partners import PartnerWebhookVerifier, WebhookEnvelope
from samples.console import webhook_receiver as sample
from tests.support.products import full_read
from tests.support.webhooks import APPLICATION, URL, FixedClock, signed_delivery
from tests.verification.test_webhook_verifier import CountingKeys


@contextmanager
def receiver(
    database: sqlite3.Connection, verifier: PartnerWebhookVerifier, action: Callable[[WebhookEnvelope], None]
) -> Iterator[str]:
    class Handler(sample._Receiver):
        def log_message(self, format: str, *args: object) -> None:
            pass

        @staticmethod
        def _act_on(envelope: WebhookEnvelope) -> None:
            action(envelope)

    Handler.database = database
    Handler.verifier = verifier
    Handler.public_url = URL
    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01))
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()


def test_failed_handling_survives_restart_and_successful_retry_is_deduplicated(tmp_path: Path) -> None:
    delivery, keys = signed_delivery(full_read(False), "directRecharge.completed")
    verifier = PartnerWebhookVerifier(
        CountingKeys(keys), configured_url=URL, application_id=APPLICATION, clock=FixedClock()
    )
    path = tmp_path / "inbox.db"
    database = sample._open_database(str(path))
    database.execute("CREATE TABLE business_outcomes (id TEXT PRIMARY KEY)")
    calls: list[str] = []

    def fail(envelope: WebhookEnvelope) -> None:
        calls.append(str(envelope.id))
        database.execute("INSERT INTO business_outcomes (id) VALUES (?)", (str(envelope.id),))
        raise RuntimeError("handler unavailable")

    target = urlsplit(URL)
    with receiver(database, verifier, fail) as origin:
        response = httpx.post(
            origin + target.path + "?" + target.query, headers=delivery.headers, content=delivery.body
        )
    assert response.status_code == 503
    rows = database.execute("SELECT id, envelope, handled FROM inbox").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == json.loads(delivery.body)["id"]
    assert json.loads(rows[0][1]) == json.loads(delivery.body)
    assert rows[0][2] == 0
    assert database.execute("SELECT count(*) FROM business_outcomes").fetchone() == (0,)
    database.close()
    assert path.stat().st_mode & 0o777 == 0o600

    recovered = sample._open_database(str(path))
    database = recovered
    handled: list[WebhookEnvelope] = []

    def succeed(envelope: WebhookEnvelope) -> None:
        recovered.execute("INSERT INTO business_outcomes (id) VALUES (?)", (str(envelope.id),))
        handled.append(envelope)

    try:
        sample._recover_pending(recovered, fail)
        assert recovered.execute("SELECT handled FROM inbox").fetchone() == (0,)
        assert recovered.execute("SELECT count(*) FROM business_outcomes").fetchone() == (0,)
        sample._recover_pending(recovered, succeed)
        assert len(handled) == 1
        assert handled[0].to_json() == json.loads(delivery.body)
        assert recovered.execute("SELECT handled FROM inbox").fetchone() == (1,)
        with receiver(recovered, verifier, succeed) as origin:
            response = httpx.post(
                origin + target.path + "?" + target.query, headers=delivery.headers, content=delivery.body
            )
        assert response.status_code == 200
        assert len(handled) == 1
        assert len(calls) == 2
        assert recovered.execute("SELECT id FROM business_outcomes").fetchall() == [(rows[0][0],)]
        assert recovered.execute("SELECT count(*) FROM inbox").fetchone() == (1,)
    finally:
        recovered.close()


@pytest.mark.parametrize(
    "target",
    [
        "/wrong?registration=1%2B2",
        "/hooks/anis",
        "/hooks/anis?registration=other",
        "/hooks/anis?registration=1+2",
        "//evil.example/hooks/anis?registration=1%2B2",
    ],
)
def test_replayed_delivery_to_another_raw_target_is_refused(tmp_path: Path, target: str) -> None:
    delivery, keys = signed_delivery(full_read(False), "directRecharge.completed")
    verifier = PartnerWebhookVerifier(
        CountingKeys(keys), configured_url=URL, application_id=APPLICATION, clock=FixedClock()
    )
    database = sample._open_database(str(tmp_path / "inbox.db"))
    handled: list[WebhookEnvelope] = []
    try:
        with receiver(database, verifier, handled.append) as origin:
            # Connect locally while sending the observed raw target, even for a network-path reference.
            from http.client import HTTPConnection

            connection = HTTPConnection("127.0.0.1", int(origin.rsplit(":", 1)[1]))
            connection.request(
                "POST",
                target,
                body=delivery.body,
                headers={**delivery.headers, "X-Forwarded-Host": "receiver.example", "X-Original-URL": URL},
            )
            response = connection.getresponse()
            assert response.status == 401
            response.read()
            connection.close()
        assert handled == []
        assert database.execute("SELECT count(*) FROM inbox").fetchone() == (0,)
    finally:
        database.close()


def test_correct_raw_target_and_verified_challenge_are_accepted(tmp_path: Path) -> None:
    delivery, keys = signed_delivery(
        {"challenge": "private-challenge", "generation": 1}, "webhook_endpoint.verification"
    )
    verifier = PartnerWebhookVerifier(
        CountingKeys(keys), configured_url=URL, application_id=APPLICATION, clock=FixedClock()
    )
    database = sample._open_database(str(tmp_path / "inbox.db"))
    handled: list[WebhookEnvelope] = []
    try:
        with receiver(database, verifier, handled.append) as origin:
            target = urlsplit(URL)
            response = httpx.post(
                origin + target.path + "?" + target.query,
                headers={**delivery.headers, "X-Forwarded-Host": "evil.example"},
                content=delivery.body,
            )
            assert response.status_code == 200
            assert response.json() == {"challenge": "private-challenge"}
            forged = httpx.post(
                origin + target.path + "?" + target.query, headers=delivery.headers, content=delivery.body + b" "
            )
            assert forged.status_code == 401
            assert forged.content == b""
        assert handled == []
        assert database.execute("SELECT count(*) FROM inbox").fetchone() == (0,)
    finally:
        database.close()
