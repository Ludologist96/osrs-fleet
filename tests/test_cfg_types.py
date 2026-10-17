#!/usr/bin/env python3
"""
Comprehensive tests for all configuration parameter types and their JSON import/export functionality.
"""

import pytest
import json
import sys
from pathlib import Path

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from bots.core.cfg_types import (
    RGBParam, RangeParam, BreakCfgParam, WaypointParam, RouteParam
)


class TestRGBParam:
    """Test RGBParam functionality including JSON serialization."""
    
    def test_create_from_rgb_values(self):
        """Test creating RGBParam from individual RGB values."""
        rgb = RGBParam.from_rgb(255, 128, 0)
        assert rgb.r == 255
        assert rgb.g == 128
        assert rgb.b == 0
        assert rgb.value == (255, 128, 0)
    
    def test_create_from_tuple(self):
        """Test creating RGBParam from RGB tuple."""
        rgb = RGBParam.from_tuple((0, 255, 128))
        assert rgb.r == 0
        assert rgb.g == 255
        assert rgb.b == 128
        assert rgb.value == (0, 255, 128)
    
    def test_create_from_hex(self):
        """Test creating RGBParam from hex string."""
        # Test with # prefix
        rgb1 = RGBParam.from_hex("#FF8000")
        assert rgb1.r == 255
        assert rgb1.g == 128
        assert rgb1.b == 0
        
        # Test without # prefix
        rgb2 = RGBParam.from_hex("00FF80")
        assert rgb2.r == 0
        assert rgb2.g == 255
        assert rgb2.b == 128
    
    def test_to_hex(self):
        """Test converting RGB to hex string."""
        rgb = RGBParam.from_rgb(255, 0, 128)
        assert rgb.to_hex() == "#FF0080"
    
    def test_to_rgb_tuple(self):
        """Test converting to RGB tuple."""
        rgb = RGBParam.from_rgb(128, 255, 0)
        assert rgb.to_rgb_tuple() == (128, 255, 0)
    
    def test_tuple_like_behavior(self):
        """Test that RGBParam behaves like a tuple."""
        rgb = RGBParam.from_rgb(255, 128, 64)
        
        # Test indexing
        assert rgb[0] == 255
        assert rgb[1] == 128
        assert rgb[2] == 64
        
        # Test length
        assert len(rgb) == 3
        
        # Test unpacking
        r, g, b = rgb
        assert r == 255
        assert g == 128
        assert b == 64
        
        # Test iteration
        assert list(rgb) == [255, 128, 64]
    
    def test_equality(self):
        """Test equality comparison."""
        rgb1 = RGBParam.from_rgb(255, 0, 0)
        rgb2 = RGBParam.from_rgb(255, 0, 0)
        rgb3 = RGBParam.from_rgb(0, 255, 0)
        
        assert rgb1 == rgb2
        assert rgb1 != rgb3
        assert rgb1 == (255, 0, 0)
        assert rgb1 != (0, 255, 0)
    
    def test_load_various_formats(self):
        """Test loading from various input formats."""
        # From list
        rgb1 = RGBParam.load([255, 128, 0])
        assert rgb1.value == (255, 128, 0)
        
        # From tuple
        rgb2 = RGBParam.load((0, 255, 128))
        assert rgb2.value == (0, 255, 128)
        
        # From hex string
        rgb3 = RGBParam.load("#FF0080")
        assert rgb3.value == (255, 0, 128)
    
    def test_invalid_values(self):
        """Test that invalid RGB values raise errors."""
        with pytest.raises(ValueError):
            RGBParam.from_rgb(256, 0, 0)  # > 255
        
        with pytest.raises(ValueError):
            RGBParam.from_rgb(-1, 0, 0)  # < 0
        
        with pytest.raises(ValueError):
            RGBParam.from_hex("invalid")  # Invalid hex
    
    def test_json_export(self):
        """Test JSON export functionality."""
        rgb = RGBParam.from_rgb(255, 128, 64)
        json_data = rgb.to_json()
        
        assert json_data["type"] == "RGB"
        assert json_data["value"]["rgb"] == [255, 128, 64]
        assert json_data["value"]["hex"] == "#FF8040"
    
    def test_json_import(self):
        """Test JSON import functionality."""
        # Test import from structured JSON
        json_data = {
            "type": "RGB",
            "value": {
                "rgb": [255, 128, 64],
                "hex": "#FF8040"
            }
        }
        rgb = RGBParam.from_json(json_data)
        assert rgb.value == (255, 128, 64)
        
        # Test import from simple format
        json_data_simple = {
            "type": "RGB",
            "value": [128, 255, 0]
        }
        rgb2 = RGBParam.from_json(json_data_simple)
        assert rgb2.value == (128, 255, 0)
    
    def test_json_roundtrip(self):
        """Test that export->import preserves data."""
        original = RGBParam.from_rgb(192, 168, 1)
        json_data = original.to_json()
        restored = RGBParam.from_json(json_data)
        
        assert original == restored
        assert original.to_hex() == restored.to_hex()


