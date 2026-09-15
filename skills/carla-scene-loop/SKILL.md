---
name: carla-scene-loop
description: Prepare, review, and refine CARLA corner-case scenes using the Lang2Drive shared manifest workflow.
---

# CARLA scene loop

Read `SCENE_GENERATION_REFERENCE.md` from the repository root before preparing a scene. Use `scene_catalog.json`, the selected workbook row, and `prompt.txt` as the generation inputs.

1. Prepare one scene with `agent_skill_scene_loop.py prepare --scene-serial N`.
2. Inspect the scene-specific constraints and enhance the prompt without changing its event intent.
3. Implement the generated script, reusing a compatible seed where available. Preserve required environment arguments, camera capture, logging, and checked cleanup.
4. Validate readiness using the explicit manifest path.
5. Run the baseline only in the configured simulator environment. Avoid concurrent simulator clients.
6. Review event frames and logs with the scene Evaluator Agent. Preserve structured failure feedback and prior attempts before refining.
7. After baseline acceptance, use the resumable eight-condition matrix entrypoint and review the resulting captures.

Keep scene-generation review separate from downstream model evaluation. Report actual execution and visual evidence; dry runs and frame counts do not establish scene correctness.
