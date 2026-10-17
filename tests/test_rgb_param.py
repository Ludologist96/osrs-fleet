#!/usr/bin/env python3
"""
Test script to verify RGBParam functionality
"""

from bots.core.cfg_types import RGBParam

def test_rgb_param():
    print("Testing RGBParam functionality...")
    
    # Test creation from tuple
    rgb1 = RGBParam.from_tuple((255, 0, 0))
    print(f"Created from tuple: {rgb1}")
    print(f"  RGB values: {rgb1.r}, {rgb1.g}, {rgb1.b}")
    print(f"  As tuple: {rgb1.to_rgb_tuple()}")
    print(f"  As hex: {rgb1.to_hex()}")
    
    # Test creation from hex
    rgb2 = RGBParam.from_hex("#00FF00")
    print(f"\nCreated from hex: {rgb2}")
    print(f"  RGB values: {rgb2.r}, {rgb2.g}, {rgb2.b}")
    print(f"  As tuple: {rgb2.to_rgb_tuple()}")
    print(f"  As hex: {rgb2.to_hex()}")
    
    # Test creation from RGB values
    rgb3 = RGBParam.from_rgb(0, 0, 255)
    print(f"\nCreated from RGB: {rgb3}")
    print(f"  RGB values: {rgb3.r}, {rgb3.g}, {rgb3.b}")
    print(f"  As tuple: {rgb3.to_rgb_tuple()}")
    print(f"  As hex: {rgb3.to_hex()}")
    
    # Test tuple-like behavior
    print(f"\nTesting tuple-like behavior:")
    print(f"  Indexing: rgb1[0]={rgb1[0]}, rgb1[1]={rgb1[1]}, rgb1[2]={rgb1[2]}")
    print(f"  Length: len(rgb1)={len(rgb1)}")
    print(f"  Unpacking: {tuple(rgb1)}")
    
    # Test with function that expects tuple
    def test_function(color_tuple):
        return f"Received: {color_tuple}, type: {type(color_tuple)}"
    
    print(f"\nPassing to function expecting tuple:")
    print(f"  {test_function(rgb1)}")
    
    # Test equality
    print(f"\nTesting equality:")
    print(f"  rgb1 == (255, 0, 0): {rgb1 == (255, 0, 0)}")
    print(f"  rgb1 == rgb2: {rgb1 == rgb2}")
    
    # Test .load() method with various inputs
    print(f"\nTesting .load() method:")
    rgb4 = RGBParam.load([128, 128, 128])
    print(f"  From list: {rgb4}")
    
    rgb5 = RGBParam.load("#FFFF00")
    print(f"  From hex string: {rgb5}")
    
    rgb6 = RGBParam.load((255, 128, 0))
    print(f"  From tuple: {rgb6}")
    
    print("\nAll tests completed successfully!")

if __name__ == "__main__":
    test_rgb_param()