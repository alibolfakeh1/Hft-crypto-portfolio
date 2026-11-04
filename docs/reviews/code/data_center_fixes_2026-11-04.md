# Fixes to the data center: one row per finding

Author: `developer`. Date: 2026-11-04. Branch `pipeline/first-data-run`, working tree on top of commit `e6dd3f8`. For the recheck by `python-reviewer` and
`leak-auditor`. A writer does not approve its own work, so this file claims no verdict.

Reviews answered: [code review](data_center_2026-11-04.md), findings `F-01` to `F-23`, and the [leak audit](../leak/data_center_2026-11-04.md), findings `DC-01` to `DC-15`, its rulings and its
section 9. All data used is generated. No document outside this file was changed, so any departure from a document below still needs its owner.

Test names are in `tests/`. A name with no file prefix is in the file named at the start of its row.

## Code review

| ID | What changed | Covering test | Departure |
|---|---|---|---|
| F-01 | `guard.canonical_rel_path` refuses `..`, a backslash and an absolute path. `classify`, `Catalog.register_file` (and parents) and `delete_file` all go through it, so the class and the file come from one path | `data/test_retention.py`: traversal attack tests, the row from the review through both `execute_plan` and `--delete-raw-after-curated`. `test_ledger_files_survive_a_rule_that_really_selects_their_zone` replaces the test that passed because its zone did not match | None |
| F-02 | `delete_file(ctx, rel_path, rule, *, used_pct)` runs the whole protocol at the moment of deletion. It takes no class. `execute_plan` measures real use and re-checks each item, using nothing from the plan but its path and rule | `data/test_retention.py`: forged plan, stale plan, forged class | None |
| F-03 | Each dataset declares `max_quiet_s`. A longer silence or an id skip calls `add_gap`, sets `gap=True`, and stores `check_status=warn`. A higher bar with any gap minute has `complete=False` | `data/test_ingest.py`: `test_a_six_hour_hole_in_a_file_is_recorded_and_flagged`, `test_a_break_in_the_ids_with_no_silence_is_a_warning_and_flags_its_minutes` | The bar holding the last row before a silence is flagged only when ids skip. How long a silence lasts is known only when it ends, so otherwise that bar would depend on the future. See `test_a_quiet_stretch_cannot_reach_back_into_the_bar_before_it` |
| F-04 | `reconcile_official` rewritten. A forward path check per minute, on integer quantities, for all volume and for taker buy volume separately. Conservation across midnight against both neighbours. A day is provisional until both are known. Price is relative and fails. Fill count warns. `warn` keeps raw and leaves the day out of published statistics | `bars/test_reconcile.py`: rows B, A2, C2, D, E2, F, K by name. `data/test_ingest.py`: `test_a_damaged_file_fails_its_day_and_keeps_its_raw_data` for each row through `run_ingest`, `test_a2_...`, `test_k_...`. `reports/test_report.py`: `test_a_slipped_digit_cannot_reach_the_published_statistics`, `test_a_day_that_only_warned_is_left_out_of_results` | The first day of a dataset can never be confirmed, so an unconfirmed carry there warns and flags its first bar, and does not fail. The same applies beside a neighbour whose own path broke, since its figure for that midnight is not what crossed it. That neighbour is re-derived if the broken day recovers |
| F-05 | `zlib.error` caught in the three readers. In `_attempt`, every broken response becomes a failed attempt. Around each task in `run_ingest`, any `Exception` is recorded and quarantined and the run goes on, and the run row always finishes | `data/test_parsers.py`: corrupt zip and gzip. `data/test_ingest.py`: `test_one_corrupt_file_cannot_stop_catch_up`, `test_anything_escaping_a_task_is_contained_and_the_run_row_finishes`. `data/test_source_switches.py`: `test_every_kind_of_broken_response_is_retried_and_then_a_fetch_error` | `_attempt` catches `Exception`, not `http.client.HTTPException`, because `test_safety.py` forbids importing `http.client` from the source and I did not weaken it. `ForbiddenHostError` and `FetchError` are re-raised first |
| F-06 | Both fixes the review offers. `derive_day` sets the task `pending` before its first write, and it writes higher timeframes first and `bars_1m` last | `data/test_ingest.py`: `test_a_crash_during_a_rebuild_heals_on_the_next_run`, byte-identical to a run that never crashed, `test_a_crash_after_the_last_write_of_a_rebuild_still_finishes_the_day`, `test_a_rebuild_marks_its_task_pending_before_its_first_write` | None |
| F-07 | Emission runs only through `min(t_cut, floor_1m(newest_trade - 1))`. The cut comes from `t_poll` at the start of the attempt. A stamp ahead of the clock, or out of range, fails the page | `data/test_poll.py`: `test_an_empty_answer_is_not_a_quiet_market`, `test_a_short_page_mid_history_is_not_caught_up`, `test_a_slow_write_cannot_move_the_cut_past_the_start_of_the_attempt`, `test_a_row_stamped_ahead_of_the_clock_is_refused` | None |
| F-08 | Flags at emission come from `catalog.gaps()`, which outlives a pass. The stored rows show a skip too, since each day's window now holds the rows on either side of it, so these are two sources for one flag | `data/test_poll.py`: `test_dc01a_a_gap_found_in_a_failed_pass_flags_bars_emitted_by_a_later_pass`, `test_dc01d_a_jump_past_the_budget_still_flags_its_last_minute_in_the_next_pass`, `test_a_gap_in_the_catalog_flags_bars_whatever_the_rows_show` | None |
| F-09 | `is_finite` on every numeric column and each polled row. Fill ids must be present. Book sizes must be finite and not negative | `data/test_parsers.py`: `test_*_not_finite`, `test_empty_fill_ids_are_refused`. `data/test_poll.py`: `test_bad_responses_are_recognised`. `data/test_book_replay.py`: `test_a_size_that_cannot_be_real_is_malformed` | None |
| F-10 | `PROHIBITED_SOURCES` and `PROHIBITED_HOSTS` in code. The Binance host left `ALLOWED_HOSTS`. `check_url` takes a required list, and refuses a prohibited host first, a backslash, a user part and any port. Strict booleans, and unknown keys are errors. `find_config_dir` no longer reads the working directory | `data/test_source_switches.py`: `test_route_0` to `test_route_7`, one per row of the table, `test_netloc_tricks_are_refused`, `test_a_redirect_off_the_list_is_refused_before_anything_is_asked_of_it`, `test_a_redirect_within_the_list_is_followed_and_read` | `HFT_CONFIG_DIR` still selects another file, and that file gets every check (`test_route_5b`). Workflows do not set it |
| F-11 | A rule on a `raw/` zone needs a requirement for each kind, or it fails closed. `raw/archive` needs a `source_url`. `reviewed = "false"` is a config error. `raw-archive-after-curated` is back to `reviewed = false` | `data/test_retention.py`: strict booleans, missing requirement, missing `source_url`, `test_the_shipped_raw_rule_asks_for_a_passing_day_and_is_not_reviewed` | Runs of generated data, and tests of what the rule does, mark it reviewed in memory only |
| F-12 | `benchmark_venue` must name a usable source at load. `build_benchmark` asks again. `data_kind=MARKET` needs that too | `data/test_source_switches.py`: `test_the_benchmark_venue_must_be_usable`. `reports/test_report.py`: `test_a_prohibited_venue_is_never_published_even_with_its_files_on_disk`, `test_a_market_label_needs_a_usable_venue` | None |
| F-13 | The flag is stored in the catalog too. A root whose catalog or datasets say generated, with the marker gone, refuses to report. A marked live root is refused by real `report` and `reconcile-live`. `data_kind` is on each log line | `reports/test_report.py`: `test_a_root_of_generated_data_with_its_marker_gone_refuses_to_report`, `test_a_dataset_naming_a_generated_venue_needs_the_marker`, `test_every_log_line_carries_what_kind_of_data_it_is_about`. `test_synthetic_end_to_end.py`: `test_a_real_job_refuses_a_marked_live_root`, `test_a_generated_root_that_lost_its_marker_cannot_become_market_data` | None |
| F-14 | `publish_results.sh` checks the whole bundle first: only `status.json`, `live_state.json`, `run_log/*.jsonl`, `ledger/*`, `decisions/*`. It refuses anything else, a segment starting with a dot, and anything not a regular file. A refusal changes nothing | `test_workflows.py`: `test_publish_copies_only_what_is_on_the_list`, `test_publish_refuses_a_link_in_the_bundle` | The link test skips where creating a file symlink needs a privilege, which includes this machine |
| F-15 | Only the incoming file is filtered, so existing duplicate lines stay. A ledger `.jsonl` must keep its old bytes as an exact prefix, and that case comes first | `test_workflows.py`: `test_publish_keeps_duplicate_lines_already_in_a_log`, `test_publish_refuses_an_edited_line_in_a_ledger_log` | None |
| F-16 | Ingest gives status `nothing_selected` and an alert. Health lists an enabled dataset nothing has started, and alerts when the daily job selects nothing from an enabled source | `data/test_ingest.py`: `test_approving_a_source_the_daily_job_does_not_select_raises_an_alert`. `data/test_health.py`: `test_an_enabled_dataset_nothing_has_started_shows_as_a_coverage_problem` | None |
| F-17 | Pruning uses `--ref refs/heads/<default>`. Prune, publish and deploy run only on the default branch. `DATA_QUOTA_GB` and the default are 4 | `test_workflows.py`: `test_only_the_default_branch_prunes_and_publishes`, `test_daily_deletes_raw_and_keeps_only_the_persisted_zones`. `data/test_health.py`: `test_quota_defaults_to_under_half_of_the_cache_limit_and_the_variable_wins` | **`08_DATA_CENTER.md` and `05_DATA_LIFECYCLE.md` say 8 GB, and were not edited.** Their owner needs to update them. Not run on GitHub |
| F-18 | The watchdog reads `stale` and `health.alerts` as well as the date. It alerts on a change, remembering a digest in the Actions cache. A bad date counts as stale and fails nothing | `test_workflows.py`: `test_the_watchdog_reads_what_the_result_says_and_alerts_on_a_change`, `test_watchdog_is_quiet_without_secrets_and_never_fails` | Checked on its text only. Not run on GitHub |
| F-19 | No comparison on a reset snapshot. Negative or non-finite sizes are malformed. `ok` needs `crossed_checks > 0` | `data/test_book_replay.py`: `test_a_service_restart_snapshot_is_a_reset_and_not_a_break`, now with a new book and `ok`, `test_a_snapshot_that_is_not_a_reset_still_has_to_agree`, `test_a_size_that_cannot_be_real_is_malformed`, `test_a_file_with_an_empty_side_never_checked_for_a_crossed_book_does_not_pass` | How often a real file holds a restart is still unknown |
| F-20 | Every day in the tail must have its marks, and both series must end on one price. Otherwise `max_drawdown=None` with a reason, shown on the page | `reports/test_report.py`: `test_missing_hourly_marks_give_no_drawdown_and_a_reason`, `test_marks_that_end_on_another_price_give_no_drawdown` | None |
| F-21 | `_sweep_open_bars` checks the deadline and counts what is left, giving status `partial`. `_emit_bars` stops between days, always doing at least one. The fetch gets 75 percent of a symbol's share. The poll has its own `timeout_s` of 15 and `attempts` of 2 | `data/test_ingest.py`: `test_the_time_budget_also_bounds_the_bar_sweep`. `data/test_poll.py`: `test_the_budget_also_bounds_emission_and_the_next_pass_carries_on`, `test_one_page_cannot_take_a_whole_run_budget`, `test_the_poll_command_gives_its_client_the_polls_own_limits` | One day's emission can run past the budget, because stopping inside a day would be the crash F-06 is about |
| F-22 | See the clause table below | See the clause table below | Four clauses need a ruling |
| F-23 | See the table below | See the table below | See the table below |

