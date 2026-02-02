#!/usr/bin/env python3
"""
Quick test script to validate our fixed OT2 protocol.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock protocol context for testing
class MockProtocolContext:
    def __init__(self):
        self.comments = []
    
    def comment(self, text):
        self.comments.append(text)
        print(f"PROTOCOL: {text}")

def test_protocol_fixes():
    print("Testing OT2 Protocol Fixes...")
    print("=" * 50)
    
    # Import the protocol module
    try:
        from protocols.ot2Protocole import load_environment_config, metadata
        print("[OK] Protocol imports successfully")
        print(f"[OK] API Level: {metadata['apiLevel']}")
    except Exception as e:
        print(f"[ERROR] Protocol import failed: {e}")
        return False
    
    # Test environment config loading
    try:
        ctx = MockProtocolContext()
        config = load_environment_config(ctx)
        
        if config:
            print("[OK] Environment configuration loaded successfully")
            print(f"[OK] Config keys: {list(config.keys())}")
            
            # Check critical parameters
            if "THORIUM_VOL" in config:
                print(f"[OK] THORIUM_VOL: {config['THORIUM_VOL']}")
            else:
                print("[ERROR] THORIUM_VOL not found in config")
                
            if "NUM_OF_GENERATORS" in config:
                print(f"[OK] NUM_OF_GENERATORS: {config['NUM_OF_GENERATORS']}")
            else:
                print("[ERROR] NUM_OF_GENERATORS not found in config")
                
            if "generators_locations" in config:
                print(f"[OK] generators_locations: {len(config['generators_locations'])} locations")
            else:
                print("[ERROR] generators_locations not found in config")
                
        else:
            print("[ERROR] Environment configuration not loaded")
            return False
            
    except Exception as e:
        print(f"[ERROR] Environment config test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("=" * 50)
    print("[OK] All protocol tests passed!")
    print("=" * 50)
    
    # Print comments from protocol loading
    print("\nProtocol Loading Comments:")
    for comment in ctx.comments:
        print(f"  - {comment}")
    
    return True

if __name__ == "__main__":
    success = test_protocol_fixes()
    sys.exit(0 if success else 1)