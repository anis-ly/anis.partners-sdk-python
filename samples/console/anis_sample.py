"""Small command-line integration that exercises the synchronous Partner SDK."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO, cast
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from anis_partners import (
    AnisApiError,
    AnisEnrollmentClient,
    AnisPartnersClient,
    AnisPartnersError,
    ClientOptions,
    CreateOrderRequest,
    EnrollmentKeyRequest,
    HttpSigningKeySource,
    Money,
    OrderCompleted,
    OrderNotPlaced,
    OrderOutcomeUnknown,
    OrderProcessing,
    OrderReplayed,
    OrderStatus,
    PemP256Signer,
    RequestSigner,
    UnverifiableResponseError,
)


class _DryRunFinished(BaseException):
    """Stop at the in-memory transport after showing a fully prepared request."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise Anis Partner API operations.")
    parser.add_argument("--settings", type=Path, help="JSON settings file; environment variables override it.")
    commands = parser.add_subparsers(dest="command")

    def add(
        name: str, help_text: str, *arguments: tuple[str, Callable[[str], object] | None]
    ) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--dry-run", action="store_true", help="show the signed request and send nothing")
        command.add_argument("--show-secrets", action="store_true", help="print revealed card codes in full")
        for argument, converter in arguments:
            if converter is None:
                command.add_argument(argument)
            else:
                command.add_argument(argument, type=converter)
        return command

    add("profile", "read the application profile")
    add("wallets", "list every granted wallet")
    add("wallet", "read one wallet", ("wallet_id", UUID))
    add("categories", "list one page of categories", ("wallet_id", UUID))
    add(
        "subcategories",
        "list one page of subcategories",
        ("wallet_id", UUID),
        ("category_id", UUID),
    )
    add("subcategory", "read a subcategory", ("wallet_id", UUID), ("subcategory_id", UUID))
    add(
        "cards",
        "list one page of wallet-priced cards",
        ("wallet_id", UUID),
        ("subcategory_id", UUID),
    )
    order = add(
        "order",
        "record an order intent, then place it",
        ("wallet_id", UUID),
        ("subcategory_id", UUID),
        ("card_id", UUID),
        ("quantity", int),
        ("--operation", UUID),
        ("--reference", None),
        ("--expected-unit-price", _decimal_argument),
    )
    order.add_argument("--use-allowed-debt", action="store_true")
    add("resume", "resume a saved order with its same id and body", ("operation_id", UUID))
    add("order-status", "read an order state", ("operation_id", UUID))
    add("owned", "list masked owned cards", ("wallet_id", UUID))
    add("owned-card", "read one masked owned card", ("wallet_id", UUID), ("sold_card_id", UUID))
    add("reveal", "explicitly reveal one card code", ("wallet_id", UUID), ("sold_card_id", UUID))
    add(
        "reveal-invoice",
        "explicitly reveal all codes for an invoice",
        ("wallet_id", UUID),
        ("invoice_id", UUID),
    )
    add("diagnostic", "run the signature self-check")
    add("signing-keys", "fetch the public signing-key document")
    enrol = add("enrol", "create and prove a P-256 enrollment key")
    enrol.add_argument("--invitation", type=UUID, required=True, metavar="<id>")
    enrol.add_argument("--token", required=True, metavar="<token>")
    enrol.add_argument("--key-file", metavar="f")
    enrol.add_argument("--days", type=int, default=365, metavar="N")
    status = add("enrol-status", "read enrollment approval state")
    status.add_argument("--invitation", type=UUID, required=True, metavar="<id>")
    status.add_argument("--token", required=True, metavar="<token>")
    add("tour", "walk the read routes using returned ids")
    commands.add_parser("help", help="show sample commands")
    return parser


def _settings(args: argparse.Namespace, supplied: dict[str, object] | None) -> dict[str, object]:
    settings = dict(supplied or {})
    path = args.settings or (Path(os.environ["SAMPLE_SETTINGS_FILE"]) if "SAMPLE_SETTINGS_FILE" in os.environ else None)
    if path is not None:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("The sample settings file must contain a JSON object.")
        settings.update(loaded)
    section = settings.get("AnisPartners", settings)
    if not isinstance(section, dict):
        raise ValueError("AnisPartners settings must be a JSON object.")
    result = dict(section)
    environment = {
        "ANIS_PARTNERS_AUTHORITY": "Authority",
        "SAMPLE_KEY_FILE": "key_file",
        "SAMPLE_KEY_ID": "key_id",
        "SAMPLE_ORDERS_FOLDER": "orders_folder",
    }
    result.update({key: os.environ[var] for var, key in environment.items() if var in os.environ})
    return result


