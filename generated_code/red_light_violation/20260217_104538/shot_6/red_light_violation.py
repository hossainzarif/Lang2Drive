#!/usr/bin/env python3

import argparse
import math
import os
import random
import sys
import threading
import time
from collections import defaultdict

import numpy as np
from PIL import Image

try:
    import carla
except ImportError:
    print("[ERROR] CARLA Python API not found. Please install it.")
    sys.exit(1)

CAMERA_KEYS = ["front", "front_left", "front_right", "rear", "drone_follow"]
images_received = {key: None for key in CAMERA_KEYS}
images_lock = threading.Lock()
frame_ready = threading.Event()
collision_detected = False

BUSY_MIN_PER_DIRECTION = 20
BUSY_TOTAL_MIN = 80
NEARBY_TARGETS = {"behind": 6, "beside": 8, "crossing": 8}
NON_EGO_SIGNAL_CYCLE = [
    (carla.TrafficLightState.Green, 100),
    (carla.TrafficLightState.Yellow, 20),
    (carla.TrafficLightState.Red, 60),
]


def save_image_to_disk(image, output_path):
    """Save CARLA image as RGB PNG."""
    try:
        if image is None:
            return False
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = array.reshape((image.height, image.width, 4))
        array = array[:, :, :3][:, :, ::-1]  # BGRA -> RGB
        img = Image.fromarray(array)
        img.save(output_path, "PNG")
        return True
    except Exception as err:
        print(f"[ERROR] Failed to save image: {err}")
        return False


def make_camera_callback(camera_name):
    def callback(image):
        with images_lock:
            images_received[camera_name] = image
            if all(images_received[k] is not None for k in CAMERA_KEYS):
                frame_ready.set()

    return callback


def on_collision(event):
    global collision_detected
    collision_detected = True
    actor_type = event.other_actor.type_id if event.other_actor else "unknown"
    print(f"[WARNING] Collision detected with {actor_type} at frame {event.frame}")


def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))


def normalize_heading(yaw):
    while yaw > 180.0:
        yaw -= 360.0
    while yaw < -180.0:
        yaw += 360.0
    return yaw


def classify_direction(reference_loc, candidate_loc):
    dx = candidate_loc.x - reference_loc.x
    dy = candidate_loc.y - reference_loc.y
    if abs(dx) > abs(dy):
        return "east" if dx > 0 else "west"
    return "north" if dy > 0 else "south"


def gather_direction_counts(spawn_points, center_location, min_dist=18.0, max_dist=180.0):
    counts = {"north": 0, "south": 0, "east": 0, "west": 0}
    for spawn in spawn_points:
        dist = spawn.location.distance(center_location)
        if min_dist <= dist <= max_dist:
            direction = classify_direction(center_location, spawn.location)
            counts[direction] += 1
    return counts


def has_two_lanes_each_way(world_map, center_location, radius=28):
    lane_profile_by_road = defaultdict(lambda: {"pos": set(), "neg": set()})

    step = 3
    z = center_location.z + 0.5
    for dx in range(-radius, radius + 1, step):
        for dy in range(-radius, radius + 1, step):
            loc = carla.Location(x=center_location.x + dx, y=center_location.y + dy, z=z)
            waypoint = world_map.get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Driving)
            if waypoint is None:
                continue
            if waypoint.transform.location.distance(center_location) > radius:
                continue

            lane_id = int(waypoint.lane_id)
            if lane_id > 0:
                lane_profile_by_road[int(waypoint.road_id)]["pos"].add(abs(lane_id))
            elif lane_id < 0:
                lane_profile_by_road[int(waypoint.road_id)]["neg"].add(abs(lane_id))

    best = None
    best_score = -1
    for road_id, profile in lane_profile_by_road.items():
        pos_count = len(profile["pos"])
        neg_count = len(profile["neg"])
        score = min(pos_count, neg_count) * 10 + pos_count + neg_count
        if score > best_score:
            best_score = score
            best = (road_id, pos_count, neg_count)

    if best is None:
        return False, None, {"pos": set(), "neg": set()}

    road_id, pos_count, neg_count = best
    profile = lane_profile_by_road[road_id]
    return pos_count >= 2 and neg_count >= 2, road_id, profile


def select_local_intersection_target(
    world_map,
    spawn_points,
    traffic_lights,
    min_per_direction=BUSY_MIN_PER_DIRECTION,
):
    best = None
    best_score = -1.0
    best_diag = None

    for tl in traffic_lights:
        center = tl.get_location()
        counts = gather_direction_counts(spawn_points, center, min_dist=18.0, max_dist=180.0)
        lane_ok, road_id, profile = has_two_lanes_each_way(world_map, center)

        min_dir = min(counts.values())
        total = sum(counts.values())
        diag = {
            "counts": counts,
            "lane_ok": lane_ok,
            "road_id": road_id,
            "lanes_pos": sorted(profile["pos"]),
            "lanes_neg": sorted(profile["neg"]),
        }

        if min_dir < min_per_direction or not lane_ok:
            if best_diag is None:
                best_diag = diag
            continue

        score = (min_dir * 200.0) + total
        if score > best_score:
            best_score = score
            best = (tl, counts, road_id, profile)

    if best is None:
        raise RuntimeError(
            "No suitable local 4-lane signalized intersection found "
            f"(need >= {min_per_direction} spawn points per direction and 2 lanes each way). "
            f"Example candidate diagnostics: {best_diag}"
        )

    return best


