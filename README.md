# Lang2Drive

CARLA scenario generation and evaluation toolkit for autonomous-driving edge-case research.

## Current Execution Modes

1. **Codex-app skill loop (recommended, no Codex CLI required)**
- Stage 1 on macOS: prepare next scene and handoff.
- Stage 2 in Wine CMD: run simulation.
- Stage 3 on macOS: evaluate generated output and iterate.

2. **Agentic v2 script (`agentic_scene_generator.py`)**
- Provider-agnostic Python orchestrator.
- Optional backend (`--backend codex` or `--backend none`).
- Preserves legacy output/report paths.

3. **Legacy Claude script (`automated_scene_generator.py`)**
- Existing interactive flow retained unchanged.

## Recommended 3-Stage Flow (mac -> Wine -> mac)

### Stage 1: Prepare next scene (sequential serial)

```bash
cd "/Users/ashfak/Applications/Sikarugir/CARLA.app/Contents/SharedSupport/prefix/drive_c/Program Files/WindowsNoEditor/VLM-AV"
./01_generate_scene.sh
```

This stage:
- Picks next scene serial from `handoffs/NEXT_SCENE_SERIAL.txt`.
- Creates `manifest.json` and stage-1 logs.
- Seeds code from latest existing scenario code when available.

Before Stage 2, mark code ready:

```bash
python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs
```

Stage 1 deliverables for each shot must include:
- a standalone scene script at `generated_code/<scenario>/<run_id>/shot_<n>/<scenario>.py`
- a scene-specific Wine runner cmd (for example `03_run_<scenario>_shot<n>.cmd`) that prints progress in CMD and writes logs to the handoff folder
- no shared runtime wrapper imports in scene script (forbidden: `from scene_utils.fresh_scene_runtime import run_scene`)

### Stage 2: Run latest prepared scene in Wine CMD

Preferred (scene-specific standalone runner):
```cmd
cd "C:\Program Files\WindowsNoEditor\VLM-AV"
03_run_<scenario>_shot<n>.cmd
```

Fallback (legacy latest-manifest runner):
```cmd
cd "C:\Program Files\WindowsNoEditor\VLM-AV"
02_run_latest_scene.cmd
```

Outputs:
- `handoffs/<run_id>/<scenario>/simulation_result.json`
- `handoffs/<run_id>/<scenario>/stage2_runner_YYYYMMDD_HHMMSS.log`
- Wine CMD compatibility: do not use `timeout /t` in repo `.cmd` runners.
- Use `ping -n 9 127.0.0.1 >nul` for retry cooldowns instead of `timeout /t 8 >nul`.

### Stage 3: Evaluate latest output on macOS

```bash
cd "/Users/ashfak/Applications/Sikarugir/CARLA.app/Contents/SharedSupport/prefix/drive_c/Program Files/WindowsNoEditor/VLM-AV"
./03_evaluate_latest.sh
```

Output:
- `handoffs/<run_id>/<scenario>/<scenario>_visual_eval.json`

Default evaluation mode is strict manual fallback (`--manual-only --strict-intent`), so Codex CLI is not required.
After reviewing key frames, rerun with explicit human verdict:

```bash
python3 agentic_visual_evaluator.py --manual-only --strict-intent --human-intent-verdict pass --human-intent-notes "intent satisfied in key frames"
```

## Direct Python Commands

```bash
# Stage 1
python3 agent_skill_scene_loop.py prepare --handoff-dir handoffs
python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs

# Stage 2
python3 agentic_wine_handoff_runner.py --handoff-dir handoffs

# Stage 3
python3 agentic_visual_evaluator.py --handoff-dir handoffs --manual-only --strict-intent
```

## Standalone Script Policy

- Every generated scene code file must be fully runnable on its own in Wine-side Python.
- Do not depend on shared runtime wrappers for scene execution orchestration.
- Include robust map-load retry/reconnect logic, synchronous settings handling, progress logging, and cleanup directly in the scene script.
- Reuse relevant patterns from previously successful scene scripts when useful, but copy/adapt only the needed parts for the current scene.

