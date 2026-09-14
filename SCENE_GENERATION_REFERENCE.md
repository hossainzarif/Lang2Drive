# Scene Generation Reference (3csim + CARLA PythonAPI)

This document is a code-first reference for generating CARLA scenes more accurately in fewer shots.

Scope:
- Reuse useful parts from `3csim` and `PythonAPI`.
- Do **not** run `3csim` scenarios as-is.
- Use these building blocks in our generated scripts and scene loop.

## 1) High-Value Reuse Targets

### A. Reuse from `3csim` (pattern library)

Use these as logic templates, not as full scenario runners.

1. Trigger-zone and event gating primitives  
Source: `3csim/scripts/scenario_files/checks.py`
- `is_inside_bounding_box(...)` (line 9)
- `update_trigger_points(...)` (line 38)
- `adjust_pedestrian_velocity(...)` (line 155)

Why it helps:
- Reliable spatial triggering reduces false starts and timing drift.
- Dynamic trigger shift with ego speed makes events fire at the right moment.
- Pedestrian speed adaptation improves intersection timing realism.

2. Multi-stage event state machines (checkpoint pattern)  
Sources:
- `3csim/scripts/scenario_files/spawn_car_with_item.py` (`self.checkpoint` line 74, staged tick logic around lines 113-140)
- `3csim/scripts/scenario_files/spawn_roadworks_with_workers_NOVAN.py` (`self.checkpoint` and staged behavior around lines 143-171)

Why it helps:
- Scene progression is explicit (`stage0 -> stage1 -> stage2`), so event timing is debuggable and repeatable.
- Easier to tune a single stage without destabilizing the whole scene.

3. Physical event transition pattern (attached -> detached actor)  
Source: `3csim/scripts/scenario_files/spawn_car_with_item.py`
- Item attached to vehicle, then respawned and physics-enabled (`set_simulate_physics(True)` around line 133)

Why it helps:
- Clean way to trigger "drop/fall" events on cue.
- Avoids initial jitter from spawning free-body objects too early.

4. Context prop staging for scene readability  
Source: `3csim/scripts/scenario_files/spawn_roadworks_with_workers_NOVAN.py`
- Structured prop placement (`construction_cone_locations` line 98)
- Pedestrian pose shaping using bones (`set_bones(...)` line 207, `show_pose()` line 208)

Why it helps:
- Better visual cues (workzone context) increase evaluator confidence.
- Pose control improves intent clarity in key frames.

5. Collision and pass/fail instrumentation  
Source: `3csim/scripts/scenario_files/spawn_static_EMS_obstacle.py`
- Per-actor collision sensors (lines 90-92)
- Timer-based completion/failure logic (line 64 and tick lines 126-136)

Why it helps:
- Immediate failure signal is explicit and machine-readable.
- Supports faster diagnosis after each shot.

6. Weather-state cycling pattern  
Source: `3csim/scripts/weather_control.py`
- Preset sun/storm grids (`sun_states` line 24, `storm_states` line 32)
- Deterministic stepping (`world_change_weather(...)` line 65)

Why it helps:
- Simple and stable way to generate controlled weather variants.

7. Texture perturbation / adversarial visual cue pattern  
Source: `3csim/scripts/scenario_files/spawn_change_texture.py`
- `carla.TextureColor(...)` (line 97)
- `world.apply_color_texture_to_object(...)` (line 108)

Why it helps:
- Enables controlled perception stress tests without changing core traffic dynamics.

### B. Reuse from CARLA `PythonAPI` (official baseline patterns)

1. Deterministic sync mode wrapper  
Source: `PythonAPI/examples/synchronous_mode.py`
- `CarlaSyncMode` context manager (line 41)
- Fixed timestep + sync settings (lines 64-65)
- Frame alignment assertion (line 80)

Why it helps:
- Eliminates asynchronous frame mismatch.
- Critical for consistent 5-camera capture and intent evaluation.

2. Sensor queue synchronization pattern  
Source: `PythonAPI/examples/sensor_synchronization.py`
- Queue-based callback aggregation (`sensor_queue` line 71)
- Per-frame sensor waiting logic (`world.tick()` line 107, queue read line 118)

Why it helps:
- Guarantees all sensor streams correspond to the same world frame.

3. Scalable traffic + pedestrians via command batch API  
Source: `PythonAPI/examples/generate_traffic.py`
- TM spacing and sync (`set_global_distance_to_leading_vehicle` line 168, `set_synchronous_mode` line 179)
- Batch spawn (`SpawnActor` line 218, `apply_batch_sync` lines 247/296/310)
- Optional TM controls (`set_respawn_dormant_vehicles` line 170, `set_hybrid_physics_mode` line 172)

