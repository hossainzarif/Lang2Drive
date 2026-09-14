#!/usr/bin/env python3

import carla
import random
import time
import math
import sys
import os
import argparse
import logging
import numpy as np
from typing import Optional

class SingleCarRacingSimulation:
    def __init__(self, host='localhost', port=2000, timeout=10.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.client = None
        self.world = None
        self.blueprint_library = None
        self.spawned_actors = []
        self.traffic_manager = None
        self.camera = None
        self.vehicle = None
        self.recording_enabled = True
        self.frame_count = 0
        
        # Setup logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)

    def connect_to_carla(self) -> bool:
        """Test connection to CARLA server with retry logic"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self.logger.info(f"Attempting to connect to CARLA server at {self.host}:{self.port} (attempt {attempt + 1}/{max_attempts})")
                self.client = carla.Client(self.host, self.port)
                self.client.set_timeout(self.timeout)
                
                version = self.client.get_server_version()
                self.logger.info(f"Successfully connected to CARLA server version: {version}")
                
                self.world = self.client.get_world()
                self.blueprint_library = self.world.get_blueprint_library()
                self.traffic_manager = self.client.get_trafficmanager()
                
                return True
                
            except Exception as e:
                self.logger.error(f"Connection attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_attempts - 1:
                    time.sleep(2)
                    
        return False

    def setup_world_settings(self):
        """Configure world settings for the simulation"""
        try:
            settings = self.world.get_settings()
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = 0.05
            self.world.apply_settings(settings)
            
            self.traffic_manager.set_synchronous_mode(True)
            self.traffic_manager.set_global_distance_to_leading_vehicle(2.5)
            
            self.logger.info("World settings configured successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to setup world settings: {str(e)}")
            raise

    def spawn_single_vehicle(self) -> Optional[carla.Actor]:
        """Spawn a single vehicle with enhanced retry logic"""
        spawn_points = self.world.get_map().get_spawn_points()
        
        if not spawn_points:
            self.logger.error("No spawn points available on the map")
            return None
            
        # Filter vehicle blueprints to exclude problematic ones
        vehicle_blueprints = self.blueprint_library.filter('vehicle.*')
        filtered_blueprints = []
        
        for bp in vehicle_blueprints:
            # Exclude motorcycles, bicycles, and other problematic vehicles
            if not any(x in bp.id.lower() for x in ['bike', 'motorcycle', 'cyclist', 'omafiets']):
                filtered_blueprints.append(bp)
        
        if not filtered_blueprints:
            self.logger.error("No suitable vehicle blueprints found")
            return None
            
        self.logger.info(f"Found {len(filtered_blueprints)} suitable vehicle blueprints")
        self.logger.info(f"Found {len(spawn_points)} spawn points")
        
        # Try spawning vehicle with multiple attempts
        max_attempts = 20
        
        for attempt in range(max_attempts):
            try:
                # Select random blueprint and spawn point
                blueprint = random.choice(filtered_blueprints)
                spawn_point = spawn_points[attempt % len(spawn_points)]
                
                # Clear the spawn area by checking for collisions
                if self._is_spawn_point_clear(spawn_point):
                    # Try to spawn the vehicle
                    vehicle = self.world.try_spawn_actor(blueprint, spawn_point)
                    
                    if vehicle is not None:
                        self.spawned_actors.append(vehicle)
                        
                        # Configure vehicle immediately after spawning
                        self._configure_vehicle(vehicle)
                        
                        self.logger.info(f"Successfully spawned vehicle: {blueprint.id}")
                        return vehicle
                
                # If spawn point not clear or spawning failed, try next attempt
                if attempt < max_attempts - 1:
                    time.sleep(0.1)  # Brief pause between attempts
                    
            except Exception as e:
                self.logger.warning(f"Spawn attempt {attempt + 1} failed: {str(e)}")
                continue
        
        self.logger.error(f"Failed to spawn vehicle after {max_attempts} attempts")
        return None

    def _is_spawn_point_clear(self, spawn_point, radius=5.0):
        """Check if spawn point is clear of other vehicles"""
        try:
            # Get all vehicles in the world
            all_vehicles = self.world.get_actors().filter('vehicle.*')
            
            for vehicle in all_vehicles:
                if vehicle.is_alive:
                    distance = spawn_point.location.distance(vehicle.get_location())
                    if distance < radius:
                        return False
            return True
        except:
            return True  # If check fails, assume it's clear

    def _configure_vehicle(self, vehicle):
        """Configure vehicle behavior immediately after spawning"""
        try:
            # Enable autopilot and configure traffic manager
            vehicle.set_autopilot(True, self.traffic_manager.get_port())
            
            # Configure for continuous movement - ignore traffic lights and signs
            self.traffic_manager.ignore_lights_percentage(vehicle, 100)
            self.traffic_manager.ignore_signs_percentage(vehicle, 100)
            self.traffic_manager.vehicle_percentage_speed_difference(vehicle, -30)  # 30% faster
            self.traffic_manager.distance_to_leading_vehicle(vehicle, 1.5)
            self.traffic_manager.ignore_vehicles_percentage(vehicle, 70)
            self.traffic_manager.auto_lane_change(vehicle, True)
            
        except Exception as e:
            self.logger.warning(f"Failed to configure vehicle: {str(e)}")

    def attach_racing_camera(self, vehicle: carla.Actor, output_dir: str):
        """Attach racing game style third-person camera to the vehicle"""
        try:
            if vehicle is None or not vehicle.is_alive:
                self.logger.error("Cannot attach camera: vehicle is None or not alive")
                return False
            
            self.logger.info("Attaching racing camera to vehicle")
                
            # Create camera blueprint with racing game settings
            camera_bp = self.blueprint_library.find('sensor.camera.rgb')
            camera_bp.set_attribute('image_size_x', '1280')
            camera_bp.set_attribute('image_size_y', '720')
            camera_bp.set_attribute('fov', '90')
            
            # Racing game camera position
            camera_transform = carla.Transform(
                carla.Location(x=-6.0, z=2.8),
                carla.Rotation(pitch=-8, yaw=0, roll=0)
            )
            
            self.camera = self.world.spawn_actor(camera_bp, camera_transform, attach_to=vehicle)
            self.spawned_actors.append(self.camera)
            
            # Create output directory
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
            
            # Setup racing-style image callback
            def save_racing_image(image):
                if self.recording_enabled:
                    try:
                        # Convert to numpy array
                        array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
                        array = np.reshape(array, (image.height, image.width, 4))
                        array = array[:, :, :3]  # Remove alpha
                        array = array[:, :, ::-1]  # BGR to RGB
                        
                        # Save with racing game naming convention
                        filename = f"racing_frame_{self.frame_count:08d}.png"
                        filepath = os.path.join(output_dir, filename)
                        
                        # Save using PIL for better quality
                        try:
                            from PIL import Image
                            img = Image.fromarray(array)
                            img.save(filepath, quality=95, optimize=True)
                        except ImportError:
                            # Fallback to numpy
                            np.save(filepath.replace('.png', '.npy'), array)
                        
                        self.frame_count += 1
                        
                    except Exception as e:
                        pass  # Suppress frequent error messages
            
            self.camera.listen(save_racing_image)
            
            self.logger.info(f"Racing camera attached - output: {output_dir}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to attach camera: {str(e)}")
            return False

    def update_spectator_view(self):
        """Update spectator to follow the vehicle for racing game view"""
        try:
            if not self.vehicle or not self.vehicle.is_alive:
                return
            
            # Get vehicle transform for dynamic following
            vehicle_transform = self.vehicle.get_transform()
            
            # Calculate racing game spectator position
            yaw_rad = math.radians(vehicle_transform.rotation.yaw)
            
            spectator_x = vehicle_transform.location.x - 8.0 * math.cos(yaw_rad)
            spectator_y = vehicle_transform.location.y - 8.0 * math.sin(yaw_rad)
            spectator_z = vehicle_transform.location.z + 4.0
            
            spectator_transform = carla.Transform(
                carla.Location(x=spectator_x, y=spectator_y, z=spectator_z),
                carla.Rotation(pitch=-10, yaw=vehicle_transform.rotation.yaw, roll=0)
            )
            
            spectator = self.world.get_spectator()
            spectator.set_transform(spectator_transform)
            
        except Exception as e:
            pass  # Suppress frequent warning messages

    def run_simulation(self, duration: float, output_dir: str):
        """Run the single car racing simulation"""
        try:
            # Connect to CARLA
            if not self.connect_to_carla():
                raise RuntimeError("Failed to connect to CARLA server")
                
            # Setup world
            self.setup_world_settings()
            
            # Spawn single vehicle
            self.logger.info("Spawning single vehicle...")
            self.vehicle = self.spawn_single_vehicle()
            if not self.vehicle:
                raise RuntimeError("Failed to spawn vehicle")
            
            # Give vehicle time to initialize
            self.logger.info("Initializing vehicle...")
            for _ in range(10):
                self.world.tick()
                time.sleep(0.1)
                
            # Attach racing camera to the vehicle
            self.logger.info("Attaching racing camera...")
            camera_attached = self.attach_racing_camera(self.vehicle, output_dir)
            
            if not camera_attached:
                raise RuntimeError("Failed to attach racing camera")
            
            # Run simulation
            self.logger.info(f"Starting single car racing simulation for {duration} seconds...")
            self.logger.info("Camera will follow the car in racing game style")
            
            start_time = time.time()
            tick_count = 0
            
            try:
                while time.time() - start_time < duration:
                    self.world.tick()
                    tick_count += 1
                    
                    # Update racing camera view
                    self.update_spectator_view()
                    
                    # Progress reporting
                    if tick_count % 200 == 0:  # Every 10 seconds at 20 FPS
                        elapsed = time.time() - start_time
                        progress = (elapsed / duration) * 100
                        
                        if self.vehicle.is_alive:
                            vehicle_speed = self.get_vehicle_speed(self.vehicle)
                            location = self.vehicle.get_location()
                            
                            self.logger.info(f"Racing Simulation: {progress:.1f}% | Speed: {vehicle_speed:.1f} km/h | Frames: {self.frame_count} | Location: ({location.x:.1f}, {location.y:.1f})")
                        else:
                            self.logger.warning("Vehicle is no longer alive!")
                        
            except KeyboardInterrupt:
                self.logger.info("Racing simulation interrupted by user")
                
            # Final statistics
            self.logger.info(f"Single car racing simulation completed!")
            self.logger.info(f"Total frames captured: {self.frame_count}")
            self.logger.info(f"Racing footage available in: {output_dir}")
            
        except Exception as e:
            self.logger.error(f"Simulation error: {str(e)}")
            raise

    def get_vehicle_speed(self, vehicle):
        """Get vehicle speed in km/h"""
        try:
            if vehicle.is_alive:
                velocity = vehicle.get_velocity()
                speed_ms = math.sqrt(velocity.x**2 + velocity.y**2 + velocity.z**2)
                return speed_ms * 3.6  # Convert to km/h
        except:
            pass
        return 0.0
            
    def cleanup_resources(self):
        """Clean up all spawned resources"""
        try:
            self.recording_enabled = False
            
            # Stop camera
            if self.camera:
                try:
                    self.camera.stop()
                except Exception as e:
                    pass
                    
            # Destroy all spawned actors
            self.logger.info(f"Cleaning up {len(self.spawned_actors)} spawned actors...")
            
            for actor in self.spawned_actors:
                try:
                    if actor.is_alive:
                        actor.destroy()
                except Exception as e:
                    pass
                    
            self.spawned_actors.clear()
            
            # Reset world settings
            if self.world is not None:
                try:
                    settings = self.world.get_settings()
                    settings.synchronous_mode = False
                    settings.fixed_delta_seconds = None
                    self.world.apply_settings(settings)
                except Exception as e:
                    pass
                    
            self.logger.info("Resource cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description='CARLA Single Car Racing Simulation')
    parser.add_argument('--host', default='localhost', help='CARLA server host')
    parser.add_argument('--port', type=int, default=2000, help='CARLA server port')
    parser.add_argument('--duration', type=float, default=60.0, help='Simulation duration in seconds')
    parser.add_argument('--output-dir', default='./single_car_racing', help='Output directory for recordings')
    parser.add_argument('--timeout', type=float, default=10.0, help='Connection timeout')
    
    args = parser.parse_args()
    
    simulation = SingleCarRacingSimulation(args.host, args.port, args.timeout)
    
    try:
        simulation.run_simulation(args.duration, args.output_dir)
        
    except KeyboardInterrupt:
        print("\nSingle car racing simulation interrupted by user")
        
    except Exception as e:
        print(f"Single car racing simulation failed: {str(e)}")
        sys.exit(1)
        
    finally:
        simulation.cleanup_resources()
        print("Single car racing simulation ended")

if __name__ == '__main__':
    main()