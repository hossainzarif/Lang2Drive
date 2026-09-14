import carla
import random
import time
import numpy as np
import math
import threading
import argparse
from PIL import Image
import os
import sys

# Shared state for 4-camera synchronization
images_received = {'front': None, 'front_left': None, 'front_right': None, 'rear': None}
images_lock = threading.Lock()
frame_ready = threading.Event()

def save_image_to_disk(image, output_path):
    """Save CARLA image as RGB PNG"""
    try:
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = array.reshape((image.height, image.width, 4))
        array = array[:, :, :3][:, :, ::-1]
        img = Image.fromarray(array)
        img.save(output_path, 'PNG')
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save image: {e}")
        return False

def make_camera_callback(camera_name):
    def callback(image):
        with images_lock:
            images_received[camera_name] = image
            if all(img is not None for img in images_received.values()):
                frame_ready.set()
    return callback

def collision_callback(event, actor_name):
    print(f"[COLLISION] {actor_name} collided with {event.other_actor.type_id} at frame {event.frame}")

def is_straight_road(waypoint, distance=60.0):
    """Check if the road ahead is relatively straight"""
    if not waypoint:
        return False
    
    current_wp = waypoint
    for _ in range(int(distance / 5.0)):
        next_wps = current_wp.next(5.0)
        if not next_wps:
            return False
        next_wp = next_wps[0]
        
        # Check if it's a junction/roundabout
        if next_wp.is_junction:
            return False
        
        # Check angle change
        yaw_diff = abs(next_wp.transform.rotation.yaw - current_wp.transform.rotation.yaw)
        if yaw_diff > 180:
            yaw_diff = 360 - yaw_diff
        if yaw_diff > 15:
            return False
        
        current_wp = next_wp
    
    return True

def find_suitable_spawn_point(world, spawn_points):
    """Find a spawn point on a straight multi-lane road without roundabouts"""
    best_spawn = None
    
    for sp in spawn_points:
        waypoint = world.get_map().get_waypoint(sp.location)
        
        # Must be driving lane
        if waypoint.lane_type != carla.LaneType.Driving:
            continue
        
        # Must not be in junction
        if waypoint.is_junction:
            continue
        
        # Check for multiple lanes
        left_lane = waypoint.get_left_lane()
        right_lane = waypoint.get_right_lane()
        
        # Must have adjacent lanes
        if not (left_lane or right_lane):
            continue
        
        # Must be straight road ahead
        if not is_straight_road(waypoint, 70.0):
            continue
        
        # Check that forward path exists
        forward_waypoints = waypoint.next(60.0)
        if not forward_waypoints:
            continue
        
        # Prefer roads with lanes on both sides
        if left_lane and right_lane:
            return sp
        elif best_spawn is None:
            best_spawn = sp
    
    return best_spawn

