import asyncio
import aiohttp
import json

async def trigger_drop():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("ws://localhost:8000/ws") as ws:
            drop_cmd = {
                "type": "command",
                "command_type": "meca_drop",
                "data": {
                    "start": 0,
                    "count": 5,
                    "is_last_batch": False
                }
            }
            await ws.send_json(drop_cmd)
            print("Sent drop command")
            # Wait a bit to ensure sent
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(trigger_drop())
