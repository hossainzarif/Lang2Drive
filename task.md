# Scene Verification Task Plan (Post 6 Finalized Scenes)

## Goal
- Process all non-finalized scenes one by one through the full pipeline: prompt -> code -> run -> strict verify -> improve -> finalize.
- Keep a single reliable Excel data trail for later visualization.
- Use the latest workflow/guardrails from:
  - `skills/carla-scene-loop/SKILL.md`
  - `agent.md`

## Finalized Scenes (Reference Baseline)
- Red Light Violation
- Sudden Pedestrian Crossing
- Oil Spill Hazard
- Overhead Sign Collapse
- Giant Tree Log Blocking the Road
- Bicycle in Highway Lane

Use these finalized scenes only as **general quality references** (dense traffic, realistic actors/props, clear event visibility), not for scene-specific behavior.

## Non-Negotiable Standards (Every Remaining Scene)
- Keep scenario intent from workbook prompt + scene specifications.
- Fresh map load on every run (`client.load_world(...)`), no stale runtime state.
- Standalone scene script only (no deprecated shared runtime wrapper import).
- Busy realistic context:
  - >=20 active vehicles per approach direction where feasible.
  - Dense near-ego traffic visible behind/beside/crossing.
  - >=10 vehicle types where map supports it.
  - Realistic humans/objects/road context.
  - Props on shoulders/medians/roadside unless obstacle scene requires lane blockage.
- Default front camera capture unless multi-angle is explicitly requested.
- If numeric targets are not reachable due map limits, log achieved counts + warnings.
- Stage traffic + actors + event so key event is clearly visible in key frames.

## Drop Old Non-Compliant Artifacts Policy
- Previously generated prompt/code artifacts for a scene are **not source of truth** if they predate the latest workflow.
- For each scene, keep only the current regeneration run as active.
- Move older per-scene run folders under an archive location before/while regenerating:
  - `generated_code/<scenario_keyword>/<old_run_id>/`
  - `generated_prompts/<scenario_keyword>/<old_run_id>/`
  - optional scene outputs under `scenes/<scenario_keyword>/<old_run_id>/`
- Do not archive/delete the 6 finalized scenes’ latest accepted run artifacts.

## Required Per-Scene Workflow (Do In Order)
1. Stage 1 prepare:
   - `python3 agent_skill_scene_loop.py prepare --handoff-dir handoffs`
   - Read `manifest.json`, `prompt_file`, `code_file`.
2. Enforce latest contract in code:
   - Apply universal standards above.
   - Use `SCENE_GENERATION_REFERENCE.md` patterns when needed.
   - Keep script standalone and production-logged.
3. Mark ready:
   - `python3 agent_skill_scene_loop.py mark-ready --handoff-dir handoffs`
4. Stage 2 simulation (Wine CMD):
   - `03_run_<scenario>_shot<n>.cmd` (preferred)
   - `02_run_latest_scene.cmd` (fallback)
5. Stage 3 strict evaluation:
   - `python3 agentic_visual_evaluator.py --manual-only --strict-intent`
   - Re-run with human verdict pass/fail + notes.
6. Iterate until pass:
   - Patch same scene, rerun stage 2, reevaluate.
7. Stage 4 logging (mandatory after each loop):
   - `python3 shot_history_excel.py --manifest handoffs/<run_id>/<scenario_keyword>/manifest.json`
   - `python3 research_scene_history_excel.py`
8. Workbook updates:
   - Update `Keyword Prompt Verification.xlsx` row for scene:
     - `Code Ouput`: final run summary + artifact pointers.
     - `Verification`: shot history summary + `Verification Status: VERIFIED (Finalized)` only when truly done.

## Excel/Data Outputs We Must Maintain
- Scene tracker: `Keyword Prompt Verification.xlsx`
- Per-run shot workbook: `handoffs/<run_id>/<scenario_keyword>/shot_history.xlsx`
- Unified analytics workbook (main visualization source): `handoffs/research_scene_history.xlsx`
- Verified-scenes rollup (already created): `handoffs/verified_scenes_consolidated.xlsx`

## Definition Of Done (Per Scene)
- Strict-intent evaluation passes with human verdict pass.
- Final code + full prompt + enhanced prompt exist for final accepted shot/run.
- Shot/run metrics logged in `shot_history.xlsx` and `research_scene_history.xlsx`.
- Scene row updated in `Keyword Prompt Verification.xlsx` and marked verified.

## Remaining Scene Queue (53)

### Group A (Master/Ashfak remaining)
- [ ] Wrong-Way Driver
- [ ] Sudden Heavy Rain
- [ ] Emergency Vehicle Priority
- [ ] Vehicle Door Opening
- [ ] Pothole Avoidance
- [ ] Sudden Obstacle Drop
- [ ] Jaywalking Animal
- [ ] Meteor Shower Crash
- [ ] Flying Car/UFO Hovering Over Intersection
- [ ] Sudden Tornado Formation
- [ ] Floating Rocks on the Road
- [ ] Time Freeze Except One Car
- [ ] Giant Rolling Sphere
- [ ] Zero Gravity Street
- [ ] Lightning Strike Hazard
- [ ] Collapsing Bridge Segment
- [ ] Tentacle Roadblock

### Group B (Zarif remaining)
- [ ] Flash Floods
- [ ] Landslide Debris
- [ ] Low Visibility Fog Bank
- [ ] Sudden Blackout
- [ ] Sinkhole Opening
- [ ] Wrong Turn into Construction Zone
- [ ] Ambulance Stuck at Railroad Crossing
- [ ] Sudden Pedestrian Protest March
- [ ] Runaway Shopping Cart
- [ ] Vehicle Tire Blowout
- [ ] Flooded Underpass
- [ ] Fallen Power Lines
- [ ] Floating Traffic Cones
- [ ] Infinite Loop Road
- [ ] Giant Insects Crossing
- [ ] Melting Asphalt
- [ ] Shattered Glass Rain

### Group C (Awal remaining)
- [ ] Scooter Swerving in Traffic Lane
- [ ] Truck Jackknifing
- [ ] Motorcycle Wheelie / Reckless Rider
- [ ] Pedestrian Dropping Objects
- [ ] Roadside Crowd Spillover
- [ ] Sudden Sandstorm or Dust Cloud
- [ ] Snowstorm with Icy Road
- [ ] Volcanic Ash Fall
- [ ] Bridge Icing Patch
- [ ] Roadside Fire / Smoke Drift
- [ ] Traffic Light Malfunction (All Green/All Red)
- [ ] Drawbridge Lifting Mid-Crossing
- [ ] Tunnel Blockage from Stalled Vehicles
- [ ] Vehicle Hood Pop-Up
- [ ] Drone Crash on Roadway
- [ ] Sudden Earthquake Tremor
- [ ] Magnetic Field Anomaly
- [ ] Illusionary Road Split
- [ ] Portal Opening / Wormhole Disruption

## Execution Rule
- Always pick the next unchecked scene, complete full pipeline + logging, then check it off.
- No parallel scene work until current scene is fully finalized and logged.
