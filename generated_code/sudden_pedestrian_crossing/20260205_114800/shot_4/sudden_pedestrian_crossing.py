import carla
import random
import time
import argparse
import os
import sys
import math
import threading
import numpy as np
from PIL import Image

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

def setup_cameras(world, vehicle, output_dir):
    """Setup 4 driver-POV cameras"""
    camera_bp = world.get_blueprint_library().find('sensor.camera.rgb')
    camera_bp.set_attribute('image_size_x', '1280')
    camera_bp.set_attribute('image_size_y', '720')
    camera_bp.set_attribute('fov', '110')
    
    cameras = {}
    
    # FRONT camera
    front_transform = carla.Transform(carla.Location(x=0.8, y=0.0, z=1.4), carla.Rotation(pitch=8))
    cameras['front'] = world.spawn_actor(camera_bp, front_transform, attach_to=vehicle)
    cameras['front'].listen(make_camera_callback('front'))
    
    # FRONT_LEFT camera
    front_left_transform = carla.Transform(carla.Location(x=-0.1, y=-0.4, z=1.2), carla.Rotation(yaw=-60))
    cameras['front_left'] = world.spawn_actor(camera_bp, front_left_transform, attach_to=vehicle)
    cameras['front_left'].listen(make_camera_callback('front_left'))
    
    # FRONT_RIGHT camera
    front_right_transform = carla.Transform(carla.Location(x=-0.1, y=0.4, z=1.2), carla.Rotation(yaw=60))
    cameras['front_right'] = world.spawn_actor(camera_bp, front_right_transform, attach_to=vehicle)
    cameras['front_right'].listen(make_camera_callback('front_right'))
    
    # REAR camera
    rear_transform = carla.Transform(carla.Location(x=-0.2, y=0.3, z=1.25), carla.Rotation(yaw=180, pitch=5))
    cameras['rear'] = world.spawn_actor(camera_bp, rear_transform, attach_to=vehicle)
    cameras['rear'].listen(make_camera_callback('rear'))
    
    return cameras

def get_spawn_point_away_from_intersections(world, spawn_points, min_distance=50.0):
    """Find a spawn point at least min_distance from any traffic light"""
    traffic_lights = world.get_actors().filter('traffic.traffic_light')
    
    for sp in spawn_points:
        is_far = True
        for tl in traffic_lights:
            dist = sp.location.distance(tl.get_location())
            if dist < min_distance:
                is_far = False
                break
        if is_far:
            return sp
    return None

