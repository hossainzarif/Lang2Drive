import carla
import random
import time
import math
import numpy as np
from PIL import Image
import threading
import os
import sys
import argparse
from datetime import datetime

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

def log_message(log_file, message):
    """Write message to both console and log file"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    if log_file:
        log_file.write(log_line + "\n")
        log_file.flush()

def get_forward_vector(rotation):
    """Get forward vector from rotation"""
    yaw_rad = math.radians(rotation.yaw)
    return carla.Vector3D(
        x=math.cos(yaw_rad),
        y=math.sin(yaw_rad),
        z=0.0
    )

def find_spawn_point_near_traffic_light(world, spawn_points):
    """Find spawn point 40-55m before a traffic light, facing it"""
    traffic_lights = world.get_actors().filter('traffic.traffic_light')
    
    best_spawn = None
    target_tl = None
    best_distance = 0
    
    for sp in spawn_points:
        sp_forward = get_forward_vector(sp.rotation)
        
        for tl in traffic_lights:
            tl_loc = tl.get_location()
            dist = sp.location.distance(tl_loc)
            
            if 40.0 < dist < 55.0:
                # Check if spawn point faces the traffic light
                to_tl = tl_loc - sp.location
                to_tl_len = math.sqrt(to_tl.x**2 + to_tl.y**2)
                
                if to_tl_len > 0:
                    to_tl_norm = carla.Vector3D(to_tl.x/to_tl_len, to_tl.y/to_tl_len, 0)
                    dot = sp_forward.x * to_tl_norm.x + sp_forward.y * to_tl_norm.y
                    
                    if dot > 0.8:  # Well-aligned facing light
                        if dist > best_distance:
                            best_spawn = sp
                            target_tl = tl
                            best_distance = dist
    
    return best_spawn, target_tl

def get_perpendicular_traffic_lights(world, target_tl):
    """Find traffic lights perpendicular to target traffic light"""
    traffic_lights = world.get_actors().filter('traffic.traffic_light')
    target_loc = target_tl.get_location()
    perpendicular_lights = []
    
    for tl in traffic_lights:
        if tl.id == target_tl.id:
            continue
        
        tl_loc = tl.get_location()
        dist = target_loc.distance(tl_loc)
        
        # Traffic lights at same intersection are typically 10-50m apart
        if 10.0 < dist < 50.0:
            perpendicular_lights.append(tl)
    
    return perpendicular_lights

def spawn_pedestrians_at_crosswalk(world, blueprint_library, target_tl, log_file):
    """Spawn pedestrians near the traffic light crosswalk"""
    walker_bp = blueprint_library.filter('walker.pedestrian.*')
    walker_controller_bp = blueprint_library.find('controller.ai.walker')
    
    pedestrians = []
    controllers = []
    
    tl_loc = target_tl.get_location()
    
    # Define pedestrian spawn positions relative to traffic light
    ped_offsets = [
        carla.Location(x=8, y=3, z=1.0),
        carla.Location(x=8, y=-3, z=1.0),
        carla.Location(x=10, y=0, z=1.0)
    ]
    
    for i, offset in enumerate(ped_offsets):
        spawn_loc = tl_loc + offset
        spawn_transform = carla.Transform(spawn_loc, carla.Rotation(yaw=90))
        
        ped_bp = random.choice(walker_bp)
        pedestrian = world.try_spawn_actor(ped_bp, spawn_transform)
        
        if pedestrian:
            pedestrians.append(pedestrian)
            
            # Spawn AI controller for pedestrian
            controller = world.spawn_actor(walker_controller_bp, carla.Transform(), attach_to=pedestrian)
            if controller:
                controllers.append(controller)
                controller.start()
                controller.set_max_speed(0.0)  # Set to idle/waiting
                
            log_message(log_file, f"Spawned pedestrian {i+1} at crosswalk")
    
    return pedestrians, controllers

def main():
    parser = argparse.ArgumentParser(description='CARLA Red Light Violation Scenario')
    parser.add_argument('--host', default='127.0.0.1', help='CARLA server host')
    parser.add_argument('--port', type=int, default=2000, help='CARLA server port')
    parser.add_argument('--duration', type=int, default=25, help='Simulation duration in seconds')
    parser.add_argument('--output-dir', default='./scenes/red_light_violation', help='Output directory')
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
    
    log_file_path = os.path.join(args.output_dir, 'red_light_violation_simulation.log')
    log_file = open(log_file_path, 'w')
    
    client = None
    world = None
    actors_to_destroy = []
    cameras = []
    traffic_manager = None
    
    try:
        # Connect to CARLA
        log_message(log_file, f"Connecting to CARLA server at {args.host}:{args.port}")
        client = carla.Client(args.host, args.port)
        client.set_timeout(60.0)
        
        # Test connection
        version = client.get_server_version()
        log_message(log_file, f"Connected to CARLA {version}")
        
        # Load Town03
        log_message(log_file, "Loading Town03...")
        world = client.load_world('Town03')
        time.sleep(2.0)
        
        # Set weather
        weather = carla.WeatherParameters(
            cloudiness=10.0,
            precipitation=0.0,
            sun_altitude_angle=70.0,
            fog_density=0.0
        )
        world.set_weather(weather)
        log_message(log_file, "Weather set to clear daylight")
        
        # Set synchronous mode
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)
        log_message(log_file, "Synchronous mode enabled (20 FPS)")
        
        # Get blueprints
        blueprint_library = world.get_blueprint_library()
        
        # Setup Traffic Manager
        traffic_manager = client.get_trafficmanager(8000)
        traffic_manager.set_synchronous_mode(True)
        traffic_manager.set_global_distance_to_leading_vehicle(2.5)
        
        # Find spawn point near traffic light
        spawn_points = world.get_map().get_spawn_points()
        log_message(log_file, f"Searching {len(spawn_points)} spawn points for suitable location...")
        
        violator_spawn, target_traffic_light = find_spawn_point_near_traffic_light(world, spawn_points)
        
        if not violator_spawn or not target_traffic_light:
            log_message(log_file, "[ERROR] Could not find suitable spawn point near traffic light")
            return
        
        distance_to_light = violator_spawn.location.distance(target_traffic_light.get_location())
        log_message(log_file, f"Found spawn point {distance_to_light:.1f}m from traffic light")
        
        # Set target traffic light to RED and freeze it
        target_traffic_light.set_state(carla.TrafficLightState.Red)
        target_traffic_light.set_red_time(9999.0)
        target_traffic_light.freeze(True)
        world.tick()
        log_message(log_file, f"Target traffic light set to RED and frozen at {target_traffic_light.get_location()}")
        
        # Set perpendicular traffic lights to GREEN
        perpendicular_lights = get_perpendicular_traffic_lights(world, target_traffic_light)
        for perp_light in perpendicular_lights:
            perp_light.set_state(carla.TrafficLightState.Green)
            perp_light.set_green_time(9999.0)
            perp_light.freeze(True)
        log_message(log_file, f"Set {len(perpendicular_lights)} perpendicular traffic lights to GREEN")
        
        # Spawn violating vehicle (Tesla Model 3)
        vehicle_bp = blueprint_library.filter('vehicle.tesla.model3')[0]
        vehicle_bp.set_attribute('color', '255,0,0')  # Red color
        
        violator_vehicle = world.try_spawn_actor(vehicle_bp, violator_spawn)
        if not violator_vehicle:
            log_message(log_file, "[ERROR] Failed to spawn violator vehicle")
            return
        
        actors_to_destroy.append(violator_vehicle)
        log_message(log_file, f"Spawned violating vehicle at {violator_spawn.location}")
        
        # Spawn compliant vehicles at adjacent positions
        compliant_spawns = []
        for sp in spawn_points:
            # Find spawn points near the target traffic light but in different lanes
            dist_to_light = sp.location.distance(target_traffic_light.get_location())
            dist_to_violator = sp.location.distance(violator_spawn.location)
            
            if 15.0 < dist_to_light < 35.0 and dist_to_violator > 10.0:
                compliant_spawns.append(sp)
                if len(compliant_spawns) >= 4:
                    break
        
        # Spawn compliant vehicles
        vehicle_bps_names = [
            'vehicle.audi.a2',
            'vehicle.dodge.charger_2020',
            'vehicle.toyota.prius',
            'vehicle.nissan.patrol'
        ]
        
        colors = ['0,0,255', '255,255,255', '128,128,128', '0,0,0']
        
        compliant_vehicles = []
        for i, spawn in enumerate(compliant_spawns[:4]):
            veh_bp_list = blueprint_library.filter(vehicle_bps_names[i % len(vehicle_bps_names)])
            if len(veh_bp_list) > 0:
                veh_bp = veh_bp_list[0]
                veh_bp.set_attribute('color', colors[i % len(colors)])
                
                compliant_veh = world.try_spawn_actor(veh_bp, spawn)
                if compliant_veh:
                    actors_to_destroy.append(compliant_veh)
                    compliant_vehicles.append(compliant_veh)
                    # Set to autopilot with Traffic Manager
                    compliant_veh.set_autopilot(True, traffic_manager.get_port())
                    traffic_manager.ignore_lights_percentage(compliant_veh, 0.0)  # Respect all red lights
                    traffic_manager.auto_lane_change(compliant_veh, False)
                    # Set to stopped initially
                    compliant_veh.set_target_velocity(carla.Vector3D(0, 0, 0))
                    log_message(log_file, f"Spawned compliant vehicle {i+1} at {spawn.location}")
        
        # Spawn pedestrians at crosswalk
        pedestrians, ped_controllers = spawn_pedestrians_at_crosswalk(world, blueprint_library, target_traffic_light, log_file)
        actors_to_destroy.extend(pedestrians)
        actors_to_destroy.extend(ped_controllers)
        
        # Setup cameras on violating vehicle
        camera_bp = blueprint_library.find('sensor.camera.rgb')
        camera_bp.set_attribute('image_size_x', '1280')
        camera_bp.set_attribute('image_size_y', '720')
        camera_bp.set_attribute('fov', '110')
        
        camera_configs = {
            'front': (carla.Transform(carla.Location(x=0.8, y=0.0, z=1.4), carla.Rotation(pitch=8)), 'front'),
            'front_left': (carla.Transform(carla.Location(x=-0.1, y=-0.4, z=1.2), carla.Rotation(yaw=-60)), 'front_left'),
            'front_right': (carla.Transform(carla.Location(x=-0.1, y=0.4, z=1.2), carla.Rotation(yaw=60)), 'front_right'),
            'rear': (carla.Transform(carla.Location(x=-0.2, y=0.0, z=1.25), carla.Rotation(yaw=180, pitch=5)), 'rear')
        }
        
        for cam_name, (transform, _) in camera_configs.items():
            camera = world.spawn_actor(camera_bp, transform, attach_to=violator_vehicle)
            camera.listen(make_camera_callback(cam_name))
            cameras.append(camera)
            actors_to_destroy.append(camera)
        
        log_message(log_file, "All 4 cameras attached to violating vehicle")
        
        # Add collision sensor
        collision_bp = blueprint_library.find('sensor.other.collision')
        collision_sensor = world.spawn_actor(collision_bp, carla.Transform(), attach_to=violator_vehicle)
        actors_to_destroy.append(collision_sensor)
        
        collision_detected = {'value': False, 'frame': -1}
        
        def on_collision(event):
            collision_detected['value'] = True
            collision_detected['frame'] = event.frame
            log_message(log_file, f"[COLLISION] Detected at frame {event.frame} with {event.other_actor.type_id}")
        
        collision_sensor.listen(on_collision)
        
        # Camera warm-up
        log_message(log_file, "Warming up cameras...")
        for _ in range(20):
            world.tick()
        time.sleep(0.5)
        log_message(log_file, "Cameras ready")
        
        # Main simulation loop
        frame_number = 1
        simulation_start_time = time.time()
        max_frames = int(args.duration * 20)  # 20 FPS
        
        log_message(log_file, f"Starting red light violation simulation for {args.duration} seconds ({max_frames} frames)")
        
        TARGET_SPEED = 50.0 / 3.6  # 50 km/h in m/s
        
        # Get map and waypoint for path following
        carla_map = world.get_map()
        
        violation_logged = False
        entry_speed = None
        exit_speed = None
        min_ped_distance = float('inf')
        
        while frame_number <= max_frames:
            world.tick()
            
            # Manual control for violating vehicle
            vehicle_transform = violator_vehicle.get_transform()
            vehicle_location = vehicle_transform.location
            vehicle_velocity = violator_vehicle.get_velocity()
            current_speed = math.sqrt(vehicle_velocity.x**2 + vehicle_velocity.y**2 + vehicle_velocity.z**2)
            
            # Get current waypoint
            current_waypoint = carla_map.get_waypoint(vehicle_location)
            
            # Get waypoint ahead for steering
            next_waypoints = current_waypoint.next(5.0)
            if next_waypoints:
                target_waypoint = next_waypoints[0]
                target_location = target_waypoint.transform.location
                
                # Calculate steering angle
                vehicle_forward = get_forward_vector(vehicle_transform.rotation)
                to_target = target_location - vehicle_location
                to_target_len = math.sqrt(to_target.x**2 + to_target.y**2)
                
                if to_target_len > 0.1:
                    to_target_norm = carla.Vector3D(to_target.x/to_target_len, to_target.y/to_target_len, 0)
                    
                    # Cross product for steering direction
                    cross = vehicle_forward.x * to_target_norm.y - vehicle_forward.y * to_target_norm.x
                    dot = vehicle_forward.x * to_target_norm.x + vehicle_forward.y * to_target_norm.y
                    
                    angle = math.atan2(cross, dot)
                    steer = max(-1.0, min(1.0, angle * 2.0))
                else:
                    steer = 0.0
            else:
                steer = 0.0
            
            # Throttle control to maintain speed
            if current_speed < TARGET_SPEED * 0.85:
                throttle = 0.8
            elif current_speed < TARGET_SPEED * 0.95:
                throttle = 0.6
            elif current_speed < TARGET_SPEED:
                throttle = 0.4
            else:
                throttle = 0.3
            
            control = carla.VehicleControl(throttle=throttle, steer=steer, brake=0.0)
            violator_vehicle.apply_control(control)
            
            # Check if at intersection
            dist_to_light = vehicle_location.distance(target_traffic_light.get_location())
            
            # Calculate distance to pedestrians
            for ped in pedestrians:
                ped_loc = ped.get_location()
                ped_dist = vehicle_location.distance(ped_loc)
                if ped_dist < min_ped_distance:
                    min_ped_distance = ped_dist
            
            if dist_to_light < 15.0 and not violation_logged:
                tl_state = target_traffic_light.get_state()
                entry_speed = current_speed * 3.6  # km/h
                log_message(log_file, f"[VIOLATION] Vehicle entering intersection at {entry_speed:.1f} km/h - Traffic light is {tl_state}")
                violation_logged = True
            
            if dist_to_light > 15.0 and violation_logged and exit_speed is None:
                exit_speed = current_speed * 3.6  # km/h
                log_message(log_file, f"[INFO] Vehicle exited intersection at {exit_speed:.1f} km/h")
            
            # Wait for all cameras to capture
            if frame_ready.wait(timeout=1.0):
                with images_lock:
                    # Save all 4 images
                    for cam_name in ['front', 'front_left', 'front_right', 'rear']:
                        if images_received[cam_name] is not None:
                            output_path = os.path.join(
                                output_dirs[cam_name],
                                f"{cam_name}_frame_{frame_number:08d}.png"
                            )
                            save_image_to_disk(images_received[cam_name], output_path)
                
                frame_number += 1
            else:
                log_message(log_file, f"[WARNING] Frame {frame_number} camera timeout - skipping frame")
            
            # Clear frame state
            frame_ready.clear()
            with images_lock:
                images_received['front'] = None
                images_received['front_left'] = None
                images_received['front_right'] = None
                images_received['rear'] = None
            
            # Log progress every 200 frames
            if frame_number % 200 == 0:
                elapsed = time.time() - simulation_start_time
                speed_kmh = current_speed * 3.6
                log_message(log_file, f"Progress: Frame {frame_number}/{max_frames} | "
                           f"Time: {elapsed:.1f}s | Speed: {speed_kmh:.1f} km/h | "
                           f"Distance to light: {dist_to_light:.1f}m")
            
            # Update spectator to follow vehicle
            if frame_number % 5 == 0:
                spectator = world.get_spectator()
                transform = violator_vehicle.get_transform()
                spectator.set_transform(carla.Transform(
                    transform.location + carla.Location(x=-8, z=3),
                    carla.Rotation(pitch=-15, yaw=transform.rotation.yaw)
                ))
        
        # Final report
        log_message(log_file, "=== Red Light Violation Scenario Complete ===")
        log_message(log_file, f"Total frames captured: {frame_number - 1}")
        log_message(log_file, f"Total images saved: {(frame_number - 1) * 4}")
        
        if entry_speed:
            log_message(log_file, f"Entry speed at intersection: {entry_speed:.1f} km/h")
        if exit_speed:
            log_message(log_file, f"Exit speed from intersection: {exit_speed:.1f} km/h")
        
        if min_ped_distance < float('inf'):
            log_message(log_file, f"Minimum distance to pedestrians: {min_ped_distance:.2f} meters")
        
        if collision_detected['value']:
            log_message(log_file, f"[WARNING] Collision detected at frame {collision_detected['frame']}")
        else:
            log_message(log_file, "[INFO] No collisions detected - successful violation scenario")
        
        log_message(log_file, f"Traffic light state: {target_traffic_light.get_state()}")
        
    except Exception as e:
        if log_file:
            log_message(log_file, f"[ERROR] Exception occurred: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Cleanup
        if log_file:
            log_message(log_file, "Cleaning up actors...")
        
        for camera in cameras:
            if camera.is_listening:
                camera.stop()
        
        for actor in actors_to_destroy:
            if actor is not None and actor.is_alive:
                actor.destroy()
        
        if world is not None:
            settings = world.get_settings()
            settings.synchronous_mode = False
            world.apply_settings(settings)
        
        if log_file:
            log_message(log_file, "Cleanup complete")
            log_file.close()
        
        print(f"[INFO] Simulation complete. Output saved to {args.output_dir}")

if __name__ == '__main__':
    main()