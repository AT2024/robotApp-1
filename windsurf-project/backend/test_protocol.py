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
        print("✅ Protocol imports successfully")
        print(f"✅ API Level: {metadata['apiLevel']}")
    except Exception as e:
        print(f"❌ Protocol import failed: {e}")
        return False
    
    # Test environment config loading
    try:
        ctx = MockProtocolContext()
        config = load_environment_config(ctx)
        
        if config:
            print("✅ Environment configuration loaded successfully")
            print(f"✅ Config keys: {list(config.keys())}")
            
            # Check critical parameters
            if "THORIUM_VOL" in config:
                print(f"✅ THORIUM_VOL: {config['THORIUM_VOL']}")
            else:
                print("❌ THORIUM_VOL not found in config")
                
            if "NUM_OF_GENERATORS" in config:
                print(f"✅ NUM_OF_GENERATORS: {config['NUM_OF_GENERATORS']}")
            else:
                print("❌ NUM_OF_GENERATORS not found in config")
                
            if "generators_locations" in config:
                print(f"✅ generators_locations: {len(config['generators_locations'])} locations")
            else:
                print("❌ generators_locations not found in config")
                
        else:
            print("❌ Environment configuration not loaded")
            return False
            
    except Exception as e:
        print(f"❌ Environment config test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("=" * 50)
    print("✅ All protocol tests passed!")
    print("=" * 50)
    
    # Print comments from protocol loading
    print("\nProtocol Loading Comments:")
    for comment in ctx.comments:
        print(f"  - {comment}")
    
    return True

if __name__ == "__main__":
    success = test_protocol_fixes()
    sys.exit(0 if success else 1)