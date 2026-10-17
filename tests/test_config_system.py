#!/usr/bin/env python3
"""
Comprehensive tests for the bot configuration system.
Tests both custom parameter types and the BotConfigMixin import/export functionality.
"""

import unittest
import json
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bots.core.config import BotConfigMixin
from bots.core.cfg_types import RGBParam, RangeParam, BreakCfgParam, WaypointParam, RouteParam, ItemParam


class TestBotConfig(BotConfigMixin):
    """Test configuration class based on real bot patterns"""
    
    # RGB parameters (like in motherload_miner, mining_bot)
    bank_tile: RGBParam = RGBParam.from_tuple((0, 255, 0))
    ore_tile: RGBParam = RGBParam.from_hex("#FF0000")
    
    # Basic Python types (common in all bots)
    ore_name: str = "Iron ore"
    max_retries: int = 5
    success_rate: float = 0.85
    enabled: bool = True
    
    # List of RGB parameters (like ore_options in mining_bot)
    ore_options: list[RGBParam] = [
        RGBParam.from_tuple((255, 0, 100)),
        RGBParam.from_tuple((255, 0, 150)),
    ]
    
    # Range parameters
    click_delay: RangeParam = RangeParam(0.2, 0.5)
    
    # Break configuration
    break_cfg: BreakCfgParam = BreakCfgParam(
        RangeParam(15, 45),
        0.01
    )
    
    # Waypoint and route (like in mining_bot)
    start_point: WaypointParam = WaypointParam(3253, 3424, 0, 831916, 5)
    mining_route: RouteParam = RouteParam([
        WaypointParam(3253, 3424, 0, 831916, 5),
        WaypointParam(3286, 3430, 0, 840108, 5),
    ])
    
    # Item parameter
    target_item: ItemParam = ItemParam.from_name("Iron ore")