def _safe_value(value: object, show_secrets: bool = False) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _safe_value(asdict(cast(Any, value)), show_secrets)
    if isinstance(value, dict):
        return {
            key: _mask_secret(str(item))
            if key.casefold() in {"voucher", "serial_number", "serialnumber"} and not show_secrets
            else _safe_value(item, show_secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, show_secrets) for item in value]
    if isinstance(value, (UUID, datetime, Decimal, timedelta)):
        return str(value)
    return value


def _show(value: object, output: TextIO, *, show_secrets: bool = False) -> None:
    print(json.dumps(_safe_value(value, show_secrets), indent=2, default=str), file=output)


def _mask_secret(value: str) -> str:
    """Keep the last two characters recognizable so operators can match a code without exposing it."""
    return "*" * max(0, len(value) - 2) + value[-2:]


def _decimal_argument(value: str) -> Decimal:
    """Turn malformed command-line prices into one argparse line instead of a Decimal traceback."""
    try:
        return Decimal(value)
    except Exception:
        raise argparse.ArgumentTypeError("expected a decimal price") from None


def _refusal_line(error: AnisPartnersError, *, order: bool = False) -> str:
    """Show the stable refusal facts needed to decide whether a recorded answer can be resumed."""
    if not isinstance(error, AnisApiError):
        return "REFUSED code=unknown status=0 request_id=none retryable=False recorded_answer=no"
    recorded = "yes" if error.is_replayed else "no"
    retryable = "yes" if error.is_retryable else "no"
    request_id = error.request_id or "-"
    return (
        f"{('NOT PLACED' if order else 'REFUSED')} code={error.raw_code} "
        f"status={error.status} request_id={request_id} "
        f"retryable={retryable} recorded_answer={recorded}"
    )


def _show_order_outcome(result: object, operation_id: UUID, output: TextIO) -> None:
    """Print the recovery state directly so a partner can act without interpreting a JSON dump."""
    if isinstance(result, OrderCompleted):
        if result.codes_withheld:
            print(
                f"COMPLETED, CODES WITHHELD — do not buy again; contact support@anis.ly with operation {operation_id}",
                file=output,
            )
        else:
            print(f"COMPLETED operation {operation_id}", file=output)
    elif isinstance(result, OrderProcessing):
        if result.order.status is OrderStatus.RECOVERY_EXHAUSTED:
            print(
                f"RECOVERY EXHAUSTED operation {operation_id}; keep the same id and resume slowly; "
                f"contact support@anis.ly with operation {operation_id}",
                file=output,
            )
            return
        print(
            f"PROCESSING operation {operation_id}; resume {operation_id} after "
            f"{int(result.retry_after.total_seconds())} s",
            file=output,
        )
    elif isinstance(result, OrderReplayed):
        print(f"REPLAYED operation {operation_id}", file=output)
    elif isinstance(result, OrderNotPlaced):
        print(_refusal_line(result.refusal, order=True), file=output)
    elif isinstance(result, OrderOutcomeUnknown):
        print(
            f"UNKNOWN operation {operation_id}; resume {operation_id} after "
            f"{int(result.suggested_delay.total_seconds())} s",
            file=output,
        )


def _dry_transport(output: TextIO) -> httpx.MockTransport:
    def intercept(request: httpx.Request) -> httpx.Response:
        print(f"DRY RUN — not sent\n→ {request.method} {request.url}", file=output)
        print("  headers: " + ", ".join(sorted(request.headers.keys())), file=output)
        body = request.content
        print("  (no body)" if not body else "  " + body.decode("utf-8"), file=output)
        raise _DryRunFinished()

    return httpx.MockTransport(intercept)


def _signer(settings: dict[str, object]) -> RequestSigner:
    key_file = settings.get("key_file")
    key_id = settings.get("key_id")
    if not isinstance(key_file, str) or not isinstance(key_id, str):
        raise ValueError("Set SAMPLE_KEY_FILE and SAMPLE_KEY_ID or add key_file and key_id to settings.")
    return PemP256Signer.from_pem_file(key_file).for_key(key_id)


def _journal_path(settings: dict[str, object], operation_id: UUID) -> Path:
    folder = Path(str(settings.get("orders_folder", "./anis-orders")))
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{operation_id}.json"


def _record_intent(path: Path, wallet_id: UUID, request: CreateOrderRequest) -> None:
    if path.exists():
        raise ValueError(f"Intent {path.stem} already exists; resume that order instead of placing it again.")
    document = {"wallet_id": str(wallet_id), "operation_id": path.stem, "request": request.to_json()}
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        Path(temporary).unlink()
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)
        raise


