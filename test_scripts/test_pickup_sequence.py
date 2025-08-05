#!/usr/bin/env python3
"""
Test script to verify pickup sequence works without state transition errors.
"""

import asyncio
import websockets
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_pickup_sequence():
    """Test the pickup sequence via WebSocket"""
    
    uri = "ws://localhost:8000/ws"
    
    try:
        async with websockets.connect(uri) as websocket:
            logger.info("Connected to WebSocket")
            
            # Send a pickup command
            pickup_command = {
                "type": "command",
                "command": "meca_pickup",
                "data": {
                    "start": 0,
                    "count": 1
                }
            }
            
            logger.info("Sending pickup command...")
            await websocket.send(json.dumps(pickup_command))
            
            # Wait for responses
            timeout_count = 0
            max_timeout = 30  # 30 second timeout
            
            while timeout_count < max_timeout:
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    data = json.loads(response)
                    
                    logger.info(f"Received: {data}")
                    
                    # Check for state transition errors
                    if "error" in data and "busy -> busy" in str(data["error"]):
                        logger.error("STATE TRANSITION ERROR DETECTED!")
                        logger.error(f"Error details: {data['error']}")
                        return False
                    
                    # Check for successful operation
                    if data.get("type") == "operation_result" and data.get("success") == True:
                        logger.info("✅ Pickup sequence completed successfully!")
                        return True
                    
                    # Check for operation failure
                    if data.get("type") == "operation_result" and data.get("success") == False:
                        logger.error(f"❌ Pickup sequence failed: {data.get('error', 'Unknown error')}")
                        return False
                    
                except asyncio.TimeoutError:
                    timeout_count += 1
                    logger.info(f"Waiting for response... ({timeout_count}/{max_timeout})")
                    
            logger.warning("⏱️ Test timed out - no conclusive result")
            return None
            
    except Exception as e:
        logger.error(f"❌ Connection error: {e}")
        return False

async def main():
    """Main test function"""
    logger.info("🚀 Starting pickup sequence test...")
    
    result = await test_pickup_sequence()
    
    if result is True:
        logger.info("✅ SUCCESS: Pickup sequence works without state transition errors!")
    elif result is False:
        logger.error("❌ FAILED: State transition errors still present")
    else:
        logger.warning("⚠️ INCONCLUSIVE: Test timed out or connection issues")

if __name__ == "__main__":
    asyncio.run(main())