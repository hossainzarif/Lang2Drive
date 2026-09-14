import carla
import random
import time
import math
import numpy as np
from PIL import Image
import argparse
import os
import threading
import logging

# Shared state for 4-camera synchronization
images_received = {'front': None, 'front_left': None, 'front_right': None, 'rear': None}
images_lock = threading.Lock()
frame_ready = threading.Event()

def save_image_to_disk(image, output_path):
    """Save CARLA image as RGB PNG"""
    try:
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = array.reshape((image.height, image.width, 4))
        # CRITICAL: CARLA uses BGRA - convert BGR to RGB
        array = array[:, :, :3][:, :, ::-1]  # BGR to RGB conversion
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

def setup_logger(log_path):
    """Setup logger for simulation data"""
    logger = logging.getLogger('sudden_pedestrian_crossing')
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger

def main():
    parser = argparse.ArgumentParser(description='CARLA Sudden Pedestrian Crossing Scenario')
    parser.add_argument('--host', default='127.0.0.1', help='CARLA server host')
    parser.add_argument('--port', type=int, default=2000, help='CARLA server port')
    parser.add_argument('--duration', type=float, default=25.0, help='Simulation duration in seconds')
    parser.add_argument('--output-dir', default='./scenes/sudden_pedestrian_crossing', help='Output directory')
    args = parser.parse_args()

    # Create output directories
    os.makedirs(args.output_dir, exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'front'), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'front_left'), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'front_right'), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'rear'), exist_ok=True)

    # Setup logger
    log_path = os.path.join(args.output_dir, 'sudden_pedestrian_crossing_simulation.log')
    logger = setup_logger(log_path)

    client = None
    world = None
    actors = []
    cameras = []

    try:
        # Connect to CARLA
        print(f"[INFO] Connecting to CARLA server at {args.host}:{args.port}")
        client = carla.Client(args.host, args.port)
        client.set_timeout(60.0)
        
        # Test connection
        print(f"[INFO] CARLA server version: {client.get_server_version()}")

        # Load Town03 (good for urban scenarios)
        print("[INFO] Loading Town03...")
        world = client.load_world('Town03')
        time.sleep(2.0)

        blueprint_library = world.get_blueprint_library()
        spawn_points = world.get_map().get_spawn_points()

        # Set synchronous mode
        print("[INFO] Setting synchronous mode...")
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05  # 20 FPS
        world.apply_settings(settings)

        # Set weather to clear noon
        weather = carla.WeatherParameters(
            cloudiness=10.0,
            precipitation=0.0,
            sun_altitude_angle=70.0,
            fog_density=0.0
        )
        world.set_weather(weather)
        print("[INFO] Weather set to clear noon")

        # Find a suitable spawn point for ego vehicle on a straight road
        print("[INFO] Finding suitable spawn point...")
        ego_spawn = None
        for sp in spawn_points:
            # Look for spawn points in Town03 that have good straight sections
            if sp.location.x > 0 and sp.location.y < 0:  # Eastern part of Town03
                ego_spawn = sp
                break
        
        if ego_spawn is None:
            ego_spawn = spawn_points[50]  # Fallback

        print(f"[INFO] Ego spawn location: {ego_spawn.location}")

        # Spawn ego vehicle (Tesla Model 3)
        print("[INFO] Spawning ego vehicle...")
        ego_bp = blueprint_library.filter('vehicle.tesla.model3')[0]
        ego_vehicle = world.try_spawn_actor(ego_bp, ego_spawn)
        if ego_vehicle is None:
            print("[ERROR] Failed to spawn ego vehicle, trying alternative spawn points...")
            for sp in spawn_points[:10]:
                ego_vehicle = world.try_spawn_actor(ego_bp, sp)
                if ego_vehicle:
                    ego_spawn = sp
                    break
        
        if ego_vehicle is None:
            raise Exception("Failed to spawn ego vehicle after multiple attempts")
        
        actors.append(ego_vehicle)
        print(f"[INFO] Ego vehicle spawned: {ego_vehicle.id}")

        # Set initial velocity to 40 km/h
        forward_vector = ego_spawn.rotation.get_forward_vector()
        initial_velocity = carla.Vector3D(
            forward_vector.x * (40.0 / 3.6),
            forward_vector.y * (40.0 / 3.6),
            forward_vector.z * (40.0 / 3.6)
        )
        ego_vehicle.set_target_velocity(initial_velocity)

        # Attach collision sensor
        collision_bp = blueprint_library.find('sensor.other.collision')
        collision_sensor = world.spawn_actor(
            collision_bp,
            carla.Transform(),
            attach_to=ego_vehicle
        )
        actors.append(collision_sensor)
        
        collision_detected = {'value': False}
        def on_collision(event):
            collision_detected['value'] = True
            logger.info(f"COLLISION detected with {event.other_actor.type_id}")
            print(f"[WARNING] COLLISION detected with {event.other_actor.type_id}")
        
        collision_sensor.listen(on_collision)

        # Attach lane invasion sensor
        lane_invasion_bp = blueprint_library.find('sensor.other.lane_invasion')
        lane_invasion_sensor = world.spawn_actor(
            lane_invasion_bp,
            carla.Transform(),
            attach_to=ego_vehicle
        )
        actors.append(lane_invasion_sensor)
        
        def on_lane_invasion(event):
            logger.info(f"Lane invasion: {event.crossed_lane_markings}")
        
        lane_invasion_sensor.listen(on_lane_invasion)

        # Setup 4 driver-POV cameras
        print("[INFO] Setting up 4 driver-POV cameras...")
        camera_bp = blueprint_library.find('sensor.camera.rgb')
        camera_bp.set_attribute('image_size_x', '1280')
        camera_bp.set_attribute('image_size_y', '720')
        camera_bp.set_attribute('fov', '110')

        # Front camera (hood-cam view)
        front_transform = carla.Transform(
            carla.Location(x=0.8, y=0.0, z=1.4),
            carla.Rotation(pitch=-8)
        )
        front_camera = world.spawn_actor(camera_bp, front_transform, attach_to=ego_vehicle)
        front_camera.listen(make_camera_callback('front'))
        actors.append(front_camera)
        cameras.append(front_camera)

        # Front-left camera
        front_left_transform = carla.Transform(
            carla.Location(x=-0.1, y=-0.4, z=1.2),
            carla.Rotation(yaw=-60)
        )
        front_left_camera = world.spawn_actor(camera_bp, front_left_transform, attach_to=ego_vehicle)
        front_left_camera.listen(make_camera_callback('front_left'))
        actors.append(front_left_camera)
        cameras.append(front_left_camera)

        # Front-right camera
        front_right_transform = carla.Transform(
            carla.Location(x=-0.1, y=0.4, z=1.2),
            carla.Rotation(yaw=60)
        )
        front_right_camera = world.spawn_actor(camera_bp, front_right_transform, attach_to=ego_vehicle)
        front_right_camera.listen(make_camera_callback('front_right'))
        actors.append(front_right_camera)
        cameras.append(front_right_camera)

        # Rear camera
        rear_transform = carla.Transform(
            carla.Location(x=-0.2, y=0.3, z=1.25),
            carla.Rotation(yaw=180, pitch=5)
        )
        rear_camera = world.spawn_actor(camera_bp, rear_transform, attach_to=ego_vehicle)
        rear_camera.listen(make_camera_callback('rear'))
        actors.append(rear_camera)
        cameras.append(rear_camera)

        print("[INFO] All cameras attached")

        # Calculate pedestrian crossing point (35 meters ahead of ego - closer for better visibility)
        ego_location = ego_vehicle.get_location()
        ego_forward = ego_spawn.rotation.get_forward_vector()
        
        # Pedestrian crossing point: 35 meters ahead of ego
        crossing_point = carla.Location(
            x=ego_location.x + ego_forward.x * 35.0,
            y=ego_location.y + ego_forward.y * 35.0,
            z=ego_location.z
        )

        # Calculate right sidewalk position (6 meters to the right of crossing point)
        ego_right = ego_spawn.rotation.get_right_vector()
        pedestrian_start = carla.Location(
            x=crossing_point.x + ego_right.x * 6.0,
            y=crossing_point.y + ego_right.y * 6.0,
            z=ego_location.z + 1.2
        )

        # Try to find a valid waypoint near the pedestrian start
        carla_map = world.get_map()
        nearest_waypoint = carla_map.get_waypoint(pedestrian_start, project_to_road=False, lane_type=carla.LaneType.Sidewalk)
        if nearest_waypoint:
            pedestrian_start = nearest_waypoint.transform.location
            pedestrian_start.z += 1.0
            print(f"[INFO] Adjusted pedestrian start to valid sidewalk position")

        # Spawn pedestrian
        print("[INFO] Spawning pedestrian...")
        walker_bp = random.choice(blueprint_library.filter('walker.pedestrian.*'))
        if walker_bp.has_attribute('is_invincible'):
            walker_bp.set_attribute('is_invincible', 'false')
        
        pedestrian_spawn = carla.Transform(pedestrian_start, carla.Rotation(yaw=0))
        pedestrian = None
        
        # Try multiple spawn attempts with different heights
        for height_offset in [0.0, 0.5, 1.0, -0.5, 1.5]:
            test_location = carla.Location(
                x=pedestrian_start.x,
                y=pedestrian_start.y,
                z=pedestrian_start.z + height_offset
            )
            pedestrian_spawn = carla.Transform(test_location, carla.Rotation(yaw=0))
            pedestrian = world.try_spawn_actor(walker_bp, pedestrian_spawn)
            if pedestrian:
                print(f"[INFO] Pedestrian spawned at height offset {height_offset}")
                break
        
        if pedestrian:
            actors.append(pedestrian)
            print(f"[INFO] Pedestrian spawned at {pedestrian.get_location()}")
            
            # Spawn pedestrian controller
            walker_controller_bp = blueprint_library.find('controller.ai.walker')
            pedestrian_controller = world.spawn_actor(walker_controller_bp, carla.Transform(), pedestrian)
            actors.append(pedestrian_controller)
            
            # Start pedestrian (initially stopped)
            pedestrian_controller.start()
            pedestrian_controller.set_max_speed(0.0)
            print(f"[INFO] Pedestrian controller initialized")
        else:
            print("[WARNING] Failed to spawn pedestrian after multiple attempts")
            pedestrian_controller = None

        # Setup Traffic Manager for ambient vehicles
        print("[INFO] Setting up Traffic Manager...")
        traffic_manager = client.get_trafficmanager(8000)
        traffic_manager.set_synchronous_mode(True)
        traffic_manager.set_global_distance_to_leading_vehicle(2.5)

        # Spawn ambient vehicles
        print("[INFO] Spawning ambient vehicles...")
        vehicle_bps = blueprint_library.filter('vehicle.*')
        vehicle_bps = [x for x in vehicle_bps if int(x.get_attribute('number_of_wheels')) == 4]
        vehicle_bps = [x for x in vehicle_bps if not x.id.endswith('isetta')]
        vehicle_bps = [x for x in vehicle_bps if not x.id.endswith('carlacola')]
        vehicle_bps = [x for x in vehicle_bps if not x.id.endswith('cybertruck')]
        vehicle_bps = [x for x in vehicle_bps if not x.id.endswith('t2')]

        # Vehicle 1: 20m ahead in left lane
        ahead_left_location = carla.Location(
            x=ego_location.x + ego_forward.x * 20.0 - ego_right.x * 3.5,
            y=ego_location.y + ego_forward.y * 20.0 - ego_right.y * 3.5,
            z=ego_location.z + 0.5
        )
        ahead_left_spawn = carla.Transform(ahead_left_location, ego_spawn.rotation)
        vehicle1 = world.try_spawn_actor(random.choice(vehicle_bps), ahead_left_spawn)
        if vehicle1:
            actors.append(vehicle1)
            vehicle1.set_autopilot(True, traffic_manager.get_port())
            traffic_manager.vehicle_percentage_speed_difference(vehicle1, -20)

        # Vehicle 2: 30m behind in right lane
        behind_right_location = carla.Location(
            x=ego_location.x - ego_forward.x * 30.0,
            y=ego_location.y - ego_forward.y * 30.0,
            z=ego_location.z + 0.5
        )
        behind_right_spawn = carla.Transform(behind_right_location, ego_spawn.rotation)
        vehicle2 = world.try_spawn_actor(random.choice(vehicle_bps), behind_right_spawn)
        if vehicle2:
            actors.append(vehicle2)
            vehicle2.set_autopilot(True, traffic_manager.get_port())
            traffic_manager.vehicle_percentage_speed_difference(vehicle2, -15)

        # Vehicles in opposite direction
        opposite_rotation = carla.Rotation(
            pitch=ego_spawn.rotation.pitch,
            yaw=ego_spawn.rotation.yaw + 180,
            roll=ego_spawn.rotation.roll
        )
        
        # Vehicle 3: opposite direction, offset
        opposite1_location = carla.Location(
            x=ego_location.x + ego_forward.x * 40.0 - ego_right.x * 7.0,
            y=ego_location.y + ego_forward.y * 40.0 - ego_right.y * 7.0,
            z=ego_location.z + 0.5
        )
        opposite1_spawn = carla.Transform(opposite1_location, opposite_rotation)
        vehicle3 = world.try_spawn_actor(random.choice(vehicle_bps), opposite1_spawn)
        if vehicle3:
            actors.append(vehicle3)
            vehicle3.set_autopilot(True, traffic_manager.get_port())
            traffic_manager.vehicle_percentage_speed_difference(vehicle3, -30)

        # Vehicle 4: opposite direction, different position
        opposite2_location = carla.Location(
            x=ego_location.x + ego_forward.x * 60.0 - ego_right.x * 10.5,
            y=ego_location.y + ego_forward.y * 60.0 - ego_right.y * 10.5,
            z=ego_location.z + 0.5
        )
        opposite2_spawn = carla.Transform(opposite2_location, opposite_rotation)
        vehicle4 = world.try_spawn_actor(random.choice(vehicle_bps), opposite2_spawn)
        if vehicle4:
            actors.append(vehicle4)
            vehicle4.set_autopilot(True, traffic_manager.get_port())
            traffic_manager.vehicle_percentage_speed_difference(vehicle4, -25)

        print(f"[INFO] Spawned {len([a for a in actors if 'vehicle' in a.type_id])} total vehicles")

        # Camera warm-up
        print("[INFO] Warming up cameras...")
        for _ in range(20):
            world.tick()
        time.sleep(0.5)
        print("[INFO] Cameras ready")

        # Setup spectator to follow ego vehicle
        spectator = world.get_spectator()

        # Main simulation loop
        print("[INFO] Starting simulation...")
        frame_number = 0
        max_frames = min(int(args.duration * 20), 500)
        
        pedestrian_crossing_started = False
        pedestrian_wait_frames = 40  # Wait ~2 seconds (40 frames at 20 FPS)
        pedestrian_trigger_distance = 28.0  # Start crossing when ego is 28m away
        frames_since_start = 0
        
        logger.info("=== Simulation Start ===")
        logger.info(f"Ego vehicle: {ego_vehicle.id}")
        logger.info(f"Initial location: {ego_location}")
        logger.info(f"Pedestrian crossing point: {crossing_point}")
        if pedestrian:
            logger.info(f"Pedestrian spawned at: {pedestrian.get_location()}")

        start_time = time.time()

        while frame_number < max_frames:
            world.tick()
            frames_since_start += 1
            
            # Get ego vehicle state
            ego_transform = ego_vehicle.get_transform()
            ego_velocity = ego_vehicle.get_velocity()
            ego_speed_kmh = 3.6 * math.sqrt(ego_velocity.x**2 + ego_velocity.y**2 + ego_velocity.z**2)
            ego_control = ego_vehicle.get_control()
            
            # Calculate distance to crossing point
            distance_to_crossing = ego_transform.location.distance(crossing_point)
            
            # Trigger pedestrian crossing when:
            # 1. Waited initial frames (1-2 seconds)
            # 2. Ego is close enough (25-30 meters)
            if not pedestrian_crossing_started and frames_since_start > pedestrian_wait_frames and pedestrian_controller:
                if distance_to_crossing <= pedestrian_trigger_distance:
                    pedestrian_crossing_started = True
                    
                    # Set pedestrian to run across the road at 5 m/s
                    pedestrian_controller.set_max_speed(5.0)
                    
                    # Calculate perpendicular crossing direction (from right to left of ego)
                    # Move pedestrian to the opposite side of the road
                    crossing_target = carla.Location(
                        x=crossing_point.x - ego_right.x * 15.0,
                        y=crossing_point.y - ego_right.y * 15.0,
                        z=crossing_point.z
                    )
                    pedestrian_controller.go_to_location(crossing_target)
                    
                    print(f"[INFO] Frame {frame_number}: PEDESTRIAN STARTS CROSSING! Distance: {distance_to_crossing:.2f}m")
                    logger.info(f"Frame {frame_number}: Pedestrian crossing triggered at distance {distance_to_crossing:.2f}m")
                    logger.info(f"Pedestrian target location: {crossing_target}")
            
            # Get pedestrian state and log
            if pedestrian:
                ped_location = pedestrian.get_location()
                ped_velocity = pedestrian.get_velocity()
                ped_speed = math.sqrt(ped_velocity.x**2 + ped_velocity.y**2 + ped_velocity.z**2)
                distance_ego_to_ped = ego_transform.location.distance(ped_location)
                
                if frame_number % 10 == 0:  # Log every 10 frames (0.5 seconds)
                    logger.info(
                        f"Frame {frame_number:04d}: "
                        f"Ego Speed={ego_speed_kmh:.1f} km/h, "
                        f"Throttle={ego_control.throttle:.2f}, "
                        f"Brake={ego_control.brake:.2f}, "
                        f"Dist to Crossing={distance_to_crossing:.2f}m, "
                        f"Dist to Ped={distance_ego_to_ped:.2f}m, "
                        f"Ped Speed={ped_speed:.2f} m/s, "
                        f"Ped Crossing={pedestrian_crossing_started}"
                    )
            
            # Wait for all 4 cameras to capture
            if frame_ready.wait(timeout=1.0):
                with images_lock:
                    # Save all 4 camera images
                    front_path = os.path.join(args.output_dir, 'front', f'front_frame_{frame_number:08d}.png')
                    front_left_path = os.path.join(args.output_dir, 'front_left', f'front_left_frame_{frame_number:08d}.png')
                    front_right_path = os.path.join(args.output_dir, 'front_right', f'front_right_frame_{frame_number:08d}.png')
                    rear_path = os.path.join(args.output_dir, 'rear', f'rear_frame_{frame_number:08d}.png')
                    
                    save_image_to_disk(images_received['front'], front_path)
                    save_image_to_disk(images_received['front_left'], front_left_path)
                    save_image_to_disk(images_received['front_right'], front_right_path)
                    save_image_to_disk(images_received['rear'], rear_path)
                
                frame_number += 1
                
                # Progress update every 100 frames
                if frame_number % 100 == 0:
                    elapsed = time.time() - start_time
                    print(f"[INFO] Frame {frame_number}/{max_frames} - "
                          f"Speed: {ego_speed_kmh:.1f} km/h - "
                          f"Elapsed: {elapsed:.1f}s")
            else:
                print(f"[WARNING] Frame {frame_number} camera timeout - skipping frame")
            
            # Clear for next frame
            frame_ready.clear()
            with images_lock:
                images_received['front'] = None
                images_received['front_left'] = None
                images_received['front_right'] = None
                images_received['rear'] = None
            
            # Update spectator position to follow ego vehicle from above-rear angle
            spectator_transform = carla.Transform(
                ego_transform.location + carla.Location(x=-10, z=10),
                carla.Rotation(pitch=-30, yaw=ego_transform.rotation.yaw)
            )
            spectator.set_transform(spectator_transform)
            
            # Check for collision
            if collision_detected['value']:
                print("[WARNING] Collision detected! Continuing simulation...")
                logger.info(f"Frame {frame_number}: Collision occurred")

        # Simulation complete
        elapsed_time = time.time() - start_time
        print(f"\n[INFO] Simulation complete!")
        print(f"[INFO] Total frames captured: {frame_number}")
        print(f"[INFO] Total time: {elapsed_time:.2f}s")
        print(f"[INFO] Images saved to: {args.output_dir}")
        
        logger.info("=== Simulation End ===")
        logger.info(f"Total frames: {frame_number}")
        logger.info(f"Total time: {elapsed_time:.2f}s")
        logger.info(f"Collision occurred: {collision_detected['value']}")

    except Exception as e:
        print(f"[ERROR] Exception occurred: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("\n[INFO] Cleaning up...")
        
        # Stop cameras
        for camera in cameras:
            if camera is not None:
                camera.stop()
        
        # Destroy all actors
        if world is not None:
            for actor in actors:
                if actor is not None and actor.is_alive:
                    actor.destroy()
            print(f"[INFO] Destroyed {len(actors)} actors")
        
        # Restore asynchronous mode
        if world is not None:
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)
            print("[INFO] Restored asynchronous mode")
        
        print("[INFO] Cleanup complete")

if __name__ == '__main__':
    main()