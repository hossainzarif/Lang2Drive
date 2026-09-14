#!/usr/bin/env python3

import carla
import time
import sys

def test_carla_connection():
    """Test different connection configurations to CARLA"""
    
    # Common CARLA ports and configurations to try
    test_configs = [
        {'host': 'localhost', 'port': 2000, 'timeout': 10.0},
        {'host': '127.0.0.1', 'port': 2000, 'timeout': 10.0},
        {'host': 'localhost', 'port': 2001, 'timeout': 10.0},
        {'host': '127.0.0.1', 'port': 2001, 'timeout': 10.0},
        {'host': 'localhost', 'port': 2000, 'timeout': 20.0},
    ]
    
    print("Testing CARLA connection configurations...")
    print("=" * 50)
    
    for i, config in enumerate(test_configs, 1):
        host = config['host']
        port = config['port']
        timeout = config['timeout']
        
        print(f"\nTest {i}: Trying {host}:{port} with timeout {timeout}s")
        
        try:
            # Create client
            client = carla.Client(host, port)
            client.set_timeout(timeout)
            
            # Test connection by getting server version
            print(f"  Connecting...")
            version = client.get_server_version()
            print(f"  ✓ SUCCESS! Connected to CARLA server version: {version}")
            
            # Test getting world
            world = client.get_world()
            map_name = world.get_map().name
            print(f"  ✓ World loaded: {map_name}")
            
            # Test getting actors
            actors = world.get_actors()
            print(f"  ✓ Found {len(actors)} actors in the world")
            
            # Test traffic manager
            traffic_manager = client.get_trafficmanager()
            print(f"  ✓ Traffic manager port: {traffic_manager.get_port()}")
            
            print(f"  ✓ All tests passed for {host}:{port}!")
            return True, config
            
        except Exception as e:
            print(f"  ✗ FAILED: {str(e)}")
            continue
    
    print("\n" + "=" * 50)
    print("❌ All connection attempts failed!")
    print("\nPossible issues:")
    print("1. CARLA server is not running")
    print("2. CARLA server is running on a different port")
    print("3. Firewall blocking the connection")
    print("4. CARLA server is not ready yet (try waiting longer)")
    
    return False, None

def get_carla_info(config):
    """Get detailed CARLA server information"""
    try:
        client = carla.Client(config['host'], config['port'])
        client.set_timeout(config['timeout'])
        
        world = client.get_world()
        
        print(f"\n📊 CARLA Server Information:")
        print(f"   Server Version: {client.get_server_version()}")
        print(f"   Available Maps: {client.get_available_maps()}")
        print(f"   Current Map: {world.get_map().name}")
        
        # Get world settings
        settings = world.get_settings()
        print(f"   Synchronous Mode: {settings.synchronous_mode}")
        print(f"   Fixed Delta Seconds: {settings.fixed_delta_seconds}")
        print(f"   No Rendering Mode: {settings.no_rendering_mode}")
        
        # Get spawn points
        spawn_points = world.get_map().get_spawn_points()
        print(f"   Available Spawn Points: {len(spawn_points)}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to get CARLA info: {str(e)}")
        return False

if __name__ == '__main__':
    print("CARLA Connection Diagnostic Tool")
    print("=" * 50)
    
    success, working_config = test_carla_connection()
    
    if success:
        print(f"\n✅ Connection successful! Use these settings:")
        print(f"   Host: {working_config['host']}")
        print(f"   Port: {working_config['port']}")
        print(f"   Timeout: {working_config['timeout']}")
        
        # Get additional info
        get_carla_info(working_config)
        
    else:
        print(f"\n❌ No working connection found.")
        print("Please ensure CARLA server is running and try again.")
