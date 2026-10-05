# Python parity — stages A, B1, and B2

Source: .NET SDK 1.3.0 test methods listed in the shared parity table. The string-valued Python error enum cannot preserve C# numeric enum values; its replacement row checks that the generated file exactly matches the error catalogue. Python clients are constructed directly instead of registered through a .NET dependency-injection container, so container-only rows are marked n/a.

## ConfigurationTests

| .NET test | Python |
|---|---|
| `Options_bind_from_the_AnisPartners_section` | test_options_bind_from_the_anis_partners_section |
| `Code_can_adjust_what_the_file_says` | n/a — Python options are frozen values; the host supplies overrides when constructing or mapping the settings |
| `A_settings_file_that_cannot_work_fails_at_startup` | test_invalid_authority_or_lifetime_is_rejected_at_construction + test_nonpositive_timeouts_and_cache_lifetimes_are_refused |
| `A_registration_without_a_signer_says_so_when_the_client_is_resolved` | n/a — direct Python construction requires the signer argument before a client exists |
| `The_hosts_own_clock_is_kept` | test_host_clock_and_nonce_factory_are_used_for_signed_requests |
| `The_hosts_own_nonce_source_is_kept` | test_host_clock_and_nonce_factory_are_used_for_signed_requests |
| `A_named_application_never_borrows_an_unnamed_signer` | n/a — Python has no named service registrations; each client receives its signer explicitly |
| `Registering_twice_without_a_name_is_refused_at_startup` | n/a — Python has no service-registration container |
| `A_name_can_be_registered_once` | n/a — Python has no named service registrations |
| `Named_applications_each_sign_with_their_own_key_at_their_own_authority` | n/a — separate Python client instances carry their own authority and signer |
| `Each_named_application_verifies_with_the_keys_of_its_own_authority` | n/a — each client constructs its key source from its own authority |
| `Create_builds_a_signed_and_verified_client_without_a_container` | test_sync_profile_is_signed_and_returns_only_verified_data |
| `An_unnamed_and_a_named_application_live_side_by_side` | n/a — Python has no named service registrations |
| `An_unknown_name_says_which_names_exist` | n/a — Python has no named service lookup |
| `A_named_application_without_a_signer_names_itself_in_the_failure` | n/a — Python construction requires an explicit signer |

## ConnectionRotationTests

| .NET test | Python |
|---|---|
| `Calls_after_the_handler_lifetime_go_out_on_fresh_connections` | n/a — the SDK takes ownership only of clients it creates; httpx connection rotation has no SDK lifetime knob |

## ContractDriftTests

| .NET test | Python |
|---|---|
| `The_sdk_route_table_matches_the_published_surface_exactly` | test_sdk_route_table_matches_published_surface_in_both_directions |
| `Every_route_signs_under_the_profile_the_contract_assigns_it` | test_each_route_has_the_profile_assigned_by_the_contract |
| `Every_public_error_code_in_the_catalogue_is_known_to_the_sdk` | test_every_public_error_code_in_the_catalogue_is_known_to_the_sdk |
| `The_key_submission_answer_model_carries_exactly_the_published_members` | test_key_submission_answer_model_has_exactly_the_published_members |
| `A_released_error_code_keeps_its_number` | test_generated_error_codes_equal_the_generator_output (string-code substitution; see note below) |
| `The_covered_component_profiles_match_the_contracts_description` | test_covered_component_profiles_match_the_contract_description |

## EnrollmentTests

