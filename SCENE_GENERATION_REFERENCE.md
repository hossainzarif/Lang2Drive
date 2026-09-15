# Scene generation guide

## Installation and inputs

Install `requirements-generation.txt` with Python 3.10+. Install the CARLA Python API matching your simulator version separately. Confirm that the runtime contains the maps and actors required by the selected specification. The retained mesh examples require a build exposing `static.prop.mesh`; availability must be checked in the installed simulator.

The workbook `Keyword Prompt Verification.xlsx` contains one `Scenarios` sheet. `Keyword`, `Prompt`, and `Scene Specifications` are the generation inputs. `Paper Name`, `Hazard Family`, and `Scenario ID` provide display names and stable identifiers. `scene_catalog.json` records the same 30-scene roster in a text format.

Some source IDs differ from the paper labels: `floating_rocks_on_the_road` maps to Landslide rocks on the road, and `zero_gravity_street` maps to Overhead car crash. Preserve source IDs when locating existing artifacts. Scene prompts and specifications are explicit inputs; review their actor and event constraints before generation.

## Text Scene Agent and Code Agent

List scenes and prepare a selected specification:

```bash
python agent_skill_scene_loop.py list-scenes
python agent_skill_scene_loop.py prepare --scene-serial 1 --duration 20
```

Preparation writes the full prompt, initial code file, and shared manifest. It normalizes the default front-camera contract and can reuse an existing script for the same scenario. A placeholder contains `TODO_IMPLEMENT_SCENARIO_LOGIC` and must be replaced before execution. Inspect the prepared prompt and supply the scene-specific enhancement before asking the Code Agent to implement it.

The Code Agent should implement `prompt.txt` and the scene-specific requirements. It must expose duration, output, and environment arguments; capture the required camera streams; log the incident; and perform checked cleanup. Validate asset names against the running simulator rather than assuming an asset exists.

The optional `agentic_scene_generator.py` backend adapter can prepare handoffs using its documented `--help` options. The manifest workflow below is the common execution path.

## Shared manifest and readiness

Set `MANIFEST` to the path printed by preparation:

```bash
MANIFEST="handoffs/<run_id>/<scenario>/manifest.json"
python agent_skill_scene_loop.py mark-ready --manifest "$MANIFEST"
```

Readiness checks script syntax, placeholder markers, the output argument, and required environment flags. A readiness pass is not a simulation or visual-acceptance result.

The manifest retains:

- `scenario_keyword`, `scene_prompt_original`, and `scene_specifications`.
- `run_id`, `shot_index`, `generation_status`, and optional seed provenance.
- `code_file_posix`/`code_file_windows` and `output_dir_posix`/`output_dir_windows`.
- `duration_seconds`, prompt paths, and generation log paths.

Use host-appropriate paths when moving between machines. Preserve older manifests and output folders when starting a refinement attempt.

## Simulation

Start CARLA manually. From the repository root, use the Python environment associated with that simulator:

```bash
python agentic_wine_handoff_runner.py --handoff-manifest "$MANIFEST" --min-success-ratio 1.0
```

On Windows/Wine, pass the Windows manifest path in quotes instead of the shell variable. The handoff runner executes locally in that environment. macOS preparation can translate Wine paths when `CARLA_APP_PATH` is configured; `CARLA_WINE_PYTHON_EXE` configures the optional bridge interpreter.

The runner writes `simulation_result.json` and a stage log. A nonzero process exit remains a failure even when frames exist. Both baseline and matrix entrypoints share a local simulator lock; do not run other simulator clients concurrently.

Generated scripts must write `cleanup_status.json` in their output root, with `complete` and `errors`. Set `complete: true` only after stopping sensors, disabling Traffic Manager synchrony, checking actor destruction, and restoring world settings. Cleanup errors must cause a nonzero exit.

## Evaluator Agent and refinement

For automated scene review with an available configured backend:

```bash
python agentic_visual_evaluator.py --handoff-manifest "$MANIFEST"
```

For manual review:

```bash
python agentic_visual_evaluator.py --handoff-manifest "$MANIFEST" --manual-only --strict-intent
```

Inspect the selected event frames, scene checklist, and simulation log. Then record the actual human verdict and a concise observation using `--human-intent-verdict pass|fail` and `--human-intent-notes`. An unknown manual verdict cannot pass strict review. The scene evaluator requires every checklist criterion to pass; its output includes `evaluation_mode` so automated and manual reviews remain distinguishable.

Use failure observations and `suggested_fix_prompt` to revise the code. Prepare the same scene with `--shot-index 1` (increment for later attempts), retain prior evidence, and attach the relevant previous feedback to the next full prompt. The new preparation has its own run directory; `code_seed_source` records reused code. This workflow exposes agent steps and feedback explicitly; preparation does not autonomously complete the refinement loop.

## Weather sweep and recovery

After accepting the baseline, prepare the eight-condition capture:

```bash
python agentic_wine_time_weather_matrix_runner.py --handoff-manifest "$MANIFEST" --dry-run
```

A dry run checks preparation and prints commands without starting the simulator. It writes `matrix_preparation.json`, never a successful capture receipt.

Execute in the simulator environment:

```bash
python agentic_wine_time_weather_matrix_runner.py --handoff-manifest "$MANIFEST"
```

Or use `04_run_scene_matrix8.cmd "path\to\manifest.json"` in Windows/Wine.

- Each variant retains a `variant_result.json` containing source/configuration fingerprints and capture hashes.
- Reruns verify source, arguments, successful exit, cleanup, consecutive frame IDs, decoding, dimensions, and capture hashes before skipping.
- Changed code, settings, corrupt images, and missing frames invalidate a previous success.
- Previous payloads move under `failed_attempts/<variant>/<attempt>/` before retry, including logs and receipts.
- A missing or failed cleanup receipt stops further variants. Inspect the simulator and resolve cleanup before rerunning.
- `simulation_result_matrix8.json` is checkpointed after each variant; previous summaries are retained in `matrix_history/`.

At 20 FPS, the default 20-second run requires 400 frames in each required stream. Dimensions default to 1280×720; `image_dimensions` can explicitly specify another capture size. Frame integrity does not establish synchronized world-frame timing, incident correctness, or physical realism; inspect relevant telemetry and the event visually.

## Asset checks

Query the installed blueprint library for required IDs and reject unavailable assets before capture. The retained examples use packaged mesh paths through `static.prop.mesh`. Mesh availability depends on the CARLA build; do not silently replace the intended object with an unrelated prop. Keep scale, collision behavior, and visibility checks in the scene-specific specification.
