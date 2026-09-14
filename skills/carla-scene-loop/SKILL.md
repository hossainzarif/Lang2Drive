---
name: carla-scene-loop
description: Use when the user wants a Codex-app-driven CARLA scene loop without Codex CLI: prepare the next scene by serial, update code, mark it ready for Wine CMD, then evaluate generated frames after simulation.
---

# CARLA Scene Loop (No Codex CLI)

Use this workflow when scene generation/editing is done by the agent in chat, simulation runs in Wine CMD, and evaluation returns to chat.

## Universal Generation Contract (Apply to Every Scene)
- Maintain scene-specific intent from the selected scenario prompt.
- Start each simulation from a fresh map load (`client.load_world(...)`), not from a previously open runtime map state.
- Generate standalone scene scripts only (no shared runtime wrapper execution import).
- Enforce busy-area baseline in code:
  - At least 20 active vehicles per approach direction (hard requirement).
  - For 4-way intersections: at least 80 active moving vehicles around ego context.
  - At least 10 distinct vehicle types across the scene when available.
  - Dense road context typical of busy/construction areas (cones, barriers, warning props, service vehicles) without over-cluttering active lanes.
  - Place context props on shoulder/median/roadside only unless scenario is explicitly an obstacle/blockage case.
  - **Prefer `static.prop.mesh` for realistic scene objects** (trees, rocks, bushes, debris, barriers) that lack dedicated blueprints: `bp_lib.find('static.prop.mesh')` + `set_attribute('mesh_path', '/Game/Carla/Static/...')`. This spawns any UE4 static mesh at runtime without a source rebuild. Set `mass` > 0 for physics-enabled objects (e.g., fallen trees). See `SCENE_GENERATION_REFERENCE.md` §9 for the full mesh catalog and usage pattern.
  - Keep nearby moving traffic visible around ego (behind, beside, and crossing approaches), not only far ahead.
  - Maintain near-ego moving traffic targets whenever map capacity allows: behind>=6, beside>=8, crossing>=8.
  - Stage traffic + objects + scenario event so they are visible at the same time in camera views.
- Generation rule:
  - Scripts must enforce and log per-direction counts.
  - If thresholds cannot be met after retries because of map/topology limits, continue with explicit warning + achieved count diagnostics.
- Enforce front-camera capture by default:
  - Save `front` stream unless the user explicitly asks for multi-angle capture.
  - Only use 5-camera capture (`front`, `front_left`, `front_right`, `rear`, `drone_follow`) when explicitly requested.
- Enforce modular environment-control CLI contract in every generated scene script:
  - Standalone scripts remain single-run and accept one environment per run.
  - Required args: `--time-preset`, `--weather-preset`, `--sun-altitude`, `--sun-azimuth`, `--streetlights`, `--cloudiness`, `--precipitation`, `--precipitation-deposits`, `--wind-intensity`, `--fog-density`, `--fog-distance`, `--wetness`.
  - Default to the scene's intended environment when no preset/override is passed.
  - Shared spec standard time presets: `noon`, `sunset`, `night`, `sunrise`, `almost_night_no_streetlights`.
  - Shared spec standard weather presets: `clear`, `storm`, `foggy`, `worst`.
  - Matrix lighting rule: for `night` and `almost_night_no_streetlights` variants, enable vehicle headlights (at least position + low beam) on traffic/ego vehicles, not just streetlights.
- Use local signalized 4-lane approaches (2 lanes each way) as the global default map/road context.
- Only use highway/freeway segments when a scene explicitly requires highway behavior.
- Smart reference requirement:
  - Use `SCENE_GENERATION_REFERENCE.md` as the primary pattern index for scene generation quality.
  - If a scene fails intent/eval or needs a second retry, explicitly apply relevant reusable patterns from both `3csim` and CARLA `PythonAPI` sections in that doc.
- Reuse policy:
  - Reuse proven code patterns from relevant successful scenes when helpful.
  - Adapt copied patterns to current scenario intent and naming; do not keep stale scene behavior.
- Specification policy:
  - Treat global requirements and scene-specific workbook requirements (`Scene Specifications`) as jointly mandatory.
  - If strict numeric targets cannot be met due map topology limits, script must log achieved counts and explicit warnings.

## Standalone Runtime Contract (Hard Requirement)

- Do not use `from scene_utils.fresh_scene_runtime import run_scene` in generated scene scripts.
- Each scene script must include:
  - CARLA connection + timeout handling
  - map-load retries with reconnect handling
  - synchronous-mode apply with retries
  - actor/sensor creation and camera capture (front only by default; 5-angle only when explicitly requested)
  - per-frame progress logs in CMD
  - persistent simulation log file writes
  - deterministic cleanup and world settings restore
- For each prepared shot, also provide a scene-specific Wine runner command file:
  - `03_run_<scenario>_shot<n>.cmd`
  - It must print progress, capture Python exit code, and point to log outputs.

## Inputs/State
- Scene source: `Keyword Prompt Verification.xlsx`.
- Serial state file: `handoffs/NEXT_SCENE_SERIAL.txt`.
- Latest manifest pointers:
  - `handoffs/LATEST_MANIFEST_POSIX.txt`
  - `handoffs/LATEST_MANIFEST_WINDOWS.txt`