### F-22, clause by clause

| Clause | State now | Covering test | Needs |
|---|---|---|---|
| 08 section 2: live bars reconciled against that day's archive | `compare_live_with_archive`, run by `run_live_checks` when the venue has an archive | `bars/test_reconcile.py`: `test_live_against_the_archive_*` | Nothing |
| 08 section 3: `raw/live/` with receive time | **Not written.** Receive times live on the rows of `trades_live`, which are in the cache, not in `raw/live/`. A lost cache loses them. The run log's `emitted_hash` is what survives | None | Ruling from `data-steward` |
| 05 section 7: expected size and record count | A wrong candle count warns, and a warning keeps raw. Nothing checks expected size | `data/test_ingest.py`: `test_a_six_hour_hole_in_a_file_is_recorded_and_flagged` for a silence | Ruling from `data-steward`. Sizes need a measured source |
| 05 section 4: retention at 80, 85 and 90 percent | **Not triggered.** `retention` stays a dry run in the workflow, and its rules stay unreviewed | `test_workflows.py`: `test_retention_is_a_dry_run_in_the_workflow` | Ruling from `data-steward`, after this recheck, as F-11 asks |
| 05 section 4: live paper keeps running at 95 percent | The poll keeps running, with an alert and a `storage_critical` state change | `data/test_poll.py`: `test_the_poll_keeps_running_at_the_critical_watermark_and_says_so` | Nothing |
| 05 section 3: sample days of `T1` and `T2` | Unchanged. Curated only, as disclosed | None | Ruling from `data-steward` |
| 08 section 3: quarantine reviewed by `data-steward` | **Unchanged.** Not in `persisted_zones`, so the evidence goes with the runner | None | Ruling from `data-steward` |
| 08 section 5: each run logs how late it was | `ingest --scheduled-cron --job-started-at` writes `pipeline_runs.jsonl`, and the published line carries it | `test_synthetic_end_to_end.py`: `test_the_daily_job_logs_how_late_it_ran` | Nothing |
| G1: reconciliation against the source | **Unchanged.** A source with no official candles has none. Holes there are caught only by ids and silences | `data/test_ingest.py`: `test_on_a_source_with_no_sequence_every_empty_minute_is_a_gap` | Ruling from `project-manager` for G1 |

