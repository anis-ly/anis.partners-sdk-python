"""Keep the documented command-line entry point and its safe preview usable."""

from __future__ import annotations

import io
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners import (
    AnisApiError,
    CreateOrderRequest,
    DependencyUnavailableError,
    Order,
    OrderCompleted,
    OrderNotPlaced,
    OrderOutcomeUnknown,
    OrderProcessing,
    OrderReplayed,
    OrderStatus,
    PriceChangedError,
)
from anis_partners.models import Money, Problem
from samples.console import anis_sample
from samples.console.anis_sample import main


def test_help_lists_commands_without_loading_settings() -> None:
    """Help must work on a clean machine without a key or authority configured."""
    output = io.StringIO()

    assert main(["help"], output=output) == 0

    assert "profile" in output.getvalue()
    assert "reveal-invoice" in output.getvalue()


def test_dry_run_profile_uses_stub_and_never_prints_signature_values(tmp_path: Path) -> None:
    """The sample should show its prepared request while MockTransport prevents a real send."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    key_file = tmp_path / "partner-key.pem"
    key_file.write_bytes(pem)
    output = io.StringIO()

    assert (
        main(
            ["profile", "--dry-run"],
            settings={
                "Authority": "https://partners.example",
                "key_file": str(key_file),
                "key_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            },
            output=output,
        )
        == 0
    )

    printed = output.getvalue()
    assert "DRY RUN — not sent" in printed
    assert "GET https://partners.example/v1/profile" in printed
    assert "signature" in printed
    assert "sig1=:" not in printed


def test_enrol_dry_run_creates_key_in_memory_without_writing_file(tmp_path: Path) -> None:
    key_file = tmp_path / "not-created.pem"
    output = io.StringIO()

    result = main(
        [
            "enrol",
            "--invitation",
            "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "--token",
            "one-time-token",
            "--key-file",
            str(key_file),
            "--dry-run",
        ],
        settings={"Authority": "https://partners.example"},
        output=output,
    )

    assert result == 0
    assert not key_file.exists()
    assert "POST https://partners.example/v1/enrollments/7c9e6679-7425-40de-944b-e07fc1f90ae7/keys" in output.getvalue()
    assert "one-time-token" not in output.getvalue()


def test_sample_parser_accepts_reference_order_and_enrollment_arguments() -> None:
    parsed = anis_sample._parser().parse_args(
        [
            "order",
            "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "7c9e6679-7425-40de-944b-e07fc1f90ae8",
            "7c9e6679-7425-40de-944b-e07fc1f90ae9",
            "2",
            "--reference",
            "order-ref-1",
            "--use-allowed-debt",
            "--operation",
            "7c9e6679-7425-40de-944b-e07fc1f90aea",
            "--expected-unit-price",
            "10.500",
        ]
    )
    enrol = anis_sample._parser().parse_args(
        [
            "enrol",
            "--invitation",
            "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "--token",
            "token",
            "--days",
            "30",
        ]
    )
    status = anis_sample._parser().parse_args(
        [
            "enrol-status",
            "--invitation",
            "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "--token",
            "token",
        ]
    )

    assert parsed.reference == "order-ref-1"
    assert parsed.use_allowed_debt is True
    assert parsed.operation == UUID("7c9e6679-7425-40de-944b-e07fc1f90aea")
    assert parsed.expected_unit_price == Decimal("10.500")
    assert enrol.days == 30
    assert status.invitation == UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")


class _FakeClient:
    def __init__(self, _options: object, _signer: object, **_kwargs: object) -> None:
        self.profile = self
        self.wallets = self
        self.catalogue = self
        self.orders = self
        self.captured: tuple[object, ...] | None = None
        self.error: Exception | None = None
        self.result: object | None = None

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, *_args: object) -> object:
        if self.error is not None:
            raise self.error
        return {"ok": True}

    def list_cards(self, *_args: object) -> list[object]:
        card = type("Card", (), {})()
        card.id = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae9")
        card.unit_price = Money(Decimal("12.000"), "LYD")
        return [card]

    def create(self, *args: object) -> object:
        self.captured = args
        if self.result is None:
            raise AssertionError("The test must configure an order result.")
        return self.result


def test_expected_unit_price_reference_and_debt_are_sent_to_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    operation = UUID("7c9e6679-7425-40de-944b-e07fc1f90aea")
    card = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae9")
    api = _FakeClient(None, None)
    api.result = OrderNotPlaced(operation, PriceChangedError(Problem(status=409, code="price_changed"), 409))
    monkeypatch.setattr(anis_sample, "_signer", lambda _settings: object())
    monkeypatch.setattr(anis_sample, "AnisPartnersClient", lambda *args, **kwargs: api)
    output = io.StringIO()

    result = main(
        [
            "order",
            "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "7c9e6679-7425-40de-944b-e07fc1f90ae8",
            str(card),
            "2",
            "--operation",
            str(operation),
            "--reference",
            "merchant-17",
            "--use-allowed-debt",
            "--expected-unit-price",
            "10.500",
        ],
        settings={"Authority": "https://partners.example", "orders_folder": str(tmp_path)},
        output=output,
    )

    assert result != 0
    assert api.captured is not None
    request = api.captured[2]
    assert isinstance(request, CreateOrderRequest)
    assert request.expected_unit_price == Money(Decimal("10.500"), "LYD")
    assert request.expected_total == Money(Decimal("21.000"), "LYD")
    assert request.external_reference == "merchant-17"
    assert request.use_allowed_debt is True
    assert "NOT PLACED code=price_changed status=409" in output.getvalue()


def test_refused_wallet_read_prints_refused_and_returns_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _FakeClient(None, None)
    api.error = AnisApiError(Problem(status=403, code="wallet_not_granted", request_id="request-17"), 403)
    monkeypatch.setattr(anis_sample, "_signer", lambda _settings: object())
    monkeypatch.setattr(anis_sample, "AnisPartnersClient", lambda *args, **kwargs: api)
    output = io.StringIO()

    result = main(
        ["wallet", "7c9e6679-7425-40de-944b-e07fc1f90ae7"],
        settings={"Authority": "https://partners.example"},
        output=output,
    )

    lines = output.getvalue().splitlines()
    assert result != 0
    assert len(lines) == 1
    assert lines[0].startswith("REFUSED code=wallet_not_granted")
    assert "status=403" in lines[0]
    assert "request_id=request-17" in lines[0]
    assert "retryable=no" in lines[0]
    assert "recorded_answer=no" in lines[0]
    assert not lines[0].startswith("NOT PLACED")
    assert "Traceback" not in output.getvalue()


def test_tour_displays_the_published_signing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    class TourClient:
        profile = SimpleNamespace(get=lambda: {"profile": "sample"})
        wallets = SimpleNamespace(list=lambda: [])
        diagnostics = SimpleNamespace(check_signature=lambda: {"ok": True})

        def __enter__(self) -> TourClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    client = TourClient()
    keys = {"keys": [{"kid": "signing-key-7"}]}
    monkeypatch.setattr(anis_sample, "_signer", lambda _settings: object())
    monkeypatch.setattr(anis_sample, "AnisPartnersClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(
        anis_sample,
        "HttpSigningKeySource",
        lambda *_args: SimpleNamespace(refresh=lambda: keys),
    )
    output = io.StringIO()

    result = main(["tour"], settings={"Authority": "https://partners.example"}, output=output)

    assert result == 0
    assert "signing-key-7" in output.getvalue()


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (OrderCompleted(Order(operation_id=UUID(int=1), status=OrderStatus.COMPLETED)), "COMPLETED"),
        (
            OrderProcessing(Order(operation_id=UUID(int=1), status=OrderStatus.PROCESSING), timedelta(seconds=3)),
            "PROCESSING operation",
        ),
        (OrderReplayed(Order(operation_id=UUID(int=1), status=OrderStatus.COMPLETED)), "REPLAYED"),
        (
            OrderNotPlaced(UUID(int=1), PriceChangedError(Problem(status=409, code="price_changed"), 409)),
            "NOT PLACED code=price_changed",
        ),
        (
            OrderOutcomeUnknown(
                UUID(int=1), timedelta(seconds=5), DependencyUnavailableError(Problem(code="request_timeout"), 504)
            ),
            "UNKNOWN operation",
        ),
    ],
    ids=["completed", "processing", "replayed", "not-placed", "unknown"],
)
def test_sample_prints_each_order_recovery_outcome(result: object, expected: str) -> None:
    output = io.StringIO()

    anis_sample._show_order_outcome(result, UUID(int=1), output)

    assert expected in output.getvalue()
