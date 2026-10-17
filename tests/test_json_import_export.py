#!/usr/bin/env python3
"""
Test import/export functionality for all configuration parameter types.
This test file focuses specifically on JSON serialization and deserialization.
"""

import json
import sys
from pathlib import Path

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Direct import to avoid issues with other modules
import bots.core.cfg_types as cfg_types


def test_rgb_param_json():
    """Test RGBParam JSON import/export."""
    print("Testing RGBParam JSON functionality...")
    
    # Create RGB parameter
    rgb = cfg_types.RGBParam.from_hex("#FF8040")
    print(f"  Original: {rgb} -> {rgb.to_hex()}")
    
    # Export to JSON
    json_data = rgb.to_json()
    print(f"  JSON export: {json_data}")
    
    # Convert to JSON string and back
    json_string = json.dumps(json_data)
    loaded_json = json.loads(json_string)
    
    # Import from JSON
    restored = cfg_types.RGBParam.from_json(loaded_json)
    print(f"  Restored: {restored} -> {restored.to_hex()}")
    
    # Verify data integrity
    assert rgb == restored
    assert rgb.to_hex() == restored.to_hex()
    print("  ✓ RGBParam JSON roundtrip successful")


def test_range_param_json():
    """Test RangeParam JSON import/export."""
    print("\nTesting RangeParam JSON functionality...")
    
    # Create range parameter
    range_param = cfg_types.RangeParam(10.5, 25.75)
    print(f"  Original: {range_param.value}")
    
    # Export to JSON
    json_data = range_param.to_json()
    print(f"  JSON export: {json_data}")
    
    # Convert to JSON string and back
    json_string = json.dumps(json_data)
    loaded_json = json.loads(json_string)
    
    # Import from JSON
    restored = cfg_types.RangeParam.from_json(loaded_json)
    print(f"  Restored: {restored.value}")
    
    # Verify data integrity
    assert range_param.value == restored.value
    print("  ✓ RangeParam JSON roundtrip successful")


def test_break_cfg_param_json():
    """Test BreakCfgParam JSON import/export."""
    print("\nTesting BreakCfgParam JSON functionality...")
    
    # Create break config parameter
    duration = cfg_types.RangeParam(30.0, 60.0)
    break_cfg = cfg_types.BreakCfgParam(duration, 0.05)
    print(f"  Original: duration={break_cfg.break_duration.value}, chance={break_cfg.break_chance}")
    
    # Export to JSON
    json_data = break_cfg.to_json()
    print(f"  JSON export: {json_data}")
    
    # Convert to JSON string and back
    json_string = json.dumps(json_data)
    loaded_json = json.loads(json_string)
    
    # Import from JSON
    restored = cfg_types.BreakCfgParam.from_json(loaded_json)
    print(f"  Restored: duration={restored.break_duration.value}, chance={restored.break_chance}")
    
    # Verify data integrity
    assert break_cfg.break_duration.value == restored.break_duration.value
    assert break_cfg.break_chance == restored.break_chance
    print("  ✓ BreakCfgParam JSON roundtrip successful")


def test_waypoint_param_json():
    """Test WaypointParam JSON import/export."""
    print("\nTesting WaypointParam JSON functionality...")
    
    # Create waypoint parameter
    waypoint = cfg_types.WaypointParam(100, 200, 0, 12345, 8)
    print(f"  Original: x={waypoint.x}, y={waypoint.y}, z={waypoint.z}, chunk={waypoint.chunk}, tolerance={waypoint.tolerance}")
    
    # Export to JSON
    json_data = waypoint.to_json()
    print(f"  JSON export: {json_data}")
    
    # Convert to JSON string and back
    json_string = json.dumps(json_data)
    loaded_json = json.loads(json_string)
    
    # Import from JSON
    restored = cfg_types.WaypointParam.from_json(loaded_json)
    print(f"  Restored: x={restored.x}, y={restored.y}, z={restored.z}, chunk={restored.chunk}, tolerance={restored.tolerance}")
    
    # Verify data integrity
    assert waypoint.x == restored.x
    assert waypoint.y == restored.y
    assert waypoint.z == restored.z
    assert waypoint.chunk == restored.chunk
    assert waypoint.tolerance == restored.tolerance
    print("  ✓ WaypointParam JSON roundtrip successful")


def test_route_param_json():
    """Test RouteParam JSON import/export."""
    print("\nTesting RouteParam JSON functionality...")
    
    # Create route parameter
    wp1 = cfg_types.WaypointParam(50, 100, 0, 11111)
    wp2 = cfg_types.WaypointParam(150, 250, 1, 22222, 10)
    route = cfg_types.RouteParam([wp1, wp2])
    print(f"  Original: {len(route.waypoints)} waypoints")
    print(f"    WP1: ({wp1.x}, {wp1.y}, {wp1.z}) chunk={wp1.chunk}")
    print(f"    WP2: ({wp2.x}, {wp2.y}, {wp2.z}) chunk={wp2.chunk}")
    
    # Export to JSON
    json_data = route.to_json()
    print(f"  JSON export has {len(json_data['value'])} waypoints")
    
    # Convert to JSON string and back
    json_string = json.dumps(json_data)
    loaded_json = json.loads(json_string)
    
    # Import from JSON
    restored = cfg_types.RouteParam.from_json(loaded_json)
    print(f"  Restored: {len(restored.waypoints)} waypoints")
    print(f"    WP1: ({restored.waypoints[0].x}, {restored.waypoints[0].y}, {restored.waypoints[0].z}) chunk={restored.waypoints[0].chunk}")
    print(f"    WP2: ({restored.waypoints[1].x}, {restored.waypoints[1].y}, {restored.waypoints[1].z}) chunk={restored.waypoints[1].chunk}")
    
    # Verify data integrity
    assert len(route.waypoints) == len(restored.waypoints)
    for orig_wp, rest_wp in zip(route.waypoints, restored.waypoints):
        assert orig_wp.x == rest_wp.x
        assert orig_wp.y == rest_wp.y
        assert orig_wp.z == rest_wp.z
        assert orig_wp.chunk == rest_wp.chunk
        assert orig_wp.tolerance == rest_wp.tolerance
    print("  ✓ RouteParam JSON roundtrip successful")