### F-23, item by item

| Item | What changed | Covering test | Departure |
|---|---|---|---|
| `provisional` accepted for raw deletion | `warn` removed. Raw needs `trades:pass` and `bars_1m:pass,provisional`. Other rules need `bars_1m:pass` | `data/test_retention.py`: `test_the_shipped_raw_rule_asks_for_a_passing_day_and_is_not_reviewed` | **`provisional` stays accepted**, where the review reads the lifecycle as "passes its checks". Curated trades remain, and a later failure fetches the file again. On GitHub raw goes with the runner anyway. For `data-steward` to confirm |
| `DATA_ROOT` through a junction into a work tree | `_refuse_inside_repository` checks the path as written and where it really leads | `data/test_foundation.py`: `test_a_data_root_through_a_link_into_a_repository_is_refused` | None |
| `os.walk` enters a junction | `is_link` in the sweep and in disk measurement | `data/test_foundation.py`: `test_a_link_inside_a_zone_stops_nothing_and_its_target_is_not_counted` | None |
| Temp sweep covers `ledger/` and `decisions/` | Excluded | `data/test_ingest.py`: `test_the_temp_sweep_leaves_the_ledger_and_decisions_alone` | None |
| A file in two rules counts twice | `bytes_freed_if_run` dedupes by path | `data/test_retention.py`: `test_a_file_in_two_rules_counts_once_in_the_space_freed` | None |
| A dry run creates a mistyped root | `retention`, `health`, `report` and `reconcile-live` need it to exist | `test_synthetic_end_to_end.py`: `test_commands_that_only_look_do_not_create_a_mistyped_root` | None |
| A row repeated in one page | Rows are taken one at a time against the last id | `data/test_poll.py`: `test_a_row_repeated_inside_one_page_is_not_a_gap_and_counts_once` | None |
| `no_approved_source` stored as `failed` | Stored as itself | `data/test_poll.py`: `test_with_no_approved_source_the_poll_contacts_nothing` | None |
| `get_bytes` has no length check | Added | `data/test_source_switches.py`: `test_a_short_or_unreadable_length_fails_the_attempt` | None |
| Page says "the daily totals must match" | Replaced with the real rule | `reports/test_report.py`: `test_the_page_states_the_rule_that_is_really_used` | None |
| `${{ inputs }}` and `${{ matrix }}` in `run` | Through `env` | `test_workflows.py`: `test_no_input_reaches_a_shell_except_through_the_environment` | None |
| `date -d` can fail the watchdog | Guarded | `test_workflows.py`: `test_the_watchdog_reads_what_the_result_says_and_alerts_on_a_change` | None |
| `setup-uv` has no tool version | `version: "0.11.24"` on every use | `test_workflows.py`: `test_the_tool_is_pinned_as_well_as_the_action` | Uses `version`, not `required-version`, since the action then installs exactly that |
| Drawdown on hourly closes | Unchanged. Declared on the page, and fine for a benchmark | None | A strategy report must consider its stop model, as the review says |