class TestRangeParam:
    """Test RangeParam functionality including JSON serialization."""
    
    def test_create_range(self):
        """Test creating RangeParam."""
        range_param = RangeParam(10.0, 20.0)
        assert range_param.min_value == 10.0
        assert range_param.max_value == 20.0
        assert range_param.value == (10.0, 20.0)
    
    def test_choose_value(self):
        """Test choosing random value within range."""
        range_param = RangeParam(5.0, 15.0)
        
        # Test multiple times to ensure it's within range
        for _ in range(100):
            value = range_param.choose()
            assert 5.0 <= value <= 15.0
    
    def test_load(self):
        """Test loading from list."""
        range_param = RangeParam.load([1.5, 3.7])
        assert range_param.min_value == 1.5
        assert range_param.max_value == 3.7
    
    def test_json_export(self):
        """Test JSON export."""
        range_param = RangeParam(2.5, 7.8)
        json_data = range_param.to_json()
        
        assert json_data["type"] == "Range"
        assert json_data["value"] == [2.5, 7.8]
    
    def test_json_import(self):
        """Test JSON import."""
        json_data = {
            "type": "Range",
            "value": [3.14, 6.28]
        }
        range_param = RangeParam.from_json(json_data)
        assert range_param.min_value == 3.14
        assert range_param.max_value == 6.28
    
    def test_json_roundtrip(self):
        """Test export->import preserves data."""
        original = RangeParam(0.5, 99.9)
        json_data = original.to_json()
        restored = RangeParam.from_json(json_data)
        
        assert original.value == restored.value


class TestBreakCfgParam:
    """Test BreakCfgParam functionality including JSON serialization."""
    
    def test_create_break_cfg(self):
        """Test creating BreakCfgParam."""
        duration = RangeParam(15.0, 45.0)
        break_cfg = BreakCfgParam(duration, 0.1)
        
        assert break_cfg.break_duration == duration
        assert break_cfg.break_chance == 0.1
        assert break_cfg.value == (duration.value, 0.1)
    
    def test_should_break(self):
        """Test break decision logic."""
        # Test with 0% chance
        break_cfg_never = BreakCfgParam(RangeParam(10, 20), 0.0)
        for _ in range(100):
            assert not break_cfg_never.should_break()
        
        # Test with 100% chance
        break_cfg_always = BreakCfgParam(RangeParam(10, 20), 1.0)
        for _ in range(100):
            assert break_cfg_always.should_break()
    
    def test_load(self):
        """Test loading from list."""
        break_cfg = BreakCfgParam.load([[5.0, 15.0], 0.05])
        assert break_cfg.break_duration.value == (5.0, 15.0)
        assert break_cfg.break_chance == 0.05
    
    def test_json_export(self):
        """Test JSON export."""
        duration = RangeParam(20.0, 60.0)
        break_cfg = BreakCfgParam(duration, 0.02)
        json_data = break_cfg.to_json()
        
        assert json_data["type"] == "BreakCfg"
        assert json_data["value"]["break_duration"]["type"] == "Range"
        assert json_data["value"]["break_duration"]["value"] == [20.0, 60.0]
        assert json_data["value"]["break_chance"] == 0.02
    
    def test_json_import(self):
        """Test JSON import."""
        json_data = {
            "type": "BreakCfg",
            "value": {
                "break_duration": {
                    "type": "Range",
                    "value": [30.0, 90.0]
                },
                "break_chance": 0.03
            }
        }
        break_cfg = BreakCfgParam.from_json(json_data)
        
        assert break_cfg.break_duration.value == (30.0, 90.0)
        assert break_cfg.break_chance == 0.03
    
    def test_json_roundtrip(self):
        """Test export->import preserves data."""
        duration = RangeParam(12.5, 37.5)
        original = BreakCfgParam(duration, 0.075)
        json_data = original.to_json()
        restored = BreakCfgParam.from_json(json_data)
        
        assert original.break_duration.value == restored.break_duration.value
        assert original.break_chance == restored.break_chance