def pick_ego_spawn_facing_light(world_map, spawn_points, target_tl, preferred_road_id=None):
    best_spawn = None
    best_score = -1.0
    tl_loc = target_tl.get_location()

    for spawn in spawn_points:
        dist = spawn.location.distance(tl_loc)
        if dist < 34.0 or dist > 52.0:
            continue

        spawn_wp = world_map.get_waypoint(spawn.location, project_to_road=True, lane_type=carla.LaneType.Driving)
        if spawn_wp is None:
            continue
        if spawn_wp.is_junction:
            continue
        if preferred_road_id is not None and int(spawn_wp.road_id) != int(preferred_road_id):
            continue

        forward = spawn.rotation.get_forward_vector()
        to_light = tl_loc - spawn.location
        planar = math.sqrt((to_light.x * to_light.x) + (to_light.y * to_light.y))
        if planar < 1e-3:
            continue
        to_light_norm = carla.Vector3D(to_light.x / planar, to_light.y / planar, 0.0)
        alignment = (forward.x * to_light_norm.x) + (forward.y * to_light_norm.y)
        if alignment < 0.84:
            continue

        score = (alignment * 2.0) - (abs(dist - 44.0) / 45.0)
        if score > best_score:
            best_score = score
            best_spawn = spawn

    if best_spawn is None:
        raise RuntimeError("Could not find ego spawn on local approach lane facing target red light")
    return best_spawn


def _get_light_stop_waypoints(light):
    try:
        if hasattr(light, "get_stop_waypoints"):
            waypoints = light.get_stop_waypoints()
            if waypoints:
                return list(waypoints)
    except Exception:
        pass
    try:
        if hasattr(light, "get_affected_lane_waypoints"):
            waypoints = light.get_affected_lane_waypoints()
            if waypoints:
                return list(waypoints)
    except Exception:
        pass
    return []


def _along_lateral(origin, forward, target):
    rel_x = target.x - origin.x
    rel_y = target.y - origin.y
    along = rel_x * forward.x + rel_y * forward.y
    lateral = rel_x * -forward.y + rel_y * forward.x
    return along, lateral


def controls_ego_approach_light(world_map, light, ego_spawn):
    ego_wp = world_map.get_waypoint(ego_spawn.location, project_to_road=True, lane_type=carla.LaneType.Driving)
    if ego_wp is None:
        return False

    ego_forward = ego_spawn.rotation.get_forward_vector()
    stop_waypoints = _get_light_stop_waypoints(light)

    for stop_wp in stop_waypoints:
        if int(stop_wp.road_id) != int(ego_wp.road_id) or int(stop_wp.lane_id) != int(ego_wp.lane_id):
            continue
        along, lateral = _along_lateral(ego_spawn.location, ego_forward, stop_wp.transform.location)
        if 8.0 <= along <= 95.0 and abs(lateral) <= 12.0:
            return True

    # Fallback when stop waypoint APIs are unavailable.
    light_loc = light.get_location()
    along, lateral = _along_lateral(ego_spawn.location, ego_forward, light_loc)
    return 12.0 <= along <= 75.0 and abs(lateral) <= 14.0


def get_intersection_signal_lights(world, center_loc, fallback_target_tl):
    group_lights = []
    if fallback_target_tl is not None:
        try:
            if hasattr(fallback_target_tl, "get_group_traffic_lights"):
                group_lights = list(fallback_target_tl.get_group_traffic_lights() or [])
        except Exception:
            group_lights = []

    nearby_lights = []
    for light in world.get_actors().filter("traffic.traffic_light"):
        if light.get_location().distance(center_loc) <= 75.0:
            nearby_lights.append(light)

    merged = []
    seen_ids = set()
    for light in group_lights + nearby_lights:
        if light.id in seen_ids:
            continue
        seen_ids.add(light.id)
        merged.append(light)
    return merged


def partition_intersection_lights_for_ego(world_map, intersection_lights, ego_spawn, fallback_target_tl):
    nearby_lights = list(intersection_lights)

    ego_lights = []
    crossing_lights = []
    for light in nearby_lights:
        if controls_ego_approach_light(world_map, light, ego_spawn):
            ego_lights.append(light)
        else:
            crossing_lights.append(light)

    if not ego_lights and fallback_target_tl is not None:
        ego_lights = [fallback_target_tl]
        crossing_lights = [l for l in nearby_lights if l.id != fallback_target_tl.id]

    ego_ids = {light.id for light in ego_lights}
    crossing_lights = [light for light in crossing_lights if light.id not in ego_ids]
    return ego_lights, crossing_lights