## Tests judged weak in section 5 of the review

| Test | What changed |
|---|---|
| `reports/test_benchmark.py` lines 68-74 | The call compared with itself is gone. It now also says the ratio is not the 252-day one |
| `test_synthetic_end_to_end.py` lines 150-163 | The generator now spills one aggregate 400 ms before a boundary, past the window, so the failing path runs in every long run. The test asserts that exact day fails and that the others are explained |
| `test_synthetic_end_to_end.py` lines 198-206 | Kept, and read as a late-trade check, as the review says. Live against archive has its own tests |
| `bars/test_reconcile.py` lines 200-204 | The frame compared with itself is gone |
| `reports/test_report.py` lines 269-276 | Now plants a script in the poll log and reads the page |
| `data/test_book_replay.py` lines 109-117 | See F-19 |
| `data/test_retention.py` lines 343-349, 291-301, 608-618, 679-680 | Replaced with tests that reach the logic they are named for |
| `test_synthetic_end_to_end.py` line 238 | The `.get` default is gone |
| `data/test_safety.py` lines 72-82 | Replaced by the route tests in `data/test_source_switches.py` |

## Leak audit

| ID | What changed | Covering test | Departure or what is deferred |
|---|---|---|---|
| DC-01 | Emission stops at the newest trade held. Flags come from the catalog. Minutes before the first row are `gap=True` with `DATA_GAP`. A late row goes in `catalog/bar_corrections.jsonl` and no bar changes. Column `empty_proof` is `traded`, `id_run` or `none`, and `gap` is true on `none` | `data/test_poll.py`: `test_dc01a_...`, `test_with_no_record_after_the_step_back_...` for (b), `test_a_trade_arriving_after_its_minute_was_emitted_is_logged_and_does_not_repaint`, `test_dc01c_...`, `test_dc01d_...`, `test_c17_a_stop_inside_a_hole_cannot_pass_as_a_quiet_market` | Reading the corrections log belongs to `decide`, which does not exist |
| DC-02 | Required per-source `continuity`, with no default. Real ids are kept, and a skip flags every minute from the row before through the row after, with neighbouring files at the day's edges. The Bybit row number is now `file_row`, and `trade_id` is null there | `bars/test_core.py`: `test_consecutive_ids_prove_an_empty_minute`, `test_a_skip_in_the_ids_flags_...`, `test_continuity_none_never_proves_an_empty_minute`, `test_a_row_number_can_never_prove_continuity`, `test_rows_outside_the_grid_prove_its_edges_...`. `data/test_ingest.py`: `test_a_six_hour_hole_...`, `test_on_a_source_with_no_sequence_...`. `data/test_parsers.py`: `test_a_row_number_is_never_passed_off_as_a_trade_id` | The G1 report of empty minutes with and without proof is not built. The column it needs is there |
| DC-03 | Required per-source `stamp_kind` and `fill_span_allowance_ms`. A trade's `knowable_time` is `ts` plus the allowance, and a bar's is its close plus the allowance, or receipt if later. `settled_*` columns. `ideal_view` replaces the plain columns and refuses a source that cannot give them. The poll asserts `A >= allowance`. `largest_window_needed_ms` above the allowance raises a warning | `leak/test_bars_leak.py`: `test_a_fill_after_the_close_cannot_change_what_ideal_reads_at_that_close`, a generator at the level of fills. `bars/test_core.py`: settled tests. `data/test_reader.py`: `test_ideal_reads_only_what_had_printed_...`. `data/test_ingest.py`: `test_a_window_needed_beyond_the_allowance_warns` | **The charter and C2 sentence is for `project-manager` and `strategy-architect`, and is not done.** IDEAL also needs `allowance_state = "measured"`, stricter than the ruling, so with no detector and no measurement it stays blocked. The IDEAL reader goes by close time. A `gap` flag on an empty minute there can rest on a later row, and how `decide` treats that needs a ruling |
| DC-04 | `data/reader.py` is the read API: `bars`, `trades`, `live_bars`, `live_trades`, `ideal_bars`, `live_dataset`. `DatasetSpec.live_eligible` is required, and all are false | `data/test_reader.py`: all. `test_strategy_and_feature_code_cannot_read_stored_data_directly`, with `test_the_scanner_finds_what_it_is_looking_for` so it cannot pass by finding nothing | `decide` holding no root, and `assert_knowable` on every join, wait for that code |
| DC-05 | `received_at_us` is required. A bar's knowable time takes its newest row's. `rebuild_day_bars` has no `knowable_time` column. `derive_day` refuses rows received after their stamp plus the allowance. `poll` and `ingest` refuse `--now` | `bars/test_core.py`: `test_every_argument_that_decides_timing_is_required`, `test_a_bar_is_never_knowable_before_its_newest_row_is`. `data/test_poll.py`: `test_a_rebuild_for_comparison_cannot_be_read_by_time`. `data/test_ingest.py`: `test_rows_received_after_their_stamp_cannot_become_archive_bars`. `test_synthetic_end_to_end.py`: `test_jobs_that_record_receipts_refuse_a_fixed_clock` | None |
| DC-06 | The poll writes `trades_live`, `bars_1m_live`, `bars_*_live`. A replaced trade or candle part reopens the derive tasks of D-1, D and D+1 | `data/test_poll.py`: `test_the_poll_writes_only_its_own_datasets`. `data/test_ingest.py`: `test_a_replaced_file_rebuilds_its_day_and_its_neighbours` | None |
| DC-07 | C17 step 0: `t_poll` at the start of the attempt, `t_cut`, the evidence check with one step back, `DATA_GAP`, skew, all logged per symbol. `bar_grace_s` is gone. `bars_for_run` and `trades_for_run` apply both conditions and raise. Cron is minute 7 | `data/test_poll.py`: the section "the run clock of C17". `bars/test_core.py`: `test_a_run_reads_by_both_of_its_clocks`, `test_a_bar_at_or_before_the_cut_that_this_run_could_not_have_had_is_an_error`. `test_workflows.py`: `test_hourly_poll_...` | **Deferred, because the code does not exist:** `decide`, `settle`, `t_dec`, the modelled fetch of a backtest, the `lateness` events. No adapter reads a server time, so `skew_s` is null and `passed_on_server_time` is false on every run, and reports show that share as zero. Minute 7 replaces the 23 this code used earlier |
| DC-08 | A failed day keeps its bars, flagged from the first boundary the check cannot explain. A disagreement at a midnight flags that bar only. Each exclusion goes to `catalog/exclusions.jsonl` and a table, with `resolved_at`. Every result counts them. Trades now derive after their candles, and a retry fetches again rather than reusing raw | `data/test_ingest.py`: `test_a_failed_day_keeps_its_bars_flagged_...`, `test_a_failed_day_is_logged_...`, `test_a_failed_day_recovers_when_a_good_file_is_published`. `bars/test_reconcile.py`: `test_a_minutes_standing_never_depends_on_what_came_later_in_the_day`. `reports/test_report.py`: `test_a_slipped_digit_...` | Quarantine stays for structural failures. The midnight window stays frozen at 250 ms and is declared a placeholder under D-18 in `configs/pipeline.toml`. `GAP_UNRESOLVED` for an open position waits for `settle` |
| DC-09 | `compare_live_with_archive`, same venue only, on trade count, volume, high, low and close. `cross_venue_check` refuses a same-venue pair | `bars/test_reconcile.py`: `test_live_against_the_archive_*`, `test_cross_venue_refuses_a_same_venue_pair` | The G8 mismatch report does not exist. Status reaches the catalog and `status.json` |
| DC-10 | A hash of each run's emitted rows in the run log. Rows carry `emission`, `first` or `rebuild`. `poll_rebuild` returns `not_applicable` for rebuilt rows | `data/test_poll.py`: `test_a_lost_cache_rebuilds_through_the_cursor_and_says_so_on_every_bar`, `test_each_run_logs_a_hash_of_what_it_emitted` | G8 replays and the C3 wording belong to later work and to the strategy documents. The run that catches up after a lost cache marks all its bars `rebuild`, including its own new ones |
| DC-11 | `tests/leak` rewritten: an explicit grid, `derive_day` and `run_poll`. Every minute a cut for 1m. Every configured timeframe, on its closes one minute either side. Dense and sparse data. A generator at the level of fills | `leak/test_bars_leak.py`. The injected leaks are in the table below | None |
| DC-12 | `first_close_us`, `last_close_us` and `through_close_us` are required | `bars/test_core.py`: `test_a_grid_is_required_...`, `test_a_stated_closing_time_is_required`, `test_higher_timeframe_does_not_appear_until_its_close_is_known` | None |
| DC-13 | The per-source allowance applies to trades, candles and funding, and configuration says what it covers | `data/test_parsers.py`: `test_every_row_says_when_it_can_be_known_with_the_sources_allowance` | Every value is a placeholder, `UNVERIFIED` until measured on the approved source. Health alerts on that for an enabled source |
| DC-14 | `reconciliation_history` is append-only. `file_history` records a changed hash, and a changed delivered file is an alert. Manifests carry hashes | `data/test_ingest.py`: `test_a_failed_day_recovers_...`. `reports/test_report.py`: `test_a_manifest_names_what_it_read_by_hash_...`. `data/test_health.py`: `test_exclusions_and_changed_files_reach_the_alerts` | None |
| DC-15 | Reconciliation counts and poll summaries are filtered by the stated time. Only a day whose next file could exist counts, so what a report says does not depend on later deliveries | `reports/test_report.py`: `test_status_fields_are_as_of_the_stated_time`, `test_the_report_cannot_see_bars_from_after_its_own_time` | The stored bars of a day are its latest build. A report stated long before that build reads the build, and the rule above bounds what that can change |

