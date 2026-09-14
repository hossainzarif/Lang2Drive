# Plan: Intervention-Aware Retention + Execution Modes

## Goal
Update the core solution so full testing retains durable metrics grouped by intervention level:
- No human intervention
- Two-shot / one intervention
- Multi-shot / more than one intervention

Each group must report:
- Tested
- Success
- Fail
- Success Rate

## Confirmed Semantics (locked)
1. Two-shot = exactly 1 human-requested fix round.
2. Human intervention count includes only issue/fix feedback.
3. Rerun/regenerate actions due code not working do not count as human intervention.
4. Success = simulation success + frame verification.
5. Retention = per-run JSON + cumulative output.
6. Scope = implement in `automated_scene_generator.py` only.
7. Autonomous mode includes auto-fix retries, max 5.
8. Skip semantics:
   - Skip with previously generated scenario assets/code => count as PASS.
   - Skip without previously generated assets/code => exclude from Tested.
9. Record user adjustment prompts per shot/fix round in CSV.
10. For human-intervention shots, keep prompt/code/output isolated per shot (separate folders/files, no overwrite).
11. Keep retention in a single scenario-level CSV: one row per scenario, with shot-specific columns for multi-shot data.
12. After implementation, add and run automated tests for function behavior/coverage paths without requiring CARLA runtime.
13. For multi-shot fixing, show the user the previous shot prompt/context before collecting the next fix prompt.
14. For each new shot prompt to Claude, include previous shot context/issues so Claude avoids repeating earlier mistakes.

## Phase 0 - Clarification Status
- No remaining semantic blockers.

## Phase 1 - Instrument Scenario Lifecycle
In `automated_scene_generator.py`, add per-scenario metrics object:
- `scenario_keyword`
- `mode` (`autonomous` or `interactive`)
- `intervention_count`
- `fix_rounds`
- `llm_generation_count`
- `sim_runs`
- `final_success`
- `final_bucket`
- `adjustment_prompts` (ordered list of user feedback entries per shot)
- `shot_artifacts` (paths for prompt/code/output per shot)
- `timestamps` and errors (optional but useful)

Track intervention events at current user decision points:
- User-reported issues with retry
- Do not increment for rerun/regenerate decisions

Capture adjustment prompt details for each fix round:
- `run_id`
- `scenario_keyword`
- `shot_index` (1-based per scenario fix round)
- `intervention_count_after_shot`
- `user_adjustment_prompt` (raw user feedback text)
- `code_file`
- `prompt_file`
- `scene_output_dir`
- `timestamp`

Add artifact isolation strategy for intervention shots:
- Initial generation: `shot_0` (or equivalent baseline version tag).
- Human intervention fix rounds: `shot_1`, `shot_2`, ...
- Save each shot separately without replacing prior assets:
  - prompts: `generated_prompts/<scenario_keyword>/shot_<n>/...`
  - code: `generated_code/<scenario_keyword>/shot_<n>/...`
  - outputs/logs: `scenes/<scenario_keyword>/shot_<n>/...`
- Keep pointer to "active/latest shot" for execution while preserving prior shot history.

Single CSV schema shape (wide format):
- Base columns per scenario: run metadata, tested/success/fail, bucket, intervention counts, final status.
- Shot columns: `shot_0_*`, `shot_1_*`, `shot_2_*`, ... (prompt text, prompt path, code path, output dir, shot status/timestamp).
- For scenarios with fewer shots, leave higher shot columns empty.

## Phase 2 - Add Execution Mode Options
Add explicit runtime selection:
1. `autonomous` (new):
   - No prompts during execution.
   - Use objective checks only (simulation exit status + frame verification).
   - Bounded auto-fix retries: max 5 attempts.
2. `interactive` (current style):
   - Keep existing prompts.
   - Dynamically count interventions from user-driven corrections.
   - Before requesting a new fix prompt, display prior shot context (at least previous shot index + prompt text/path).
   - Build the next Claude fix prompt with historical context (previous shot prompts + reported issues + prior generated code summary/path).

Implementation approach:
- Route prompts through wrapper methods.
- In autonomous mode, wrappers return deterministic policy choices without `input()`.

## Phase 3 - Bucketing + Retention
Add classification function (single source of truth), e.g.:
- `0 interventions` -> `no_human_intervention`
- `1 intervention` -> `two_shot_or_single_intervention`
- `>=2 interventions` -> `multi_shot_or_multi_intervention`

Persist outputs:
- Per-run detail file (JSON): scenario-level records + aggregate bucket table.
- Cumulative output file (CSV or JSONL append) for longitudinal tracking.
- Shot-level artifact index in report JSON (prompt/code/output path per shot).

CSV retention strategy:
- Single file (e.g., `scenario_intervention_data.csv`) with one row per scenario execution.
- Columns include both base scenario fields and shot-specific fields.
- When a run introduces a higher shot index than existing columns, extend CSV headers and backfill blanks for old rows.

## Phase 4 - Reporting
At run end, print and save:
- Bucket table with Tested/Success/Fail/Success Rate
- Overall totals
- Metadata: run mode, durations, scenario count, timestamp

Suggested output names:
- `intervention_report_YYYYMMDD_HHMMSS.json`
- `intervention_summary.csv` (append mode) or `intervention_history.jsonl`
- `scenario_intervention_data.csv` (single row per scenario, wide shot columns)

## Phase 5 - Validation
Minimum checks:
- Bucket classifier unit-like tests (quick local assertions)
- Success-rate math (`0 tested -> 0.0%` safe handling)
- Interactive mode regression sanity (existing flow still usable)
- Autonomous mode smoke test with 1-2 scenarios
- Non-CARLA automated tests for core functions and branching paths (mock subprocess/API/filesystem where needed)
- Verify artifact path generation, shot separation, and CSV wide-column generation logic
- Verify skip semantics, intervention counting, and bucket assignment rules
- Verify interactive flow shows previous-shot context before accepting next-shot fix input
- Verify new-shot Claude prompts include previous-shot context and issue history
- Run test suite locally as part of implementation completion (without launching CARLA)

## Risks / Compatibility
- Existing interactive flow is heavily prompt-driven; mode gating must avoid regressions.
- CARLA nondeterminism may produce flaky pass/fail rates; retain raw per-scenario detail for traceability.
- Keep legacy reports untouched to preserve current workflow.

## Deliverables
- Updated `automated_scene_generator.py` with autonomous + interactive tracking
- New intervention report artifact(s)
- Single CSV retention with scenario rows and shot-specific columns
- Automated tests (non-CARLA) covering key functional paths
- Updated `agent.md` (if definitions change after clarification)
- Optional README notes for new mode and metrics