def _cycle_state_for_frame(frame_number):
    cycle_total = sum(duration for _, duration in NON_EGO_SIGNAL_CYCLE)
    phase = (frame_number - 1) % cycle_total
    cursor = 0
    for state, duration in NON_EGO_SIGNAL_CYCLE:
        cursor += duration
        if phase < cursor:
            return state
    return carla.TrafficLightState.Red


def _state_label(state):
    text = str(state)
    return text.split(".")[-1]


def enforce_signal_plan(frame_number, ego_signal_lights, crossing_lights):
    for light in ego_signal_lights:
        light.set_state(carla.TrafficLightState.Red)
        light.set_red_time(9999.0)
        light.freeze(True)

    crossing_state = _cycle_state_for_frame(frame_number)
    for light in crossing_lights:
        light.set_state(crossing_state)
        if crossing_state == carla.TrafficLightState.Green:
            light.set_green_time(5.0)
        elif crossing_state == carla.TrafficLightState.Yellow:
            light.set_yellow_time(1.0)
        else:
            light.set_red_time(3.0)
        light.freeze(True)
    return _state_label(crossing_state)


def collect_light_states(lights):
    states = []
    for light in lights:
        try:
            states.append(str(light.get_state()))
        except Exception:
            states.append("Unknown")
    return states


def build_reserved_corridor(world_map, ego_spawn, target_light_loc, max_distance=95.0, step=2.0):
    corridor = []
    start_wp = world_map.get_waypoint(ego_spawn.location, project_to_road=True, lane_type=carla.LaneType.Driving)
    if start_wp is None:
        return corridor

    current = start_wp
    corridor.append(current.transform.location)

    steps = int(max_distance / step)
    for _ in range(steps):
        next_wps = current.next(step)
        if not next_wps:
            break
        current = min(next_wps, key=lambda wp: wp.transform.location.distance(target_light_loc))
        corridor.append(current.transform.location)

    return corridor


def is_spawn_in_corridor(spawn, corridor_locations, corridor_width=5.6):
    for loc in corridor_locations:
        if spawn.location.distance(loc) <= corridor_width:
            return True
    return False


def select_vehicle_blueprints(blueprint_library):
    selected = []
    for bp in blueprint_library.filter("vehicle.*"):
        bp_id = bp.id.lower()
        wheels = 4
        if bp.has_attribute("number_of_wheels"):
            try:
                wheels = int(bp.get_attribute("number_of_wheels").as_int())
            except Exception:
                wheels = 4
        if wheels >= 4 and not any(token in bp_id for token in ["microlino", "firetruck", "bike", "motorcycle"]):
            selected.append(bp)
    if not selected:
        raise RuntimeError("No suitable 4-wheel vehicle blueprints available")
    return selected


def spawn_vehicle_with_tm(world, traffic_manager, bp, spawn, actors_to_cleanup):
    vehicle = world.try_spawn_actor(bp, spawn)
    if vehicle is None:
        return None

    actors_to_cleanup.append(vehicle)
    vehicle.set_autopilot(True, traffic_manager.get_port())
    traffic_manager.vehicle_percentage_speed_difference(vehicle, random.uniform(-20.0, 10.0))
    traffic_manager.distance_to_leading_vehicle(vehicle, random.uniform(2.0, 4.5))
    traffic_manager.auto_lane_change(vehicle, True)
    traffic_manager.ignore_lights_percentage(vehicle, random.uniform(0.0, 4.0))
    return vehicle