def main():
    parser = argparse.ArgumentParser(description='CARLA Sudden Pedestrian Crossing Scenario')
    parser.add_argument('--host', default='127.0.0.1', help='CARLA server host')
    parser.add_argument('--port', type=int, default=2000, help='CARLA server port')
    parser.add_argument('--duration', type=int, default=20, help='Simulation duration in seconds')
    parser.add_argument('--output-dir', default='./scenes/sudden_pedestrian_crossing', help='Output directory')
    args = parser.parse_args()

    client = None
    world = None
    actors = []
    cameras = []

    try:
        # Create output directories
        output_dirs = {
            'front': os.path.join(args.output_dir, 'front'),
            'front_left': os.path.join(args.output_dir, 'front_left'),
            'front_right': os.path.join(args.output_dir, 'front_right'),
            'rear': os.path.join(args.output_dir, 'rear')
        }
        
        for dir_path in output_dirs.values():
            os.makedirs(dir_path, exist_ok=True)

        log_file = open(os.path.join(args.output_dir, 'sudden_pedestrian_crossing_simulation.log'), 'w')
        
        print("[INFO] Connecting to CARLA server...")
        client = carla.Client(args.host, args.port)
        client.set_timeout(60.0)
        
        # Test connection
        version = client.get_server_version()
        print(f"[INFO] Connected to CARLA server version {version}")
        log_file.write(f"Connected to CARLA server version {version}\n")

        # Load Town03 (or Town05)
        print("[INFO] Loading Town03...")
        world = client.load_world('Town03')
        time.sleep(2)
        
        # Set synchronous mode
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)
        print("[INFO] Synchronous mode enabled (20 FPS)")

        blueprint_library = world.get_blueprint_library()
        spawn_points = world.get_map().get_spawn_points()

        # Set clear daytime weather
        weather = carla.WeatherParameters.ClearNoon
        world.set_weather(weather)
        print("[INFO] Weather set to clear daytime")

        # Find a suitable spawn point on straight multi-lane road
        print("[INFO] Searching for suitable straight road...")
        suitable_spawn = find_suitable_spawn_point(world, spawn_points)
        
        if not suitable_spawn:
            print("[WARNING] No ideal spawn point found, using fallback locations")
            # Try specific spawn point indices known to be on straight roads in Town03
            fallback_indices = [45, 78, 120, 150, 200, 25, 60, 90]
            for idx in fallback_indices:
                if idx < len(spawn_points):
                    test_spawn = spawn_points[idx]
                    test_wp = world.get_map().get_waypoint(test_spawn.location)
                    if not test_wp.is_junction and is_straight_road(test_wp, 60.0):
                        suitable_spawn = test_spawn
                        break
        
        if not suitable_spawn:
            suitable_spawn = spawn_points[45]
        
        print(f"[INFO] Selected spawn point at index: {spawn_points.index(suitable_spawn)}")

        # Spawn ego vehicle
        ego_bp = blueprint_library.filter('vehicle.tesla.model3')[0]
        ego_vehicle = world.try_spawn_actor(ego_bp, suitable_spawn)
        
        if not ego_vehicle:
            print("[ERROR] Failed to spawn ego vehicle")
            return
        
        actors.append(ego_vehicle)
        print(f"[INFO] Ego vehicle spawned at {ego_vehicle.get_location()}")

        # Get ego vehicle waypoint for positioning
        ego_waypoint = world.get_map().get_waypoint(ego_vehicle.get_location())
        
        # Define jaywalking point 47 meters ahead (mid-point between 45-50)
        jaywalking_distance = 47.0
        jaywalking_waypoints = ego_waypoint.next(jaywalking_distance)
        jaywalking_waypoint = jaywalking_waypoints[0] if jaywalking_waypoints else ego_waypoint
        jaywalking_location = jaywalking_waypoint.transform.location
        
        print(f"[INFO] Jaywalking point set at {jaywalking_location}")

        # Spawn pedestrian on the right sidewalk, 3 meters from road edge
        walker_bp = blueprint_library.filter('walker.pedestrian.*')[0]
        
        # Get right side of road relative to ego vehicle direction
        right_vector = jaywalking_waypoint.transform.get_right_vector()
        
        # Calculate pedestrian start location (right side, 6 meters from center = ~3m from road edge)
        pedestrian_start_location = carla.Location(
            x=jaywalking_location.x + right_vector.x * 6.0,
            y=jaywalking_location.y + right_vector.y * 6.0,
            z=jaywalking_location.z + 1.2
        )
        
        # Calculate the yaw to face across the road (perpendicular to traffic)
        forward_vector = jaywalking_waypoint.transform.get_forward_vector()
        cross_yaw = math.degrees(math.atan2(-right_vector.y, -right_vector.x))
        
        pedestrian_spawn_transform = carla.Transform(
            pedestrian_start_location, 
            carla.Rotation(yaw=cross_yaw)
        )
        
        pedestrian = world.try_spawn_actor(walker_bp, pedestrian_spawn_transform)
        
        if not pedestrian:
            print("[WARNING] Failed to spawn pedestrian, trying alternate heights")
            for z_offset in [0.5, 1.5, 2.0, 0.0]:
                pedestrian_start_location.z = jaywalking_location.z + z_offset
                pedestrian_spawn_transform.location = pedestrian_start_location
                pedestrian = world.try_spawn_actor(walker_bp, pedestrian_spawn_transform)
                if pedestrian:
                    break
        
        if pedestrian:
            actors.append(pedestrian)
            print(f"[INFO] Pedestrian spawned at {pedestrian.get_location()}")
        else:
            print("[ERROR] Failed to spawn pedestrian after multiple attempts")

        # Spawn walker controller for pedestrian
        walker_controller = None
        if pedestrian:
            walker_controller_bp = blueprint_library.find('controller.ai.walker')
            walker_controller = world.spawn_actor(walker_controller_bp, carla.Transform(), pedestrian)
            actors.append(walker_controller)
            walker_controller.start()
            walker_controller.set_max_speed(0.0)
            print("[INFO] Walker AI controller initialized (stationary)")

        # Spawn 2-3 NPC vehicles in adjacent lanes
        vehicle_bps = [bp for bp in blueprint_library.filter('vehicle.*') if 
                      'bike' not in bp.id.lower() and 'motorcycle' not in bp.id.lower() and
                      'carlacola' not in bp.id.lower() and 'cybertruck' not in bp.id.lower()]
        
        num_npc = 3
        npc_vehicles = []
        
        for i in range(num_npc):
            # Spawn NPC vehicles at various positions relative to ego
            if i == 0:
                offset_distance = -20.0
                target_waypoint = ego_waypoint
                if ego_waypoint.get_left_lane():
                    target_waypoint = ego_waypoint.get_left_lane()
            elif i == 1:
                offset_distance = 15.0
                target_waypoint = ego_waypoint
            else:
                offset_distance = -35.0
                target_waypoint = ego_waypoint
                if ego_waypoint.get_right_lane():
                    target_waypoint = ego_waypoint.get_right_lane()
            
            if offset_distance > 0:
                npc_waypoint_list = target_waypoint.next(offset_distance)
            else:
                npc_waypoint_list = target_waypoint.previous(-offset_distance)
            
            if npc_waypoint_list:
                npc_waypoint = npc_waypoint_list[0]
            else:
                npc_waypoint = target_waypoint
            
            npc_bp = random.choice(vehicle_bps)
            npc_transform = npc_waypoint.transform
            npc_transform.location.z += 0.5
            
            npc_vehicle = world.try_spawn_actor(npc_bp, npc_transform)
            if npc_vehicle:
                actors.append(npc_vehicle)
                npc_vehicles.append(npc_vehicle)
                print(f"[INFO] NPC vehicle {i+1} spawned at {npc_vehicle.get_location()}")

        # Spawn parked vehicles along curbs for visual occlusion
        parked_count = 0
        for side in [-1, 1]:
            for j in range(4):
                park_distance = 25.0 + j * 12.0
                park_waypoint_list = ego_waypoint.next(park_distance)
                if not park_waypoint_list:
                    continue
                park_waypoint = park_waypoint_list[0]
                
                # Offset to curb
                side_vector = park_waypoint.transform.get_right_vector()
                park_location = carla.Location(
                    x=park_waypoint.transform.location.x + side_vector.x * side * 5.5,
                    y=park_waypoint.transform.location.y + side_vector.y * side * 5.5,
                    z=park_waypoint.transform.location.z + 0.3
                )
                
                park_transform = carla.Transform(park_location, park_waypoint.transform.rotation)
                parked_bp = random.choice(vehicle_bps)
                parked_vehicle = world.try_spawn_actor(parked_bp, park_transform)
                
                if parked_vehicle:
                    actors.append(parked_vehicle)
                    parked_count += 1

        print(f"[INFO] Spawned {parked_count} parked vehicles for visual occlusion")

        # Set up Traffic Manager for NPC vehicles
        traffic_manager = client.get_trafficmanager(8000)
        traffic_manager.set_synchronous_mode(True)
        traffic_manager.set_global_distance_to_leading_vehicle(2.5)
        
        # Configure NPC vehicles with Traffic Manager
        for npc_vehicle in npc_vehicles:
            npc_vehicle.set_autopilot(True, 8000)
            speed_diff = random.uniform(-20, 5)
            traffic_manager.vehicle_percentage_speed_difference(npc_vehicle, speed_diff)
            traffic_manager.auto_lane_change(npc_vehicle, True)
            traffic_manager.distance_to_leading_vehicle(npc_vehicle, 2.0)
            traffic_manager.ignore_lights_percentage(npc_vehicle, 0)
            traffic_manager.ignore_walkers_percentage(npc_vehicle, 0)

        # Set ego vehicle to desired speed (40 km/h)
        ego_vehicle.set_autopilot(True, 8000)
        traffic_manager.vehicle_percentage_speed_difference(ego_vehicle, -10.0)
        traffic_manager.auto_lane_change(ego_vehicle, False)
        traffic_manager.distance_to_leading_vehicle(ego_vehicle, 2.0)
        traffic_manager.ignore_lights_percentage(ego_vehicle, 0)
        traffic_manager.ignore_walkers_percentage(ego_vehicle, 0)

        # Attach collision sensors
        collision_bp = blueprint_library.find('sensor.other.collision')
        
        ego_collision_sensor = world.spawn_actor(
            collision_bp, 
            carla.Transform(), 
            attach_to=ego_vehicle
        )
        ego_collision_sensor.listen(lambda event: collision_callback(event, "Ego Vehicle"))
        actors.append(ego_collision_sensor)
        
        if pedestrian:
            pedestrian_collision_sensor = world.spawn_actor(
                collision_bp,
                carla.Transform(),
                attach_to=pedestrian
            )
            pedestrian_collision_sensor.listen(lambda event: collision_callback(event, "Pedestrian"))
            actors.append(pedestrian_collision_sensor)

        # Setup 4 driver-POV RGB cameras
        camera_bp = blueprint_library.find('sensor.camera.rgb')
        camera_bp.set_attribute('image_size_x', '1280')
        camera_bp.set_attribute('image_size_y', '720')
        camera_bp.set_attribute('fov', '110')

        camera_configs = {
            'front': (carla.Transform(carla.Location(x=0.8, y=0.0, z=1.4), carla.Rotation(pitch=8)), 'front'),
            'front_left': (carla.Transform(carla.Location(x=-0.1, y=-0.4, z=1.2), carla.Rotation(yaw=-60)), 'front_left'),
            'front_right': (carla.Transform(carla.Location(x=-0.1, y=0.4, z=1.2), carla.Rotation(yaw=60)), 'front_right'),
            'rear': (carla.Transform(carla.Location(x=-0.2, y=0.3, z=1.25), carla.Rotation(yaw=180, pitch=5)), 'rear')
        }

        for cam_name, (transform, _) in camera_configs.items():
            camera = world.spawn_actor(camera_bp, transform, attach_to=ego_vehicle)
            camera.listen(make_camera_callback(cam_name))
            cameras.append(camera)
            actors.append(camera)
            print(f"[INFO] {cam_name} camera attached")

        # Setup semantic segmentation camera for ego vehicle
        semseg_bp = blueprint_library.find('sensor.camera.semantic_segmentation')
        semseg_bp.set_attribute('image_size_x', '1280')
        semseg_bp.set_attribute('image_size_y', '720')
        semseg_camera = world.spawn_actor(
            semseg_bp,
            carla.Transform(carla.Location(x=0.8, z=1.4)),
            attach_to=ego_vehicle
        )
        actors.append(semseg_camera)
        print("[INFO] Semantic segmentation camera attached")

        # Setup spectator to follow ego vehicle
        spectator = world.get_spectator()

        # Camera warm-up
        print("[INFO] Warming up cameras...")
        for _ in range(30):
            world.tick()
        time.sleep(0.5)
        print("[INFO] Cameras ready")

        # Main simulation loop
        print("[INFO] Starting simulation...")
        log_file.write("Starting simulation\n")
        
        frame_number = 1
        simulation_start_time = time.time()
        max_frames = args.duration * 20
        
        pedestrian_started_crossing = False
        pedestrian_start_frame = int(2.0 / 0.05)
        pedestrian_crossed = False
        
        # Calculate crossing target location
        crossing_target = carla.Location(
            x=jaywalking_location.x - right_vector.x * 18.0,
            y=jaywalking_location.y - right_vector.y * 18.0,
            z=jaywalking_location.z + 1.0
        )

        while frame_number <= max_frames:
            world.tick()
            
            # Control pedestrian crossing behavior
            if pedestrian and walker_controller and not pedestrian_crossed:
                if frame_number >= pedestrian_start_frame and not pedestrian_started_crossing:
                    # Start pedestrian crossing suddenly
                    walker_controller.go_to_location(crossing_target)
                    walker_controller.set_max_speed(4.5)
                    pedestrian_started_crossing = True
                    print(f"[INFO] Frame {frame_number}: Pedestrian SUDDENLY started crossing at running speed (4.5 m/s)")
                    log_file.write(f"Frame {frame_number}: Pedestrian started crossing\n")
                
                # Check if pedestrian reached other side
                if pedestrian_started_crossing:
                    ped_location = pedestrian.get_location()
                    distance_to_target = ped_location.distance(crossing_target)
                    
                    if distance_to_target < 3.0:
                        pedestrian_crossed = True
                        print(f"[INFO] Frame {frame_number}: Pedestrian reached opposite sidewalk")
                        log_file.write(f"Frame {frame_number}: Pedestrian reached opposite sidewalk\n")

            # Update spectator to follow ego vehicle
            ego_transform = ego_vehicle.get_transform()
            spectator_transform = carla.Transform(
                ego_transform.location + carla.Location(x=-8, z=5),
                carla.Rotation(pitch=-15, yaw=ego_transform.rotation.yaw)
            )
            spectator.set_transform(spectator_transform)

            # Wait for all 4 cameras to capture
            if frame_ready.wait(timeout=1.0):
                with images_lock:
                    # Save all 4 camera images
                    for cam_name in ['front', 'front_left', 'front_right', 'rear']:
                        output_path = os.path.join(
                            output_dirs[cam_name],
                            f"{cam_name}_frame_{frame_number:08d}.png"
                        )
                        save_image_to_disk(images_received[cam_name], output_path)
                
                # Log progress every 100 frames
                if frame_number % 100 == 0:
                    ego_velocity = ego_vehicle.get_velocity()
                    speed_kmh = 3.6 * math.sqrt(ego_velocity.x**2 + ego_velocity.y**2 + ego_velocity.z**2)
                    ego_loc = ego_vehicle.get_location()
                    
                    elapsed = time.time() - simulation_start_time
                    progress_msg = (f"[INFO] Frame {frame_number}/{max_frames} | "
                                  f"Speed: {speed_kmh:.1f} km/h | "
                                  f"Location: ({ego_loc.x:.1f}, {ego_loc.y:.1f}) | "
                                  f"Elapsed: {elapsed:.1f}s")
                    print(progress_msg)
                    log_file.write(progress_msg + "\n")
                    
                    if pedestrian and pedestrian_started_crossing and not pedestrian_crossed:
                        ped_loc = pedestrian.get_location()
                        dist_to_ego = ego_loc.distance(ped_loc)
                        log_file.write(f"  Pedestrian crossing - Distance to ego: {dist_to_ego:.1f}m\n")

                frame_number += 1
            else:
                print(f"[WARNING] Frame {frame_number} camera timeout - skipping frame")
                log_file.write(f"[WARNING] Frame {frame_number} camera timeout\n")

            # Clear frame sync
            frame_ready.clear()
            with images_lock:
                images_received['front'] = None
                images_received['front_left'] = None
                images_received['front_right'] = None
                images_received['rear'] = None

            # End simulation if pedestrian has crossed and enough time passed
            if pedestrian_crossed and frame_number > pedestrian_start_frame + 300:
                print("[INFO] Pedestrian successfully crossed - ending simulation")
                log_file.write("Pedestrian successfully crossed - ending simulation\n")
                break

        print(f"[INFO] Simulation complete. {frame_number-1} frames captured per camera.")
        log_file.write(f"Simulation complete. {frame_number-1} frames captured per camera.\n")
        log_file.close()

    except KeyboardInterrupt:
        print("\n[INFO] Simulation interrupted by user")
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("[INFO] Cleaning up...")
        
        # Stop cameras
        for camera in cameras:
            if camera.is_listening:
                camera.stop()
        
        # Restore asynchronous mode
        if world is not None:
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)
        
        # Destroy actors
        if client is not None:
            client.apply_batch([carla.command.DestroyActor(actor) for actor in actors])
        
        print("[INFO] Cleanup complete")

if __name__ == '__main__':
    main()