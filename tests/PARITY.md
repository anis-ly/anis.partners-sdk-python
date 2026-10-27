`tests/conformance/test_request_vectors.py::test_request_vector_reproduces_base_and_signature` → proves the request signature base and bytes match the request vectors.

`tests/conformance/test_response_vectors.py::test_sync_verifier_reaches_each_declared_vector_outcome` and `test_async_verifier_reaches_each_declared_vector_outcome` → prove sync and async response verification match each declared vector result.

`tests/conformance/test_safety_code_vectors.py::test_safety_code_vector_has_expected_thumbprint_and_code` and `tests/conformance/test_enrollment_proof_vectors.py::test_enrollment_vector_builds_and_signs_exact_proof_message` → prove safety codes and enrollment proofs match their vectors.

`tests/conformance/test_contract_drift.py::test_sdk_route_table_matches_published_surface_in_both_directions`, `test_each_route_has_the_profile_assigned_by_the_contract`, `test_generated_error_codes_equal_the_generator_output`, and `test_generated_error_status_and_guidance_match_the_catalogue` → prove routes, signing profiles, and generated error metadata track the contracts.

`tests/operations/test_signed_wire_capture.py::test_client_signatures_verify_over_the_requests_actually_sent` → proves signatures cover the final HTTPX URL and body for paging, reveal, diagnostics, and ordering.

`tests/operations/test_pipeline.py::test_sync_order_preflight_guards_run_before_both_order_calls` and `test_async_order_preflight_guards_run_before_both_order_calls` → prove invalid quantities and prices fail before requests on create and resume for both clients.

`tests/operations/test_pipeline.py::test_sync_door_refusals_keep_create_and_resume_unknown` and `test_async_door_refusals_keep_create_and_resume_unknown` → prove access-boundary refusals remain recoverable on create and resume.

`tests/operations/test_pipeline.py::test_sync_order_credentials_survive_key_cache_faults` and `test_async_order_credentials_survive_key_cache_faults` → prove completed orders retain credentials through cache failures and slow or hanging hooks.

`tests/operations/test_pipeline.py::test_sync_wallet_iteration_refuses_a_nonadjacent_cursor_cycle` and `test_async_wallet_iteration_refuses_a_nonadjacent_cursor_cycle` → prove A-to-B-to-A cursor cycles stop in both clients.

`tests/operations/test_pipeline.py::test_sync_wallet_iteration_follows_cursor_pages`, `test_async_wallet_iteration_follows_cursor_pages`, `test_catalogue_cards_iterate_all_cursor_pages`, `test_catalogue_categories_and_subcategories_iterate_all_cursor_pages`, `test_owned_cards_iterate_all_cursor_pages`, and `test_async_catalogue_and_owned_card_iterators_yield_nonempty_later_pages` → prove nonempty later pages are yielded.

`tests/errors/test_error_mapping.py::test_retry_after_accepts_decimal_seconds_by_value` → proves Retry-After accepts leading-zero digits and enforces the numeric bound.

`tests/verification/test_http_signing_key_source.py::test_key_document_fetch_failures_use_the_sdk_error_and_bounded_transport_reason` and `tests/verification/test_async_http_signing_key_source.py::test_async_key_document_fetch_failures_use_the_sdk_error_and_bounded_transport_reason` → prove key-document HTTP, transport, timeout, malformed-document, and corrupt-gzip failures use the SDK error type with a bounded connection or timeout classification.

`tests/verification/test_async_http_signing_key_source.py::test_async_cache_that_swallows_cancellation_cannot_hold_fetch_or_refresh_lock` → proves cancellation-resistant async cache hooks cannot pin key verification.

`tests/observability/test_signals.py::test_no_secret_reaches_any_captured_telemetry_signal` and `test_signer_secret_in_exception_never_reaches_span_event_or_status` → prove real key, signature input, nonce, token, voucher, and serial sentinels stay out of telemetry.

`tests/observability/test_signals.py::test_key_document_http_failure_is_a_connection_type_unknown_metric` and `test_key_document_timeout_is_a_timeout_type_unknown_metric` → prove key-fetch failures carry connection or timeout reason on unknown order metrics.

`tests/observability/test_signals.py::test_signing_event_includes_the_selected_key_id` → proves the signing event names the selected key id.

`tests/enrollment/test_client.py::test_async_enrollment_stops_on_a_mismatched_key_thumbprint`, `test_async_enrollment_proves_the_submitted_key_generation`, and `test_async_enrollment_refusal_remains_a_typed_refusal` → prove async enrollment key matching, proof submission, and refusal handling.

`tests/enrollment/test_client.py::test_enrollment_client_rejects_tokens_outside_visible_ascii_without_exposing_them` → proves sync and async enrollment clients refuse unsafe header tokens without exposing them through messages or exception chains.

`tests/models/test_money.py::test_money_refuses_more_than_three_decimal_places_in_the_constructor`, `test_money_refuses_more_than_three_decimal_places_on_the_wire`, and `test_money_pads_allowed_scale_without_rounding` → prove money keeps exact values up to three decimal places.

`tests/sample/test_sample.py::test_enrol_dry_run_creates_key_in_memory_without_writing_file`, `test_enrollment_proof_must_be_accepted`, `test_withheld_completion_merges_supplied_credentials`, `test_withheld_completion_adds_credentials_when_journal_list_is_empty`, `test_withheld_completion_retains_stored_credentials_when_answer_has_none`, and `test_sample_commits_private_intent_before_the_order_call` → prove sample enrollment and journal safety.

`tests/docs/test_python_markdown_blocks.py::test_every_markdown_python_block_type_checks` → proves README and guide Python blocks type-check against the package.

