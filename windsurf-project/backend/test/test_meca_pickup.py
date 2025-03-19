import sys
import asyncio
from core.robot_manager import RobotManager
from routers.meca import create_pickup


async def test_meca_pickup():
    robot_manager = RobotManager()
    try:
        await create_pickup(robot_manager)
        print("Meca robot pickup sequence test: PASSED")
    except Exception as e:
        print(f"Meca robot pickup sequence test: FAILED with error: {e}")
    finally:
        await robot_manager.close_meca_connection()


if __name__ == "__main__":
    asyncio.run(test_meca_pickup())
