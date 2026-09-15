# Generation artifacts

## Scenario inputs

- `scene_catalog.json`: Figure 1's 30 scenarios, paper display names, stable IDs, prompts, and specifications.
- `Keyword Prompt Verification.xlsx`: the same inputs on a single scene sheet.
- `prompt.txt`: the shared Code Agent prompt and execution contract.

## Retained seed examples

| Scene | Code | Prompt |
| --- | --- | --- |
| Giant tree log blocking the road | [Python](generated_code/giant_tree_log_blocking_the_road/20260222_141049_896767/shot_3/giant_tree_log_blocking_the_road.py) | [Full prompt](generated_prompts/giant_tree_log_blocking_the_road/20260222_141049_896767/shot_3/full_prompt.txt) |
| Oil spill hazard | [Python](generated_code/oil_spill_hazard/20260220_123052_486705/shot_5/oil_spill_hazard.py) | See the scene catalog and script specification |

These scripts expose the environment arguments for the eight-condition runner and checked cleanup. They require CARLA, compatible maps and meshes, and `scene_utils/time_weather_matrix.py`. Keep the repository structure intact so the helper import resolves. Their original scenario-specific camera configurations are preserved; the general generation default is a single front camera.

These are reusable seed examples, not a complete set of 30 generated scenarios. Review a seed against the current scene specification before running it. Changes to cleanup and public configuration have offline test coverage; simulator execution must be checked in the target runtime.

## Human-verified frames

[Manifest and preview](examples/verified_keyframes/README.md) of the human-verified evaluation keyframes, including field definitions and actual scenario coverage.
