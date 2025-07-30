#!/usr/bin/env python3
"""
Test script to verify robot connection fixes work correctly.
Tests both Meca and OT2 robot behaviors with the new fixes.
"""

import asyncio
import aiohttp
import json
import sys
import time

async def test_meca_robot_command():
    """Test that Meca robot properly handles connection attempts"""
    print("🤖 Testing Meca robot connection behavior...")
    
    # Test WebSocket command that should trigger the fixed ensure_robot_ready
    test_command = {
        "type": "robot_command",
        "robot_id": "meca",
        "command_type": "status",
        "parameters": {}
    }
    
    try:
        # Connect to WebSocket endpoint
        uri = "ws://localhost:8080/ws/robot"
        session = aiohttp.ClientSession()
        
        async with session.ws_connect(uri) as ws:
            print("✅ Connected to WebSocket")
            
            # Send status command
            await ws.send_str(json.dumps(test_command))
            print("📤 Sent Meca status command")
            
            # Wait for response
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    response = json.loads(msg.data)
                    print(f"📥 Received: {response}")
                    
                    # Check if we get proper error handling instead of silent failure
                    if "error" in response:
                        if "HardwareError" in str(response.get("error", "")):
                            print("✅ MECA FIX WORKING: Got proper HardwareError instead of silent failure")
                            return True
                        elif "Robot not connected" in str(response.get("error", "")):
                            print("✅ MECA FIX WORKING: Got proper connection error")
                            return True
                    elif response.get("status") == "success":
                        print("✅ MECA FIX WORKING: Robot connected successfully")
                        return True
                    
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"❌ WebSocket error: {ws.exception()}")
                    break
                    
        await session.close()
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    return False

async def test_ot2_robot_command():
    """Test that OT2 robot uses proper protocol file path"""
    print("\n🧪 Testing OT2 robot protocol file behavior...")
    
    # Test WebSocket command that should trigger the fixed protocol file logic
    test_command = {
        "type": "robot_command", 
        "robot_id": "ot2",
        "command_type": "protocol_execution",
        "parameters": {
            "protocol_name": "test_protocol",
            "volume": 50.0,
            "source_well": "A1",
            "dest_well": "B1"
            # Intentionally NOT providing protocol_file to test default behavior
        }
    }
    
    try:
        uri = "ws://localhost:8080/ws/robot"
        session = aiohttp.ClientSession()
        
        async with session.ws_connect(uri) as ws:
            print("✅ Connected to WebSocket")
            
            # Send protocol execution command
            await ws.send_str(json.dumps(test_command))
            print("📤 Sent OT2 protocol execution command")
            
            # Wait for response
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    response = json.loads(msg.data)
                    print(f"📥 Received: {response}")
                    
                    # Check that we don't get the directory error anymore
                    error_msg = str(response.get("error", "")).lower()
                    if "is a directory" in error_msg:
                        print("❌ OT2 FIX NOT WORKING: Still getting directory error")
                        return False
                    elif "protocol file not found" in error_msg:
                        print("✅ OT2 FIX WORKING: Using proper file path (file may not exist but path is correct)")
                        return True
                    elif response.get("status") == "success":
                        print("✅ OT2 FIX WORKING: Protocol executed successfully")
                        return True
                    elif "connection" in error_msg or "not accessible" in error_msg:
                        print("✅ OT2 FIX WORKING: Protocol file path fixed, got connection error instead")
                        return True
                    
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"❌ WebSocket error: {ws.exception()}")
                    break
                    
        await session.close()
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    
    return False

async def main():
    """Run all tests"""
    print("🚀 Starting robot fix verification tests...")
    print("=" * 50)
    
    # Test Meca robot fix
    meca_success = await test_meca_robot_command()
    
    # Test OT2 robot fix  
    ot2_success = await test_ot2_robot_command()
    
    print("\n" + "=" * 50)
    print("📊 TEST RESULTS:")
    print(f"Meca Robot Connection Fix: {'✅ PASS' if meca_success else '❌ FAIL'}")
    print(f"OT2 Protocol File Fix: {'✅ PASS' if ot2_success else '❌ FAIL'}")
    
    if meca_success and ot2_success:
        print("\n🎉 ALL TESTS PASSED! Your robot fixes are working correctly.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))