| .NET test | Python |
|---|---|
| `The_sdk_builds_the_proof_Commands_verifies` | test_enrollment_vector_builds_and_signs_exact_proof_message [2 parametrized vectors] |
| `A_der_signature_is_refused_before_it_reaches_Anis` | test_enrollment_proof_refuses_non_p1363_signatures_before_sending |
| `A_key_on_another_curve_is_refused` | test_incomplete_or_other_curve_jwks_cannot_be_fingerprinted |
| `A_submission_result_without_its_challenge_cannot_be_proved` | test_unprovable_submission_stops_before_an_http_request |
| `Submit_then_prove_walks_the_enrollment_routes_and_verifies_every_answer` | test_submit_then_prove_verifies_both_unsigned_enrollment_answers |
| `A_refused_step_is_an_enrollment_exception` | test_enrollment_refusal_is_a_typed_enrollment_exception |
| `An_enrollment_call_is_measured_like_every_other_call` | test_enrollment_request_is_measured_without_recording_its_token |
| `The_status_read_carries_the_key_end_date_and_tolerates_its_absence` | test_enrollment_status_preserves_optional_key_expiry |
| `The_sdk_computes_the_thumbprint_Commands_computed` | test_submit_then_prove_verifies_both_unsigned_enrollment_answers |
| `A_jwk_that_is_not_a_complete_p256_public_key_has_no_thumbprint` | test_incomplete_or_other_curve_jwks_cannot_be_fingerprinted |
| `The_private_member_does_not_change_the_thumbprint` | test_thumbprint_ignores_private_and_noncanonical_key_members |
| `The_safety_code_is_derived_from_the_verified_thumbprint_never_taken_from_the_answer` | test_submit_key_sends_only_public_jwk_with_enrollment_authorization |
| `A_key_Anis_answers_for_with_another_thumbprint_stops_the_enrollment_before_any_proof` | test_submit_key_stops_on_a_mismatched_server_thumbprint |
| `An_answer_without_a_thumbprint_is_a_mismatch_too` | test_submit_key_stops_on_a_mismatched_server_thumbprint |
| `A_key_the_sdk_cannot_fingerprint_is_refused_before_anything_is_sent` | test_incomplete_or_other_curve_jwks_cannot_be_fingerprinted |

## ErrorMappingTests

| .NET test | Python |
|---|---|
| `Every_public_code_has_a_decision` | test_every_public_code_has_a_deliberate_decision |
| `A_code_becomes_its_decided_exception_and_outcome` | test_a_code_becomes_its_decided_error_and_order_outcome [37 parametrized cases] |
| `A_code_this_version_does_not_know_is_treated_as_an_open_order` | test_an_unknown_code_is_open_and_not_assumed_retryable |
| `A_replayed_refusal_is_a_closed_order_whatever_its_code` | test_a_replayed_refusal_is_closed_whatever_its_code [3 parametrized cases] |
| `A_signed_body_that_is_not_a_problem_is_still_a_refusal` | test_an_unreadable_problem_body_uses_the_internal_error_fallback |

## HostRetryTests

| .NET test | Python |
|---|---|
| `A_retry_handler_from_the_host_defaults_resends_one_fresh_signature_per_attempt` | test_create_does_not_retry_a_lost_answer_and_a_caller_retry_gets_a_fresh_nonce |

## ModelFieldTests

| .NET test | Python |
|---|---|
| `A_subcategory_reads_its_disclaimer` | test_subcategory_reads_its_disclaimer |
| `A_subcategory_without_a_disclaimer_has_none` | test_subcategory_without_a_disclaimer_has_none |
| `A_catalogue_card_reads_its_quantity_limits` | test_catalogue_card_reads_its_quantity_limits |
| `A_catalogue_card_without_quantity_limits_has_none` | test_catalogue_card_without_quantity_limits_has_none |
| `An_order_reads_its_reference_failure_code_and_withheld_flag` | test_order_reads_its_reference_failure_code_and_withheld_flag |
| `An_order_without_the_new_members_leaves_them_null` | test_order_without_the_new_members_leaves_them_none |
| `A_revealed_credential_reads_its_expiry_and_reveal_details` | test_revealed_credential_reads_its_expiry_and_reveal_details |
| `A_revealed_credential_without_the_new_members_leaves_them_null` | test_revealed_credential_without_the_new_members_leaves_them_none |
| `A_masked_card_reads_its_price_expiry_invoice_number_face_value_and_subcategory` | test_masked_card_reads_its_price_expiry_invoice_number_face_value_and_subcategory |
| `A_masked_card_without_the_new_members_leaves_them_null` | test_masked_card_without_the_new_members_leaves_them_none |

## ObservabilityTests