class TestConfigSystem(unittest.TestCase):
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = TestBotConfig()
    
    def test_export_config_basic(self):
        """Test basic config export functionality"""
        exported = self.config.export_config()
        
        # Check that all expected keys are present
        expected_keys = {
            'bank_tile', 'ore_tile', 'ore_name', 'max_retries', 'success_rate', 
            'enabled', 'ore_options', 'click_delay', 'break_cfg', 'start_point', 'mining_route', 'target_item'
        }
        self.assertEqual(set(exported.keys()), expected_keys)
        
        # Check basic types are preserved
        self.assertEqual(exported['ore_name'], "Iron ore")
        self.assertEqual(exported['max_retries'], 5)
        self.assertEqual(exported['success_rate'], 0.85)
        self.assertEqual(exported['enabled'], True)
    
    def test_export_rgb_params(self):
        """Test RGB parameter export"""
        exported = self.config.export_config()
        
        # Check RGB parameter structure
        bank_tile = exported['bank_tile']
        self.assertEqual(bank_tile['type'], 'RGB')
        self.assertIn('value', bank_tile)
        
        ore_tile = exported['ore_tile']
        self.assertEqual(ore_tile['type'], 'RGB')
        self.assertIn('value', ore_tile)
    
    def test_export_complex_params(self):
        """Test complex parameter export (Break, Route, etc.)"""
        exported = self.config.export_config()
        
        # Check break config
        break_cfg = exported['break_cfg']
        self.assertEqual(break_cfg['type'], 'BreakCfg')
        self.assertIn('value', break_cfg)
        
        # Check route
        mining_route = exported['mining_route']
        self.assertEqual(mining_route['type'], 'Route')
        self.assertIn('value', mining_route)
    
    def test_export_import_roundtrip(self):
        """Test that export -> import preserves all data"""
        # Export current config
        exported = self.config.export_config()
        
        # Create new config and import
        new_config = TestBotConfig()
        new_config.import_config(exported)
        
        # Compare values
        self.assertEqual(new_config.ore_name, self.config.ore_name)
        self.assertEqual(new_config.max_retries, self.config.max_retries)
        self.assertEqual(new_config.success_rate, self.config.success_rate)
        self.assertEqual(new_config.enabled, self.config.enabled)
        
        # Compare RGB params
        self.assertEqual(new_config.bank_tile.value, self.config.bank_tile.value)
        self.assertEqual(new_config.ore_tile.value, self.config.ore_tile.value)
        
        # Compare complex params
        self.assertEqual(new_config.click_delay.value, self.config.click_delay.value)
        self.assertEqual(len(new_config.ore_options), len(self.config.ore_options))
        
        # Compare item params
        self.assertEqual(new_config.target_item.id, self.config.target_item.id)
    
    def test_json_export_import(self):
        """Test JSON string export/import"""
        # Export to JSON
        json_str = self.config.export_config_json()
        self.assertIsInstance(json_str, str)
        
        # Verify it's valid JSON
        parsed = json.loads(json_str)
        self.assertIsInstance(parsed, dict)
        
        # Import from JSON
        new_config = TestBotConfig()
        new_config.import_config_json(json_str)
        
        # Verify data integrity
        self.assertEqual(new_config.ore_name, self.config.ore_name)
        self.assertEqual(new_config.bank_tile.value, self.config.bank_tile.value)
    
    def test_import_with_mixed_data(self):
        """Test importing configuration with mixed data types"""
        mixed_config = {
            'ore_name': 'Gold ore',  # Basic string
            'max_retries': 10,       # Basic int
            'bank_tile': {           # Custom RGB param
                'type': 'RGB',
                'value': {'rgb': [255, 255, 0], 'hex': '#FFFF00'}
            },
            'click_delay': {         # Custom Range param
                'type': 'Range',
                'value': [0.1, 0.3]
            },
            'target_item': {         # Custom Item param
                'type': 'Item',
                'value': {'name': 'Coal'}
            }
        }
        
        new_config = TestBotConfig()
        new_config.import_config(mixed_config)
        
        self.assertEqual(new_config.ore_name, 'Gold ore')
        self.assertEqual(new_config.max_retries, 10)
        self.assertEqual(new_config.bank_tile.value, (255, 255, 0))
        self.assertEqual(new_config.click_delay.value, (0.1, 0.3))
        self.assertEqual(new_config.target_item.name, 'Coal')
    
    def test_import_rgb_from_different_formats(self):
        """Test importing RGB from various formats"""
        # Test hex format
        hex_config = {
            'bank_tile': {
                'type': 'RGB',
                'value': {'hex': '#FF0080'}
            }
        }
        
        new_config = TestBotConfig()
        new_config.import_config(hex_config)
        self.assertEqual(new_config.bank_tile.to_hex(), '#FF0080')
        
        # Test RGB tuple format
        rgb_config = {
            'ore_tile': {
                'type': 'RGB', 
                'value': {'rgb': [128, 64, 192]}
            }
        }
        
        new_config.import_config(rgb_config)
        self.assertEqual(new_config.ore_tile.value, (128, 64, 192))
    
    def test_error_handling_unknown_key(self):
        """Test error handling for unknown configuration keys"""
        bad_config = {'unknown_key': 'value'}
        
        with self.assertRaises(KeyError):
            self.config.import_config(bad_config)
    
    def test_error_handling_type_mismatch(self):
        """Test error handling for type mismatches"""
        bad_config = {'max_retries': 'not_a_number'}  # Should be int
        
        with self.assertRaises(TypeError):
            self.config.import_config(bad_config)
    
    def test_error_handling_unknown_param_type(self):
        """Test error handling for unknown parameter types"""
        bad_config = {
            'bank_tile': {
                'type': 'UnknownType',
                'value': [1, 2, 3]
            }
        }
        
        with self.assertRaises(ValueError):
            self.config.import_config(bad_config)
    
    def test_motherload_miner_like_config(self):
        """Test configuration similar to motherload miner bot"""
        motherload_config = {
            'vein_tile_1': {'type': 'RGB', 'value': {'rgb': [255, 0, 0]}},
            'vein_tile_2': {'type': 'RGB', 'value': {'rgb': [255, 0, 40]}},
            'hopper_tile': {'type': 'RGB', 'value': {'hex': '#FF00FF'}},
            'sack_size': 189,
            'max_retries': 5,
            'fail_retry_delay': 1.5,
        }
        
        # Create a config class similar to motherload miner
        class MotherloadConfig(BotConfigMixin):
            vein_tile_1: RGBParam = RGBParam.from_tuple((255, 0, 0))
            vein_tile_2: RGBParam = RGBParam.from_tuple((255, 0, 40))
            hopper_tile: RGBParam = RGBParam.from_tuple((255, 0, 255))
            sack_size: int = 189
            max_retries: int = 5
            fail_retry_delay: float = 1.5
        
        config = MotherloadConfig()
        config.import_config(motherload_config)
        
        self.assertEqual(config.vein_tile_1.value, (255, 0, 0))
        self.assertEqual(config.vein_tile_2.value, (255, 0, 40))
        self.assertEqual(config.hopper_tile.to_hex(), '#FF00FF')
        self.assertEqual(config.sack_size, 189)
        self.assertEqual(config.max_retries, 5)
        self.assertEqual(config.fail_retry_delay, 1.5)
    
    def test_mining_bot_like_config(self):
        """Test configuration similar to mining bot"""
        mining_config = {
            'bank_tile': {'type': 'RGB', 'value': {'rgb': [0, 255, 0]}},
            'ore_type': 'Iron ore',
            'inv_full_at': 27,
            'ore_options': [
                {'type': 'RGB', 'value': {'rgb': [255, 0, 100]}},
                {'type': 'RGB', 'value': {'rgb': [255, 0, 150]}},
            ],
            'mine_click_delay': {'type': 'Range', 'value': [0.2, 0.5]},
        }
        
        class MiningConfig(BotConfigMixin):
            bank_tile: RGBParam = RGBParam.from_tuple((0, 255, 0))
            ore_type: str = "Iron ore"
            inv_full_at: int = 27
            ore_options: list[RGBParam] = [
                RGBParam.from_tuple((255, 0, 100)),
                RGBParam.from_tuple((255, 0, 150)),
            ]
            mine_click_delay: RangeParam = RangeParam(0.2, 0.5)
        
        config = MiningConfig()
        config.import_config(mining_config)
        
        self.assertEqual(config.bank_tile.value, (0, 255, 0))
        self.assertEqual(config.ore_type, 'Iron ore')
        self.assertEqual(config.inv_full_at, 27)
        self.assertEqual(len(config.ore_options), 2)
        self.assertEqual(config.ore_options[0].value, (255, 0, 100))
        self.assertEqual(config.mine_click_delay.value, (0.2, 0.5))


