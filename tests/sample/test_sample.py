"""Keep the documented command-line entry point and its safe preview usable."""

from __future__ import annotations

import io
import json
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
    MeterChargeOutcomeUnknown,
    Order,
    OrderCompleted,
    OrderNotPlaced,
    OrderOutcomeUnknown,
    OrderProcessing,
    OrderReplayed,
    OrderStatus,
    PriceChangedError,
    RevealedCredential,
)
from anis_partners.models import EnrollmentStatus, Money, Problem
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


def test_enrollment_proof_must_be_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Return a failing process code when the enrollment proof was not accepted by Anis."""

    class FakeEnrollment:
        def __init__(self, authority: str, invitation_id: str, token: str, *, http_client: object) -> None:
            pass

        def __enter__(self) -> FakeEnrollment:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def submit_key(self, request: object) -> object:
            return SimpleNamespace(key_id=UUID("9e96dc41-c715-4cc4-b1aa-836fe42ad0bb"), safety_code="1234567890123456")

        def prove(self, submitted: object, signer: object) -> EnrollmentStatus:
            return EnrollmentStatus(proof_state="pending")

    key_file = tmp_path / "partner-key.pem"
    monkeypatch.setattr(anis_sample, "AnisEnrollmentClient", FakeEnrollment)
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
        ],
        settings={"Authority": "https://partners.example"},
        output=output,
    )
    assert result != 0
    assert "ENROLLMENT PROOF NOT ACCEPTED" in output.getvalue()
    assert key_file.exists()
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert "Safety code:" not in output.getvalue()


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
        self.intent_path: Path | None = None

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

    def create(self, *args: object, **kwargs: object) -> object:
        self.captured = args or (kwargs["wallet_id"], kwargs["operation_id"], kwargs["order"])
        if self.intent_path is not None:
            saved = json.loads(self.intent_path.read_text(encoding="utf-8"))
            assert UUID(saved["operation_id"]) == args[1]
            assert self.intent_path.stat().st_mode & 0o777 == 0o600
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


def test_sample_commits_private_intent_before_the_order_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Ensure the journal already contains the operation id when the purchase reaches the client."""
    operation = UUID("7c9e6679-7425-40de-944b-e07fc1f90aea")
    card = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae9")
    api = _FakeClient(None, None)
    api.intent_path = tmp_path / f"{operation}.json"
    api.result = OrderNotPlaced(operation, PriceChangedError(Problem(status=409, code="price_changed"), 409))
    monkeypatch.setattr(anis_sample, "_signer", lambda _settings: object())
    monkeypatch.setattr(anis_sample, "AnisPartnersClient", lambda *args, **kwargs: api)
    output = io.StringIO()
    main(
        [
            "order",
            "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "7c9e6679-7425-40de-944b-e07fc1f90ae8",
            str(card),
            "1",
            "--operation",
            str(operation),
            "--expected-unit-price",
            "10.500",
        ],
        settings={"Authority": "https://partners.example", "orders_folder": str(tmp_path)},
        output=output,
    )
    assert api.intent_path.exists()
    assert f'"operation_id": "{operation}"' in api.intent_path.read_text(encoding="utf-8")


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


def test_sample_reveals_codes_only_with_the_explicit_switch() -> None:
    credential = RevealedCredential(
        UUID("4a6c2e81-7b39-4d15-a2f8-3e7b9c1d5046"), serial_number="private-serial", voucher="private-voucher"
    )
    hidden = io.StringIO()
    shown = io.StringIO()

    anis_sample._show(credential, hidden)
    anis_sample._show(credential, shown, show_secrets=True)

    assert "private-serial" not in hidden.getvalue()
    assert "private-voucher" not in hidden.getvalue()
    assert "private-serial" in shown.getvalue()
    assert "private-voucher" in shown.getvalue()


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
        (
            OrderCompleted(Order(operation_id=UUID(int=1), status=OrderStatus.COMPLETED, codes_withheld=True)),
            "COMPLETED, CODES WITHHELD",
        ),
        (
            OrderProcessing(
                Order(operation_id=UUID(int=1), status=OrderStatus.RECOVERY_EXHAUSTED), timedelta(minutes=1)
            ),
            "RECOVERY EXHAUSTED",
        ),
    ],
    ids=["completed", "processing", "replayed", "not-placed", "unknown", "withheld", "recovery-exhausted"],
)
def test_sample_prints_each_order_recovery_outcome(result: object, expected: str) -> None:
    output = io.StringIO()

    anis_sample._show_order_outcome(result, UUID(int=1), output)

    assert expected in output.getvalue()