| .NET test | Python |
|---|---|
| `A_call_produces_a_span_tagged_with_the_route_TEMPLATE_not_the_path` | test_calls_emit_route_template_spans_duration_and_order_outcome |
| `Duration_and_signing_cost_are_measured_separately` | test_calls_emit_route_template_spans_duration_and_order_outcome |
| `An_order_reports_its_outcome_and_carries_the_operation_id_on_the_span` | test_calls_emit_route_template_spans_duration_and_order_outcome |
| `A_refusal_is_one_warning_carrying_the_code_and_the_request_id` | test_typed_refusal_is_verified_before_it_becomes_not_placed + test_client_uses_a_route_template_in_safe_structured_logs |
| `A_discarded_response_is_counted_by_the_rule_that_refused_it` | test_discarded_answer_records_the_verification_failure |
| `A_timed_out_order_is_a_failed_span_a_measured_call_and_an_unknown_outcome` | test_timeout_marks_span_and_order_metric_unknown |
| `A_lost_connection_on_an_order_is_counted_unknown` | test_transport_failure_leaves_order_unknown_with_original_cause |
| `An_unverifiable_order_answer_is_counted_unknown` | test_discarded_answer_records_the_verification_failure |
| `A_refusal_that_reached_no_decision_is_counted_unknown_and_a_final_one_is_not` | test_resume_refusal_without_replay_marker_remains_unknown + test_typed_refusal_is_verified_before_it_becomes_not_placed |
| `A_refusal_of_access_on_create_is_counted_unknown_and_logged` | test_create_refusal_at_access_boundary_suggests_one_minute |
| `A_failing_signer_is_named_as_such_and_is_not_an_unknown_order` | test_signer_failure_propagates_without_sending_or_counting_unknown |
| `A_verified_success_with_an_empty_body_is_counted_unknown` | test_empty_verified_success_leaves_order_unknown |
| `A_replayed_refusal_is_not_counted_as_an_unknown_order` | test_replayed_refusal_is_not_placed |
| `No_secret_reaches_any_telemetry_signal` | test_no_secret_reaches_any_captured_telemetry_signal |

## OrderOutcomeTests

| .NET test | Python |
|---|---|
| `A_201_is_completed_and_carries_the_credentials` | test_create_order_sends_exact_body_and_caller_operation_id |
| `A_completion_whose_codes_are_withheld_is_completed_with_no_credentials` | test_completion_without_credentials_is_withheld |
| `A_completion_that_says_its_codes_are_withheld_is_withheld_and_carries_the_reference` | test_completion_without_credentials_is_withheld |
| `The_withheld_flag_alone_makes_the_completion_withheld` | test_completion_withheld_flag_is_preserved_without_credentials |
| `A_completion_with_credentials_and_no_flag_is_not_withheld` | test_completed_credentials_are_not_withheld_without_a_flag |
| `A_repeat_after_completion_is_replayed_and_carries_no_credentials` | test_processing_and_replay_are_distinct_order_outcomes |
| `A_resume_that_recovers_the_completion_returns_the_credentials` | test_success_credentials_win_over_a_replayed_marker |
| `A_recorded_refusal_says_it_was_replayed_and_that_nothing_was_placed` | test_replayed_refusal_is_not_placed |
| `A_fresh_refusal_is_not_marked_replayed` | test_typed_refusal_is_verified_before_it_becomes_not_placed |
| `An_unavailable_dependency_leaves_the_order_open_for_a_resume` | test_dependency_refusal_keeps_the_order_open_for_resume |
| `A_202_is_processing_and_reports_when_to_resume` | test_processing_and_replay_are_distinct_order_outcomes |
| `A_price_change_is_not_placed_and_carries_its_typed_refusal` | test_price_change_refusal_is_final_on_a_fresh_create |
| `A_rate_limited_create_leaves_the_order_open_and_carries_the_signed_retry_after` | test_rate_limited_create_uses_the_signed_retry_after |
| `A_rate_limited_create_without_a_retry_after_suggests_the_default_delay` | test_rate_limited_create_without_retry_after_uses_five_seconds |
| `A_fresh_refusal_of_a_resume_leaves_the_order_open` | test_resume_refusal_without_replay_marker_remains_unknown |
| `A_refusal_at_the_door_on_create_leaves_the_order_open_and_suggests_a_minute` | test_create_refusal_at_access_boundary_suggests_one_minute |
| `A_refusal_at_the_door_on_resume_suggests_a_minute` | test_resume_door_refusal_without_retry_after_suggests_one_minute |
| `A_refusal_at_the_door_with_a_retry_after_suggests_that_wait` | test_door_refusal_retry_after_overrides_the_one_minute_default |
| `A_replayed_refusal_at_the_door_is_not_placed` | test_replayed_door_refusal_is_not_placed |
| `A_unit_price_that_is_not_positive_never_leaves_the_process` | test_nonpositive_price_is_rejected_before_any_request |
| `A_timeout_leaves_the_order_open_on_create_and_on_resume` | test_timeout_on_create_and_resume_keeps_the_operation_unknown |
| `An_unexpected_failure_while_sending_leaves_the_order_open` | test_unexpected_send_failure_leaves_order_unknown |
| `A_call_the_caller_cancelled_is_rethrown` | test_async_cancellation_propagates_after_counting_the_order_unknown |
| `A_verified_success_with_invalid_order_json_leaves_the_order_open` | test_invalid_verified_order_json_leaves_order_unknown |
| `A_total_that_is_not_unit_times_quantity_never_leaves_the_process` | test_mismatched_order_total_is_rejected_before_any_request |