Why it helps:
- Fast and reliable dense traffic setup.
- Much better than one-by-one spawn for large scenes.

4. Weather and lighting controls  
Source: `PythonAPI/util/environment.py`
- Presets (`SUN_PRESETS` line 22, `WEATHER_PRESETS` line 27)
- Fine-grained weather overrides (`apply_weather_values` line 86)
- Vehicle/street light control (`apply_lights_to_cars` line 118, light manager line 320)

Why it helps:
- Consistent ambiance control per scene intent.

5. Spawn-point extraction for map-aware generation  
Source: `PythonAPI/util/extract_spawn_points.py`
- Map spawn point export (`get_spawn_points()` line 37, CSV output line 38)

Why it helps:
- Precomputed spawn inventories reduce trial-and-error in generation.

6. Route planning and lane-change feasibility
Sources:
- `PythonAPI/carla/agents/navigation/global_route_planner.py`
  - topology + graph build (`_build_topology` line 84, `_build_graph` line 124)
  - shortest path search (`nx.astar_path` line 298)
- `PythonAPI/carla/agents/navigation/basic_agent.py`
  - destination and route tracing (`set_destination` line 141, `trace_route` line 178)
  - hazard-aware step (`run_step` line 189)
  - toggles for traffic lights/vehicles (`ignore_traffic_lights` line 220, `ignore_vehicles` line 228)
- `PythonAPI/carla/agents/navigation/local_planner.py`
  - waypoint queue and execution (`set_global_plan` line 192, `run_step` line 223)

Why it helps:
- Produces route-consistent behavior and cleaner intersection interactions.

7. Useful geometric helpers for event timing and hazard checks  
Source: `PythonAPI/carla/agents/tools/misc.py`
- `get_speed` line 31
- `get_trafficlight_trigger_location` line 42
- `is_within_distance` line 66
- `vector` line 138
- `compute_distance` line 152

Why it helps:
- Robust geometry utilities reduce ad-hoc math bugs in generated scenes.

## 2) What to Reuse vs What to Avoid

### Reuse
- Scenario-independent helper logic (`checks.py`, agent tools).
- State-machine event progression (checkpoint pattern).
- Batch spawning, sync settings, queue synchronization.
- Weather/light presets + controlled perturbations.
- Map/topology-aware route logic.

### Avoid Copying Directly
- Full `3csim` scenario `main()` runners.
- Hardcoded output paths (for example `E:/CARLA/images` in many 3csim scripts).
- Hardcoded map coordinates unless intentionally map-specific.
- `3csim/scripts/generate_dataset.py` as a pipeline template (contains list/typo issues).

## 3) Practical Generation Recipe (to reduce retries)

For each generated scene script:

1. Deterministic runtime setup
- `world.apply_settings(...)` with sync + fixed delta.
- Seed randomness once and log the seed.

2. Map and route prevalidation
- Load map fresh (`client.load_world(...)`).
- Select spawn points from precomputed inventory or waypoint constraints.
- Validate route feasibility before event injection.

3. Dense context first, event second
- Spawn ambient traffic/walkers with batch API.
- Verify counts by direction (behind/beside/crossing), then trigger event actors.

4. Event as staged state machine
- Build clear checkpoints (`armed`, `active`, `peak`, `resolved`).
- Use trigger-box utilities and speed-adaptive timing.

5. Synchronized sensors and frame naming
- Use queue or `CarlaSyncMode` pattern.
- Save all camera views from the same `frame` id.

6. Instrumentation
- Add collision sensors and pass/fail timers.
- Write a compact scene log with stage transitions and counts.

7. Cleanup
- Stop sensors first.
- Restore world settings.
- Destroy all actors via batch.

## 4) Recommended Internal Reuse Wrappers

Create thin internal modules (in VLM-AV) around borrowed patterns:

- `scene_utils/triggering.py`
  - bbox checks + trigger update logic
- `scene_utils/sync.py`
  - world+sensor sync wrappers
- `scene_utils/traffic_seed.py`
  - batch vehicle/walker spawn and count validation
- `scene_utils/weather.py`
  - weather presets and deterministic stepping
- `scene_utils/weather_snow_profiles.py`
  - snow-capable weather application with native-snow detection + fallback
- `scene_utils/eval_signals.py`
  - collision hooks, stage transitions, success/failure logging

This keeps generated scripts short and reduces prompt drift.

## 5) Official CARLA Documentation Links (primary references)