def test_withheld_completion_merges_supplied_credentials(tmp_path: Path) -> None:
    """Merge every supplied credential into the journal even when the result is marked withheld."""
    path = tmp_path / "order.json"
    previous = [{"voucher": "previous-voucher", "serialNumber": "previous-serial"}]
    path.write_text(json.dumps({"credentials": previous}), encoding="utf-8")
    partial = RevealedCredential(sold_card_id=UUID(int=2), voucher="partial-voucher", serial_number="partial-serial")
    result = OrderCompleted(
        Order(
            operation_id=UUID(int=1),
            status=OrderStatus.COMPLETED,
            sold_cards=(partial,),
            codes_withheld=True,
        )
    )

    anis_sample._record_result(path, result)

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["outcome"] == "completed-withheld"
    assert record["credentials"] == [*previous, partial.to_json()]


def test_withheld_completion_adds_credentials_when_journal_list_is_empty(tmp_path: Path) -> None:
    """Persist credentials supplied by a withheld completion when the journal has an empty credentials list."""
    path = tmp_path / "order.json"
    path.write_text(json.dumps({"credentials": []}), encoding="utf-8")
    supplied = RevealedCredential(sold_card_id=UUID(int=3), voucher="supplied-voucher", serial_number="supplied-serial")
    result = OrderCompleted(
        Order(
            operation_id=UUID(int=1),
            status=OrderStatus.COMPLETED,
            sold_cards=(supplied,),
            codes_withheld=True,
        )
    )

    anis_sample._record_result(path, result)

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["credentials"] == [supplied.to_json()]


def test_withheld_completion_retains_stored_credentials_when_answer_has_none(tmp_path: Path) -> None:
    """Keep previously journalled credentials when a withheld answer supplies no new credentials."""
    path = tmp_path / "order.json"
    previous = [{"voucher": "previous-voucher", "serialNumber": "previous-serial"}]
    path.write_text(json.dumps({"credentials": previous}), encoding="utf-8")
    result = OrderCompleted(Order(operation_id=UUID(int=1), status=OrderStatus.COMPLETED, codes_withheld=True))

    anis_sample._record_result(path, result)

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["credentials"] == previous


class _ProductClient:
    """Stand-in for the product groups that records what the sample sends."""

    def __init__(self) -> None:
        self.meter_charges = self
        self.direct_recharges = self
        self.intent_path: Path | None = None
        self.calls: list[tuple[str, dict[str, object]]] = []

    def __enter__(self) -> _ProductClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def _outcome(self, name: str, kwargs: dict[str, object]) -> object:
        self.calls.append((name, kwargs))
        if self.intent_path is not None:
            assert self.intent_path.stat().st_mode & 0o777 == 0o600
            assert json.loads(self.intent_path.read_text(encoding="utf-8"))["operation_id"] == str(
                kwargs["operation_id"]
            )
        return MeterChargeOutcomeUnknown(kwargs["operation_id"], timedelta(seconds=5), TimeoutError())  # type: ignore[arg-type]

    def create(self, **kwargs: object) -> object:
        return self._outcome("create", kwargs)

    def resume(self, **kwargs: object) -> object:
        return self._outcome("resume", kwargs)


