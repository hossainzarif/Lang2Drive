# Automated CARLA Scene Generator

This repository now supports a **Codex-app-driven scene loop** that does not require Codex CLI for generation.

## Paths
- `automated_scene_generator.py`: legacy Claude-based pipeline (unchanged).
- `agentic_scene_generator.py`: v2 Python orchestrator (optional backend, keeps legacy output/report layout).
- `agent_skill_scene_loop.py`: recommended Stage 1 helper for Codex-app/manual generation loop.
- `agentic_wine_handoff_runner.py`: Stage 2 runner for Wine CMD.
- `agentic_visual_evaluator.py`: Stage 3 evaluator (manual fallback; Codex CLI optional).
- `skills/carla-scene-loop/SKILL.md`: reusable skill instructions for Codex app sessions.
- `Keyword Prompt Verification.xlsx`: scene source with optional per-row `Scene Specifications` column used in regenerated prompts.

## Recommended Workflow (mac -> Wine -> mac)

### Stage 1 (macOS / Codex app): Prepare next scene

```bash
cd "/Users/ashfak/Applications/Sikarugir/CARLA.app/Contents/SharedSupport/prefix/drive_c/Program Files/WindowsNoEditor/VLM-AV"
./01_generate_scene.sh
```

What this does:
- Selects the next scene by serial from `Keyword Prompt Verification.xlsx`.
- Uses `handoffs/NEXT_SCENE_SERIAL.txt` to continue sequentially.
- Creates handoff manifest + prompt/code/output paths.
- Seeds code from latest existing scenario code when available.

Then in Codex app:
1. Open the latest manifest path from command output.
2. Update the generated code file for the scenario intent.
3. Keep the scene script standalone (no shared runtime wrapper import).
4. Create/update a scene-specific runner cmd (`03_run_<scenario>_shot<n>.cmd`) that shows progress and writes log path details.
5. Mark ready:

```bash
python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs
```

### Stage 2 (Wine CMD): Run simulation

Preferred (scene-specific standalone runner):
```cmd
cd "C:\Program Files\WindowsNoEditor\VLM-AV"
03_run_<scenario>_shot<n>.cmd
```

Legacy fallback:
```cmd
cd "C:\Program Files\WindowsNoEditor\VLM-AV"
02_run_latest_scene.cmd
```

Notes:
- Start `CARLA.app` first.
- Stage 2 writes:
  - `handoffs/<run_id>/<scenario>/simulation_result.json`
  - `handoffs/<run_id>/<scenario>/stage2_runner_YYYYMMDD_HHMMSS.log`
- If process exits non-zero but frame coverage meets threshold, Stage 2 marks success.

## Mandatory Implementation Rules

- Generated scene scripts must be fully standalone and runnable in Wine-side Python.
- Do not rely on `scene_utils/fresh_scene_runtime.py` from generated scene files.
- Scripts must follow both:
  - global scene-generation baseline rules, and
  - scene-specific requirements from workbook `Scene Specifications`.
- For time×weather matrix runs, night-like variants (`night`, `almost_night_no_streetlights`) must enable vehicle headlights (at least position + low beam) for ego/traffic vehicles, not only streetlights.
- Relevant successful scene code patterns may be reused, but must be adapted to the current scene intent.

### Stage 3 (macOS / Codex app): Evaluate output

```bash
cd "/Users/ashfak/Applications/Sikarugir/CARLA.app/Contents/SharedSupport/prefix/drive_c/Program Files/WindowsNoEditor/VLM-AV"
./03_evaluate_latest.sh
```

Notes:
- Default is `--manual-only --strict-intent` evaluator mode (no Codex CLI dependency).
- Output file:
  - `handoffs/<run_id>/<scenario>/<scenario>_visual_eval.json`
- For final sign-off after key-frame review:
```bash
python3 agentic_visual_evaluator.py --manual-only --strict-intent --human-intent-verdict pass --human-intent-notes "intent satisfied in key frames"
```

## Zero-Argument Wrappers

- `01_generate_scene.sh`: Stage 1 prepare (sequential serial state, no keyword required).
- `02_run_latest_scene.cmd`: Stage 2 simulation from latest manifest.
- `03_evaluate_latest.sh`: Stage 3 evaluation from latest manifest.

Reset Stage 1 serial to 1:

```bash
RESET_SCENE_SERIAL=1 ./01_generate_scene.sh
```

## Direct Python Equivalents

```bash
# Stage 1
python3 agent_skill_scene_loop.py prepare --handoff-dir handoffs
python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs

# Stage 2
python3 agentic_wine_handoff_runner.py --handoff-dir handoffs

# Stage 3
python3 agentic_visual_evaluator.py --handoff-dir handoffs --manual-only --strict-intent
```

## Handoff Contract

Per-run directory:
- `handoffs/<run_id>/<scenario>/manifest.json`
- `handoffs/<run_id>/<scenario>/NEXT_STEPS.md`
- `handoffs/<run_id>/<scenario>/stage1_agent_prepare.log`
- `handoffs/<run_id>/<scenario>/simulation_result.json` (after Stage 2)
- `handoffs/<run_id>/<scenario>/<scenario>_visual_eval.json` (after Stage 3)

Latest pointers:
- `handoffs/LATEST_MANIFEST_POSIX.txt`
- `handoffs/LATEST_MANIFEST_WINDOWS.txt`

Serial state:
- `handoffs/NEXT_SCENE_SERIAL.txt`

## Runtime Requirements

- CARLA must be started manually before Stage 2.
- Wine runtime must be available inside `CARLA.app`.
- `libinotify.0.dylib` must be discoverable by Wine runtime.
- Codex CLI is optional; only needed if you want evaluator CLI mode instead of manual fallback.

## Troubleshooting

- Scene-specific success criteria missing in generated prompts:
  - Ensure the workbook includes a `Scene Specifications` header and the row has values.
  - Parser resolves by header name, not fixed column index.
- Stage 2 says failed but frames exist:
  - Check `simulation_result.json` for `frames_ok`, `coverage_ratio`, and `note`.
  - Check Stage 2 log in the handoff folder.
- No latest manifest:
  - Run Stage 1 (`./01_generate_scene.sh`) first.
- Code not ready for Stage 2:
  - Run `python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs` and fix reported issues.
- Missing frames:
  - Confirm CARLA is running and reachable from Wine CMD runtime.

## Legacy Path

`automated_scene_generator.py` remains unchanged and continues to use Claude API + original interactive flow.