- Python API reference: https://carla.readthedocs.io/en/latest/python_api/
- Synchrony and timestep: https://carla.readthedocs.io/en/latest/adv_synchrony_timestep/
- Traffic Manager: https://carla.readthedocs.io/en/latest/adv_traffic_manager/
- Actors and blueprints: https://carla.readthedocs.io/en/latest/core_actors/
- Sensors and data: https://carla.readthedocs.io/en/latest/core_sensors/

## 6) Snow Capability Matrix

Use this decision table when generating snow scenes:

1. Patched/native snow build available
- `carla.WeatherParameters` exposes `.snow`.
- Weather blueprint contains snow particle logic and snow assets are present in runtime content.
- Use `scene_utils/weather_snow_profiles.py -> apply_snow_weather(...)`; mode should resolve to `native_snow`.

2. Stock CARLA build (current default in most packaged installs)
- `.snow` Python attribute is unavailable; forcing `weather.snow = ...` is not reliable.
- **However**: snow visual assets (`NE_Snowfall`, `P_snowfall`, `T_SnowTile`, `M_Snow`) ARE already bundled in stock CARLA at `Content/Carla/Static/Particles/Snow/`. The `carla_snow` patch only adds API wiring — the assets themselves are stock.
- Use fallback profile (precipitation + deposits + fog + wind + wetness) for snow-like conditions.
- **Snow ground texture**: Apply `T_SnowTile` to road/ground objects via `world.apply_color_texture_to_object()` for visual snow coverage on surfaces.
- Compensate with behavior tuning (lower speed, larger headway, cautious lane change).

3. Validation rule before scenario execution
- Always log whether applied mode is `native_snow` or `fallback`.
- If `fallback`, do not claim true snow particle rendering in evaluation notes.

## 7) Vendored Reusable Artifacts

These files were copied into this repo for direct reuse/reference:

1. Snow patch assets from `carla_snow-main`
- `assets/carla_snow_patch/Weather/BP_Weather.uasset`
- `assets/carla_snow_patch/Particles/Snow/M_Snow.uasset`
- `assets/carla_snow_patch/Particles/Snow/NE_Snowfall.uasset`
- `assets/carla_snow_patch/Particles/Snow/NE_Snowfall_System.uasset`
- `assets/carla_snow_patch/Particles/Snow/T_SnowTile.uasset`
- `assets/carla_snow_patch/Particles/Snow/Snow1/M_snowfall.uasset`
- `assets/carla_snow_patch/Particles/Snow/Snow1/P_snowfall.uasset`

2. 3csim texture artifacts (useful for adversarial/edited-sign scenes)
- `assets/3csim_textures/T_Cartel_Add_05_Opt_d_1.tga`
- `assets/3csim_textures/T_Cartel_Add_05_Opt_d_2.tga`
- `assets/3csim_textures/T_Cartel_Add_05_Opt_d_3.tga`
- `assets/3csim_textures/T_Cartel_Add_05_Opt_d_4.tga`

3. 3csim actor/prop blueprint catalog
- `knowledge/3csim_blueprint_catalog.json`
- `knowledge/3csim_blueprint_quicklist.md`

## 8) Local Path Index

- 3csim root: `/Users/ashfak/Applications/Sikarugir/CARLA.app/Contents/SharedSupport/prefix/drive_c/Program Files/WindowsNoEditor/VLM-AV/3csim`
- PythonAPI root: `/Users/ashfak/Applications/Sikarugir/CARLA.app/Contents/SharedSupport/prefix/drive_c/Program Files/WindowsNoEditor/PythonAPI`

## 9) StaticMeshFactory — Spawn Any UE4 Static Mesh at Runtime

### Discovery

The stock packaged CARLA binary includes **`AStaticMeshFactory`** which exposes the
blueprint ID **`static.prop.mesh`**. It accepts a `mesh_path` attribute pointing to
any UE4 static mesh in the game content, enabling runtime spawning of trees, rocks,
bushes, signs, and any other mesh — without a source rebuild or PropFactory patch.

Confirmed via: `strings CarlaUE4-Win64-Shipping.exe | grep static.prop.mesh`

### API Reference

```python
bp_lib = world.get_blueprint_library()
bp = bp_lib.find('static.prop.mesh')

# Required: UE4 content path to the static mesh asset
bp.set_attribute('mesh_path', '/Game/Carla/Static/Vegetation/Trees/SM_BeechTree_3.SM_BeechTree_3')

# Optional: mass in kg (>0 enables physics simulation; 0 or omit = static fixture)
bp.set_attribute('mass', '0')

actor = world.try_spawn_actor(bp, transform)
```

### Content Path Format

```
/Game/Carla/Static/<Category>/<SubCategory>/<MeshName>.<MeshName>
```

The mesh name is repeated after the dot (UE4 .uasset convention).