def _record_result(path: Path, result: object) -> None:
    """Save one verified outcome with a restrictive journal file so completion codes survive a restart."""
    record = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(result, OrderCompleted):
        record["outcome"] = "completed-withheld" if result.codes_withheld else "completed"
        if result.credentials:
            stored = record.get("credentials", [])
            if not isinstance(stored, list):
                stored = []
            record["credentials"] = [*stored, *(credential.to_json() for credential in result.credentials)]
    elif isinstance(result, OrderProcessing):
        record["outcome"] = "processing"
    elif isinstance(result, OrderReplayed):
        if "credentials" not in record:
            record["outcome"] = "replayed"
    elif isinstance(result, OrderNotPlaced):
        record["outcome"] = "not-placed"
        record["error_code"] = result.refusal.raw_code if isinstance(result.refusal, AnisApiError) else "unknown"
    elif isinstance(result, OrderOutcomeUnknown):
        if "credentials" not in record:
            record["outcome"] = "unknown"
            record["cause_type"] = type(result.cause).__name__
    _atomic_private_json(path, record)


def _atomic_private_json(path: Path, value: object) -> None:
    """Replace the journal atomically so a crash cannot truncate its operation id or delivered codes."""
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        Path(temporary).unlink(missing_ok=True)
        raise


def _run_command(
    args: argparse.Namespace, settings: dict[str, object], output: TextIO, transport: httpx.BaseTransport | None
) -> int | None:
    authority = str(settings.get("Authority", settings.get("authority", "")))
    if not authority:
        raise ValueError("Set ANIS_PARTNERS_AUTHORITY or Authority in the settings file.")
    client_options = ClientOptions.from_mapping(settings)
    http = httpx.Client(transport=transport) if transport is not None or args.command == "tour" else None
    signer = None if args.command in {"enrol", "enrol-status", "signing-keys"} else _signer(settings)
    try:
        if args.command in {"enrol", "enrol-status"}:
            http = http or httpx.Client()
            with AnisEnrollmentClient(authority, args.invitation, args.token, http_client=http) as enrollment:
                if args.command == "enrol-status":
                    _show(enrollment.get_status(), output)
                    return None
                configured_key_file = args.key_file or settings.get("key_file")
                if not args.dry_run and (not isinstance(configured_key_file, str) or not configured_key_file):
                    raise ValueError("Set --key-file or SAMPLE_KEY_FILE before enrolling a key.")
                key_path = Path(configured_key_file) if isinstance(configured_key_file, str) else None
                if not args.dry_run and key_path is not None and key_path.exists():
                    raise ValueError(f"{key_path} already exists; enrollment creates a new private key.")
                if not args.dry_run and key_path is not None:
                    key_path.parent.mkdir(parents=True, exist_ok=True)
                private_key = ec.generate_private_key(ec.SECP256R1())
                pem = private_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
                if not args.dry_run and key_path is not None:
                    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(pem)
                local_signer = PemP256Signer.from_pem(pem)
                now = datetime.now(UTC)
                submitted = enrollment.submit_key(
                    EnrollmentKeyRequest(local_signer.public_jwk(), now, now + timedelta(days=args.days))
                )
                status = enrollment.prove(submitted, local_signer)
                _show(status, output)
                if status.proof_state != "accepted":
                    print("ENROLLMENT PROOF NOT ACCEPTED; ask Anis staff to restart enrollment.", file=output)
                    return 2
                print(f"key id: {submitted.key_id}\nSafety code: {submitted.safety_code}", file=output)
            return None

        if args.command == "signing-keys":
            http = http or httpx.Client()
            source = HttpSigningKeySource(http, authority, client_options.signing_key_cache_seconds)
            _show(source.get(), output)
            return None

        if signer is None:
            raise ValueError("A signing key is required for this command.")
        with AnisPartnersClient(client_options, signer, http_client=http) as anis:
            command = args.command
            if command == "profile":
                _show(anis.profile.get(), output)
            elif command == "wallets":
                _show(list(anis.wallets.list()), output)
            elif command == "wallet":
                _show(anis.wallets.get(args.wallet_id), output)
            elif command == "categories":
                _show(anis.catalogue.list_categories_page(args.wallet_id), output)
            elif command == "subcategories":
                _show(anis.catalogue.list_subcategories_page(args.wallet_id, args.category_id), output)
            elif command == "subcategory":
                _show(anis.catalogue.get_subcategory(args.wallet_id, args.subcategory_id), output)
            elif command == "cards":
                _show(anis.catalogue.list_cards_page(args.wallet_id, args.subcategory_id), output)
            elif command == "owned":
                _show(list(anis.owned_cards.list(args.wallet_id)), output)
            elif command == "owned-card":
                _show(anis.owned_cards.get(args.wallet_id, args.sold_card_id), output)
            elif command == "reveal":
                _show(
                    anis.owned_cards.reveal(args.wallet_id, args.sold_card_id), output, show_secrets=args.show_secrets
                )
            elif command == "reveal-invoice":
                _show(
                    anis.owned_cards.reveal_invoice(args.wallet_id, args.invoice_id),
                    output,
                    show_secrets=args.show_secrets,
                )
            elif command == "diagnostic":
                _show(anis.diagnostics.check_signature(), output)
            elif command == "order-status":
                _show(anis.orders.get(args.operation_id), output)
            elif command == "order":
                if args.dry_run and args.expected_unit_price is not None:
                    # An offline preview needs the caller's explicit price and configured currency.
                    price = Money(args.expected_unit_price, str(settings.get("currency", "LYD")))
                else:
                    card = next(
                        (
                            item
                            for item in anis.catalogue.list_cards(args.wallet_id, args.subcategory_id)
                            if item.id == args.card_id
                        ),
                        None,
                    )
                    if card is None or card.unit_price is None:
                        raise ValueError("The card was not found at a price for this wallet.")
                    price = card.unit_price
                if args.expected_unit_price is not None:
                    price = Money(args.expected_unit_price, price.currency)
                request = CreateOrderRequest(
                    args.card_id,
                    args.quantity,
                    price,
                    price.multiply(args.quantity),
                    args.reference,
                    args.use_allowed_debt,
                )
                operation_id = args.operation or uuid4()
                path: Path | None = None
                if not args.dry_run:
                    path = _journal_path(settings, operation_id)
                    _record_intent(path, args.wallet_id, request)  # durable intent precedes the order request
                    print(f"Intent recorded at {path}; operation id {operation_id}", file=output)
                result = anis.orders.create(wallet_id=args.wallet_id, operation_id=operation_id, order=request)
                if path is not None:
                    _record_result(path, result)
                _show_order_outcome(result, operation_id, output)
                if not isinstance(result, OrderNotPlaced):
                    if not isinstance(result, OrderOutcomeUnknown):
                        _show(result, output)
                else:
                    return 2
            elif command == "resume":
                path = _journal_path(settings, args.operation_id)
                saved = json.loads(path.read_text(encoding="utf-8"))
                operation_id = UUID(saved["operation_id"])
                if operation_id != args.operation_id:
                    raise ValueError("The journal operation id does not match the requested resume id.")
                request = CreateOrderRequest.from_json(saved["request"])
                result = anis.orders.resume(
                    wallet_id=UUID(saved["wallet_id"]), operation_id=operation_id, order=request
                )
                _record_result(path, result)
                _show_order_outcome(result, operation_id, output)
                if not isinstance(result, OrderNotPlaced):
                    if not isinstance(result, OrderOutcomeUnknown):
                        _show(result, output)
                else:
                    return 2
            elif command == "tour":
                _show(anis.profile.get(), output)
                wallets = list(anis.wallets.list())
                _show(wallets, output)
                if wallets:
                    wallet_id = wallets[0].id
                    _show(anis.wallets.get(wallet_id), output)
                    categories = anis.catalogue.list_categories_page(wallet_id)
                    _show(categories, output)
                    if categories.items:
                        subs = anis.catalogue.list_subcategories_page(wallet_id, categories.items[0].id)
                        _show(subs, output)
                        if subs.items:
                            subcategory_id = subs.items[0].id
                            _show(anis.catalogue.get_subcategory(wallet_id, subcategory_id), output)
                            _show(anis.catalogue.list_cards_page(wallet_id, subcategory_id), output)
                    _show(list(anis.owned_cards.list(wallet_id)), output)
                _show(anis.diagnostics.check_signature(), output)
                source_http = http if http is not None else anis._http
                source = HttpSigningKeySource(source_http, authority, client_options.signing_key_cache_seconds)
                _show(source.refresh(), output)
            else:
                raise ValueError("Choose a command; run the sample with 'help' to list them.")
        return None
    finally:
        if http is not None:
            http.close()


def main(
    argv: list[str] | None = None,
    *,
    settings: dict[str, object] | None = None,
    output: TextIO | None = None,
) -> int:
    """Run a sample command; injected output and settings make the CLI easy to exercise without a service."""
    stream = output or sys.stdout
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in {None, "help"}:
        parser.print_help(file=stream)
        return 0
    try:
        config = _settings(args, settings)
        transport = _dry_transport(stream) if args.dry_run else None
        result = _run_command(args, config, stream, transport)
    except _DryRunFinished:
        return 0
    except AnisApiError as error:
        print(_refusal_line(error), file=stream)
        return 2
    except UnverifiableResponseError as error:
        print(f"UNVERIFIABLE reason={error.failure.value}; response discarded", file=stream)
        return 3
    except Exception as error:
        print(f"ERROR {type(error).__name__}", file=stream)
        return 1
    return result or 0


if __name__ == "__main__":
    raise SystemExit(main())