class TestWaypointParam:
    """Test WaypointParam functionality including JSON serialization."""
    
    def test_create_waypoint(self):
        """Test creating WaypointParam."""
        wp = WaypointParam(100, 200, 0, 12345, 10)
        assert wp.x == 100
        assert wp.y == 200
        assert wp.z == 0
        assert wp.chunk == 12345
        assert wp.tolerance == 10
    
    def test_create_waypoint_default_tolerance(self):
        """Test creating WaypointParam with default tolerance."""
        wp = WaypointParam(50, 75, 1, 54321)
        assert wp.tolerance == 5  # Default value
    
    def test_gen_tile(self):
        """Test generating tile configuration."""
        wp = WaypointParam(25, 50, 0, 98765, 3)
        color = RGBParam.from_rgb(255, 0, 128)
        tile = wp.gen_tile(color)
        
        assert tile["regionId"] == 98765
        assert tile["regionX"] == 25
        assert tile["regionY"] == 50
        assert tile["z"] == 0
        assert tile["color"] == "#FF0080"
    
    def test_load_various_formats(self):
        """Test loading from various formats."""
        # Format: [[x, y, z], chunk, tolerance]
        wp1 = WaypointParam.load([[10, 20, 0], 1234, 8])
        assert wp1.x == 10
        assert wp1.y == 20
        assert wp1.z == 0
        assert wp1.chunk == 1234
        assert wp1.tolerance == 8
        
        # Format: [[x, y, z], chunk] (default tolerance)
        wp2 = WaypointParam.load([[30, 40, 1], 5678])
        assert wp2.x == 30
        assert wp2.y == 40
        assert wp2.z == 1
        assert wp2.chunk == 5678
        assert wp2.tolerance == 5
        
        # Format: [x, y, z, chunk]
        wp3 = WaypointParam.load([50, 60, 2, 9012])
        assert wp3.x == 50
        assert wp3.y == 60
        assert wp3.z == 2
        assert wp3.chunk == 9012
        assert wp3.tolerance == 5
    
    def test_json_export(self):
        """Test JSON export."""
        wp = WaypointParam(75, 125, 1, 11111, 7)
        json_data = wp.to_json()
        
        assert json_data["type"] == "Waypoint"
        assert json_data["value"]["x"] == 75
        assert json_data["value"]["y"] == 125
        assert json_data["value"]["z"] == 1
        assert json_data["value"]["chunk"] == 11111
        assert json_data["value"]["tolerance"] == 7
    
    def test_json_import(self):
        """Test JSON import."""
        json_data = {
            "type": "Waypoint",
            "value": {
                "x": 85,
                "y": 135,
                "z": 2,
                "chunk": 22222,
                "tolerance": 12
            }
        }
        wp = WaypointParam.from_json(json_data)
        
        assert wp.x == 85
        assert wp.y == 135
        assert wp.z == 2
        assert wp.chunk == 22222
        assert wp.tolerance == 12
    
    def test_json_roundtrip(self):
        """Test export->import preserves data."""
        original = WaypointParam(999, 888, 3, 77777, 15)
        json_data = original.to_json()
        restored = WaypointParam.from_json(json_data)
        
        assert original.x == restored.x
        assert original.y == restored.y
        assert original.z == restored.z
        assert original.chunk == restored.chunk
        assert original.tolerance == restored.tolerance


