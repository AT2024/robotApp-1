import asyncio
from mecademicpy.robot import Robot
from ..config.meca_config import meca_config
import time

async def test_connection():
    robot = Robot()
    print(f"Starting connection test to robot at {meca_config['ip']}")
    
    try:
        # First attempt to disconnect any existing connections
        try:
            print("Attempting to clear any existing connections...")
            robot.Disconnect()
            await asyncio.sleep(2)  # Give time for disconnect to complete
        except:
            print("Initial disconnect attempt completed (errors ignored)")
        
        # Now attempt the connection with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"\nConnection attempt {attempt + 1} of {max_retries}")
                result = await asyncio.to_thread(
                    lambda: robot.Connect(meca_config['ip'], offline_mode=False)
                )
                
                # Check connection status
                is_connected = await asyncio.to_thread(robot.IsConnected)
                if is_connected:
                    print("Successfully connected to robot!")
                    
                    # Get additional status information
                    status = await asyncio.to_thread(robot.GetStatusRobot)
                    print(f"Robot status: {status}")
                    
                    is_homed = await asyncio.to_thread(robot.IsHomed)
                    print(f"Is homed: {is_homed}")
                    
                    is_activated = await asyncio.to_thread(robot.IsActivated)
                    print(f"Is activated: {is_activated}")
                    
                    break  # Successfully connected, exit retry loop
                    
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt < max_retries - 1:
                    print("Waiting before retry...")
                    await asyncio.sleep(5)  # Wait between attempts
                else:
                    print("All connection attempts failed")
                    raise
                    
    except Exception as e:
        print(f"Error during connection test: {str(e)}")
        
    finally:
        # Always try to cleanup
        try:
            if await asyncio.to_thread(robot.IsConnected):
                print("\nDisconnecting from robot...")
                await asyncio.to_thread(robot.Disconnect)
                print("Disconnection successful")
        except Exception as e:
            print(f"Error during disconnect: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_connection())