## Parallel Batch Mode (For Unconfirmed Scenes)
- Use this mode when the user wants many unconfirmed scenes regenerated in parallel before any per-scene human feedback is applied.
- In parallel batch mode:
  - Treat `LATEST_MANIFEST_*` and `NEXT_SCENE_SERIAL.txt` as convenience pointers only, not as the source of truth.
  - The source of truth is the explicit per-scene `manifest.json` path for each prepared scene.
  - Do not rely on the latest-manifest runner for batch tracking except as a fallback.
  - Prefer fresh regeneration with `--no-seed-from-latest` for unconfirmed scenes whose old prompt/code artifacts do not match the latest standards.
- Recommended batch flow:
  1. Identify the set of unlocked, unconfirmed scenes to regenerate.
  2. Archive/remove old unconfirmed artifacts from active consideration for those scenes.
  3. Prepare one new baseline run per scene using explicit serials.
  4. Edit each generated code file to satisfy the universal generation contract.
  5. Mark each scene ready using its explicit manifest path.
  6. User runs the single clear/sunny baseline for all prepared scenes in Wine CMD.
  7. Collect saved images for all scenes first.
  8. User provides human feedback scene by scene.
  9. Patch only the scenes that need changes, rerun those scenes, and keep finalized scenes locked.
  10. Run matrix20 only after a scene is human-confirmed/finalized.
- Locking rule:
  - Once the user explicitly says a scene is finalized, treat that scene as locked.
  - Do not regenerate prompt/code for a locked scene unless the user explicitly unlocks it.

## Batch Prepare Pattern
- Example prepare command for a specific scene serial:
```bash
python3 agent_skill_scene_loop.py prepare --handoff-dir handoffs --scene-serial <serial> --no-seed-from-latest
```
- Example mark-ready command for a specific prepared scene:
```bash
python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs --manifest handoffs/<run_id>/<scenario>/manifest.json
```

## Stage 1 (Prepare + Code Ready)
1. Prepare next scene (serial auto-increments):
```bash
python3 agent_skill_scene_loop.py prepare --handoff-dir handoffs
```
2. Read JSON output and open these paths:
- `manifest_path`
- `prompt_file`
- `code_file`
3. Before editing, review `SCENE_GENERATION_REFERENCE.md` and pick the most relevant reusable patterns for this scene.
4. Edit `code_file` for scenario intent + Universal Generation Contract above.
   - If relevant prior scene scripts exist, copy/adapt only the needed robust functions into this standalone script.
5. Mark ready:
```bash
python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs
```
6. If not ready, fix issues and rerun step 5.

### Stage 1 Variant For Parallel Batches
- Instead of auto-increment prepare, call `prepare` once per target scene with explicit `--scene-serial`.
- Track every emitted `manifest.json` separately.
- For unconfirmed scenes, prefer:
```bash
python3 agent_skill_scene_loop.py prepare --handoff-dir handoffs --scene-serial <serial> --no-seed-from-latest
```
- After editing each scene, mark it ready with its own manifest path:
```bash
python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs --manifest handoffs/<run_id>/<scenario>/manifest.json
```

## Stage 2 (User in Wine CMD)
Tell user to run:
```cmd
cd "C:\Program Files\WindowsNoEditor\VLM-AV"
03_run_<scenario>_shot<n>.cmd
```
For retry cooldowns in Wine CMD:
- Never use `timeout /t`.
- Use `ping -n 9 127.0.0.1 >nul`.

When a finalized scene needs the full 20 time×weather variants:
```cmd
cd "C:\Program Files\WindowsNoEditor\VLM-AV"
04_run_scene_matrix20.cmd "C:\Program Files\WindowsNoEditor\VLM-AV\handoffs\<run_id>\<scenario>\manifest.json"
```
This writes per-variant frames under `.../time_weather_matrix/<time>__<weather>/`.

Fallback (legacy latest-manifest runner):
```cmd
cd "C:\Program Files\WindowsNoEditor\VLM-AV"
02_run_latest_scene.cmd
```

### Stage 2 Policy For Parallel Batches
- First run for every unconfirmed scene should be a single clear/sunny baseline only.
- User may run all prepared baseline scenes first, save all images, then return with human feedback for each scene.
- Matrix20 is deferred until a specific scene is confirmed/finalized.

## Stage 3 (Strict Intent Evaluation on macOS/Codex)
1. Run strict evaluator (manual fallback, no Codex CLI required):
```bash
python3 agentic_visual_evaluator.py --manual-only --strict-intent
```
2. Open:
- `handoffs/<run_id>/<scenario>/simulation_result.json`
- `handoffs/<run_id>/<scenario>/<scenario>_visual_eval.json`
3. Review `key_frames` and `intent_checklist` from eval JSON.
4. After human visual review of key frames, rerun with verdict:
```bash
python3 agentic_visual_evaluator.py --manual-only --strict-intent --human-intent-verdict pass --human-intent-notes "event clearly visible in key frames"
```
or:
```bash
python3 agentic_visual_evaluator.py --manual-only --strict-intent --human-intent-verdict fail --human-intent-notes "pedestrian not in crossing path"
```

## Iteration Rule
- If output does not match intent on key frames/event window, patch the same scenario code, run `mark-ready`, ask user to rerun Stage 2, then reevaluate with strict intent mode.
- Keep all artifacts in the same handoff folder for auditability.
- In parallel batches, iterate per scene after the user gives scene-specific feedback; do not churn locked/finalized scenes.