### Section 9 of the leak audit

| Note | What changed | Covering test |
|---|---|---|
| Stuck failed day | With the partner file still due in the run, candles wait for it. A failed day sets both its tasks to retry | `data/test_ingest.py`: `test_a_failed_day_recovers_when_a_good_file_is_published` |
| Raw reuse | A retry after failure ignores the file on disk | The same test |
| `needs_derive` after a replaced part | `reopen_day` for D-1, D and D+1 | `data/test_ingest.py`: `test_a_replaced_file_rebuilds_its_day_and_its_neighbours` |
| `aggregate_bars` mixes venues | Refused | `bars/test_core.py`: `test_two_venues_are_never_merged_into_one_bar` |

### Injected leaks from section 4 of the audit

Each was put back into a temporary copy of the source, and only the named tests were run against that copy. All of these fail with the leak in place. Clean, they pass.

| Leak | How the audit found it | Direct test now |
|---|---|---|
| 1m high peeking one minute ahead on one bar in seven | Missed by the whole suite | `leak/test_bars_leak.py`: `test_truncation_invariance_at_every_minute_for_one_minute_bars` |
| Higher close peeking one minute past its bar on 240m only | Missed by the whole suite | `test_truncation_invariance_around_every_close_of_every_configured_timeframe`, `test_a_peek_past_a_higher_bar_shows_on_every_configured_timeframe` |
| The same on 30m and 120m | Missed by the whole suite | The same tests |
| The same on 1440m | Missed by the whole suite | `test_a_peek_past_a_higher_bar_shows_on_every_configured_timeframe`. The first version of it missed this one, because the minute after the close happened to have no trade, so it now uses data with a trade in every minute |
| 1m close peeking one minute ahead on every bar, with a grid | Caught only by accident | `test_truncation_invariance_at_every_minute_for_one_minute_bars`, `test_a_trade_cannot_change_the_bar_before_its_own` |
| The same peek placed only in `derive_day` | Caught only by accident | `test_derive_day_truncation_invariance_on_every_dataset`, `test_derive_day_future_perturbation` |
| Report equity marks with no as-of filter | Not run on the whole suite | `reports/test_report.py`: `test_equity_marks_are_read_as_of_the_stated_time` |