def main():
    parser = argparse.ArgumentParser(description='CARLA Sudden Pedestrian Crossing Scenario')
    parser.add_argument('--host', default='127.0.0.1', help='CARLA server host')
    parser.add_argument('--port', type=int, default=2000, help='CARLA server port')
    parser.add_argument('--duration', type=float, default=15.0, help='Simulation duration in seconds')
    parser.add_argument('--output-dir', default='./scenes/sudden_pedestrian_crossing', help='Output directory')
    args = parser.parse_args()
    
    # Create output directories
    os.makedirs(os.path.join(args.output_dir, 'front'), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'front_left'), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'front_right'), exist_ok=True)
    os.makedirs(os.path.join(args.output_dir, 'rear'), exist_ok=True)
    
    log_file = open(os.path.join(args.output_dir, 'sudden_pedestrian_crossing_simulation.log'), 'w')
    
    client = None
    world = None
    actors = []
    cameras = {}
    
    try:
        # Connect to CARLA
        client = carla.Client(args.host, args.port)
        client.set_timeout(60.0)
        
        print("[INFO] Testing CARLA connection...")
        world = client.get_world()
        print("[INFO] Connected to CARLA")
        
        # CRITICAL: Clear all existing vehicles first
        print("[INFO] Clearing all existing vehicles...")
        existing_vehicles = world.get_actors().filter('vehicle.*')
        for vehicle in existing_vehicles:
            vehicle.destroy()
        time.sleep(0.5)
        print(f"[INFO] Cleared {len(existing_vehicles)} vehicles")
        
        # Clear all existing walkers
        print("[INFO] Clearing all existing walkers...")
        existing_walkers = world.get_actors().filter('walker.*')
        for walker in existing_walkers:
            walker.destroy()
        time.sleep(0.5)
        print(f"[INFO] Cleared {len(existing_walkers)} walkers")
        
        # Set synchronous mode
        original_settings = world.get_settings()
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)
        
        # Set weather
        weather = carla.WeatherParameters(
            cloudiness=20.0,
            precipitation=0.0,
            sun_altitude_angle=45.0,
            fog_density=0.0
        )
        world.set_weather(weather)
        
        blueprint_library = world.get_blueprint_library()
        spawn_points = world.get_map().get_spawn_points()
        
        # Find spawn point away from intersections
        ego_spawn = get_spawn_point_away_from_intersections(world, spawn_points, min_distance=50.0)
        if not ego_spawn:
            ego_spawn = random.choice(spawn_points)
        
        print(f"[INFO] Ego spawn point: {ego_spawn.location}")
        
        # Spawn ego vehicle
        ego_bp = blueprint_library.filter('vehicle.tesla.model3')[0]
        ego_vehicle = world.try_spawn_actor(ego_bp, ego_spawn)
        if not ego_vehicle:
            ego_spawn = random.choice(spawn_points)
            ego_vehicle = world.spawn_actor(ego_bp, ego_spawn)
        actors.append(ego_vehicle)
        print(f"[INFO] Spawned ego vehicle at {ego_vehicle.get_location()}")
        
        # Setup cameras
        cameras = setup_cameras(world, ego_vehicle, args.output_dir)
        actors.extend(cameras.values())
        
        # Camera warm-up
        print("[INFO] Warming up cameras...")
        for _ in range(30):
            world.tick()
        time.sleep(0.5)
        print("[INFO] Cameras ready")
        
        # Calculate pedestrian crossing point - 50 meters ahead
        ego_transform = ego_vehicle.get_transform()
        forward = ego_transform.rotation.get_forward_vector()
        right = ego_transform.rotation.get_right_vector()
        
        # Pedestrian crossing point 50m ahead in ego lane
        crossing_distance = 50.0
        crossing_point = carla.Location(
            x=ego_transform.location.x + forward.x * crossing_distance,
            y=ego_transform.location.y + forward.y * crossing_distance,
            z=ego_transform.location.z
        )
        
        # Spawn pedestrian on right sidewalk at crossing point
        walker_bp = random.choice(blueprint_library.filter('walker.pedestrian.*'))
        # Place pedestrian 6m to the right of the road (on sidewalk)
        pedestrian_spawn_loc = carla.Location(
            x=crossing_point.x + right.x * 6.0,
            y=crossing_point.y + right.y * 6.0,
            z=crossing_point.z + 1.0
        )
        pedestrian_spawn = carla.Transform(pedestrian_spawn_loc, carla.Rotation(yaw=ego_transform.rotation.yaw - 90))
        pedestrian = world.try_spawn_actor(walker_bp, pedestrian_spawn)
        if not pedestrian:
            pedestrian_spawn_loc.z += 0.5
            pedestrian_spawn = carla.Transform(pedestrian_spawn_loc)
            pedestrian = world.spawn_actor(walker_bp, pedestrian_spawn)
        actors.append(pedestrian)
        print(f"[INFO] Spawned pedestrian at {pedestrian.get_location()}")
        
        # Spawn pedestrian controller
        walker_controller_bp = blueprint_library.find('controller.ai.walker')
        pedestrian_controller = world.spawn_actor(walker_controller_bp, carla.Transform(), pedestrian)
        actors.append(pedestrian_controller)
        pedestrian_controller.start()
        
        # Set ego vehicle speed to 50 km/h (13.9 m/s) with autopilot disabled
        ego_vehicle.set_autopilot(False)
        
        # Collision detection
        collision_detected = [False]
        collision_frame = [0]
        def on_collision(event):
            if not collision_detected[0]:
                collision_detected[0] = True
                collision_frame[0] = frame_number
                log_file.write(f"[COLLISION] Frame {frame_number}: {event}\n")
                print(f"[COLLISION] Detected at frame {frame_number}")
        
        collision_sensor_bp = blueprint_library.find('sensor.other.collision')
        collision_sensor = world.spawn_actor(collision_sensor_bp, carla.Transform(), attach_to=ego_vehicle)
        actors.append(collision_sensor)
        collision_sensor.listen(on_collision)
        
        # Spectator setup
        spectator = world.get_spectator()
        
        # Simulation variables
        max_frames = 300  # 15 seconds at 20 FPS
        frame_number = 0
        simulation_start_time = time.time()
        pedestrian_crossing_started = False
        pedestrian_standing_in_lane = False
        emergency_braking = False
        pedestrian_wait_frames = 40  # Wait 2 seconds before crossing (40 frames * 0.05s)
        standing_start_frame = 0
        standing_duration_frames = 40  # Stand for 2 seconds
        
        # Target position in ego lane (center of road, slightly left)
        target_standing_location = carla.Location(
            x=crossing_point.x - right.x * 0.5,
            y=crossing_point.y - right.y * 0.5,
            z=crossing_point.z
        )
        
        log_file.write(f"[INFO] Simulation started\n")
        log_file.write(f"[INFO] Ego vehicle spawn: {ego_spawn.location}\n")
        log_file.write(f"[INFO] Pedestrian crossing point: {crossing_point}\n")
        log_file.write(f"[INFO] Target standing location: {target_standing_location}\n")
        log_file.write(f"[INFO] Max frames: {max_frames}\n")
        
        print(f"[INFO] Starting main simulation loop (max {max_frames} frames)")
        
        # Main simulation loop
        while frame_number < max_frames:
            world.tick()
            
            # Control ego vehicle manually to maintain constant speed
            if not emergency_braking:
                control = carla.VehicleControl(throttle=0.5, steer=0.0, brake=0.0)
                ego_vehicle.apply_control(control)
            
            # Wait for all 4 cameras with timeout
            if frame_ready.wait(timeout=2.0):
                with images_lock:
                    # Save images
                    front_path = os.path.join(args.output_dir, 'front', f'front_frame_{frame_number:08d}.png')
                    front_left_path = os.path.join(args.output_dir, 'front_left', f'front_left_frame_{frame_number:08d}.png')
                    front_right_path = os.path.join(args.output_dir, 'front_right', f'front_right_frame_{frame_number:08d}.png')
                    rear_path = os.path.join(args.output_dir, 'rear', f'rear_frame_{frame_number:08d}.png')
                    
                    success_front = save_image_to_disk(images_received['front'], front_path)
                    success_fl = save_image_to_disk(images_received['front_left'], front_left_path)
                    success_fr = save_image_to_disk(images_received['front_right'], front_right_path)
                    success_rear = save_image_to_disk(images_received['rear'], rear_path)
                    
                    if success_front and success_fl and success_fr and success_rear:
                        frame_number += 1
                    else:
                        print(f"[WARNING] Frame save failed - retrying")
            else:
                print(f"[WARNING] Frame {frame_number} camera timeout")
            
            frame_ready.clear()
            with images_lock:
                images_received = {'front': None, 'front_left': None, 'front_right': None, 'rear': None}
            
            # Pedestrian crossing logic - wait then cross and stand
            if frame_number >= pedestrian_wait_frames and not pedestrian_crossing_started:
                pedestrian_crossing_started = True
                # Walk directly into ego vehicle's lane
                pedestrian_controller.go_to_location(target_standing_location)
                pedestrian_controller.set_max_speed(3.8)  # Fast jaywalking speed (3.5-4.0 m/s)
                print(f"[INFO] Frame {frame_number}: Pedestrian started crossing into ego lane")
                log_file.write(f"[INFO] Frame {frame_number}: Pedestrian started crossing\n")
            
            # Check if pedestrian reached the standing position in ego lane
            if pedestrian_crossing_started and not pedestrian_standing_in_lane and pedestrian:
                ped_loc = pedestrian.get_location()
                distance_to_target = ped_loc.distance(target_standing_location)
                
                # When pedestrian is close to center of ego lane, STOP and STAND
                if distance_to_target < 1.5:
                    pedestrian_standing_in_lane = True
                    standing_start_frame = frame_number
                    pedestrian_controller.stop()
                    print(f"[INFO] Frame {frame_number}: Pedestrian STANDING in ego vehicle lane")
                    log_file.write(f"[INFO] Frame {frame_number}: Pedestrian standing in ego lane\n")
            
            # Resume pedestrian movement after standing
            if pedestrian_standing_in_lane and (frame_number - standing_start_frame) >= standing_duration_frames:
                # Continue crossing to opposite sidewalk
                final_target = carla.Location(
                    x=crossing_point.x - right.x * 8.0,
                    y=crossing_point.y - right.y * 8.0,
                    z=crossing_point.z
                )
                pedestrian_controller.start()
                pedestrian_controller.go_to_location(final_target)
                pedestrian_controller.set_max_speed(3.5)
                pedestrian_standing_in_lane = False
                print(f"[INFO] Frame {frame_number}: Pedestrian resumed crossing after standing")
                log_file.write(f"[INFO] Frame {frame_number}: Pedestrian resumed crossing\n")
            
            # Emergency braking logic
            if pedestrian_crossing_started and not emergency_braking and pedestrian:
                ego_loc = ego_vehicle.get_location()
                ped_loc = pedestrian.get_location()
                
                # Calculate distance to pedestrian
                distance_to_ped = ego_loc.distance(ped_loc)
                ego_forward = ego_vehicle.get_transform().rotation.get_forward_vector()
                to_ped = carla.Vector3D(ped_loc.x - ego_loc.x, ped_loc.y - ego_loc.y, 0)
                forward_distance = to_ped.x * ego_forward.x + to_ped.y * ego_forward.y
                
                # Trigger emergency braking when pedestrian enters roadway ahead
                if forward_distance > 0 and forward_distance < 30.0 and distance_to_ped < 30.0:
                    emergency_braking = True
                    control = carla.VehicleControl(throttle=0.0, brake=1.0)
                    ego_vehicle.apply_control(control)
                    print(f"[INFO] Frame {frame_number}: Emergency braking activated")
                    log_file.write(f"[INFO] Frame {frame_number}: Emergency braking activated\n")
            
            # Update spectator to follow ego vehicle
            ego_transform = ego_vehicle.get_transform()
            ego_forward = ego_transform.rotation.get_forward_vector()
            spectator_transform = carla.Transform(
                ego_transform.location + carla.Location(z=6.0) - carla.Location(x=ego_forward.x * 12, y=ego_forward.y * 12),
                carla.Rotation(pitch=-20, yaw=ego_transform.rotation.yaw)
            )
            spectator.set_transform(spectator_transform)
            
            # Logging every 20 frames (1 second)
            if frame_number % 20 == 0:
                ego_velocity = ego_vehicle.get_velocity()
                speed = math.sqrt(ego_velocity.x**2 + ego_velocity.y**2 + ego_velocity.z**2) * 3.6
                ego_loc = ego_vehicle.get_location()
                log_msg = f"[INFO] Frame {frame_number}: Speed={speed:.2f} km/h, Location=({ego_loc.x:.2f}, {ego_loc.y:.2f}), Emergency_Braking={emergency_braking}, Ped_Standing={pedestrian_standing_in_lane}"
                print(log_msg)
                log_file.write(log_msg + '\n')
                
                if pedestrian:
                    ped_loc = pedestrian.get_location()
                    distance_to_ped = ego_loc.distance(ped_loc)
                    if distance_to_ped > 0 and speed > 1.0:
                        ttc = distance_to_ped / (speed / 3.6)
                        log_file.write(f"[INFO] Frame {frame_number}: Distance to pedestrian={distance_to_ped:.2f}m, TTC={ttc:.2f}s\n")
            
            # End simulation if collision occurred and save additional frames
            if collision_detected[0] and (frame_number - collision_frame[0]) > 20:
                print(f"[INFO] Collision detected - ending simulation after capturing post-collision frames")
                break
        
        elapsed_time = time.time() - simulation_start_time
        print(f"[INFO] Simulation completed: {frame_number} frames in {elapsed_time:.2f} seconds")
        log_file.write(f"[INFO] Simulation completed: {frame_number} frames in {elapsed_time:.2f} seconds\n")
        log_file.write(f"[INFO] Collision occurred: {collision_detected[0]}\n")
        
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        log_file.write(f"[ERROR] {e}\n")
        
    finally:
        print("[INFO] Cleaning up...")
        
        # Stop cameras
        for camera in cameras.values():
            if camera.is_alive:
                camera.stop()
        
        # Destroy actors
        for actor in actors:
            if actor.is_alive:
                actor.destroy()
        
        # Restore settings
        if world is not None:
            world.apply_settings(original_settings)
        
        log_file.close()
        print("[INFO] Cleanup complete")

if __name__ == '__main__':
    main()