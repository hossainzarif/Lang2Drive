#!/usr/bin/env python3

import carla
import random
import time
import math
import threading
import argparse
import os
import sys
import numpy as np
from PIL import Image

# ============================================================================
# GLOBAL SYNCHRONIZATION STATE FOR 4 CAMERAS
# ============================================================================
images_received = {'front': None, 'front_left': None, 'front_right': None, 'rear': None}
images_lock = threading.Lock()
frame_ready = threading.Event()

# ============================================================================
# CAMERA CALLBACK FACTORY
# ============================================================================
def make_camera_callback(camera_name):
    def callback(image):
        with images_lock:
            images_received[camera_name] = image
            if all(img is not None for img in images_received.values()):
                frame_ready.set()
    return callback

# ============================================================================
# IMAGE SAVING WITH BGR TO RGB CONVERSION
# ============================================================================
def save_image_to_disk(image, output_path):
    """Save CARLA image as RGB PNG with proper BGR to RGB conversion"""
    try:
        array = np.frombuffer(image.raw_data, dtype=np.uint8)
        array = array.reshape((image.height, image.width, 4))
        # CRITICAL: CARLA uses BGRA - convert BGR to RGB
        array = array[:, :, :3][:, :, ::-1]  # BGR to RGB conversion
        img = Image.fromarray(array)
        img.save(output_path, 'PNG')
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save image to {output_path}: {e}")
        return False

# ============================================================================
# COLLISION SENSOR CALLBACK
# ============================================================================
def collision_callback(event, collision_data):
    collision_data['occurred'] = True
    collision_data['frame'] = event.frame
    impulse = event.normal_impulse
    intensity = math.sqrt(impulse.x**2 + impulse.y**2 + impulse.z**2)
    collision_data['intensity'] = intensity
    other_actor = event.other_actor
    collision_data['other_actor'] = other_actor.type_id if other_actor else "Unknown"
    print(f"[COLLISION] Frame {event.frame}: Collision with {collision_data['other_actor']}, intensity={intensity:.2f}")

