# Asset Reuse Manifest (Snow + 3csim)

This file tracks which copied artifacts are immediately usable in scene scripts and which require CARLA source/runtime patching.

## Immediately Usable in Current Workflow

1. 3csim texture assets (for texture-change/adversarial visual scenes)
- `assets/3csim_textures/T_Cartel_Add_05_Opt_d_1.tga`
- `assets/3csim_textures/T_Cartel_Add_05_Opt_d_2.tga`
- `assets/3csim_textures/T_Cartel_Add_05_Opt_d_3.tga`
- `assets/3csim_textures/T_Cartel_Add_05_Opt_d_4.tga`

Usage pattern:
- Load with PIL/OpenCV in script.
- Convert to `carla.TextureColor`.
- Apply to target map object via `world.apply_color_texture_to_object(...)`.

2. 3csim actor/prop IDs as generation vocabulary
- `knowledge/3csim_blueprint_catalog.json`

Usage pattern:
- Pick blueprint IDs known to exist in scenario files.
- Prefer IDs with multiple source-file appearances for higher availability.

3. **`static.prop.mesh` (StaticMeshFactory) — Universal mesh spawner**
- Built into stock packaged CARLA (confirmed in shipping binary).
- Blueprint: `static.prop.mesh`
- Attributes: `mesh_path` (UE4 content path), `mass` (float, >0 = physics), `scale` (float).
- Spawns ANY UE4 static mesh at runtime: trees, rocks, bushes, signs, barriers, etc.
- No source rebuild, no plugin, no UE4 Editor needed.

Usage pattern:
```python
bp = bp_lib.find('static.prop.mesh')
bp.set_attribute('mesh_path', '/Game/Carla/Static/Vegetation/Trees/SM_BeechTree_3.SM_BeechTree_3')
bp.set_attribute('mass', '0')  # 0=static, >0=physics
actor = world.try_spawn_actor(bp, transform)
```
- See `SCENE_GENERATION_REFERENCE.md` §9 for full mesh catalog.

4. Snow-like weather fallback helper
- `scene_utils/weather_snow_profiles.py`

Usage pattern:
- `apply_snow_weather(world, carla, intensity=80.0)` and log returned mode.

## Rebuild-Time / Patch-Time Assets

These are useful references, but do not activate snow in stock packaged CARLA by themselves.

1. Snow weather blueprint and particles
- `assets/carla_snow_patch/Weather/BP_Weather.uasset`
- `assets/carla_snow_patch/Particles/Snow/*`

2. Source patch reference (from cloned `carla_snow-main`)
- Adds `snow` field into weather RPC/Python/UE structs.
- Requires rebuilding and packaging CARLA to be truly active runtime functionality.

## Recommended Agent Behavior

1. Default to stock-compatible fallback (precipitation/fog/wetness/wind).
2. Use native snow only when runtime capability is confirmed (`supports_native_snow(...) == True`).
3. Keep scene logs explicit: `snow_mode=native_snow|fallback`.