def ensure_dense_traffic(
    world,
    world_map,
    blueprint_library,
    spawn_points,
    center_location,
    traffic_manager,
    actors_to_cleanup,
    ego_spawn,
    corridor_locations,
    min_per_direction=BUSY_MIN_PER_DIRECTION,
):
    directions = ["north", "south", "east", "west"]
    per_direction = defaultdict(int)
    used_spawn_keys = set()
    spawned_vehicles = []
    used_vehicle_types = set()

    ego_wp = world_map.get_waypoint(ego_spawn.location, project_to_road=True, lane_type=carla.LaneType.Driving)
    if ego_wp is None:
        raise RuntimeError("Ego waypoint unavailable for lane-clearance checks")

    vehicle_bps = select_vehicle_blueprints(blueprint_library)

    directional_pool = {"north": [], "south": [], "east": [], "west": []}
    for spawn in spawn_points:
        dist = spawn.location.distance(center_location)
        if 14.0 <= dist <= 170.0:
            directional_pool[classify_direction(center_location, spawn.location)].append((dist, spawn))

    for direction in directional_pool:
        directional_pool[direction].sort(key=lambda item: item[0])
        directional_pool[direction] = [item[1] for item in directional_pool[direction]]

    def blocked_for_ego_lane(spawn):
        if spawn.location.distance(ego_spawn.location) < 9.0:
            return True
        if is_spawn_in_corridor(spawn, corridor_locations, corridor_width=5.6):
            return True

        wp = world_map.get_waypoint(spawn.location, project_to_road=True, lane_type=carla.LaneType.Driving)
        if wp and wp.road_id == ego_wp.road_id and wp.lane_id == ego_wp.lane_id:
            forward = ego_spawn.rotation.get_forward_vector()
            rel_x = spawn.location.x - ego_spawn.location.x
            rel_y = spawn.location.y - ego_spawn.location.y
            along = rel_x * forward.x + rel_y * forward.y
            if along > 3.0:
                return True
        return False

    for attempt in range(10):
        progress = 0
        for direction in directions:
            needed = min_per_direction - per_direction[direction]
            if needed <= 0:
                continue

            candidates = list(directional_pool[direction])
            random.shuffle(candidates)
            for spawn in candidates:
                if needed <= 0:
                    break
                key = (round(spawn.location.x, 1), round(spawn.location.y, 1), round(spawn.rotation.yaw, 1))
                if key in used_spawn_keys:
                    continue
                if blocked_for_ego_lane(spawn):
                    continue

                bp = random.choice(vehicle_bps)
                vehicle = spawn_vehicle_with_tm(world, traffic_manager, bp, spawn, actors_to_cleanup)
                if vehicle is None:
                    continue

                used_spawn_keys.add(key)
                spawned_vehicles.append(vehicle)
                used_vehicle_types.add(bp.id)
                per_direction[direction] += 1
                needed -= 1
                progress += 1

        if all(per_direction[d] >= min_per_direction for d in directions):
            break
        if progress == 0 and attempt >= 1:
            break

    counts = {d: per_direction[d] for d in directions}
    if not all(counts[d] >= min_per_direction for d in directions):
        raise RuntimeError(
            "Failed dense traffic requirement: "
            f"need >= {min_per_direction} per direction, got {counts}"
        )

    total_needed = max(BUSY_TOTAL_MIN - len(spawned_vehicles), 0)
    if total_needed > 0:
        fill_candidates = [
            sp for sp in spawn_points
            if 14.0 <= sp.location.distance(center_location) <= 160.0 and not blocked_for_ego_lane(sp)
        ]
        random.shuffle(fill_candidates)

        for spawn in fill_candidates:
            if total_needed <= 0:
                break
            key = (round(spawn.location.x, 1), round(spawn.location.y, 1), round(spawn.rotation.yaw, 1))
            if key in used_spawn_keys:
                continue
            bp = random.choice(vehicle_bps)
            vehicle = spawn_vehicle_with_tm(world, traffic_manager, bp, spawn, actors_to_cleanup)
            if vehicle is None:
                continue
            used_spawn_keys.add(key)
            spawned_vehicles.append(vehicle)
            used_vehicle_types.add(bp.id)
            total_needed -= 1

    if len(spawned_vehicles) < BUSY_TOTAL_MIN:
        raise RuntimeError(
            f"Failed total traffic requirement: need >= {BUSY_TOTAL_MIN}, got {len(spawned_vehicles)}"
        )

    visibility_counts = ensure_nearby_visibility(
        world=world,
        world_map=world_map,
        traffic_manager=traffic_manager,
        vehicle_blueprints=vehicle_bps,
        spawn_points=spawn_points,
        center_location=center_location,
        ego_spawn=ego_spawn,
        used_spawn_keys=used_spawn_keys,
        actors_to_cleanup=actors_to_cleanup,
        spawned_vehicles=spawned_vehicles,
        corridor_locations=corridor_locations,
    )

    return spawned_vehicles, counts, len(used_vehicle_types), visibility_counts


def ensure_nearby_visibility(
    world,
    world_map,
    traffic_manager,
    vehicle_blueprints,
    spawn_points,
    center_location,
    ego_spawn,
    used_spawn_keys,
    actors_to_cleanup,
    spawned_vehicles,
    corridor_locations,
):
    ego_forward = ego_spawn.rotation.get_forward_vector()
    buckets = {"behind": [], "beside": [], "crossing": []}

    for sp in spawn_points:
        if is_spawn_in_corridor(sp, corridor_locations, corridor_width=5.2):
            continue

        dist_center = sp.location.distance(center_location)
        dist_ego = sp.location.distance(ego_spawn.location)
        if dist_center > 150.0 or dist_ego < 8.0 or dist_ego > 90.0:
            continue

        key = (round(sp.location.x, 1), round(sp.location.y, 1), round(sp.rotation.yaw, 1))
        if key in used_spawn_keys:
            continue

        rel_x = sp.location.x - ego_spawn.location.x
        rel_y = sp.location.y - ego_spawn.location.y
        along = rel_x * ego_forward.x + rel_y * ego_forward.y
        lateral = rel_x * -ego_forward.y + rel_y * ego_forward.x

        if along < -10.0 and abs(lateral) < 14.0:
            buckets["behind"].append(sp)
        elif abs(along) < 34.0 and abs(lateral) > 14.0:
            buckets["crossing"].append(sp)
        elif abs(lateral) >= 6.0 and abs(along) < 46.0:
            buckets["beside"].append(sp)

    targets = dict(NEARBY_TARGETS)
    counts = {"behind": 0, "beside": 0, "crossing": 0}

    for bucket_name in ["crossing", "beside", "behind"]:
        random.shuffle(buckets[bucket_name])
        for spawn in buckets[bucket_name]:
            if counts[bucket_name] >= targets[bucket_name]:
                break
            bp = random.choice(vehicle_blueprints)
            vehicle = spawn_vehicle_with_tm(world, traffic_manager, bp, spawn, actors_to_cleanup)
            if vehicle is None:
                continue
            key = (round(spawn.location.x, 1), round(spawn.location.y, 1), round(spawn.rotation.yaw, 1))
            used_spawn_keys.add(key)
            spawned_vehicles.append(vehicle)
            counts[bucket_name] += 1

    return counts