def test_complex_configuration():
    """Test a complex configuration with multiple parameter types."""
    print("\nTesting complex configuration with multiple parameter types...")
    
    # Create a complex configuration
    config = {
        "target_color": cfg_types.RGBParam.from_rgb(255, 128, 64),
        "wait_time": cfg_types.RangeParam(2.5, 5.0),
        "break_settings": cfg_types.BreakCfgParam(
            cfg_types.RangeParam(30.0, 90.0), 0.02
        ),
        "home_base": cfg_types.WaypointParam(100, 200, 0, 12345, 5),
        "patrol_path": cfg_types.RouteParam([
            cfg_types.WaypointParam(50, 75, 0, 11111),
            cfg_types.WaypointParam(125, 175, 0, 22222),
            cfg_types.WaypointParam(200, 250, 1, 33333, 8)
        ])
    }
    
    print("  Original configuration:")
    print(f"    target_color: {config['target_color'].to_hex()}")
    print(f"    wait_time: {config['wait_time'].value}")
    print(f"    break_settings: duration={config['break_settings'].break_duration.value}, chance={config['break_settings'].break_chance}")
    print(f"    home_base: ({config['home_base'].x}, {config['home_base'].y}, {config['home_base'].z}) chunk={config['home_base'].chunk}")
    print(f"    patrol_path: {len(config['patrol_path'].waypoints)} waypoints")
    
    # Export entire configuration to JSON
    json_config = {}
    for key, param in config.items():
        json_config[key] = param.to_json()
    
    print(f"  JSON export keys: {list(json_config.keys())}")
    
    # Convert to JSON string and back
    json_string = json.dumps(json_config, indent=2)
    loaded_json = json.loads(json_string)
    
    # Import from JSON
    restored_config = {}
    restored_config["target_color"] = cfg_types.RGBParam.from_json(loaded_json["target_color"])
    restored_config["wait_time"] = cfg_types.RangeParam.from_json(loaded_json["wait_time"])
    restored_config["break_settings"] = cfg_types.BreakCfgParam.from_json(loaded_json["break_settings"])
    restored_config["home_base"] = cfg_types.WaypointParam.from_json(loaded_json["home_base"])
    restored_config["patrol_path"] = cfg_types.RouteParam.from_json(loaded_json["patrol_path"])
    
    print("  Restored configuration:")
    print(f"    target_color: {restored_config['target_color'].to_hex()}")
    print(f"    wait_time: {restored_config['wait_time'].value}")
    print(f"    break_settings: duration={restored_config['break_settings'].break_duration.value}, chance={restored_config['break_settings'].break_chance}")
    print(f"    home_base: ({restored_config['home_base'].x}, {restored_config['home_base'].y}, {restored_config['home_base'].z}) chunk={restored_config['home_base'].chunk}")
    print(f"    patrol_path: {len(restored_config['patrol_path'].waypoints)} waypoints")
    
    # Verify all data is preserved
    assert config["target_color"] == restored_config["target_color"]
    assert config["wait_time"].value == restored_config["wait_time"].value
    assert config["break_settings"].break_chance == restored_config["break_settings"].break_chance
    assert config["home_base"].x == restored_config["home_base"].x
    assert len(config["patrol_path"].waypoints) == len(restored_config["patrol_path"].waypoints)
    
    print("  ✓ Complex configuration JSON roundtrip successful")


def test_rgb_various_formats():
    """Test RGBParam with various input formats."""
    print("\nTesting RGBParam with various input formats...")
    
    # Test tuple input
    rgb1 = cfg_types.RGBParam.load((255, 128, 0))
    print(f"  From tuple: {rgb1} -> {rgb1.to_hex()}")
    
    # Test list input
    rgb2 = cfg_types.RGBParam.load([128, 255, 64])
    print(f"  From list: {rgb2} -> {rgb2.to_hex()}")
    
    # Test hex input
    rgb3 = cfg_types.RGBParam.load("#FF0080")
    print(f"  From hex: {rgb3} -> {rgb3.to_hex()}")
    
    # Test JSON roundtrip for each
    for i, rgb in enumerate([rgb1, rgb2, rgb3], 1):
        json_data = rgb.to_json()
        restored = cfg_types.RGBParam.from_json(json_data)
        assert rgb == restored
        print(f"  ✓ Format {i} JSON roundtrip successful")


def main():
    """Run all tests."""
    print("=== Configuration Parameter JSON Import/Export Tests ===")
    
    try:
        test_rgb_param_json()
        test_range_param_json()
        test_break_cfg_param_json()
        test_waypoint_param_json()
        test_route_param_json()
        test_complex_configuration()
        test_rgb_various_formats()
        
        print("\n=== All Tests Passed! ===")
        print("✓ All parameter types support JSON import/export")
        print("✓ Data integrity preserved through serialization")
        print("✓ Complex configurations work correctly")
        print("✓ Various input formats supported")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)