## PagingTests

| .NET test | Python |
|---|---|
| `ListAsync_follows_the_cursor_and_signs_the_query_it_transmits` | test_async_wallet_iteration_follows_cursor_pages |
| `Owned_cards_page_the_same_way` | test_owned_cards_iterate_all_cursor_pages |
| `Catalogue_cards_page_the_same_way` | test_catalogue_cards_iterate_all_cursor_pages |
| `Catalogue_categories_and_subcategories_page_the_same_way` | test_catalogue_categories_and_subcategories_iterate_all_cursor_pages |

## PipelineBehaviourTests

| .NET test | Python |
|---|---|
| `A_safe_read_carries_a_signature_and_no_nonce_or_digest` | test_sync_profile_is_signed_and_returns_only_verified_data |
| `A_reveal_transmits_zero_body_bytes_and_digests_them` | test_reveal_sends_zero_bytes_and_diagnostic_sends_exact_empty_object |
| `An_invoice_reveal_transmits_zero_body_bytes_and_digests_them` | test_invoice_reveal_sends_zero_bytes_and_returns_the_verified_collection |
| `The_signature_self_check_transmits_exactly_an_empty_object` | test_reveal_sends_zero_bytes_and_diagnostic_sends_exact_empty_object |
| `An_order_carries_the_callers_idempotency_key` | test_create_order_sends_exact_body_and_caller_operation_id |
| `A_tampered_body_is_discarded_rather_than_returned` | test_tampered_response_body_is_discarded_before_model_parsing |
| `A_credential_never_reaches_a_log_through_ToString` | test_no_secret_reaches_any_captured_telemetry_signal |
| `Money_multiplies_exactly_and_renders_at_scale_three` | test_money_multiplies_exactly_and_clears_as_of + test_money_parses_and_writes_three_decimal_places |

## RequestVectorTests

| .NET test | Python |
|---|---|
| `The_sdk_reproduces_the_vector_base_exactly` | test_request_vector_reproduces_base_and_signature [9 parametrized vectors] |

## ResponseVectorTests

| .NET test | Python |
|---|---|
| `The_verifier_reaches_the_declared_outcome` | test_sync_verifier_reaches_each_declared_vector_outcome + test_async_verifier_reaches_each_declared_vector_outcome [39 each] |

## SafetyCodeVectorTests

| .NET test | Python |
|---|---|
| `The_key_has_the_declared_thumbprint_and_code` | test_safety_code_vector_has_expected_thumbprint_and_code [4 parametrized vectors] |
| `Every_entry_matches_or_does_not_as_declared` | test_safety_code_vector_entries_have_declared_match_results [4 parametrized vectors] |
| `The_manifest_lists_exactly_the_vectors_on_disk` | test_safety_code_manifest_lists_exactly_the_vectors_on_disk |
| `Only_a_thumbprint_has_a_safety_code` | test_only_a_thumbprint_has_a_safety_code [4 parametrized values] |