def spawn_context_objects_offlane(
    world,
    world_map,
    blueprint_library,
    spawn_points,
    center_location,
    actors_to_cleanup,
    target_count=10,
):
    props = []
    for bp in blueprint_library.filter("static.prop.*"):
        bp_id = bp.id.lower()
        if any(token in bp_id for token in ["cone", "barrier", "construction", "warning", "fence"]):
            props.append(bp)

    if not props:
        return 0

    spawned = 0
    candidates = [sp for sp in spawn_points if 16.0 <= sp.location.distance(center_location) <= 80.0]
    random.shuffle(candidates)

    for sp in candidates:
        if spawned >= target_count:
            break

        base_wp = world_map.get_waypoint(sp.location, project_to_road=True, lane_type=carla.LaneType.Driving)
        if base_wp is None:
            continue

        lane_width = max(2.5, float(base_wp.lane_width))
        right = base_wp.transform.get_right_vector()

        for sign in (-1.0, 1.0):
            if spawned >= target_count:
                break
            offset = lane_width * 1.7 + random.uniform(0.5, 1.3)
            loc = carla.Location(
                x=base_wp.transform.location.x + right.x * offset * sign,
                y=base_wp.transform.location.y + right.y * offset * sign,
                z=base_wp.transform.location.z + 0.12,
            )

            lane_wp = world_map.get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Any)
            if lane_wp is not None and lane_wp.lane_type == carla.LaneType.Driving:
                continue

            actor = world.try_spawn_actor(
                random.choice(props),
                carla.Transform(loc, carla.Rotation(yaw=random.uniform(0.0, 360.0))),
            )
            if actor is None:
                continue
            actors_to_cleanup.append(actor)
            spawned += 1

    return spawned


def find_front_blocker(world_map, ego_vehicle, other_vehicles, max_distance=14.0):
    ego_loc = ego_vehicle.get_location()
    ego_tf = ego_vehicle.get_transform()
    ego_forward = ego_tf.rotation.get_forward_vector()
    ego_wp = world_map.get_waypoint(ego_loc, project_to_road=True, lane_type=carla.LaneType.Driving)
    if ego_wp is None:
        return None

    nearest = None
    nearest_dist = 1e9

    for veh in other_vehicles:
        if not veh.is_alive:
            continue
        if veh.id == ego_vehicle.id:
            continue
        loc = veh.get_location()
        wp = world_map.get_waypoint(loc, project_to_road=True, lane_type=carla.LaneType.Driving)
        if wp is None:
            continue
        if wp.road_id != ego_wp.road_id or wp.lane_id != ego_wp.lane_id:
            continue

        rel_x = loc.x - ego_loc.x
        rel_y = loc.y - ego_loc.y
        along = rel_x * ego_forward.x + rel_y * ego_forward.y
        if along <= 0.0:
            continue
        dist = math.sqrt(rel_x * rel_x + rel_y * rel_y)
        if dist <= max_distance and dist < nearest_dist:
            nearest_dist = dist
            nearest = veh

    return nearest


def clear_output_pngs(output_dirs):
    for path in output_dirs.values():
        os.makedirs(path, exist_ok=True)
        for fname in os.listdir(path):
            if fname.lower().endswith(".png"):
                try:
                    os.remove(os.path.join(path, fname))
                except Exception:
                    pass


