# Console sample

This small CLI uses the synchronous client and an owner-only PEM key file. It reads a JSON settings file and allows the deployment environment to override the connection and key settings.

Example `settings.json`:

```json
{
  "AnisPartners": {
    "Authority": "https://<authority Anis gave you>",
    "key_file": "/secure/anis/partner-key.pem",
    "key_id": "<active key id>",
    "orders_folder": "/secure/anis/orders"
  }
}
```

Environment overrides are `ANIS_PARTNERS_AUTHORITY`, `SAMPLE_KEY_FILE`, `SAMPLE_KEY_ID`, and `SAMPLE_ORDERS_FOLDER`. Do not put private-key contents, enrollment tokens, or card codes in the settings file.

```bash
uv run python samples/console/anis_sample.py help
uv run python samples/console/anis_sample.py --settings settings.json profile
uv run python samples/console/anis_sample.py --settings settings.json profile --dry-run
```

The sample includes `enrol`, `enrol-status`, `tour`, `profile`, `wallets`, `wallet`, `categories`, `subcategories`, `subcategory`, `cards`, `order`, `resume`, `order-status`, `owned`, `owned-card`, `reveal`, `reveal-invoice`, `diagnostic`, and `signing-keys`. List commands use their all-page iterator unless the command explicitly says it reads one page.

For `order`, use `order <wallet> <subcategory> <card> <qty> [--reference r] [--use-allowed-debt] [--operation <uuid>] [--expected-unit-price <amount>]`. The sample reads the selected card's `unit_price` from that wallet's catalogue, calculates the exact total, and writes the operation id and request to the orders folder before sending. `--expected-unit-price` replaces the catalogue price in the request body, so Anis checks that exact price while placing the order. `resume` reloads the saved id and body. Unknown outcomes say to resume after the suggested delay with the same operation id; never use a new id. The owner-only journal stores returned codes after a verified completion so they survive a process restart; never copy that file into logs or shared support folders. A production integration should persist the intent with its own order row in one database transaction and store returned codes in its protected credential store.

Every network command accepts `--dry-run`. It uses an in-memory `httpx.MockTransport`, prints the prepared request method, URL, header names, and body, and stops before any network send. Since an order preview cannot fetch a catalogue answer, pass `--expected-unit-price` for `order --dry-run`; it uses the configured currency (default `LYD`) and does not save an order intent. `enrol --invitation <id> --token <token> [--key-file f] [--days N]` generates its preview key in memory and never creates a key file; a real enrollment writes the PEM first with mode `0o600`. The output never prints signature values, signature bases, key bytes, or enrollment token values. The sample masks card codes in displayed response models.

`enrol-status --invitation <id> --token <token>` reads enrollment approval state. A real `enrol` creates the P-256 PEM with mode `0o600` before submitting its public JWK. It prints the assigned key id and safety code so the technical contact can read the code to Anis staff during the confirmation call. Do not overwrite a key file during enrollment.
