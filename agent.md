# VLM-AV Agent Context

## Source Of Truth
- Use `skills/carla-scene-loop/SKILL.md` as the authoritative workflow for:
  - scene selection
  - generation contract
  - standalone runtime requirements
  - Wine handoff flow
  - strict evaluation loop
- If this file conflicts with the skill, the skill wins.

## Repo-Specific Additions

### Post-Loop Logging
- After each completed or rerun scene loop, refresh both history workbooks:
  - `python3 shot_history_excel.py --manifest handoffs/<run_id>/<scenario_keyword>/manifest.json`
  - `python3 research_scene_history_excel.py`

### Reporting Outputs
- Per-run shot workbook:
  - `handoffs/<run_id>/<scenario_keyword>/shot_history.xlsx`
- Unified scene history workbook:
  - `handoffs/research_scene_history.xlsx`

### Key Scripts
- `agent_skill_scene_loop.py`: prepare/mark-ready/list-scenes orchestration
- `agentic_wine_handoff_runner.py`: stage-2 runner; writes simulation results + stage2 logs
- `agentic_visual_evaluator.py`: strict visual evaluation flow
- `shot_history_excel.py`: builds per-run shot history workbook
- `research_scene_history_excel.py`: builds unified chart-ready scene history workbook
- `automated_scene_generator.py`: legacy pipeline kept for compatibility

### Compatibility Requirement
- Keep these output/report paths stable:
  - `generated_prompts/`
  - `generated_code/`
  - `scenes/`
  - `intervention_report_*.json`
  - `intervention_summary*.csv`
  - `scenario_intervention_data*.csv`