## Specification Compliance Policy

- Global requirements are mandatory for all scenes (traffic baseline, camera set, map selection rules, logging, output structure, cleanup).
- Scene-specific requirements from `Keyword Prompt Verification.xlsx` (`Scene Specifications` column) are also mandatory.
- Scripts and prompts must satisfy both global and scene-specific requirements together; if map/topology limits prevent a strict target, scripts must log explicit achieved counts and warning context.
- For time×weather matrix runs, night-like variants (`night`, `almost_night_no_streetlights`) must enable vehicle headlights (at least position + low beam) for ego/traffic vehicles; streetlights alone are not sufficient.

## Key Files

- `Keyword Prompt Verification.xlsx`: source scene list (`Keyword`, `Prompt`, `Scene Specifications` supported by header name).
- `prompt.txt`: prompt template for code generation.
- `agent_skill_scene_loop.py`: Stage 1 scene preparation and ready-check.
- `agentic_wine_handoff_runner.py`: Stage 2 handoff execution.
- `agentic_visual_evaluator.py`: Stage 3 visual evaluation.
- `skills/carla-scene-loop/SKILL.md`: Codex-app skill instructions for this loop.
- `carla_wine_bridge.py`: runtime adapter (`auto|wine-bridge|local`).
- `agent_backends.py`: backend abstraction and Codex CLI backend.
- `automated_scene_generator.py`: legacy Claude pipeline.

## Handoff Contract

Per-scene run folder:
- `handoffs/<run_id>/<scenario>/manifest.json`
- `handoffs/<run_id>/<scenario>/NEXT_STEPS.md`
- `handoffs/<run_id>/<scenario>/stage1_agent_prepare.log`
- `handoffs/<run_id>/<scenario>/simulation_result.json` (after Stage 2)
- `handoffs/<run_id>/<scenario>/<scenario>_visual_eval.json` (after Stage 3)

Global pointers/state:
- `handoffs/LATEST_MANIFEST_POSIX.txt`
- `handoffs/LATEST_MANIFEST_WINDOWS.txt`
- `handoffs/NEXT_SCENE_SERIAL.txt`

## Output/Report Compatibility

The project continues using existing locations:
- `generated_prompts/`
- `generated_code/`
- `scenes/`
- `intervention_report_*.json`
- `intervention_summary*.csv`
- `scenario_intervention_data*.csv`

## Research History Workbook (Single Sheet)

Generate one Excel file with one row per scene-run (aggregated over all shots), including:
- shot-by-shot change history
- tool/runtime success rates (all attempts and executed-only)
- evaluation criteria/checklist requested
- visual-eval outcomes
- embedded charts for quick visualization

Command:

```bash
python3 research_scene_history_excel.py
```

Default output:
- `handoffs/research_scene_history.xlsx`

## Runtime Requirements

- Start `CARLA.app` manually before Stage 2.
- Wine runtime in `CARLA.app` must be available.
- `libinotify.0.dylib` must be discoverable by Wine runtime.
- Python dependencies include at least: `openpyxl`, `python-dotenv`, `carla`, `pygame`, `numpy`, `Pillow`.

## Troubleshooting

- Scene-specific success criteria not appearing in regenerated prompts:
  - Confirm the sheet has a `Scene Specifications` header (header-name based; column order can vary).
  - Add per-scene criteria in that column for the selected row.
- Stage 2 reports failure but frames exist:
  - Check `simulation_result.json` fields `frames_ok`, `coverage_ratio`, `note`.
  - Stage 2 may still count success when frame coverage passes threshold.
- Latest manifest missing:
  - Run Stage 1 first.
- Mark-ready fails:
  - Fix reported issues in generated script and rerun `mark-ready`.
- No frames saved:
  - Confirm CARLA is running and reachable from the Wine CMD session.

## Legacy Workflow

For the older Claude API interactive path:

```bash
python3 automated_scene_generator.py
```

That path remains unchanged for backward compatibility.
