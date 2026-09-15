# Human-verified evaluation keyframes

This collection indexes **1,200 human-verified frames** from **30 source scenarios**, across **eight weather-time conditions**, with **five temporally ordered frames per scenario-condition pair**. The images were selected and checked by human reviewers. The selection does not use the automated CLIP top-30 procedure.

[JSON manifest](manifest.json) · [CSV manifest](manifest.csv)

The manifest covers the verified collection. Three consolidated scene-review sheets are included below; the full image set is not stored in this repository.

## Manifest fields

| Field | Meaning |
| --- | --- |
| `scenario_id` | Stable source scenario identifier |
| `paper_display_name` | Figure 1 name, or null when the source scenario is outside that roster |
| `hazard_family` | `road_user`, `traffic_control`, `obstruction`, `dynamic_object`, or `environmental` |
| `weather`, `time_of_day` | Paper weather labels and Noon/Night |
| `frame_id`, `temporal_order` | Original frame identifier and position within the five-frame selection |
| `dataset_path` | Relative path within the external dataset |
| `sha256` | SHA-256 of the original PNG bytes |
| `width`, `height` | Image dimensions in pixels |
| `visual_verification_status` | `human_verified`: the selected frame was checked by a human reviewer |

Source folder aliases `storm` and `worst` correspond to Heavy Rainy and Stormy, respectively. Paths preserve these aliases. Human verification records a visual review; it does not certify dynamics, collision-free execution, annotation quality, or a particular model's performance.

## Coverage

The collection covers 29 of Figure 1's 30 scenarios and also includes `wrongway_driver`, whose `paper_display_name` is null. No verified frames for `zero_gravity_street` (Overhead car crash) are included. The source IDs `floating_rocks_on_the_road` and `zero_gravity_street` map to Landslide rocks on the road and Overhead car crash in the paper. Counts describe this collection, rather than establishing identity with any experimental split.

## Scene-wise human verification

Each consolidated review sheet shows **eight weather-time conditions in rows** and **five temporally ordered keyframes per row**, allowing the scene progression and environmental variation to be inspected together. Numbers beneath the images identify the source frames.

These are the consolidated images used for human review. Their row labels preserve source aliases: `storm` means **Heavy Rainy**, and `worst` means **Stormy**. Where a row says “400 source frames,” that is the source sequence length; five selected frames are displayed. The manifest checksums refer to the individual source PNGs, not these JPEG review sheets.

### Bicycle in highway lane

[Open full-resolution review sheet](preview/bicycle_in_highway_lane.jpg)

![Bicycle in highway lane: human verification across eight weather-time conditions](preview/bicycle_in_highway_lane.jpg)

### Red-light violation

[Open full-resolution review sheet](preview/red_light_violation.jpg)

![Red-light violation: human verification across eight weather-time conditions](preview/red_light_violation.jpg)

### Ladder falling from vehicle

[Open full-resolution review sheet](preview/ladder_falling_from_truck.jpg)

![Ladder falling from vehicle: human verification across eight weather-time conditions](preview/ladder_falling_from_truck.jpg)
