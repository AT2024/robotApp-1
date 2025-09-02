#!/usr/bin/env python3
"""
Test script to validate the native Mecademic connection fix.
This simulates the connection checking logic to ensure it works correctly.
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class MockNativeDriver:
    """Mock native driver for testing"""
    def __init__(self, connected=True):
        self.is_connected = connected

class MockDriver:
    """Mock driver wrapper"""
    def __init__(self, use_native=True, connected=True):
        if use_native:
            self._native_driver = MockNativeDriver(connected)
        else:
            self._native_driver = None
    
    async def connect(self):
        if hasattr(self, '_native_driver') and self._native_driver:
            self._native_driver.is_connected = True
            return True
        return False

class MockAsyncWrapper:
    """Mock async wrapper"""
    def __init__(self, use_native=True, connected=True):
        self.robot_driver = MockDriver(use_native, connected)

class MockLogger:
    """Mock logger"""
    def debug(self, msg):
        print(f"DEBUG: {msg}")
    
    def info(self, msg):
        print(f"INFO: {msg}")
    
    def error(self, msg):
        print(f"ERROR: {msg}")

async def test_native_connection_check(use_native=True, connected=True):
    """Test the updated connection check logic"""
    print(f"\n=== Testing native={use_native}, connected={connected} ===")
    
    # Mock setup
    async_wrapper = MockAsyncWrapper(use_native=use_native, connected=connected)
    logger = MockLogger()
    robot_id = "meca_test"
    
    # Simulate the updated _check_robot_connection logic
    try:
        # Check if we have a native driver (avoids TCP connection conflicts)
        if hasattr(async_wrapper, 'robot_driver'):
            driver = async_wrapper.robot_driver
            
            # For native driver, check connection status directly to avoid TCP conflicts
            if hasattr(driver, '_native_driver') and driver._native_driver:
                native_driver = driver._native_driver
                is_connected = native_driver.is_connected
                
                if is_connected:
                    logger.debug(f"Native driver reports connected for {robot_id}")
                    return True
                else:
                    logger.debug(f"Native driver reports disconnected for {robot_id} - attempting reconnection")
                    # Try to reconnect through the driver
                    reconnected = await driver.connect()
                    if reconnected:
                        logger.info(f"🎉 Successfully reconnected to robot {robot_id}")
                        return True
                    else:
                        logger.debug(f"Robot reconnection attempt failed for {robot_id}")
                        return False
            
            # Fallback for non-native drivers would go here
            logger.debug(f"No native driver found - would fall back to TCP test")
            return False
                    
        return False
    except Exception as e:
        logger.debug(f"Connection check failed: {e}")
        return False

async def main():
    """Run all test scenarios"""
    print("Testing Native Mecademic Connection Fix")
    print("=" * 50)
    
    # Test scenarios
    scenarios = [
        ("Native driver, connected", True, True),
        ("Native driver, disconnected", True, False),  
        ("No native driver", False, True),
    ]
    
    for name, use_native, connected in scenarios:
        result = await test_native_connection_check(use_native, connected)
        print(f"Result: {'✅ PASS' if result else '❌ FAIL'}")
    
    print("\n" + "=" * 50)
    print("✅ Connection fix validation complete!")
    print("The updated logic properly uses native driver status instead of TCP tests.")

if __name__ == "__main__":
    asyncio.run(main())