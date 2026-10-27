"""Receive Anis notifications: capture raw bytes, verify, persist pending work, then act.

Run it behind HTTPS at the URL registered with `webhook-endpoint --url`. Settings come from the environment:
ANIS_PARTNERS_AUTHORITY, WEBHOOK_PUBLIC_URL (the exact registered URL), ANIS_APPLICATION_ID and WEBHOOK_DEDUPE_DB.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

import httpx

from anis_partners import (
    HttpSigningKeySource,
    PartnerWebhookVerifier,
    UnverifiableWebhookError,
    VerifiableWebhook,
    WebhookEnvelope,
)
from anis_partners.models.webhooks import WebhookEventType


class _Receiver(BaseHTTPRequestHandler):
    verifier: PartnerWebhookVerifier
    database: sqlite3.Connection
    public_url: str

    def do_POST(self) -> None:
        # Read the raw bytes before anything parses them: the signature covers exactly these bytes.
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        received = self.headers.items()
        if len({name.lower() for name, _ in received}) != len(received):
            # Two values for one header are ambiguous; the verifier refuses them, so do not pick one here.
            self._reply(400, b"")
            return
        registered = urlsplit(self.public_url)
        expected_target = registered.path or "/"
        if "?" in self.public_url:
            expected_target += "?" + registered.query
        if self.path != expected_target:
            self._reply(401, b"")
            return
        # The proxy must forward the raw target unchanged; trust only the configured public origin.
        observed_url = f"{registered.scheme}://{registered.netloc}{self.path}"
        delivery = VerifiableWebhook("POST", observed_url, dict(received), body)
        try:
            envelope = self.verifier.verify_and_parse(delivery)
        except UnverifiableWebhookError as error:
            # Log the bounded reason only; never the body, the signature or the signature base.
            print(f"refused notification: {error.failure.value}")
            self._reply(401, b"")
            return
        if envelope.type is WebhookEventType.WEBHOOK_ENDPOINT_VERIFICATION and isinstance(envelope.data, dict):
            # Echo exactly the challenge, and only for a verified notification.
            self._reply(200, json.dumps({"challenge": envelope.data["challenge"]}).encode())
            return
        try:
            with self.database:
                self.database.execute(
                    "INSERT OR IGNORE INTO inbox (id, envelope, handled) VALUES (?, ?, 0)",
                    (str(envelope.id), json.dumps(envelope.to_json())),
                )
            _handle_pending(self.database, str(envelope.id), self._act_on)
        except Exception:
            # A failed handler leaves durable pending work; never acknowledge it as handled.
            print("notification handling failed; pending work retained")
            self._reply(503, b"")
            return
        self._reply(200, b"")

    @staticmethod
    def _act_on(envelope: WebhookEnvelope) -> None:
        # The verified data is the current state of the operation; act on its status, not on the event type alone.
        print(f"accepted {envelope.raw_type or envelope.type.value} for event {envelope.id}")

    def _reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _open_database(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
    database = sqlite3.connect(path, check_same_thread=False)
    database.execute(
        "CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, envelope TEXT NOT NULL, handled INTEGER NOT NULL)"
    )
    return database


def _handle_pending(database: sqlite3.Connection, event_id: str, handle: Callable[[WebhookEnvelope], None]) -> None:
    with database:
        pending = database.execute("SELECT envelope FROM inbox WHERE id = ? AND handled = 0", (event_id,)).fetchone()
        if pending is None:
            return
        handle(WebhookEnvelope.from_json(pending[0]))
        database.execute("UPDATE inbox SET handled = 1 WHERE id = ?", (event_id,))


def _recover_pending(database: sqlite3.Connection, handle: Callable[[WebhookEnvelope], None]) -> None:
    for (event_id,) in database.execute("SELECT id FROM inbox WHERE handled = 0").fetchall():
        try:
            _handle_pending(database, event_id, handle)
        except Exception:
            print("notification recovery failed; pending work retained")


def main() -> None:
    """Terminate TLS at a trusted proxy that preserves the request's raw path and query."""
    authority = os.environ["ANIS_PARTNERS_AUTHORITY"]
    database = _open_database(os.environ.get("WEBHOOK_DEDUPE_DB", "anis-deliveries.db"))
    keys = HttpSigningKeySource(httpx.Client(), authority)
    _Receiver.public_url = os.environ["WEBHOOK_PUBLIC_URL"]
    _Receiver.verifier = PartnerWebhookVerifier(
        keys, configured_url=_Receiver.public_url, application_id=os.environ["ANIS_APPLICATION_ID"]
    )
    _Receiver.database = database
    # Only previously verified envelopes enter the inbox. Recover them even without another delivery.
    _recover_pending(database, _Receiver._act_on)
    HTTPServer(("127.0.0.1", 8080), _Receiver).serve_forever()


if __name__ == "__main__":
    main()