class TestRouteParam:
    """Test RouteParam functionality including JSON serialization."""
    
    def test_create_route(self):
        """Test creating RouteParam."""
        wp1 = WaypointParam(10, 20, 0, 1111)
        wp2 = WaypointParam(30, 40, 1, 2222)
        route = RouteParam([wp1, wp2])
        
        assert len(route.waypoints) == 2
        assert route.waypoints[0] == wp1
        assert route.waypoints[1] == wp2
    
    def test_reverse(self):
        """Test reversing route."""
        wp1 = WaypointParam(10, 20, 0, 1111)
        wp2 = WaypointParam(30, 40, 1, 2222)
        wp3 = WaypointParam(50, 60, 2, 3333)
        route = RouteParam([wp1, wp2, wp3])
        
        reversed_route = route.reverse()
        assert reversed_route.waypoints[0].x == wp3.x
        assert reversed_route.waypoints[1].x == wp2.x
        assert reversed_route.waypoints[2].x == wp1.x
    
    def test_load(self):
        """Test loading from waypoint data."""
        waypoint_data = [
            [[100, 200, 0], 4444, 5],
            [[300, 400, 1], 5555]
        ]
        route = RouteParam.load(waypoint_data)
        
        assert len(route.waypoints) == 2
        assert route.waypoints[0].x == 100
        assert route.waypoints[1].x == 300
    
    def test_json_export(self):
        """Test JSON export."""
        wp1 = WaypointParam(111, 222, 0, 6666)
        wp2 = WaypointParam(333, 444, 1, 7777)
        route = RouteParam([wp1, wp2])
        json_data = route.to_json()
        
        assert json_data["type"] == "Route"
        assert len(json_data["value"]) == 2
        assert json_data["value"][0]["type"] == "Waypoint"
        assert json_data["value"][0]["value"]["x"] == 111
        assert json_data["value"][1]["value"]["x"] == 333
    
    def test_json_import(self):
        """Test JSON import."""
        json_data = {
            "type": "Route",
            "value": [
                {
                    "type": "Waypoint",
                    "value": {"x": 555, "y": 666, "z": 0, "chunk": 8888, "tolerance": 5}
                },
                {
                    "type": "Waypoint", 
                    "value": {"x": 777, "y": 888, "z": 1, "chunk": 9999, "tolerance": 10}
                }
            ]
        }
        route = RouteParam.from_json(json_data)
        
        assert len(route.waypoints) == 2
        assert route.waypoints[0].x == 555
        assert route.waypoints[1].x == 777
    
    def test_json_roundtrip(self):
        """Test export->import preserves data."""
        wp1 = WaypointParam(123, 456, 0, 1010, 8)
        wp2 = WaypointParam(789, 12, 2, 2020, 12)
        original = RouteParam([wp1, wp2])
        json_data = original.to_json()
        restored = RouteParam.from_json(json_data)
        
        assert len(original.waypoints) == len(restored.waypoints)
        for orig_wp, rest_wp in zip(original.waypoints, restored.waypoints):
            assert orig_wp.x == rest_wp.x
            assert orig_wp.y == rest_wp.y
            assert orig_wp.z == rest_wp.z
            assert orig_wp.chunk == rest_wp.chunk
            assert orig_wp.tolerance == rest_wp.tolerance


