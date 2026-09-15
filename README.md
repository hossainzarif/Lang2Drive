# Lang2Drive

**Agentic Prompt-to-Scene Generation and Vision-Language Reasoning for Safety-Critical Autonomous Driving**

Lang2Drive transforms natural-language corner-case descriptions into CARLA scenarios through a Text Scene Agent, Code Agent, and Evaluator Agent. A shared handoff manifest carries the scene specification, execution outputs, and feedback between refinement attempts.

## Scene generation

1. **Specify:** choose a scene and its constraints from the scenario workbook.
2. **Generate:** prepare the code-generation prompt and implement a standalone CARLA script, reusing a relevant seed when available.
3. **Execute:** check readiness, then run the script against CARLA.
4. **Evaluate and refine:** inspect the front-camera event and execution evidence; use structured feedback to revise unsuccessful attempts.
5. **Vary conditions:** capture the finalized scene under four weather conditions at Noon and Night.

The [scenario catalog](scene_catalog.json) follows Figure 1's 30 scenarios in five hazard families. The [generation guide](SCENE_GENERATION_REFERENCE.md) explains the agent workflow, manifests, refinement, and runtime requirements.

| Hazard family | Scenarios |
| --- | ---: |
| Road-User Interactions & Traffic-Rule Violations | 6 |
| Traffic-Control & Infrastructure Disruptions | 6 |
| Roadway Obstructions & Structural Debris | 6 |
| Dynamic Object Intrusions | 7 |
| Environmental & Road-Surface Hazards | 5 |

### Setup

Use Python 3.10+ and a separately installed CARLA runtime with a matching CARLA Python API. Run the simulation commands in the Python environment that can connect to that runtime.

```bash
python -m pip install -r requirements-generation.txt
python agent_skill_scene_loop.py list-scenes
```

For macOS preparation with a CARLA Wine bundle, set `CARLA_APP_PATH` to the bundle's location. Execute simulation commands in Windows/Wine. Native Windows or Linux installations can run them directly with their matching CARLA Python environment.

### Prepare a scene

```bash
python agent_skill_scene_loop.py prepare --scene-serial 1
```

The command prints the new manifest, prompt, and code paths. Preparation copies an available seed or creates a placeholder; it does not by itself complete code generation. Use the full prompt and scene specification to implement the script, then run the explicit readiness, simulation, and review commands in the [generation guide](SCENE_GENERATION_REFERENCE.md).

### Eight weather-time conditions

| Public label | Stable configuration key |
| --- | --- |
| Clear | `clear` |
| Heavy Rainy | `storm` |
| Stormy | `worst` |
| Foggy | `foggy` |

Each weather is paired with `noon` and `night`. Existing directory keys are retained for compatibility; the numerical presets are defined in [the matrix specification](scene_utils/time_weather_matrix_spec.json).

After baseline review, run the resumable matrix using an explicit manifest:

```cmd
04_run_scene_matrix8.cmd "path\to\manifest.json"
```

Completed variants are revalidated before skipping. Failed or incomplete attempts are preserved before retry. The runner stops when cleanup is unverified. Capture integrity and visual acceptance are separate checks.

## Examples and human-verified frames

- [Generation artifacts](ARTIFACT_INDEX.md): retained prompt/code examples and their runtime requirements.
- [Human-verified keyframes](examples/verified_keyframes/README.md): a manifest of the human-reviewed collection and consolidated human-review sheets for three scenes.

## Verification

```bash
python -m unittest discover -s tests -q
```

The tests exercise generation helpers, readiness, scene-evaluation acceptance, and resumable capture using temporary fixtures. They do not start CARLA or invoke a model service.