Helper function:
```python
def mesh_content_path(category, subcategory, mesh_name):
    """Build UE4 content path for a CARLA static mesh."""
    return f'/Game/Carla/Static/{category}/{subcategory}/{mesh_name}.{mesh_name}'

# Examples:
mesh_content_path('Vegetation', 'Trees', 'SM_BeechTree_3')
# => '/Game/Carla/Static/Vegetation/Trees/SM_BeechTree_3.SM_BeechTree_3'

mesh_content_path('Vegetation', 'Rocks', 'SM_Rock_01')
# => '/Game/Carla/Static/Vegetation/Rocks/SM_Rock_01.SM_Rock_01'
```

### Tree Mesh Catalog (Vegetation/Trees — 145+ meshes)

Content path prefix: `/Game/Carla/Static/Vegetation/Trees/`

| Species | Meshes |
|---------|--------|
| Beech | `SM_Beech` |
| Acer | `SM_Acer_02`, `SM_Acer_Red_01` |
| Aporosa | `SM_Aporosa`, `SM_Aporosa_base` |
| Ash | `SM_Ash_01`, `SM_Ash_02` |
| CoconutPalm | `SM_CoconutPalm_01`, `SM_CoconutPalm_02`, `SM_CoconutPalm_02_base` |
| Cypress | `SM_Cypress`, `SM_Cypress_Small` |
| FanPalm | `SM_FanPalm_01`, `SM_FanPalm_02`, `SM_FanPalm_03` |
| Japanese Maple | `SM_Japanese_Maple_01`, `SM_Japanese_Maple_03`, `SM_Japanese_Maple_04` |
| Maple Base M | `SM_Maple_Base_M_v1` – `SM_Maple_Base_M_v8` |
| Maple Base S | `SM_Maple_Base_S_v1` – `SM_Maple_Base_S_v8` |
| Maple L | `SM_Maple_L_v1` – `SM_Maple_L_v8` |
| Maple M | `SM_Maple_M_v1` – `SM_Maple_M_v8` |
| Maple S | `SM_Maple_S_v1` – `SM_Maple_S_v8` |
| Oak Base M | `SM_Oak_Base_M_v1` – `SM_Oak_Base_M_v8` |
| Oak Base S | `SM_Oak_Base_S_v1` – `SM_Oak_Base_S_v8` |
| Oak L | `SM_Oak_L_v1` – `SM_Oak_L_v8` |
| Oak M | `SM_Oak_M_v1` – `SM_Oak_M_v8` |
| Oak S | `SM_Oak_S_v1` – `SM_Oak_S_v8` |
| Pine Base M | `SM_Pine_Base_M_v1` – `SM_Pine_Base_M_v8` |
| Pine Base S | `SM_Pine_Base_S_v1` – `SM_Pine_Base_S_v8` |
| Pine L | `SM_Pine_L_v1` – `SM_Pine_L_v8` |
| Pine M | `SM_Pine_M_v1` – `SM_Pine_M_v8` |
| Pine S | `SM_Pine_S_v1` – `SM_Pine_S_v8` |
| Sassafras | `SM_Sassafras_01`, `SM_Sassafras_02`, `SM_Sassafras_03` |
| TreePine | `SM_TreePine_1`, `SM_TreePine_2`, `SM_TreePine_3` |
| Walnut | `SM_Wallnut_01` |

### Bushes Catalog (Vegetation/Bushes — 21 meshes)

Content path prefix: `/Game/Carla/Static/Vegetation/Bushes/`

| Meshes |
|--------|
| `SM_Bush`, `SM_Bush_L_v1`–`SM_Bush_L_v5`, `SM_Bush_M_v1`–`SM_Bush_M_v5` |
| `SM_Cypress_Bush`, `SM_Hedge_01`, `SM_Pine_Bush`, `SM_Willow_Bush` |
| `SM_longLeavesBush_01`, `SM_longLeavesBush_02`, `SM_longLeavesBush_03` |
| `SM_oldBush_01`, `SM_oldBush_02`, `SM_oldBush_03` |

### Rocks / Stones Catalog (Vegetation/Rocks — 6 meshes)

Content path prefix: `/Game/Carla/Static/Vegetation/Rocks/`

| Meshes |
|--------|
| `SM_Stone_1`, `SM_Stone_2`, `SM_Stone_3`, `SM_Stone_4` |
| `SM_Town03_SM_stone01`, `SM_Town03_SM_stone02` |

### Grass Catalog (Vegetation/Grass — 7 meshes)

Content path prefix: `/Game/Carla/Static/Vegetation/Grass/`

| Meshes |
|--------|
| `SM_Grass`, `SM_GrassLeaf_01`–`SM_GrassLeaf_05`, `SM_SmallGrassv2` |

