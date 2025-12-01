import asyncio
import json
import logging
import sys
import aiohttp
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("batch_verifier")

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

async def verify_sequence_config():
    """Verify GET /sequence-config endpoint"""
    logger.info("1. Verifying Sequence Config...")
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{BASE_URL}/api/meca/sequence-config") as response:
            if response.status != 200:
                logger.error(f"Failed to get config: {response.status}")
                return False
            
            data = await response.json()
            config = data.get("data", {})
            
            total_wafers = config.get("total_wafers")
            wafers_per_batch = config.get("wafers_per_batch")
            
            logger.info(f"Config received: total_wafers={total_wafers}, wafers_per_batch={wafers_per_batch}")
            
            if total_wafers != 55:
                logger.error(f"Expected 55 wafers, got {total_wafers}")
                return False
                
            return True

async def simulate_single_batch(ws: aiohttp.ClientWebSocketResponse, start: int, count: int, batch_number: int) -> bool:
    """Simulate a single batch pickup and drop."""
    logger.info(f"Testing Batch {batch_number} Pickup (Wafers {start+1}-{start+count})...")
    pickup_cmd = {
        "type": "command",
        "command_type": "meca_pickup",
        "data": {
            "start": start,
            "count": count,
            "is_last_batch": False
        }
    }
    await ws.send_json(pickup_cmd)
    
    pickup_completed = False
    drop_completed = False

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                logger.info(f"Received message: {data}")
                
                # Check for command response
                if data.get("type") == "command_response":
                    if data.get("status") == "error":
                        logger.error(f"Command failed: {data}")
                        return False
                    logger.info(f"Command accepted: {data.get('command_id')}")
                    
                # Check for batch completion
                if data.get("type") == "operation_update" and data.get("data", {}).get("event") == "batch_completion":
                    event_data = data["data"]
                    op_type = event_data.get("operation_type")
                    
                    logger.info(f"Batch completion received: {op_type} for batch {batch_number}")
                    logger.info(f"Result: {event_data}")
                    
                    if op_type == "pickup":
                        pickup_completed = True
                        logger.info(f"Batch {batch_number} Pickup complete. Testing Drop...")
                        # Send Drop Command
                        drop_cmd = {
                            "type": "command",
                            "command_type": "meca_drop",
                            "data": {
                                "start": start,
                                "count": count,
                                "is_last_batch": False
                            }
                        }
                        await ws.send_json(drop_cmd)
                        
                    elif op_type == "drop":
                        drop_completed = True
                        logger.info(f"Batch {batch_number} Drop complete. Batch {batch_number} successful.")
                        return True
                        
    except asyncio.TimeoutError:
        logger.error(f"Timeout waiting for batch {batch_number} completion")
        return False
    
    return False

async def simulate_batch_workflow():
    """Simulate the full batch workflow via WebSocket"""
    logger.info("2. Simulating Batch Workflow...")
    
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(WS_URL) as ws:
            logger.info("Connected to WebSocket")
            
            # Subscribe to updates
            await ws.send_json({"type": "subscribe", "channel": "operations"})
            
            # Test Batch 1
            if not await simulate_single_batch(ws, start=0, count=5, batch_number=1):
                logger.error("Batch 1 simulation failed.")
                return False
            
            # Test Batch 2
            if not await simulate_single_batch(ws, start=5, count=5, batch_number=2):
                logger.error("Batch 2 simulation failed.")
                return False
            
            logger.info("All batches simulated successfully.")
            return True
                
    return False

async def test_retry_logic():
    """Test retry logic parameters"""
    logger.info("3. Testing Retry Logic Parameter Passing...")
    
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(WS_URL) as ws:
            retry_cmd = {
                "type": "command",
                "command_type": "meca_pickup",
                "data": {
                    "start": 0,
                    "count": 5,
                    "retry_wafers": [2, 4]
                }
            }
            await ws.send_json(retry_cmd)
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if data.get("type") == "command_response":
                        logger.info(f"Retry command response: {data}")
                        return data.get("status") == "success"
                        
    return False

async def main():
    logger.info("Starting Multi-Batch Verification")
    
    # 1. Config Check
    if not await verify_sequence_config():
        logger.error("Config verification failed")
        return
        
    # 2. Workflow Simulation
    if not await simulate_batch_workflow():
        logger.error("Batch workflow simulation failed")
        return

    # 3. Retry Logic
    if not await test_retry_logic():
        logger.error("Retry logic test failed")
        return
        
    logger.info("✅ ALL VERIFICATION TESTS PASSED")

if __name__ == "__main__":
    asyncio.run(main())