class TestParameterTypes(unittest.TestCase):
    """Test individual parameter types"""
    
    def test_rgb_param_json_roundtrip(self):
        """Test RGBParam JSON export/import"""
        rgb = RGBParam.from_tuple((128, 64, 192))
        json_data = rgb.to_json()
        
        self.assertEqual(json_data['type'], 'RGB')
        self.assertIn('value', json_data)
        
        # Import back
        new_rgb = RGBParam.from_json(json_data)
        self.assertEqual(new_rgb.value, rgb.value)
    
    def test_range_param_json_roundtrip(self):
        """Test RangeParam JSON export/import"""
        range_param = RangeParam(0.1, 0.9)
        json_data = range_param.to_json()
        
        self.assertEqual(json_data['type'], 'Range')
        self.assertEqual(json_data['value'], [0.1, 0.9])
        
        # Import back
        new_range = RangeParam.from_json(json_data)
        self.assertEqual(new_range.value, range_param.value)
    
    def test_break_cfg_param_json_roundtrip(self):
        """Test BreakCfgParam JSON export/import"""
        break_cfg = BreakCfgParam(RangeParam(15, 45), 0.01)
        json_data = break_cfg.to_json()
        
        self.assertEqual(json_data['type'], 'BreakCfg')
        self.assertIn('value', json_data)
        
        # Import back
        new_break_cfg = BreakCfgParam.from_json(json_data)
        self.assertEqual(new_break_cfg.break_duration.value, break_cfg.break_duration.value)
        self.assertEqual(new_break_cfg.break_chance, break_cfg.break_chance)
    
    def test_waypoint_param_json_roundtrip(self):
        """Test WaypointParam JSON export/import"""
        waypoint = WaypointParam(3253, 3424, 0, 831916, 5)
        json_data = waypoint.to_json()
        
        self.assertEqual(json_data['type'], 'Waypoint')
        self.assertIn('value', json_data)
        
        # Import back
        new_waypoint = WaypointParam.from_json(json_data)
        self.assertEqual(new_waypoint.x, waypoint.x)
        self.assertEqual(new_waypoint.y, waypoint.y)
        self.assertEqual(new_waypoint.z, waypoint.z)
        self.assertEqual(new_waypoint.chunk, waypoint.chunk)
        self.assertEqual(new_waypoint.tolerance, waypoint.tolerance)
    
    def test_route_param_json_roundtrip(self):
        """Test RouteParam JSON export/import"""
        route = RouteParam([
            WaypointParam(3253, 3424, 0, 831916, 5),
            WaypointParam(3286, 3430, 0, 840108, 5),
        ])
        json_data = route.to_json()
        
        self.assertEqual(json_data['type'], 'Route')
        self.assertIn('value', json_data)
        
        # Import back
        new_route = RouteParam.from_json(json_data)
        self.assertEqual(len(new_route.waypoints), len(route.waypoints))
        self.assertEqual(new_route.waypoints[0].x, route.waypoints[0].x)
    
    def test_item_param_json_roundtrip(self):
        """Test ItemParam JSON export/import"""
        item = ItemParam.from_name("Coal")
        json_data = item.to_json()
        
        self.assertEqual(json_data['type'], 'Item')
        self.assertIn('value', json_data)
        
        # Import back
        new_item = ItemParam.from_json(json_data)
        self.assertEqual(new_item.id, item.id)
        self.assertEqual(new_item.name, item.name)


if __name__ == '__main__':
    # Run the tests
    unittest.main(verbosity=2)