# ============================================================================
# MAIN FUNCTION
# ============================================================================
def main():
    parser = argparse.ArgumentParser(description='CARLA Sudden Pedestrian Crossing Scenario')
    parser.add_argument('--host', default='127.0.0.1', help='CARLA server host')
    parser.add_argument('--port', type=int, default=2000, help='CARLA server port')
    parser.add_argument('--duration', type=float, default=25.0, help='Simulation duration in seconds')
    parser.add_argument('--output-dir', default='./scenes/sudden_pedestrian_crossing', help='Output directory')
    args = parser.parse_args()

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
    
    client = None
    world = None
    actors_to_destroy = []
    
    try:
        # Connect to CARLA
        print(f"[INFO] Connecting to CARLA server at {args.host}:{args.port}")
        client = carla.Client(args.host, args.port)
        client.set_timeout(60.0)
        
        # Test connection
        print(f"[INFO] CARLA server version: {client.get_server_version()}")
        
        # Load Town03
        print("[INFO] Loading Town03...")
        world = client.load_world('Town03')
        time.sleep(2.0)
        
        blueprint_library = world.get_blueprint_library()
        spawn_points = world.get_map().get_spawn_points()
        
        # Set weather to clear noon
        weather = carla.WeatherParameters(
            cloudiness=10.0,
            precipitation=0.0,
            sun_altitude_angle=70.0,
            sun_azimuth_angle=0.0,
            fog_density=0.0,
            wetness=0.0
        )
        world.set_weather(weather)
        print("[INFO] Weather set to clear noon")
        
        # Configure synchronous mode
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05  # 20 FPS
        world.apply_settings(settings)
        print("[INFO] Synchronous mode enabled at 20 FPS")
        
        # Get Traffic Manager
        traffic_manager = client.get_trafficmanager(8000)
        traffic_manager.set_synchronous_mode(True)
        traffic_manager.set_global_distance_to_leading_vehicle(2.5)
        
        # Find suitable spawn point for ego vehicle (on a multi-lane road)
        print("[INFO] Finding suitable spawn point...")
        suitable_spawn = None
        for sp in spawn_points:
            waypoint = world.get_map().get_waypoint(sp.location)
            if waypoint.lane_id < 0 and waypoint.lane_type == carla.LaneType.Driving:
                # Check for multi-lane road
                left_lane = waypoint.get_left_lane()
                if left_lane and left_lane.lane_type == carla.LaneType.Driving:
                    suitable_spawn = sp
                    break
        
        if not suitable_spawn:
            print("[WARNING] No ideal spawn point found, using fallback")
            suitable_spawn = spawn_points[50]
        
        print(f"[INFO] Selected spawn point at {suitable_spawn.location}")
        
        # Spawn ego vehicle (Tesla Model 3)
        ego_bp = blueprint_library.filter('model3')[0]
        ego_bp.set_attribute('role_name', 'ego')
        ego_vehicle = world.try_spawn_actor(ego_bp, suitable_spawn)
        
        if not ego_vehicle:
            print("[ERROR] Failed to spawn ego vehicle")
            return
        
        actors_to_destroy.append(ego_vehicle)
        print(f"[INFO] Spawned ego vehicle: {ego_vehicle.type_id} at {ego_vehicle.get_location()}")
        
        # Get waypoint for pedestrian spawn (right side sidewalk, 60m ahead)
        ego_waypoint = world.get_map().get_waypoint(ego_vehicle.get_location())
        crossing_waypoint = ego_waypoint
        for _ in range(120):  # Move 60m forward (0.5m per waypoint)
            next_wps = crossing_waypoint.next(0.5)
            if next_wps:
                crossing_waypoint = next_wps[0]
        
        # Find right sidewalk location for pedestrian
        crossing_location = crossing_waypoint.transform.location
        right_vector = crossing_waypoint.transform.get_right_vector()
        pedestrian_spawn_location = carla.Location(
            x=crossing_location.x + right_vector.x * 5.0,
            y=crossing_location.y + right_vector.y * 5.0,
            z=crossing_location.z + 1.0
        )
        
        # Spawn pedestrian
        walker_bp = random.choice(blueprint_library.filter('walker.pedestrian.*'))
        if walker_bp.has_attribute('is_invincible'):
            walker_bp.set_attribute('is_invincible', 'false')
        
        pedestrian_spawn_transform = carla.Transform(pedestrian_spawn_location)
        pedestrian = world.try_spawn_actor(walker_bp, pedestrian_spawn_transform)
        
        if not pedestrian:
            print("[WARNING] Failed to spawn pedestrian at first location, trying alternative")
            pedestrian_spawn_location.x += 2.0
            pedestrian_spawn_location.y += 2.0
            pedestrian_spawn_transform.location = pedestrian_spawn_location
            pedestrian = world.try_spawn_actor(walker_bp, pedestrian_spawn_transform)
        
        if pedestrian:
            actors_to_destroy.append(pedestrian)
            print(f"[INFO] Spawned pedestrian at {pedestrian.get_location()}")
            
            # Spawn walker controller
            walker_controller_bp = blueprint_library.find('controller.ai.walker')
            walker_controller = world.spawn_actor(walker_controller_bp, carla.Transform(), pedestrian)
            actors_to_destroy.append(walker_controller)
            
            # Start pedestrian standing still initially
            walker_controller.start()
            walker_controller.set_max_speed(0.0)
        else:
            print("[WARNING] Could not spawn pedestrian")
            pedestrian = None
            walker_controller = None
        
        # Spawn parked vehicles on roadside before crossing point
        parked_spawn_location = carla.Location(
            x=crossing_location.x - right_vector.x * 20.0,
            y=crossing_location.y - right_vector.y * 20.0,
            z=crossing_location.z + 0.5
        )
        parked_spawn_location.x += right_vector.x * 3.5
        parked_spawn_location.y += right_vector.y * 3.5
        
        vehicle_bps = blueprint_library.filter('vehicle.*')
        vehicle_bps = [x for x in vehicle_bps if int(x.get_attribute('number_of_wheels')) == 4]
        
        for i in range(2):
            parked_bp = random.choice(vehicle_bps)
            parked_transform = carla.Transform(
                carla.Location(
                    x=parked_spawn_location.x - ego_waypoint.transform.get_forward_vector().x * (i * 8.0),
                    y=parked_spawn_location.y - ego_waypoint.transform.get_forward_vector().y * (i * 8.0),
                    z=parked_spawn_location.z
                ),
                crossing_waypoint.transform.rotation
            )
            parked_vehicle = world.try_spawn_actor(parked_bp, parked_transform)
            if parked_vehicle:
                actors_to_destroy.append(parked_vehicle)
                print(f"[INFO] Spawned parked vehicle {i+1}")
        
        # Spawn background traffic vehicles
        print("[INFO] Spawning background traffic...")
        for i in range(5):
            traffic_spawn = random.choice(spawn_points)
            traffic_bp = random.choice(vehicle_bps)
            traffic_vehicle = world.try_spawn_actor(traffic_bp, traffic_spawn)
            if traffic_vehicle:
                actors_to_destroy.append(traffic_vehicle)
                traffic_vehicle.set_autopilot(True, 8000)
                traffic_manager.ignore_lights_percentage(traffic_vehicle, 0.0)
                traffic_manager.vehicle_percentage_speed_difference(traffic_vehicle, random.uniform(-10, 10))
        
        print(f"[INFO] Spawned {len([a for a in actors_to_destroy if 'vehicle' in a.type_id])-1} background vehicles")
        
        # Attach collision sensor
        collision_data = {'occurred': False, 'frame': -1, 'intensity': 0.0, 'other_actor': None}
        collision_bp = blueprint_library.find('sensor.other.collision')
        collision_sensor = world.spawn_actor(collision_bp, carla.Transform(), attach_to=ego_vehicle)
        actors_to_destroy.append(collision_sensor)
        collision_sensor.listen(lambda event: collision_callback(event, collision_data))
        
        # Attach 4 driver-POV cameras
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
        actors_to_destroy.append(front_camera)
        front_camera.listen(make_camera_callback('front'))
        
        # Front-left camera
        front_left_transform = carla.Transform(
            carla.Location(x=-0.1, y=-0.4, z=1.2),
            carla.Rotation(yaw=-60)
        )
        front_left_camera = world.spawn_actor(camera_bp, front_left_transform, attach_to=ego_vehicle)
        actors_to_destroy.append(front_left_camera)
        front_left_camera.listen(make_camera_callback('front_left'))
        
        # Front-right camera
        front_right_transform = carla.Transform(
            carla.Location(x=-0.1, y=0.4, z=1.2),
            carla.Rotation(yaw=60)
        )
        front_right_camera = world.spawn_actor(camera_bp, front_right_transform, attach_to=ego_vehicle)
        actors_to_destroy.append(front_right_camera)
        front_right_camera.listen(make_camera_callback('front_right'))
        
        # Rear camera
        rear_transform = carla.Transform(
            carla.Location(x=-0.2, y=0.3, z=1.25),
            carla.Rotation(yaw=180, pitch=5)
        )
        rear_camera = world.spawn_actor(camera_bp, rear_transform, attach_to=ego_vehicle)
        actors_to_destroy.append(rear_camera)
        rear_camera.listen(make_camera_callback('rear'))
        
        print("[INFO] All 4 cameras attached")
        
        # Camera warm-up
        print("[INFO] Warming up cameras...")
        for _ in range(20):
            world.tick()
        time.sleep(0.5)
        print("[INFO] Cameras ready")
        
        # Enable autopilot for ego vehicle
        ego_vehicle.set_autopilot(True, 8000)
        traffic_manager.ignore_lights_percentage(ego_vehicle, 0.0)
        traffic_manager.vehicle_percentage_speed_difference(ego_vehicle, -10.0)  # 10% faster (50 km/h)
        traffic_manager.distance_to_leading_vehicle(ego_vehicle, 2.0)
        
        # Set up spectator to follow ego vehicle
        spectator = world.get_spectator()
        
        # Simulation variables
        frame_number = 1
        start_time = time.time()
        max_frames = int(args.duration * 20)  # 20 FPS
        pedestrian_triggered = False
        trigger_distance = 27.5  # meters (midpoint of 25-30)
        min_distance_to_pedestrian = float('inf')
        
        log_file.write("Frame,Time,EgoSpeed_kmh,DistanceToPedestrian_m,BrakeInput,CollisionOccurred\n")
        
        print(f"[INFO] Starting simulation for {args.duration} seconds ({max_frames} frames)")
        print("[INFO] Pedestrian will cross when ego vehicle is ~27.5m away")
        
        # Main simulation loop
        while frame_number <= max_frames:
            world.tick()
            
            # Update spectator position
            ego_transform = ego_vehicle.get_transform()
            spectator_transform = carla.Transform(
                ego_transform.location + carla.Location(x=-10, z=5),
                carla.Rotation(pitch=-15, yaw=ego_transform.rotation.yaw)
            )
            spectator.set_transform(spectator_transform)
            
            # Get ego vehicle data
            ego_velocity = ego_vehicle.get_velocity()
            ego_speed_ms = math.sqrt(ego_velocity.x**2 + ego_velocity.y**2 + ego_velocity.z**2)
            ego_speed_kmh = ego_speed_ms * 3.6
            ego_location = ego_vehicle.get_location()
            
            # Calculate distance to pedestrian
            distance_to_pedestrian = -1.0
            if pedestrian:
                pedestrian_location = pedestrian.get_location()
                distance_to_pedestrian = ego_location.distance(pedestrian_location)
                
                if distance_to_pedestrian < min_distance_to_pedestrian:
                    min_distance_to_pedestrian = distance_to_pedestrian
                
                # Trigger pedestrian crossing when ego vehicle is at trigger distance
                if not pedestrian_triggered and distance_to_pedestrian <= trigger_distance and distance_to_pedestrian > 15.0:
                    pedestrian_triggered = True
                    # Set pedestrian to run across the road
                    walker_controller.set_max_speed(4.5)  # 4.5 m/s (realistic sprinting pace)
                    
                    # Calculate target location on opposite sidewalk
                    left_vector = crossing_waypoint.transform.get_right_vector()
                    target_location = carla.Location(
                        x=crossing_location.x - left_vector.x * 10.0,
                        y=crossing_location.y - left_vector.y * 10.0,
                        z=crossing_location.z
                    )
                    walker_controller.go_to_location(target_location)
                    print(f"[EVENT] Frame {frame_number}: Pedestrian crossing triggered! Distance: {distance_to_pedestrian:.2f}m")
            
            # Get brake input
            control = ego_vehicle.get_control()
            brake_input = control.brake * 100.0
            
            # Wait for all 4 cameras to capture
            if frame_ready.wait(timeout=1.0):
                with images_lock:
                    # Save all 4 camera images
                    front_path = os.path.join(output_dirs['front'], f'front_frame_{frame_number:08d}.png')
                    front_left_path = os.path.join(output_dirs['front_left'], f'front_left_frame_{frame_number:08d}.png')
                    front_right_path = os.path.join(output_dirs['front_right'], f'front_right_frame_{frame_number:08d}.png')
                    rear_path = os.path.join(output_dirs['rear'], f'rear_frame_{frame_number:08d}.png')
                    
                    save_image_to_disk(images_received['front'], front_path)
                    save_image_to_disk(images_received['front_left'], front_left_path)
                    save_image_to_disk(images_received['front_right'], front_right_path)
                    save_image_to_disk(images_received['rear'], rear_path)
                
                # Log data
                elapsed_time = (frame_number - 1) * 0.05
                log_file.write(f"{frame_number},{elapsed_time:.2f},{ego_speed_kmh:.2f},{distance_to_pedestrian:.2f},{brake_input:.1f},{collision_data['occurred']}\n")
                
                # Print progress every 200 frames
                if frame_number % 200 == 0:
                    print(f"[PROGRESS] Frame {frame_number}/{max_frames} | "
                          f"Speed: {ego_speed_kmh:.1f} km/h | "
                          f"Dist to Pedestrian: {distance_to_pedestrian:.1f}m | "
                          f"Brake: {brake_input:.0f}% | "
                          f"Collision: {collision_data['occurred']}")
                
                frame_number += 1
            else:
                print(f"[WARNING] Frame {frame_number} camera timeout - skipping frame")
            
            # Clear frame sync
            frame_ready.clear()
            with images_lock:
                images_received['front'] = None
                images_received['front_left'] = None
                images_received['front_right'] = None
                images_received['rear'] = None
        
        # Final statistics
        print("\n" + "="*70)
        print("SIMULATION COMPLETE")
        print("="*70)
        print(f"Total frames captured: {frame_number - 1}")
        print(f"Total images saved: {(frame_number - 1) * 4}")
        print(f"Pedestrian crossing triggered: {pedestrian_triggered}")
        print(f"Minimum distance to pedestrian: {min_distance_to_pedestrian:.2f}m")
        print(f"Collision occurred: {collision_data['occurred']}")
        if collision_data['occurred']:
            print(f"  - Collision frame: {collision_data['frame']}")
            print(f"  - Collision intensity: {collision_data['intensity']:.2f}")
            print(f"  - Other actor: {collision_data['other_actor']}")
        print("="*70)
        
        log_file.write(f"\n--- FINAL STATISTICS ---\n")
        log_file.write(f"Total frames: {frame_number - 1}\n")
        log_file.write(f"Pedestrian triggered: {pedestrian_triggered}\n")
        log_file.write(f"Min distance to pedestrian: {min_distance_to_pedestrian:.2f}m\n")
        log_file.write(f"Collision occurred: {collision_data['occurred']}\n")
        if collision_data['occurred']:
            log_file.write(f"Collision frame: {collision_data['frame']}\n")
            log_file.write(f"Collision intensity: {collision_data['intensity']:.2f}\n")
            log_file.write(f"Other actor: {collision_data['other_actor']}\n")
        
    except Exception as e:
        print(f"[ERROR] Exception occurred: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\n[INFO] Cleaning up...")
        
        # Stop all cameras
        if 'front_camera' in locals():
            front_camera.stop()
        if 'front_left_camera' in locals():
            front_left_camera.stop()
        if 'front_right_camera' in locals():
            front_right_camera.stop()
        if 'rear_camera' in locals():
            rear_camera.stop()
        if 'collision_sensor' in locals():
            collision_sensor.stop()
        
        # Destroy all actors
        if world is not None:
            print(f"[INFO] Destroying {len(actors_to_destroy)} actors...")
            for actor in actors_to_destroy:
                if actor is not None and actor.is_alive:
                    actor.destroy()
        
        # Restore asynchronous mode
        if world is not None:
            settings = world.get_settings()
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
            world.apply_settings(settings)
            print("[INFO] Restored asynchronous mode")
        
        # Close log file
        if log_file:
            log_file.close()
        
        print("[INFO] Cleanup complete")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    finally:
        print("[INFO] Script finished")