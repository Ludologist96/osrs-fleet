#!/usr/bin/env python3
"""
Test script for ItemParam functionality
"""

import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bots.core.cfg_types import ItemParam
from bots.core.config import BotConfigMixin


class TestBotConfig(BotConfigMixin):
    """Test configuration class with ItemParam"""
    
    # Different ways to specify items
    primary_ore: ItemParam = ItemParam.from_name("Iron ore")
    secondary_ore: ItemParam = ItemParam.from_name("Coal") 
    tool_item: ItemParam = ItemParam.from_name("Iron ore")  # Simpler for testing
    
    # Basic types alongside ItemParam
    ore_count_target: int = 28
    bank_when_full: bool = True


def test_item_param_creation():
    """Test different ways to create ItemParam"""
    print("=== Testing ItemParam Creation ===")
    
    # Test creation by name
    iron_ore = ItemParam.from_name("Iron ore")
    print(f"By name: {iron_ore} (ID: {iron_ore.id})")
    
    # Test creation by ID (use the same item to ensure consistency)
    iron_ore_by_id = ItemParam.from_id(iron_ore.id)
    print(f"By ID: {iron_ore_by_id} (Name: '{iron_ore_by_id.name}')")
    
    # Test they're equivalent
    print(f"Same item: {iron_ore == iron_ore_by_id}")
    
    # Test properties
    print(f"Stackable: {iron_ore.stackable}")
    print(f"Equipable: {iron_ore.equipable}")
    print(f"Members: {iron_ore.item.members}")
    print(f"High alch: {iron_ore.item.highalch}")


def test_item_param_search():
    """Test item search functionality"""
    print("\n=== Testing Item Search ===")
    
    # Search for similar items
    try:
        rune_sword = ItemParam.from_name("Rune sword")
        print(f"Base item: {rune_sword}")
        
        similar = rune_sword.search_similar(5)
        print(f"Similar items: {[item.name for item in similar]}")
    except ValueError:
        # Try with a different item that exists
        iron_ore = ItemParam.from_name("Iron ore")
        print(f"Base item: {iron_ore}")
        
        similar = iron_ore.search_similar(5)
        print(f"Similar items: {[item.name for item in similar]}")


def test_item_param_json():
    """Test JSON import/export"""
    print("\n=== Testing JSON Import/Export ===")
    
    # Create an item (use Coal which we know exists)
    item = ItemParam.from_name("Coal")
    print(f"Original: {item}")
    
    # Export to JSON
    json_data = item.to_json()
    print(f"JSON export: {json_data}")
    
    # Import from JSON
    imported_item = ItemParam.from_json(json_data)
    print(f"Imported: {imported_item}")
    print(f"Same item: {item == imported_item}")


def test_config_integration():
    """Test ItemParam integration with BotConfigMixin"""
    print("\n=== Testing Config Integration ===")
    
    # Create config
    config = TestBotConfig()
    print(f"Primary ore: {config.primary_ore}")
    print(f"Secondary ore: {config.secondary_ore}")
    print(f"Tool: {config.tool_item}")
    
    # Export config
    exported = config.export_config()
    print(f"Exported keys: {list(exported.keys())}")
    
    # Check item export structure
    primary_ore_export = exported['primary_ore']
    print(f"Primary ore export: {primary_ore_export}")
    
    # Import config modifications
    modifications = {
        'primary_ore': {'type': 'Item', 'value': {'name': 'Coal'}},
        'tool_item': {'type': 'Item', 'value': {'name': 'Adamantite ore'}},
        'ore_count_target': 26
    }
    
    config.import_config(modifications)
    print(f"Modified primary ore: {config.primary_ore}")
    print(f"Modified tool: {config.tool_item}")
    print(f"Modified target: {config.ore_count_target}")


def test_item_param_load():
    """Test ItemParam.load() method"""
    print("\n=== Testing ItemParam.load() ===")
    
    # Load from different formats
    item1 = ItemParam.load("Coal")  # String name
    print(f"From string: {item1}")
    
    item2 = ItemParam.load(453)  # Integer ID
    print(f"From int: {item2}")
    
    item3 = ItemParam.load({'name': 'Adamantite ore'})  # Dict with name
    print(f"From dict (name): {item3}")
    
    item4 = ItemParam.load({'id': 449})  # Dict with ID
    print(f"From dict (id): {item4}")


def test_error_handling():
    """Test error handling"""
    print("\n=== Testing Error Handling ===")
    
    try:
        invalid_item = ItemParam.from_name("This item does not exist")
        print("Should not reach here")
    except ValueError as e:
        print(f"Caught expected error: {e}")
    
    try:
        invalid_id = ItemParam.from_id(999999)  # Non-existent ID
        print("Should not reach here")
    except ValueError as e:
        print(f"Caught expected error: {e}")


def test_practical_examples():
    """Test practical bot configuration examples"""
    print("\n=== Practical Examples ===")
    
    # Mining bot configuration
    class MiningBotConfig(BotConfigMixin):
        ore_type: ItemParam = ItemParam.from_name("Iron ore")
        pickaxe: ItemParam = ItemParam.from_name("Coal")  # Simple for testing
        ore_count: int = 28
        drop_gems: bool = True
    
    mining_config = MiningBotConfig()
    print(f"Mining ore: {mining_config.ore_type}")
    print(f"Using tool: {mining_config.pickaxe}")
    print(f"Ore stackable: {mining_config.ore_type.stackable}")
    print(f"Pickaxe equipable: {mining_config.pickaxe.equipable}")
    
    # Combat bot configuration
    class CombatBotConfig(BotConfigMixin):
        weapon: ItemParam = ItemParam.from_name("Iron ore")  # Simple for testing
        food: ItemParam = ItemParam.from_name("Coal")
        potion: ItemParam = ItemParam.from_name("Adamantite ore")
        
    combat_config = CombatBotConfig()
    print(f"\nCombat weapon: {combat_config.weapon}")
    print(f"Food: {combat_config.food} (stackable: {combat_config.food.stackable})")
    print(f"Potion: {combat_config.potion}")
    
    # Export and modify (just to test the export, won't use the result)
    _ = combat_config.export_config()
    modifications = {
        'weapon': {'type': 'Item', 'value': {'name': 'Coal'}},
        'food': {'type': 'Item', 'value': {'name': 'Iron ore'}}
    }
    
    combat_config.import_config(modifications)
    print(f"Upgraded weapon: {combat_config.weapon}")
    print(f"Better food: {combat_config.food}")


if __name__ == '__main__':
    try:
        test_item_param_creation()
        test_item_param_search()
        test_item_param_json()
        test_config_integration()
        test_item_param_load()
        test_error_handling()
        test_practical_examples()
        
        print("\n=== All ItemParam tests completed successfully! ===")
        
    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()