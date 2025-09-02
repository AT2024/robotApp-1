#!/usr/bin/env python3
"""
Simple connection test to verify Mecademic robot connectivity
after adding protocol handshake fix.
"""

import asyncio
import sys
import time
from pathlib import Path

# Add the backend directory to Python path
backend_dir = Path(__file__).parent / "windsurf-project" / "backend"
sys.path.insert(0, str(backend_dir))

from drivers.native_mecademic import NativeMecademicDriver, MecademicConfig


async def test_robot_connection():
    """Test robot connection with the new protocol handshake."""
    
    print("🤖 Testing Mecademic Robot Connection")
    print("=" * 50)
    
    # Create configuration
    config = MecademicConfig(
        robot_ip="192.168.0.100",
        control_port=10000,
        monitor_port=10001,
        connect_timeout=30.0,
    )
    
    print(f"📡 Target: {config.robot_ip}:{config.control_port}/{config.monitor_port}")
    print(f"⏱️  Timeout: {config.connect_timeout}s")
    print()
    
    # Create driver instance
    driver = NativeMecademicDriver(config)
    
    try:
        print("🔌 Attempting connection...")
        start_time = time.time()
        
        # Test connection
        success = await driver.connect()
        connection_time = time.time() - start_time
        
        if success:
            print(f"✅ Connection successful in {connection_time:.2f}s")
            print(f"🎯 Connected: {driver.is_connected}")
            print(f"📊 Status: {driver.status}")
            
            # Test basic communication
            print("\n🔍 Testing basic communication...")
            status = driver.status
            print(f"📈 Robot State: {status.state.value}")
            print(f"📍 Position: {status.position}")
            print(f"🔗 Connection Info: {driver.connection_info}")
            
        else:
            print(f"❌ Connection failed after {connection_time:.2f}s")
            return False
            
    except Exception as e:
        print(f"💥 Connection error: {e}")
        return False
        
    finally:
        # Cleanup
        print("\n🧹 Cleaning up connection...")
        try:
            await driver.disconnect()
            print("✅ Disconnected successfully")
        except Exception as e:
            print(f"⚠️ Disconnect error: {e}")
    
    return success


async def main():
    """Main test function."""
    print("Starting Mecademic Connection Test...")
    print(f"🕐 Test started at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    success = await test_robot_connection()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 Test PASSED: Robot connection working with protocol handshake!")
    else:
        print("💔 Test FAILED: Robot connection still not working")
    
    print(f"🕐 Test completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())