### Mutation check

41 bugs, each put back into its own temporary copy, each against the tests named for it, not the whole suite. The list holds the six leaks above, the two the code review's mutants left alive (redirect check, `keep="first"`), and fixes for the findings above.

| Round | Result |
|---|---|
| First | 36 of 41 failed their tests. Five passed |
| After looking at the five | All five now fail |

The five were not alike:

| Bug | Why its test passed | What changed |
|---|---|---|
| Higher close peek on 1440m | The test had no trade in the minute after the close | Test data now has one in every minute |
| Bar knowable at its close, with no allowance | I pointed the check at the wrong test. `test_a_bar_is_knowable_at_its_close_plus_the_allowance` already covered it | Nothing but the selection |
| Flags from a local variable, F-08 | The stored rows also show the skip, so the test passes either way | `test_a_gap_in_the_catalog_flags_bars_whatever_the_rows_show` |
| No `pending` mark, F-06 | Writing `bars_1m` last, and `reopen_day`, also heal the crash in that test | `test_a_rebuild_marks_its_task_pending_before_its_first_write` |
| Report counts any complete day, F-04 | A failed day's flags already made it incomplete | `test_a_day_that_only_warned_is_left_out_of_results` |

The last three mean the code has more than one guard at those points, so each test now holds its own guard. This is a sample of what I chose to break, not a proof about what I did not.