## B1 money-specific tests

| Behavior | Python test |
|---|---|
| Three-place decimal parsing and writing | `test_money_parses_and_writes_three_decimal_places` |
| JSON number refusal | `test_money_refuses_a_json_number` |
| Float constructor refusal | `test_money_refuses_a_float_constructor_value` |
| Exact integer multiplication | `test_money_multiplies_exactly_and_clears_as_of` |
| Four-place input is refused before rounding | `test_money_refuses_more_than_three_decimal_places_in_the_constructor` + `test_money_refuses_more_than_three_decimal_places_on_the_wire` |
| Negative three-place values reach the order price guard | `test_money_accepts_negative_amounts_for_order_guards_to_reject_as_prices` + `test_nonpositive_price_is_rejected_before_any_request` |
| A .NET guard case also supplies `0.0004`; its F3 serialization rounds to `0.000`, while Python refuses the amount at construction under the recorded Money ruling | `test_money_refuses_more_than_three_decimal_places_in_the_constructor` |

Total .NET methods: 110. Stage A/B1 rows: 30; B2 rows: 80 handled by Python tests or documented dependency-injection n/a entries.

## Adversarial review fixes (F1–F8 and Python Y1–Y2)

| Review behavior | Python coverage |
|---|---|
| Diagnostics cannot replace a completed order or leak signer failures to spans | `test_throwing_logger_does_not_lose_completed_order_credentials`; `test_signer_secret_is_not_recorded_on_the_span` |
| Repeated replay header values classify success and refusal as replayed | `test_repeated_replay_values_classify_success_as_replayed`; `test_repeated_replay_values_classify_refusal_as_replayed` |
| Credential, signed-header, and enrollment-token representations redact secret values | `tests/test_redaction.py` |
| Encoded responses are discarded; requests use identity encoding | `test_encoded_signed_response_is_discarded_before_parsing`; `test_sync_profile_is_signed_and_returns_only_verified_data`; sync/async key-source redirect tests |
| Redirects remain ordinary API/key-document answers | `test_redirect_from_injected_follow_redirects_client_is_not_followed`; sync/async key-source redirect tests |
| Base64 encodings are canonical and signature envelopes reject trailing bytes | `test_base64url_refuses_nonzero_unused_padding_bits`; `test_signature_with_trailing_junk_is_malformed` |
| Network authorities require HTTPS, with loopback retained for local testing | `tests/test_options.py` |
| Shared key-cache write access is a trust boundary | `docs/caching.md` states only the application and trusted operators may write the signing-key namespace |
| Only the named `created` parameter controls freshness; duplicates are refused | `test_numeric_extra_parameter_does_not_replace_created` |
| Every SDK span disables exception recording and automatic exception status | `test_signer_secret_is_not_recorded_on_the_span` |

The previous .NET behaviors that tolerated noncanonical base64, ignored trailing signature-envelope text, and accepted plain HTTP are intentionally stricter in this port per R-common F6–F7. Unknown numeric signature parameters are ignored as in .NET, but they cannot override `created`.

## Live-stack sample and exception fixes

| Behavior | Python coverage / parity note |
|---|---|
| SDK errors survive copy, deepcopy, pickle, and `dataclasses.asdict` in order results | `tests/errors/test_exception_roundtrip.py` |
| Package logging is silent by default; event 1008 directs same-id recovery | `tests/observability/test_unknown_order_message.py` |
| The sample sends an expected price override with reference and allowed-debt fields | `test_expected_unit_price_reference_and_debt_are_sent_to_order` |
| Enrollment dry-run uses an in-memory key and leaves no key file | `test_enrol_dry_run_creates_key_in_memory_without_writing_file` |
| Refusal output is a single structured line and order outcomes are printed directly | `tests/sample/test_sample.py` |

The live-stack Python sample previously used `--expected-unit-price` only while previewing; it now replaces the request's expected unit price and total on real orders. The enrollment CLI now matches the shared .NET/PHP/Node flag shape and writes a real private key before sending its public JWK. No wire contract changed.