def test_meter_charge_persists_intent_then_reports_unknown_with_the_same_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The saved id and body precede the create call, and an unknown outcome says to resume with that id."""
    operation = UUID("7c9e6679-7425-40de-944b-e07fc1f90aea")
    api = _ProductClient()
    api.intent_path = tmp_path / f"{operation}.json"
    monkeypatch.setattr(anis_sample, "_signer", lambda _settings: object())
    monkeypatch.setattr(anis_sample, "AnisPartnersClient", lambda *args, **kwargs: api)
    output = io.StringIO()
    settings: dict[str, object] = {"Authority": "https://partners.example", "orders_folder": str(tmp_path)}

    arguments = [
        "meter-charge",
        "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "7c9e6679-7425-40de-944b-e07fc1f90ae8",
        "0268000710262",
        "97.500",
        "--operation",
        str(operation),
    ]
    assert main(arguments, settings=settings, output=output) == 0

    saved = json.loads(api.intent_path.read_text(encoding="utf-8"))
    assert saved["kind"] == "meter"
    assert saved["request"]["meterNumber"] == "0268000710262"
    assert saved["outcome"] == "unknown"
    assert f"UNKNOWN operation {operation}; meter-resume {operation}" in output.getvalue()

    assert main(["meter-resume", str(operation)], settings=settings, output=io.StringIO()) == 0
    assert [name for name, _ in api.calls] == ["create", "resume"]
    assert api.calls[1][1]["operation_id"] == operation


def test_direct_recharge_command_reads_recipient_fields_without_echoing_values() -> None:
    """A malformed recipient argument is refused by the parser and its text is not printed."""
    with pytest.raises(SystemExit):
        anis_sample._parser().parse_args(
            ["direct-recharge", "w", "p", "10.000", "12.000", "--recipient", "no-separator"]
        )
    parsed = anis_sample._parser().parse_args(
        [
            "direct-recharge",
            "7c9e6679-7425-40de-944b-e07fc1f90ae7",
            "7c9e6679-7425-40de-944b-e07fc1f90ae8",
            "10.000",
            "12.000",
            "--recipient",
            "recipient_number=0912345678",
        ]
    )
    assert parsed.recipient[0].key == "recipient_number"
    assert parsed.recipient[0].value == "0912345678"


def test_sample_hides_meter_tokens_and_recipient_details_unless_asked() -> None:
    """Receipts and recipient fields are summarised by default."""
    document = {"tokens": [{"code": "1234 5678"}], "recipient": [{"key": "recipient_number", "value": "0912345678"}]}
    hidden = io.StringIO()
    anis_sample._show(document, hidden)
    assert "1234 5678" not in hidden.getvalue()
    assert "0912345678" not in hidden.getvalue()
    shown = io.StringIO()
    anis_sample._show(document, shown, show_secrets=True)
    assert "1234 5678" in shown.getvalue()


def test_help_lists_product_and_webhook_commands() -> None:
    """Every new command is discoverable from help."""
    output = io.StringIO()
    assert main(["help"], output=output) == 0
    for command in ("meter-charge", "direct-quote", "direct-fix-recipient", "webhook-endpoint", "webhook-redeliver"):
        assert command in output.getvalue()


def test_direct_recharge_saved_empty_recipient_survives_sample_resume(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from anis_partners import CreateDirectRechargeRequest, DirectRechargeOutcomeUnknown

    operation = UUID("7c9e6679-7425-40de-944b-e07fc1f90aea")

    class DirectClient(_ProductClient):
        def _outcome(self, name: str, kwargs: dict[str, object]) -> object:
            super()._outcome(name, kwargs)
            return DirectRechargeOutcomeUnknown(operation, timedelta(seconds=5), TimeoutError())

    api = DirectClient()
    api.intent_path = tmp_path / f"{operation}.json"
    monkeypatch.setattr(anis_sample, "_signer", lambda _settings: object())
    monkeypatch.setattr(anis_sample, "AnisPartnersClient", lambda *args, **kwargs: api)
    settings: dict[str, object] = {"Authority": "https://partners.example", "orders_folder": str(tmp_path)}
    arguments = [
        "direct-recharge",
        str(UUID(int=1)),
        str(UUID(int=2)),
        "10.000",
        "12.000",
        "--operation",
        str(operation),
        "--recipient",
        "OptionalField=",
    ]
    output = io.StringIO()
    assert main(arguments, settings=settings, output=output) == 0
    saved = json.loads(api.intent_path.read_text())
    assert saved["request"]["recipient"] == [{"key": "OptionalField", "value": ""}]
    assert saved["kind"] == "direct"
    assert saved["outcome"] == "unknown"
    assert main(["direct-resume", str(operation)], settings=settings, output=output) == 0
    assert [name for name, _ in api.calls] == ["create", "resume"]
    create, resume = (call[1]["request"] for call in api.calls)
    assert isinstance(create, CreateDirectRechargeRequest)
    assert isinstance(resume, CreateDirectRechargeRequest)
    assert create == resume
    assert resume.to_json()["recipient"] == [{"key": "OptionalField", "value": ""}]
    assert api.calls[0][1]["operation_id"] == api.calls[1][1]["operation_id"] == operation


def test_recipient_correction_sample_prints_acknowledgement_and_location_without_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from anis_partners import DirectRechargeAccepted, DirectRechargeProcessing, UpdateDirectRechargeRecipientRequest

    operation = UUID(int=77)
    location = f"/v1/direct-recharges/{operation}"

    class RecipientClient(_ProductClient):
        def update_recipient(
            self, operation_id: UUID, request: UpdateDirectRechargeRecipientRequest
        ) -> DirectRechargeProcessing:
            self.calls.append(("update_recipient", {"operation_id": operation_id, "request": request}))
            return DirectRechargeProcessing(DirectRechargeAccepted(operation_id), timedelta(seconds=5), location)

    client = RecipientClient()
    monkeypatch.setattr(anis_sample, "_signer", lambda _settings: object())
    monkeypatch.setattr(anis_sample, "AnisPartnersClient", lambda *args, **kwargs: client)
    output = io.StringIO()
    assert (
        main(
            ["direct-fix-recipient", str(operation), "--recipient", "OptionalField="],
            settings={"Authority": "https://partners.example"},
            output=output,
        )
        == 0
    )
    assert len(client.calls) == 1
    assert client.calls[0][0] == "update_recipient"
    request = client.calls[0][1]["request"]
    assert isinstance(request, UpdateDirectRechargeRecipientRequest)
    assert request.to_json() == {"recipient": [{"key": "OptionalField", "value": ""}]}
    lines = output.getvalue().splitlines()
    assert f"Location={location}" in lines[-1]
    assert f"direct-status {operation}" in lines[-1]
    assert json.loads("\n".join(lines[:-1])) == {
        "operationId": str(operation),
        "operationType": "directRecharge",
        "status": "processing",
    }