## Where I think a finding is wrong

None is skipped. Two notes for the recheck:

- **F-23, `provisional`.** See the table above. I kept it and say why, and it is `data-steward`'s to overrule.
- **DC-01's phrase "the minute before the newest trade held".** I read it as `floor_1m(newest - 1 µs)`, so a trade stamped exactly on a close does not show that minute is over. The minute it closes could still get another trade stamped on that same instant.

## Limits of this work

- A failed check flags bars and does not change a price. A `fail` on a real day is still a day someone must look at.
- Every API and file assumption is untested against a real source. All sources stay disabled.
- Workflows were checked on their text, and each shell block with `bash -n`. `actionlint` is not installed here and did not run. None has run on GitHub.
- **A test run reached the network by mistake.** See below.

### Network contact during this work

While writing `tests/data/test_source_switches.py`, a fake HTTP handler built with `build_opener` sat behind the real HTTPS handler, so those tests made real GET requests to `https://public.bybit.com/x` before I saw it. Counted from the test list and not measured, that is 24 requests in each of two runs of that file and 1 in a third, 49 in all. The tracebacks show a 404 from the host. That path is not a dataset, and no dataset file was requested or received. This was outside the limit for this work, and it is disclosed to the coordinator. The tests now build their opener by hand with no real handler, and `tests/conftest.py` refuses every socket connection for the whole suite, with `test_the_guard_below_every_http_library_is_on` holding it there.