def main():
    global collision_detected

    parser = argparse.ArgumentParser(description="CARLA Red Light Violation Scenario - Shot 6")
    parser.add_argument("--host", default="127.0.0.1", help="CARLA server host")
    parser.add_argument("--port", type=int, default=2000, help="CARLA server port")
    parser.add_argument("--duration", type=float, default=20.0, help="Simulation duration in seconds")
    parser.add_argument("--output-dir", default="./scenes/red_light_violation", help="Output directory")
    parser.add_argument("--map", default="Town05", help="Map to load fresh each run (default: Town05)")
    args = parser.parse_args()

    output_dirs = {
        "front": os.path.join(args.output_dir, "front"),
        "front_left": os.path.join(args.output_dir, "front_left"),
        "front_right": os.path.join(args.output_dir, "front_right"),
        "rear": os.path.join(args.output_dir, "rear"),
        "drone_follow": os.path.join(args.output_dir, "drone_follow"),
    }
    clear_output_pngs(output_dirs)

    log_file_path = os.path.join(args.output_dir, "red_light_violation_simulation.log")
    log_file = open(log_file_path, "w", encoding="utf-8", buffering=1)

    world = None
    original_settings = None
    actors_to_cleanup = []
    target_tl = None
    ego_signal_lights = []
    crossing_signal_lights = []

    try:
        print("[INFO] Connecting to CARLA server...")
        client = carla.Client(args.host, args.port)
        client.set_timeout(90.0)

        print(f"[INFO] Loading map fresh for this run: {args.map}")
        world = client.load_world(args.map)
        for _ in range(8):
            world.wait_for_tick(4.0)

        world = client.get_world()
        world_map = world.get_map()
        map_name = world_map.name
        print(f"[INFO] Active map after fresh load: {map_name}")
        log_file.write(f"[INFO] Active map after fresh load: {map_name}\n")

        blueprint_library = world.get_blueprint_library()
        spawn_points = world_map.get_spawn_points()
        if len(spawn_points) < 80:
            raise RuntimeError("Insufficient spawn points for dense local intersection scenario")

        # Extra cleanup after fresh map load.
        for actor in world.get_actors().filter("vehicle.*"):
            try:
                actor.destroy()
            except Exception:
                pass

        original_settings = world.get_settings()
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)

        traffic_manager = client.get_trafficmanager(8000)
        traffic_manager.set_synchronous_mode(True)
        traffic_manager.set_hybrid_physics_mode(False)

        traffic_lights = world.get_actors().filter("traffic.traffic_light")
        target_tl, direction_candidates, preferred_road_id, lane_profile = select_local_intersection_target(
            world_map=world_map,
            spawn_points=spawn_points,
            traffic_lights=traffic_lights,
            min_per_direction=BUSY_MIN_PER_DIRECTION,
        )
        center_loc = target_tl.get_location()

        ego_spawn = pick_ego_spawn_facing_light(
            world_map=world_map,
            spawn_points=spawn_points,
            target_tl=target_tl,
            preferred_road_id=preferred_road_id,
        )

        corridor_locations = build_reserved_corridor(
            world_map=world_map,
            ego_spawn=ego_spawn,
            target_light_loc=center_loc,
            max_distance=95.0,
            step=2.0,
        )

        intersection_signal_lights = get_intersection_signal_lights(
            world=world,
            center_loc=center_loc,
            fallback_target_tl=target_tl,
        )
        ego_signal_lights, crossing_signal_lights = partition_intersection_lights_for_ego(
            world_map=world_map,
            intersection_lights=intersection_signal_lights,
            ego_spawn=ego_spawn,
            fallback_target_tl=target_tl,
        )
        if not ego_signal_lights:
            raise RuntimeError("Failed to identify ego-approach signal lights for red-light violation setup")

        target_tl = ego_signal_lights[0]
        crossing_phase = enforce_signal_plan(1, ego_signal_lights, crossing_signal_lights)
        world.tick()
        print(
            "[RED LIGHT] Ego-approach signal plan applied with dynamic crossing cycle: "
            f"ego_red={len(ego_signal_lights)} crossing_dynamic={len(crossing_signal_lights)} "
            f"initial_crossing_phase={crossing_phase}"
        )
        log_file.write(
            "[RED LIGHT] Ego-approach signal plan applied with dynamic crossing cycle: "
            f"ego_red={len(ego_signal_lights)} crossing_dynamic={len(crossing_signal_lights)} "
            f"initial_crossing_phase={crossing_phase}\n"
        )
        log_file.write(f"[RED LIGHT] ego_signal_ids={[light.id for light in ego_signal_lights]}\n")
        log_file.write(f"[RED LIGHT] crossing_signal_ids={[light.id for light in crossing_signal_lights]}\n")

        print(
            "[INFO] Intersection selected: "
            f"spawn_candidates={direction_candidates}, road_id={preferred_road_id}, "
            f"lanes_pos={sorted(lane_profile['pos'])}, lanes_neg={sorted(lane_profile['neg'])}"
        )
        log_file.write(
            "[INFO] Intersection selected: "
            f"spawn_candidates={direction_candidates}, road_id={preferred_road_id}, "
            f"lanes_pos={sorted(lane_profile['pos'])}, lanes_neg={sorted(lane_profile['neg'])}\n"
        )

        vehicle_bp = blueprint_library.find("vehicle.tesla.model3")
        if vehicle_bp is None:
            raise RuntimeError("vehicle.tesla.model3 blueprint unavailable")

        ego_vehicle = world.try_spawn_actor(vehicle_bp, ego_spawn)
        if ego_vehicle is None:
            raise RuntimeError("Failed to spawn ego vehicle")
        actors_to_cleanup.append(ego_vehicle)

        collision_bp = blueprint_library.find("sensor.other.collision")
        collision_sensor = world.spawn_actor(collision_bp, carla.Transform(), attach_to=ego_vehicle)
        actors_to_cleanup.append(collision_sensor)
        collision_sensor.listen(on_collision)

        dense_vehicles, direction_counts, unique_types, visibility_counts = ensure_dense_traffic(
            world=world,
            world_map=world_map,
            blueprint_library=blueprint_library,
            spawn_points=spawn_points,
            center_location=center_loc,
            traffic_manager=traffic_manager,
            actors_to_cleanup=actors_to_cleanup,
            ego_spawn=ego_spawn,
            corridor_locations=corridor_locations,
            min_per_direction=BUSY_MIN_PER_DIRECTION,
        )

        object_count = spawn_context_objects_offlane(
            world=world,
            world_map=world_map,
            blueprint_library=blueprint_library,
            spawn_points=spawn_points,
            center_location=center_loc,
            actors_to_cleanup=actors_to_cleanup,
            target_count=10,
        )

        # Force-clear accidental blockers in ego lane ahead.
        removed_blockers = 0
        while True:
            blocker = find_front_blocker(world_map, ego_vehicle, dense_vehicles, max_distance=25.0)
            if blocker is None:
                break
            try:
                blocker.destroy()
                removed_blockers += 1
            except Exception:
                break
            dense_vehicles = [v for v in dense_vehicles if v.is_alive and v.id != blocker.id]

        print(f"[INFO] Dense traffic counts: {direction_counts} total={len(dense_vehicles)}")
        print(f"[INFO] Nearby visibility traffic: {visibility_counts}")
        print(f"[INFO] Unique vehicle types: {unique_types}")
        print(f"[INFO] Off-lane context objects: {object_count}")
        print(f"[INFO] Removed ego-lane blockers before start: {removed_blockers}")
        print(f"[INFO] Density contract: per_direction>={BUSY_MIN_PER_DIRECTION}, total>={BUSY_TOTAL_MIN}")

        log_file.write(f"[INFO] Dense traffic counts: {direction_counts} total={len(dense_vehicles)}\n")
        log_file.write(f"[INFO] Nearby visibility traffic: {visibility_counts}\n")
        log_file.write(f"[INFO] Unique vehicle types: {unique_types}\n")
        log_file.write(f"[INFO] Off-lane context objects: {object_count}\n")
        log_file.write(f"[INFO] Removed ego-lane blockers before start: {removed_blockers}\n")
        log_file.write(
            f"[INFO] Density contract: per_direction>={BUSY_MIN_PER_DIRECTION}, total>={BUSY_TOTAL_MIN}\n"
        )

        camera_bp = blueprint_library.find("sensor.camera.rgb")
        camera_bp.set_attribute("image_size_x", "1280")
        camera_bp.set_attribute("image_size_y", "720")
        camera_bp.set_attribute("fov", "110")

        camera_transforms = {
            "front": carla.Transform(carla.Location(x=0.8, y=0.0, z=1.4), carla.Rotation(pitch=8)),
            "front_left": carla.Transform(carla.Location(x=-0.1, y=-0.4, z=1.2), carla.Rotation(yaw=-60)),
            "front_right": carla.Transform(carla.Location(x=-0.1, y=0.4, z=1.2), carla.Rotation(yaw=60)),
            "rear": carla.Transform(carla.Location(x=-0.2, y=0.3, z=1.25), carla.Rotation(yaw=180, pitch=5)),
            "drone_follow": carla.Transform(carla.Location(x=-12.0, y=0.0, z=12.0), carla.Rotation(pitch=-25)),
        }

        for key, transform in camera_transforms.items():
            cam = world.spawn_actor(camera_bp, transform, attach_to=ego_vehicle)
            actors_to_cleanup.append(cam)
            cam.listen(make_camera_callback(key))

        print("[INFO] Warming up cameras...")
        for _ in range(25):
            world.tick()
        time.sleep(0.4)

        with images_lock:
            for key in CAMERA_KEYS:
                images_received[key] = None
        frame_ready.clear()

        target_frames = int(max(1.0, args.duration) * 20)
        max_frames = min(target_frames, 280)
        if max_frames < target_frames:
            print(
                f"[INFO] Frame budget capped for runtime stability: {max_frames}/{target_frames} "
                "(still above coverage threshold)"
            )

        frame_number = 1
        stuck_frames = 0

        axis = center_loc - ego_spawn.location
        axis_len = max(1e-3, math.sqrt(axis.x * axis.x + axis.y * axis.y))
        axis_x = axis.x / axis_len
        axis_y = axis.y / axis_len
        violation_logged = False
        approach_red_frames = 0
        approach_slow_frames = 0

        print("[INFO] Running red-light violation scenario...")
        while frame_number <= max_frames:
            ego_tf = ego_vehicle.get_transform()
            ego_loc = ego_tf.location
            ego_vel = ego_vehicle.get_velocity()
            ego_speed = math.sqrt(ego_vel.x * ego_vel.x + ego_vel.y * ego_vel.y)

            current_wp = world_map.get_waypoint(ego_loc, project_to_road=True, lane_type=carla.LaneType.Driving)
            steer = 0.0
            if current_wp is not None:
                next_wps = current_wp.next(8.0)
                if next_wps:
                    target_wp = min(next_wps, key=lambda wp: wp.transform.location.distance(center_loc))
                    vec = target_wp.transform.location - ego_loc
                    desired_yaw = math.degrees(math.atan2(vec.y, vec.x))
                    yaw_error = normalize_heading(desired_yaw - ego_tf.rotation.yaw)
                    steer = clamp(yaw_error * 0.02, -0.5, 0.5)

            # Keep ego approach red, while crossing/other approaches cycle normally.
            crossing_phase = enforce_signal_plan(frame_number, ego_signal_lights, crossing_signal_lights)

            target_speed = 40.0 / 3.6
            if ego_speed < target_speed * 0.9:
                throttle = 0.85
            elif ego_speed < target_speed:
                throttle = 0.65
            else:
                throttle = 0.35

            ego_vehicle.apply_control(carla.VehicleControl(throttle=throttle, steer=steer, brake=0.0, hand_brake=False))
            world.tick()

            if frame_ready.wait(timeout=1.2):
                with images_lock:
                    for key in CAMERA_KEYS:
                        frame_path = os.path.join(output_dirs[key], f"{key}_frame_{frame_number:08d}.png")
                        save_image_to_disk(images_received[key], frame_path)
                        images_received[key] = None
                frame_ready.clear()
            else:
                frame_ready.clear()
                with images_lock:
                    for key in CAMERA_KEYS:
                        images_received[key] = None

            distance_along = (center_loc.x - ego_loc.x) * axis_x + (center_loc.y - ego_loc.y) * axis_y
            ego_tl_state = "Unknown"
            try:
                ego_tl_state = str(ego_vehicle.get_traffic_light_state())
            except Exception:
                ego_tl_state = "Unknown"

            ego_signal_states = collect_light_states(ego_signal_lights)
            all_ego_red = bool(ego_signal_states) and all("Red" in state for state in ego_signal_states)

            if distance_along > 0.0 and all_ego_red:
                approach_red_frames += 1

            if 2.0 < distance_along < 28.0:
                if ego_speed * 3.6 < 8.0:
                    approach_slow_frames += 1
                else:
                    approach_slow_frames = 0

            if not violation_logged and approach_slow_frames > 18:
                raise RuntimeError("Ego slowed/stopped before stop line; expected continuous acceleration through red")

            if not violation_logged and distance_along < -2.0:
                if approach_red_frames < 12 or not all_ego_red:
                    raise RuntimeError(
                        "Crossed stop line without sustained red signal on ego approach lights "
                        f"(approach_red_frames={approach_red_frames}, ego_signal_states={ego_signal_states})"
                    )
                violation_logged = True
                msg = (
                    "[VIOLATION] Ego crossed stop-line region while target signal remains RED "
                    f"at frame={frame_number} ego_tl_state={ego_tl_state} "
                    f"ego_signal_states={ego_signal_states} approach_red_frames={approach_red_frames}"
                )
                print(msg)
                log_file.write(msg + "\n")

            if ego_speed < 0.4:
                stuck_frames += 1
            else:
                stuck_frames = 0

            if stuck_frames >= 50:
                blocker = find_front_blocker(world_map, ego_vehicle, dense_vehicles, max_distance=16.0)
                if blocker is not None:
                    try:
                        blocker_id = blocker.id
                        blocker.destroy()
                        dense_vehicles = [v for v in dense_vehicles if v.is_alive and v.id != blocker_id]
                        print(f"[INFO] Removed dynamic blocker in ego lane (id={blocker_id})")
                        log_file.write(f"[INFO] Removed dynamic blocker in ego lane (id={blocker_id})\n")
                    except Exception:
                        pass
                stuck_frames = 0

            if frame_number % 40 == 0 or frame_number == 1:
                tl_state = str(target_tl.get_state()) if target_tl is not None else "unknown"
                msg = (
                    f"[PROGRESS] frame={frame_number}/{max_frames} speed={ego_speed*3.6:.1f}km/h "
                    f"dist_to_light_axis={distance_along:.1f}m tl_state={tl_state} "
                    f"ego_tl_state={ego_tl_state} traffic_total={len(dense_vehicles)} "
                    f"nearby={visibility_counts} objects={object_count} "
                    f"ego_signal_states={ego_signal_states} crossing_phase={crossing_phase} "
                    f"red_frames={approach_red_frames}"
                )
                print(msg)
                log_file.write(msg + "\n")

            frame_number += 1

        if not violation_logged:
            print("[WARNING] Violation crossing marker not detected in this run")
            log_file.write("[WARNING] Violation crossing marker not detected in this run\n")

        print("[SUCCESS] Scenario completed")
        log_file.write("[SUCCESS] Scenario completed\n")

    except Exception as err:
        print(f"[ERROR] {type(err).__name__}: {err}")
        log_file.write(f"[ERROR] {type(err).__name__}: {err}\n")
        raise

    finally:
        if target_tl is not None:
            try:
                target_tl.freeze(False)
            except Exception:
                pass
        for light in ego_signal_lights:
            try:
                light.freeze(False)
            except Exception:
                pass
        for light in crossing_signal_lights:
            try:
                light.freeze(False)
            except Exception:
                pass

        for actor in reversed(actors_to_cleanup):
            try:
                actor.destroy()
            except Exception:
                pass

        if world is not None and original_settings is not None:
            try:
                world.apply_settings(original_settings)
            except Exception:
                pass

        log_file.close()
        print("[INFO] Cleanup complete")


if __name__ == "__main__":
    main()