### Plants & Flowers Catalog (Vegetation/Plants_and_Flowers — 5 meshes)

Content path prefix: `/Game/Carla/Static/Vegetation/Plants_and_Flowers/`

| Meshes |
|--------|
| `SM_Dandelion`, `SM_plantPot_bloom`, `SM_Poppy`, `SM_Rushes`, `SM_WheatField_01` |

### Leaves Catalog (Vegetation/Leaves — 3 meshes)

Content path prefix: `/Game/Carla/Static/Vegetation/Leaves/`

| Meshes |
|--------|
| `SM_Leaf03_v1`, `SM_Leaf04_v1`, `SM_Leaf05_v1` |

### Construction / Dynamic Props (Dynamic/* — 100+ meshes)

These are moveable scene props — ideal for construction zones, debris, trash, garden, restaurant staging.

**Dynamic/Construction/** — Content path prefix: `/Game/Carla/Static/Dynamic/Construction/`

| Meshes |
|--------|
| `SM_ConstructionCone`, `SM_SheelBarrow`, `SM_StreetBarrier` |
| `SM_TrafficCones_01`, `SM_TrafficCones_02`, `SM_TrafficCones_03` |
| `SM_WarningAccident`, `SM_WarningConstruction` |

**Dynamic/Trash/** — Content path prefix: `/Game/Carla/Static/Dynamic/Trash/`

| Meshes |
|--------|
| `SM_Barrel`, `SM_BigContainer`, `SM_Bin`, `SM_Box01`, `SM_box02`, `SM_box03` |
| `SM_ClothContainer`, `SM_Container`, `SM_CreasedBox01`, `SM_CreasedBox01_v2`, `SM_CreasedBox02`, `SM_CreasedBox03` |
| `SM_Dumpster`, `SM_GlassContainer`, `SM_TrasdhBag`, `SM_TrashCan01`, `SM_TrashCan03` |

**Dynamic/Trash/Wastes/** — Content path prefix: `/Game/Carla/Static/Dynamic/Trash/Wastes/`

| Meshes |
|--------|
| `SM_BagPaper`, `SM_BagPlastic`, `SM_BottlePlastic` |
| `SM_BrokenTile01`–`SM_BrokenTile04` |
| `SM_Can01`, `SM_Can02`, `SM_Can04`, `SM_Can05`, `SM_ColaCan` |
| `SM_CupPaper`, `SM_Garbage01`–`SM_Garbage08` |
| `SM_IronPlank`, `SM_Newspaper01`, `SM_Newspaper02`, `SM_Newspaper02_v2` |

**Dynamic/Garden/** — Content path prefix: `/Game/Carla/Static/Dynamic/Garden/`

| Meshes |
|--------|
| `SM_Barbecue`, `SM_ClothesLine`, `SM_DogHouse`, `SM_GardenLamp`, `SM_Gnome` |
| `SM_Pergola`, `SM_PlasticChair`, `SM_PlasticTable`, `SM_SwingCouch` |
| `SM_Table`, `SM_Trampoline`, `SM_WateringCan` |

**Dynamic/PedestrianProps/** — Content path prefix: `/Game/Carla/Static/Dynamic/PedestrianProps/`

| Meshes |
|--------|
| `SM_bikehelmet`, `SM_Briefcase`, `SM_GuitarCase`, `SM_Letter`, `SM_Mobile` |
| `SM_PlasticBag`, `SM_Purse`, `SM_ShoppinCart`, `SM_ShoppingBag`, `SM_ShoppingTrolley`, `SM_TravelCase` |

**Dynamic/Bar-Restaurant/** — Content path prefix: `/Game/Carla/Static/Dynamic/Bar-Restaurant/`

| Meshes |
|--------|
| `SM_Advertise`, `SM_Bbottle`, `SM_Chair`, `SM_CoffeCup`, `SM_Glass` |
| `SM_NapkinBox`, `SM_Plate`, `SM_Table_Round`, `SM_Table_Square` |

**Dynamic/Farm/** — Content path prefix: `/Game/Carla/Static/Dynamic/Farm/`

| Meshes |
|--------|
| `SM_hayBale`, `SM_hayBale_LB` |

### Street Furniture / Static Objects (Static/* — 80+ meshes)

Content path prefix: `/Game/Carla/Static/Static/`

| Sub-path | Meshes |
|----------|--------|
| (root) | `SM_Atm`, `SM_AtmCashier`, `SM_Barrier`, `SM_basket1` |
| (root) | `SM_Bench01`, `SM_Bench02`, `SM_Bench03`, `SM_BikeParking` |
| (root) | `SM_CarlaCola`, `SM_Cartel_Add_02`, `SM_ChainBarrier`, `SM_ChainBarrierEnd` |
| (root) | `SM_FireHdrant`, `SM_Fountain`, `SM_Fountain_02`, `SM_Fountain_03`, `SM_fountainSmall` |
| (root) | `SM_LightBox1`, `SM_LightBox2`, `SM_MailBox`, `SM_MapTable` |
| (root) | `SM_ParkingBarrier`, `SM_ParkingBarrier_Short` |
| (root) | `SM_Plantpot01`–`SM_PlantPot08`, `SM_PlantpotM2`, `SM_PlantpotM3` |
| (root) | `SM_PlatformGarbage01`, `SM_Sculpture01`, `SM_Sculpture02` |
| (root) | `SM_Slide`, `SM_StandNews`, `SM_StreetAD01`–`SM_StreetAD04` |
| (root) | `SM_StreetBench`, `SM_StreetCounter`, `SM_StreetFountain`, `SM_Swing` |
| (root) | `SM_TrashCan04`, `SM_TrashCan05`, `SM_TrashCan1`, `SM_TrashCan2`, `SM_trashCanV3` |
| (root) | `SM_TreePot`, `SM_TreePot_round` |
| Billboard/ | `SM_Billboard1`, `SM_Billboard2`, `SM_Billboard3` |
| Calibrator/ | `SM_calibration` |
| Chainbarrier/ | `SM_LightPost`, `SM_RopePost`, `SM_RopePostEnd` |
| Materials/BusStop/ | `SM_BusStop`, `SM_BusStop_LB` |

### Traffic Signs (TrafficSign/* — 55+ meshes)

Content path prefix: `/Game/Carla/Static/TrafficSign/`

| Sub-path | Meshes |
|----------|--------|
| Stop/ | `SM_stopSign` |
| Yeld/ | `SM_yield_` |
| OneWay/ | `SM_oneWayR` |
| PostSigns/ | `SM_InterchangeSign_03_Cartel`, `SM_RoundSign` |
| SpeedLimiters/ | `SM_SpeedSign30`, `SM_SpeedSign40`, `SM_SpeedSign50`, `SM_SpeedSign60`, `SM_SpeedSign70`, `SM_SpeedSign80`, `SM_SpeedSign90`, `SM_SpeedSign100`, `SM_SpeedSign110`, `SM_SpeedSign120` |
| TrafficSigns_A1/ | `SM_A01busNoPark`, `SM_A01cleanPet`, `SM_A01minPark`, `SM_A01noBicyc`, `SM_A01nopark`, `SM_A01noPed`, `SM_A01noStand`, `SM_A01onlyCrossw`, `SM_A01parking`, `SM_A01photo`, `SM_A01reserved`, `SM_A01stopPed`, `SM_A01tow`, `SM_A01yieldPed` |
| TrafficSigns_A1/ | `SM_FlagPark`, `SM_FlagStreet`, `SM_letterAv`, `SM_letterSt`, `SM_OneWay_L_Atlas`, `SM_OneWay_R_Atlas`, `SM_passenger` |

### Traffic Lights (TrafficLight/* — 11 meshes)

Content path prefix: `/Game/Carla/Static/TrafficLight/`

| Meshes |
|--------|
| `SM_TrafficLight__Light01`, `SM_TrafficLight__Light02`, `SM_TrafficLight__Light03` |
| `SM_TrafficLight__Push_Letter`, `SM_TrafficLight__TLight_SIDE_big`, `SM_TrafficLight__TLight_walk` |
| `SM_TrafficLight_holster` |
| Streetlights_01/: `SM_TL_BotCover`, `SM_TLights_Leds`, `SM_TLights_suport`, `SM_TLights_Top` |

### GuardRails / Safety Barriers (GuardRail/* — 10 meshes)

Content path prefix: `/Game/Carla/Static/GuardRail/`

| Meshes |
|--------|
| `SM_Guardrail_02` |
| `SM_Secfence_01`–`SM_Secfence_05`, `SM_SecFence_02`, `SM_SecFence_06` |
| `SM_SecWaterDrums_01`, `SM_SecWaterDrums_02`, `SM_SecWaterDrums03` |

### Fences (Fence/* — 12+ generic meshes)

Content path prefix: `/Game/Carla/Static/Fence/`

| Meshes |
|--------|
| `SM_FenceCorner`, `SM_FenceMiddle`, `SM_fenceV1`, `SM_fenceV3`, `SM_fenceV4`, `SM_fenceV6` |
| `SM_FenceWood`, `SM_UrbanFence02`, `SM_UrbanFenceV2` |
| `SM_Wall04`, `SM_Wall09`, `SM_Wall10`, `SM_WallBridge`, `SM_WallBridge_2`, `SM_WireFence` |

### Walls (Wall/* — 18+ generic meshes)

Content path prefix: `/Game/Carla/Static/Wall/`

| Meshes |
|--------|
| `SM_ColumnTunnel`, `SM_fountainBig_T03`, `SM_ParkWallCorner`, `SM_ParkWallLeft` |
| `SM_Wall01`–`SM_Wall03`, `SM_Wall05`–`SM_Wall08`, `SM_Wall11`–`SM_Wall13`, `SM_Wall15` |
| `SM_WallHighWay_1`, `SM_WallShort_1`, `SM_WallTunnel01` |

### Bridge (Bridge/* — 7 meshes)

Content path prefix: `/Game/Carla/Static/Bridge/`

| Meshes |
|--------|
| `SM_Beam01`, `SM_Bridge`, `SM_Bridge_Rail`, `SM_BridgePilar` |
| `SM_Pier`, `SM_Pier_Square`, `SM_town03_SM_terrain01` |

### Poles / Electric / Street Lights (Pole/* — 40+ meshes)

Content path prefix: `/Game/Carla/Static/Pole/`

| Sub-path | Meshes |
|----------|--------|
| (root) | `SM_BaseRailTrain01`, `SM_BaseRailTrain02`, `SM_basketFence_SM_basketWire` |
| (root) | `SM_InterchangeSign_03_Pole`, `SM_Pole_Add_02`, `SM_PoleCylinder` |
| (root) | `SM_RoadSigns01`, `SM_Traffic_Light_Base`, `SM_TrafficLight01`, `SM_TrafficLight02`, `SM_Trafficpole_2` |
| PoweLine/ | `SM_ElectricPole01`–`SM_ElectricPole04` |
| SM_Lights/ | `SM_Bollard01`, `SM_parkLightV2`, `SM_SpotLight`, `SM_StreetLightWall` |
| TrafficLight/ | `SM_TrafficLight__Ground_base`, `SM_TrafficLight__HPole01_Long`, `SM_TrafficLight__HPole01_Mid`, `SM_TrafficLight__HPole01_Short`, `SM_TrafficLight__TLight_StreetLight`, `SM_TrafficLight__VPole_Main` |

### Rail Tracks (RailTrack/* — 11 meshes)

Content path prefix: `/Game/Carla/Static/RailTrack/`

| Meshes |
|--------|
| `SM_RailTrain`, `SM_RailTrain02` |
| `SM_T03_RailTrain01`–`SM_T03_RailTrain04` |
| `SM_Town05_RailTrain03`–`SM_Town05_RailTrain05` |

### Road Ramps (Road/Ramp — 4 meshes)

Content path prefix: `/Game/Carla/Static/Road/Ramp/`

| Meshes |
|--------|
| `SM_Ramp01`, `SM_Ramp02`, `SM_Ramp03`, `SM_Ramp04` |

### Water (Water/* — 4 meshes)

Content path prefix: `/Game/Carla/Static/Water/`

| Meshes |
|--------|
| `SM_Beach`, `SM_Sea`, `SM_sea2M`, `SM_TileLake` |

### Other / Misc (Other/* — 12+ meshes)

Content path prefix: `/Game/Carla/Static/Other/`

| Sub-path | Meshes |
|----------|--------|
| (root) | `SM_DirtDebris01`, `SM_DirtDebris02`, `SM_DirtDebris03`, `SM_Plane`, `SM_StairField`, `SM_wire` |
| Banner/ | `SM_banner`, `SM_bannerShort0B`, `SM_bannerSingle`, `SM_bannerSinglePole`, `SM_bannerSinglePoleShort`, `SM_bannerSingleShort` |
| SkatePark/ | `SM_skatePark_isle`, `SM_skatePark_Ramp`, `SM_skatePark_V`, `SM_SkatePool` |

### Particles & Weather Assets (NOT spawnable via `static.prop.mesh`)

These assets exist in stock CARLA but are **not** static meshes — they are materials,
particle systems, Niagara effects, and textures. They cannot be spawned with
`static.prop.mesh`. Use them via the APIs noted below.

**Snow** — Content path prefix: `/Game/Carla/Static/Particles/Snow/`

| Asset | Type | Usage |
|-------|------|-------|
| `M_Snow` | Material | Referenced by BP_Weather for snow surface appearance |
| `NE_Snowfall` | Niagara Effect | Snowfall particle emitter |
| `NE_Snowfall_System` | Niagara System | Snowfall system controller |
| `T_SnowTile` | Texture | Snow ground texture — can be applied to road/ground objects via `world.apply_color_texture_to_object()` |
| `Snow1/M_snowfall` | Material | Alternative snow material |
| `Snow1/P_snowfall` | Particle System | Alternative snowfall particle emitter |

**Rain** — Content path prefix: `/Game/Carla/Static/Particles/rain/`

| Asset | Type | Usage |
|-------|------|-------|
| `M_Rain` | Material | Rain drop material |
| `PS_Rain` | Particle System | Rain particle emitter |
| `T_ripples_sheet_HD_n` | Texture | Rain puddle ripple normal map |

**Falling Leaves** — Content path prefix: `/Game/Carla/Static/Particles/Leaves/`

| Asset | Type | Usage |
|-------|------|-------|
| `M_Leaf_falling` | Material | Falling leaf material |
| `PS_LeavesFalling` | Particle System | Leaf fall emitter |
| `SM_Leaf05_v5` | Static Mesh | Leaf mesh used by particle system (this one IS spawnable via `static.prop.mesh`) |

**Weather Blueprint** — `/Game/Carla/Blueprints/Weather/BP_Weather`

| Asset | Type | Notes |
|-------|------|-------|
| `BP_Weather` | Blueprint | Master weather controller — references snow/rain particles internally. Already present in stock CARLA. |

> **Key insight**: Snow particle assets (`NE_Snowfall`, `P_snowfall`, `T_SnowTile`) are
> **already bundled in stock packaged CARLA** — they are NOT exclusive to the `carla_snow` patch.
> The patch adds the Python API `.snow` attribute wiring; the visual assets are already there.
> For snow scenes on stock builds, use `scene_utils/weather_snow_profiles.py` fallback
> (precipitation + fog + wetness) and optionally apply `T_SnowTile` texture to ground objects
> for visual snow coverage.

### Usage Patterns

**Standing tree (static roadside decoration):**
```python
bp = bp_lib.find('static.prop.mesh')
bp.set_attribute('mesh_path', '/Game/Carla/Static/Vegetation/Trees/SM_OakTree_L_2.SM_OakTree_L_2')
bp.set_attribute('mass', '0')  # static fixture
tree = world.try_spawn_actor(bp, carla.Transform(
    carla.Location(x=100.0, y=-5.0, z=0.0),
    carla.Rotation(pitch=0, yaw=0, roll=0)
))
```

**Fallen tree blocking road (physics-enabled):**
```python
bp = bp_lib.find('static.prop.mesh')
bp.set_attribute('mesh_path', '/Game/Carla/Static/Vegetation/Trees/SM_BeechTree_3.SM_BeechTree_3')
bp.set_attribute('mass', '800')  # heavy fallen tree with physics
tree = world.try_spawn_actor(bp, carla.Transform(
    carla.Location(x=80.0, y=0.0, z=0.5),
    carla.Rotation(pitch=0, yaw=45, roll=-90)  # tipped on its side
))
```

**Batch spawning diverse trees along a road:**
```python
import random

TREE_MESHES = [
    'SM_BeechTree_3', 'SM_OakTree_M_3', 'SM_Pine_L_1',
    'SM_Maple_M_5', 'SM_Cypress_1', 'SM_JapaneseMaple_1',
]

def spawn_tree_row(world, bp_lib, base_location, count=10, spacing=8.0, roadside_offset=6.0):
    trees = []
    for i in range(count):
        bp = bp_lib.find('static.prop.mesh')
        mesh = random.choice(TREE_MESHES)
        bp.set_attribute('mesh_path', f'/Game/Carla/Static/Vegetation/Trees/{mesh}.{mesh}')
        bp.set_attribute('mass', '0')
        loc = carla.Location(
            x=base_location.x + i * spacing,
            y=base_location.y + roadside_offset,
            z=base_location.z
        )
        actor = world.try_spawn_actor(bp, carla.Transform(loc))
        if actor:
            trees.append(actor)
    return trees
```

### Key Rules

1. **Always prefer `static.prop.mesh`** over improvising with barrels/boxes when realistic objects are needed.
2. **Mesh path must be exact** — typos cause silent spawn failure (returns `None`).
3. **`mass=0`** = static fixture (no physics). **`mass>0`** = physics-enabled (use for fallen/tumbling objects).
4. **Cleanup**: Actors spawned via `static.prop.mesh` are destroyed normally via `actor.destroy()`.
5. **Works in stock packaged CARLA** — no source rebuild, no plugin, no UE4 Editor needed.

---

Use this file as a generation-time checklist and source index.  
Goal: better first-shot scene quality by combining deterministic PythonAPI baselines with tested 3csim event patterns.