`tests/errors/test_exception_roundtrip.py` → proves public SDK errors and order results containing errors survive copy, deepcopy, and pickle operations.

`tests/operations/test_selective_signing.py::test_answer_signing_is_set_per_route_exactly_as_the_gateway_publishes`, the sync and async `information_route_reads_its_unsigned_answer`, `unsigned_information_refusal_maps_to_its_typed_error`, and `signed_route_without_a_signature_is_refused` tests, and the unsigned order and enrollment tests → prove the information reads are read unsigned (with no key fetch) while every signed route, success or refusal, still fails with `signature_missing` when unsigned.

`tests/verification/test_response_key.py` verifies the v2 tag, raw request-signature binding, compromise precedence without refresh, and retirement/activation boundaries in both clients using fresh signed fixtures. `tests/operations/test_access.py` verifies self-service stop bodies, nonce profiles, state models, reason guards, and the current user agent.

`tests/verification/test_response_key.py::test_any_published_key_used_before_not_before_is_not_yet_valid_in_both_verifiers` → proves every published status rejects pre-activation signatures and accepts the activation instant in both verifiers.

`tests/configuration/test_options.py::test_cache_lifetime_longer_than_five_minutes_is_refused` and the sync/async key-source cache-lifetime tests → prove default trust lasts five minutes and longer settings are refused.

The sync/async `shared_entry_expires_five_minutes_after_its_original_fetch` tests → prove transferring a shared key document never restarts its age.

`tests/verification/test_http_signing_key_source.py::test_unknown_key_refetch_happens_at_most_once_per_thirty_seconds_including_failures` and `tests/verification/test_async_http_signing_key_source.py::test_async_unknown_key_refetch_happens_at_most_once_per_thirty_seconds` → prove both successful and failed refreshes start the same 30-second cooldown; the existing concurrent refresh tests prove callers share one fetch.

`.NET OrderOutcomeTests.A_spending_capped_order_is_not_placed_and_carries_the_signed_retry_after` → `tests/operations/test_pipeline.py::test_spending_capped_order_is_not_placed_and_carries_the_signed_retry_after` and its async counterpart prove a signed spending refusal returns `OrderNotPlaced` with `LimitExceededError`, the verified window reset, and no automatic retry.

`tests/operations/test_meter_charges.py`, `test_direct_recharges.py`, `test_direct_recharge_products.py`, `test_webhook_endpoint.py` and `test_webhook_events.py` (each run against the sync and async clients) → prove the product routes sign exact bytes, keep the caller's operation id through `resume`, classify Processing, Final, NotPlaced and OutcomeUnknown without inventing results, preserve filters and cursors, and never retry signed changes. `test_meter_resume_keeps_the_original_operation_id`, `test_circle_patch_signs_recipient_bytes_without_idempotency` and `test_sdk_maps_simulated_59_60_61_second_gateway_responses` pin SDK response mapping and recovery. The simulated age cases do not prove the gateway clock or duplicate-first behavior.

`tests/models/test_product_models.py` → proves the product read bodies, summaries and the three-member processing answers parse and serialize their exact wire members, including negative-safe money strings, `for`, and explicit nulls.

`tests/conformance/test_webhook_vectors.py::test_sync_verifier_reaches_each_declared_vector_outcome` and `test_async_verifier_reaches_each_declared_vector_outcome` → prove both webhook verifiers reach the declared reason and phase of every vector in the shared corpus copied byte-identically into `tests/vectors/webhook/`, and parse accepted envelopes with exact data preserved; `test_corpus_is_present_exhaustive_and_matches_its_manifest` pins the manifest counts, phases and the closed reason vocabulary.

`tests/verification/test_webhook_verifier.py` → proves the suspended-with-current-`inProgress` case, unknown-type preservation, raw-byte digest binding, configured URL and application authority, key refresh behaviour, the pure verifier, and the additive key `purpose` member.

`tests/models/test_product_optional_fields.py` derives every optional field case from the published schemas for all new model modules, checks omitted and null members, and asserts absence without defaults. Product getter tests cover each independent limit; create/PATCH/recovery tests preserve empty recipients and missing labels.

`tests/verification/test_webhook_verifier.py` also verifies omitted/null receipt metadata and recipient labels after signing, and rejects oversized attempt/created/expires headers with the exact structured reason in sync, async and pure verification.

`tests/sample/test_webhook_receiver.py` sends signed requests over local HTTP, proves failed handling remains pending across a database reopen, startup recovery, successful deduplication, exact raw target checking and verification before challenge echo.

The final gateway contract marks exactly the three named network exclusions with `x-anis-availability: staging-only` and keeps signing-key `purpose` optional. Contract tests pin those declarations. Response-key tests cover emitted/omitted purpose through serialization and both verifiers. Recipient PATCH tests require a signed 202 acknowledgement plus Location, explicit subsequent reads, rejection of 200 exchange bodies and missing/empty Location, and rejection of malformed bodies or missing/bad signatures, without automatic retries. Status and Location tampering are verified refusals. The acknowledgement body remains exactly three members; the same `DirectRechargeProcessing` result as a 202 create carries it in `recharge`, with Location and Retry-After mapped as existing response metadata. Exact-type tests cover default, zero and nonzero delays in both clients.

Webhook corpus: 75 vectors (20 accept, 55 reject), 76 JSON files including manifest; SHA-256 of the sorted per-file shasum listing is `a598d6a274516bc28e4afadf40978048a99bea0f604d84140229494739fc3cfa`. Corpus tests pin the file count, manifest coverage and aggregate hash. Timestamp vectors cover missing time/seconds/offset, offset precision and a 100 ns activation boundary; fractional activation remains refused after key serialization.
