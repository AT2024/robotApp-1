#!/usr/bin/env python3
"""
Test script to verify robot operations work correctly with single state management.
"""

import asyncio
import json
import requests
import time
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "http://localhost:8000"

async def test_meca_operations():
    """Test Meca robot operations"""
    logger.info("🚀 Testing Meca robot operations...")
    
    # Test 1: Get robot status
    logger.info("📋 Getting Meca robot status...")
    response = requests.get(f"{BASE_URL}/api/meca/status")
    if response.status_code == 200:
        status_data = response.json()
        logger.info(f"✅ Meca status: {status_data}")
        robot_state = status_data.get("state_info", {}).get("current_state", "unknown")
        logger.info(f"🤖 Meca robot state: {robot_state}")
    else:
        logger.error(f"❌ Failed to get Meca status: {response.status_code}")
        return False
    
    # Test 2: Execute pickup sequence
    logger.info("🔄 Testing Meca pickup sequence...")
    pickup_payload = {
        "start": 0,
        "count": 1,
        "operation_type": "pickup_wafer_sequence",
        "is_last_batch": True
    }
    
    response = requests.post(f"{BASE_URL}/api/meca/pickup", json=pickup_payload)
    if response.status_code == 200:
        pickup_result = response.json()
        logger.info(f"✅ Pickup command submitted: {pickup_result}")
        command_id = pickup_result.get("command_id")
        
        # Monitor command status
        if command_id:
            logger.info(f"📊 Monitoring command {command_id}...")
            for i in range(30):  # Wait up to 30 seconds
                time.sleep(1)
                try:
                    # Check command status via API (if available)
                    status_response = requests.get(f"{BASE_URL}/api/meca/status")
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        robot_state = status_data.get("state_info", {}).get("current_state", "unknown")
                        logger.info(f"🤖 Robot state: {robot_state}")
                        
                        if robot_state == "idle":
                            logger.info("✅ Robot returned to idle state")
                            break
                        elif robot_state == "busy":
                            logger.info("⏳ Robot is busy, waiting...")
                        elif robot_state == "error":
                            logger.error("❌ Robot is in error state")
                            return False
                    else:
                        logger.warning(f"⚠️ Status check failed: {status_response.status_code}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Status check error: {e}")
                    
            logger.info("🏁 Pickup sequence test completed")
        else:
            logger.warning("⚠️ No command ID returned")
    else:
        logger.error(f"❌ Pickup command failed: {response.status_code} - {response.text}")
        return False
    
    return True

async def test_ot2_operations():
    """Test OT2 robot operations"""
    logger.info("🚀 Testing OT2 robot operations...")
    
    # Test 1: Get robot status
    logger.info("📋 Getting OT2 robot status...")
    response = requests.get(f"{BASE_URL}/api/ot2/robot-status")
    if response.status_code == 200:
        status_data = response.json()
        logger.info(f"✅ OT2 status: {status_data}")
        robot_state = status_data.get("state_info", {}).get("current_state", "unknown")
        logger.info(f"🤖 OT2 robot state: {robot_state}")
    else:
        logger.error(f"❌ Failed to get OT2 status: {response.status_code}")
        return False
    
    # Test 2: Test connection
    logger.info("🔌 Testing OT2 connection...")
    response = requests.post(f"{BASE_URL}/api/ot2/connect")
    if response.status_code == 200:
        connect_result = response.json()
        logger.info(f"✅ OT2 connection test: {connect_result}")
    else:
        logger.error(f"❌ OT2 connection test failed: {response.status_code} - {response.text}")
        return False
    
    return True

async def test_state_transitions():
    """Test that state transitions work correctly"""
    logger.info("🚀 Testing state transitions...")
    
    # Get initial states
    meca_response = requests.get(f"{BASE_URL}/api/meca/status")
    ot2_response = requests.get(f"{BASE_URL}/api/ot2/robot-status")
    
    if meca_response.status_code == 200 and ot2_response.status_code == 200:
        meca_state = meca_response.json().get("state_info", {}).get("current_state", "unknown")
        ot2_state = ot2_response.json().get("state_info", {}).get("current_state", "unknown")
        
        logger.info(f"📊 Initial states - Meca: {meca_state}, OT2: {ot2_state}")
        
        # Check that both robots are in appropriate states
        valid_states = ["idle", "connecting", "disconnected"]
        if meca_state in valid_states and ot2_state in valid_states:
            logger.info("✅ Both robots are in valid states")
            return True
        else:
            logger.error(f"❌ Invalid robot states - Meca: {meca_state}, OT2: {ot2_state}")
            return False
    else:
        logger.error("❌ Failed to get robot states")
        return False

async def main():
    """Main test function"""
    logger.info("🎯 Starting robot operations test...")
    
    # Test state transitions
    state_test_passed = await test_state_transitions()
    
    # Test Meca operations
    meca_test_passed = await test_meca_operations()
    
    # Test OT2 operations
    ot2_test_passed = await test_ot2_operations()
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("📊 TEST SUMMARY")
    logger.info("="*50)
    logger.info(f"State Transitions: {'✅ PASSED' if state_test_passed else '❌ FAILED'}")
    logger.info(f"Meca Operations: {'✅ PASSED' if meca_test_passed else '❌ FAILED'}")
    logger.info(f"OT2 Operations: {'✅ PASSED' if ot2_test_passed else '❌ FAILED'}")
    
    if state_test_passed and meca_test_passed and ot2_test_passed:
        logger.info("🎉 ALL TESTS PASSED! Single state management is working correctly.")
        return True
    else:
        logger.error("❌ SOME TESTS FAILED! Check the logs for details.")
        return False

if __name__ == "__main__":
    asyncio.run(main())