class TestJSONSerialization:
    """Test JSON serialization for complex configurations."""
    
    def test_complete_config_serialization(self):
        """Test serializing a complete bot configuration."""
        # Create a complex configuration
        config = {
            "rgb_color": RGBParam.from_hex("#FF8040"),
            "range_setting": RangeParam(10.5, 25.75),
            "break_config": BreakCfgParam(RangeParam(30.0, 60.0), 0.05),
            "target_waypoint": WaypointParam(100, 200, 0, 12345, 8),
            "patrol_route": RouteParam([
                WaypointParam(50, 100, 0, 11111),
                WaypointParam(150, 250, 1, 22222, 10)
            ])
        }
        
        # Export to JSON
        json_config = {}
        for key, param in config.items():
            json_config[key] = param.to_json()
        
        # Convert to JSON string and back
        json_string = json.dumps(json_config, indent=2)
        loaded_json = json.loads(json_string)
        
        # Import from JSON
        restored_config = {}
        restored_config["rgb_color"] = RGBParam.from_json(loaded_json["rgb_color"])
        restored_config["range_setting"] = RangeParam.from_json(loaded_json["range_setting"])
        restored_config["break_config"] = BreakCfgParam.from_json(loaded_json["break_config"])
        restored_config["target_waypoint"] = WaypointParam.from_json(loaded_json["target_waypoint"])
        restored_config["patrol_route"] = RouteParam.from_json(loaded_json["patrol_route"])
        
        # Verify all data is preserved
        assert config["rgb_color"] == restored_config["rgb_color"]
        assert config["range_setting"].value == restored_config["range_setting"].value
        assert config["break_config"].break_chance == restored_config["break_config"].break_chance
        assert config["target_waypoint"].x == restored_config["target_waypoint"].x
        assert len(config["patrol_route"].waypoints) == len(restored_config["patrol_route"].waypoints)
    
    def test_json_string_handling(self):
        """Test that JSON strings can be properly handled."""
        rgb = RGBParam.from_rgb(128, 64, 192)
        json_string = json.dumps(rgb.to_json())
        
        # Verify it's valid JSON
        parsed = json.loads(json_string)
        restored = RGBParam.from_json(parsed)
        
        assert rgb == restored
    
    def test_error_handling(self):
        """Test error handling for invalid JSON data."""
        # Wrong type
        with pytest.raises(ValueError):
            RGBParam.from_json({"type": "Range", "value": [255, 0, 0]})
        
        # Missing required fields
        with pytest.raises(KeyError):
            RangeParam.from_json({"type": "Range"})  # Missing value
        
        # Invalid data format
        with pytest.raises(ValueError):
            WaypointParam.from_json({"type": "Waypoint", "value": "invalid"})


def run_all_tests():
    """Run all tests manually (for environments without pytest)."""
    test_classes = [
        TestRGBParam, TestRangeParam, TestBreakCfgParam, 
        TestWaypointParam, TestRouteParam, TestJSONSerialization
    ]
    
    total_tests = 0
    passed_tests = 0
    
    for test_class in test_classes:
        print(f"\n=== Running {test_class.__name__} ===")
        instance = test_class()
        
        for method_name in dir(instance):
            if method_name.startswith('test_'):
                total_tests += 1
                try:
                    method = getattr(instance, method_name)
                    method()
                    print(f"✓ {method_name}")
                    passed_tests += 1
                except Exception as e:
                    print(f"✗ {method_name}: {e}")
    
    print(f"\n=== Test Results ===")
    print(f"Passed: {passed_tests}/{total_tests}")
    print(f"Failed: {total_tests - passed_tests}/{total_tests}")
    
    return passed_tests == total_tests


if __name__ == "__main__":
    # Try to use pytest if available, otherwise run manually
    try:
        import pytest
        pytest.main([__file__, "-v"])
    except ImportError:
        print("pytest not available, running tests manually...")
        success = run_all_tests()
        exit(0 if success else 1)