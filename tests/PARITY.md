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
