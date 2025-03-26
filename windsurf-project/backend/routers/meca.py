import copy
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from utils.logger import get_logger
from core.robot_manager import RobotManager
from config.meca_config import (
    FIRST_BAKING_TRAY,
    FORCE,
    ACC,
    ALIGN_SPEED,
    WAFER_SPEED,
    EMPTY_SPEED,
    CLOSE_WIDTH,
    FIRST_WAFER,
    GAP_WAFERS,
    GEN_DROP,
    SAFE_POINT,
    SPEED,
    T_PHOTOGATE,
    C_PHOTOGATE,
    CAROUSEL,
    CAROUSEL_SAFEPOINT,
    ENTRY_SPEED,
    total_wafers,
    wafers_per_cycle,
    wafers_per_carousel,
)
from pydantic import BaseModel
from object import baking_trey, Carousel_object, wafer_object

router = APIRouter()
logger = get_logger("meca_router")


# -----------------------------------------------------------------------------
# Helper functions to remove duplication
# -----------------------------------------------------------------------------


async def ensure_robot_status(robot):
    """Check the robot status and reset errors if needed."""
    status = await asyncio.to_thread(robot.GetStatusRobot)
    if status is None:
        logger.error("Unable to get robot status")
        raise Exception("Unable to get robot status")
    if status.error_status:
        logger.info("Robot in error state, attempting reset...")
        await asyncio.to_thread(robot.ResetError)
        status = await asyncio.to_thread(robot.GetStatusRobot)
        if status.error_status:
            raise Exception("Unable to clear robot error state")
    return status


async def ensure_robot_ready(robot):
    """
    Ensures the robot is in a ready state by checking its status and,
    if needed, activating and homing it.
    """
    status = await ensure_robot_status(robot)
    if not status.activation_state:
        logger.info("Robot needs activation")
        await asyncio.to_thread(robot.ActivateRobot)
    if not status.homing_state:
        logger.info("Robot needs homing")
        await asyncio.to_thread(robot.Home)
        await asyncio.to_thread(robot.WaitHomed)
    return


async def attempt_robot_recovery(robot):
    """Try to recover the robot by resetting its error state if connected."""
    try:
        if await asyncio.to_thread(robot.IsConnected):
            status = await asyncio.to_thread(robot.GetStatusRobot)
            if status and status.error_status:
                await asyncio.to_thread(robot.ResetError)
    except Exception as e:
        logger.error(f"Error during recovery attempt: {e}")


async def ensure_meca_connected(robot_manager):
    """Ensure that the Mecademic robot is connected."""
    if not robot_manager.meca_connected:
        logger.info("Robot disconnected, attempting to reconnect...")
        await robot_manager._initialize_meca()


async def move_and_delay(robot, move_func, position, delay_time=0):
    """
    Helper to execute a move command (such as MovePose or MoveGripper)
    and then optionally delay.
    """
    await asyncio.to_thread(move_func, *position)
    if delay_time > 0:
        await asyncio.to_thread(robot.Delay, delay_time)


# -----------------------------------------------------------------------------
# Data Models and Dependency
# -----------------------------------------------------------------------------


class CheckRequest(BaseModel):
    carouselNumber: str
    treyNumber: str


class DismantleRequest(BaseModel):
    start: int
    count: int = 5  # default wafer count


def get_robot_manager(request: Request) -> RobotManager:
    return request.app.state.robot_manager


# -----------------------------------------------------------------------------
# Basic Movement Helpers
# -----------------------------------------------------------------------------


async def move_robot(
    robot, position, velocity=None, acceleration=None, message="Moving"
):
    """Move the robot joints with optional velocity and acceleration settings."""
    try:
        logger.info(f"{message}: {position}")
        if velocity is not None and acceleration is not None:
            await asyncio.to_thread(
                robot.MoveJoints,
                position[0],
                position[1],
                position[2],
                position[3],
                position[4],
                position[5],
                velocity,
                acceleration,
            )
        else:
            await asyncio.to_thread(
                robot.MoveJoints,
                position[0],
                position[1],
                position[2],
                position[3],
                position[4],
                position[5],
            )
        await asyncio.to_thread(robot.WaitIdle)
    except Exception as e:
        logger.error(f"Movement failed: {e}")
        raise


async def return_robot_to_home(robot, velocity=None):
    """Return the robot to the home position (all joints set to 0)."""
    try:
        logger.info("Returning robot to home position")
        if velocity is not None:
            await asyncio.to_thread(robot.SetJointVel, velocity)
        await asyncio.to_thread(robot.MoveJoints, 0, 0, 0, 0, 0, 0)
        await asyncio.to_thread(robot.WaitIdle)
        logger.info("Robot successfully returned to home position")
        return True
    except Exception as e:
        logger.error(f"Error returning robot to home position: {e}")
        raise


# -----------------------------------------------------------------------------
# Robot Sequence Functions
# -----------------------------------------------------------------------------


async def pickup_wafer_sequence(
    robot_manager: RobotManager, start: int = 0, end: int = 5
):
    """Execute the wafer pickup sequence."""
    try:
        logger.info(f"Starting wafer pickup sequence from {start+1} to {end}")
        robot = robot_manager.meca_robot
        await ensure_robot_ready(robot)

        for i in range(start, end):
            logger.info(f"Processing wafer {i+1} of {end}")

            # Set initial parameters once
            if i == start:
                logger.info("Setting initial parameters")
                await asyncio.to_thread(robot.SetGripperForce, FORCE)
                await asyncio.to_thread(robot.SetJointAcc, ACC)
                await asyncio.to_thread(robot.SetTorqueLimits, 40, 40, 40, 40, 40, 40)
                await asyncio.to_thread(robot.SetTorqueLimitsCfg, 2, 1)
                await asyncio.to_thread(robot.SetBlending, 0)

            await asyncio.to_thread(robot.SetJointVel, ALIGN_SPEED)
            await asyncio.to_thread(robot.SetConf, 1, 1, 1)
            await asyncio.to_thread(robot.GripperOpen)
            await asyncio.to_thread(robot.Delay, 1)

            # Calculate pickup positions
            pickup_high = copy.deepcopy(FIRST_WAFER)
            pickup_high[1] += GAP_WAFERS * i + 0.2
            pickup_high[2] += 11.9286

            pickup_position = copy.deepcopy(FIRST_WAFER)
            pickup_position[1] += GAP_WAFERS * i

            logger.info(f"Moving to position for wafer {i+1}")
            await move_and_delay(robot, robot.MovePose, pickup_high)
            await move_and_delay(robot, robot.MovePose, pickup_position, 1)

            logger.info("Closing gripper to pick up wafer")
            await move_and_delay(robot, robot.MoveGripper, [CLOSE_WIDTH], 1)

            # Calculate intermediate positions
            intermediate_pos1 = copy.deepcopy(FIRST_WAFER)
            intermediate_pos1[1] += GAP_WAFERS * i - 0.2
            intermediate_pos1[2] += 2.8

            intermediate_pos2 = copy.deepcopy(intermediate_pos1)
            intermediate_pos2[1] -= 0.8
            intermediate_pos2[2] += 2.7

            intermediate_pos3 = copy.deepcopy(intermediate_pos2)
            intermediate_pos3[1] -= 11.5595
            intermediate_pos3[2] += 38.4

            logger.info("Moving up with wafer")
            await asyncio.to_thread(robot.SetJointVel, WAFER_SPEED)
            await asyncio.to_thread(robot.MovePose, *intermediate_pos1)
            await asyncio.to_thread(robot.SetBlending, 100)
            await asyncio.to_thread(robot.MovePose, *intermediate_pos2)
            await asyncio.to_thread(robot.MoveLin, *intermediate_pos3)
            await asyncio.to_thread(robot.SetBlending, 0)

            logger.info("Moving to safe point")
            await asyncio.to_thread(robot.MovePose, *SAFE_POINT)

            drop_index = 4 - (i % 5)
            placement_high = copy.deepcopy(GEN_DROP[drop_index])
            placement_high[2] += 40.4987

            placement_position = copy.deepcopy(GEN_DROP[drop_index])
            placement_exit = copy.deepcopy(GEN_DROP[drop_index])
            placement_exit[2] += 56.4987

            logger.info(f"Moving to drop position {drop_index+1}")
            await asyncio.to_thread(robot.SetJointVel, ALIGN_SPEED)
            await asyncio.to_thread(robot.MovePose, *placement_high)
            await asyncio.to_thread(robot.MovePose, *placement_position)
            await asyncio.to_thread(robot.Delay, 1)

            logger.info("Opening gripper to release wafer")
            await asyncio.to_thread(robot.GripperOpen)
            await asyncio.to_thread(robot.Delay, 1)

            logger.info("Moving up from placement position")
            await asyncio.to_thread(robot.MovePose, *placement_exit)

            logger.info("Returning to safe point")
            await asyncio.to_thread(robot.SetJointVel, EMPTY_SPEED)
            await asyncio.to_thread(robot.MovePose, *SAFE_POINT)

            if drop_index == 0:
                await asyncio.to_thread(robot.Delay, 2)

        await ensure_robot_status(robot)
        logger.info("Successfully completed wafer pickup sequence")
        return {
            "status": "success",
            "message": f"Pickup sequence completed for wafers {start+1} to {end}",
        }
    except Exception as e:
        logger.error(f"Error in pickup sequence: {e}")
        raise


async def drop_wafer_sequence(
    robot_manager: RobotManager, start: int = 0, end: int = 5
):
    """Execute the wafer drop sequence from spreader to baking tray."""
    try:
        logger.info(f"Starting wafer drop sequence from {start+1} to {end}")
        robot = robot_manager.meca_robot
        await ensure_robot_status(robot)

        for i in range(start, end):
            logger.info(f"Processing wafer {i+1} drop from spreader to baking tray")
            await asyncio.to_thread(robot.SetJointVel, ALIGN_SPEED)
            spread_index = 4 - (i % 5)

            above_spreader = copy.deepcopy(GEN_DROP[spread_index])
            above_spreader[2] += 36.6
            await move_and_delay(robot, robot.MovePose, above_spreader, 1)

            await move_and_delay(robot, robot.MovePose, GEN_DROP[spread_index], 1)
            await move_and_delay(robot, robot.MoveGripper, [CLOSE_WIDTH], 1)

            above_spreader_exit = copy.deepcopy(GEN_DROP[spread_index])
            above_spreader_exit[2] += 25.4987
            await asyncio.to_thread(robot.MovePose, *above_spreader_exit)

            await asyncio.to_thread(robot.SetJointVel, SPEED)
            await asyncio.to_thread(robot.MovePose, *SAFE_POINT)

            baking_align1 = copy.deepcopy(FIRST_BAKING_TRAY)
            baking_align1[0] += GAP_WAFERS * i - 9.7
            baking_align1[1] += 0.3
            baking_align1[2] += 32.058
            await asyncio.to_thread(robot.MovePose, *baking_align1)

            await asyncio.to_thread(robot.SetJointVel, ALIGN_SPEED)
            await asyncio.to_thread(robot.SetBlending, 100)

            baking_align2 = copy.deepcopy(FIRST_BAKING_TRAY)
            baking_align2[0] += GAP_WAFERS * i - 7.7
            baking_align2[1] += 0.3
            baking_align2[2] += 22
            await asyncio.to_thread(robot.MovePose, *baking_align2)

            baking_align3 = copy.deepcopy(FIRST_BAKING_TRAY)
            baking_align3[0] += GAP_WAFERS * i - 2.1
            baking_align3[1] += 0.3
            baking_align3[2] += 6
            await asyncio.to_thread(robot.MovePose, *baking_align3)

            baking_align4 = copy.deepcopy(FIRST_BAKING_TRAY)
            baking_align4[0] += GAP_WAFERS * i - 0.7
            baking_align4[1] += 0.3
            baking_align4[2] += 2.8
            await asyncio.to_thread(robot.MovePose, *baking_align4)
            await asyncio.to_thread(robot.Delay, 1)

            await move_and_delay(robot, robot.GripperOpen, [], 0.5)

            baking_up = copy.deepcopy(FIRST_BAKING_TRAY)
            baking_up[0] += GAP_WAFERS * i
            baking_up[2] += 29.458
            await asyncio.to_thread(robot.MovePose, *baking_up)

            await asyncio.to_thread(robot.SetJointVel, SPEED)
            await asyncio.to_thread(robot.SetBlending, 0)
            await asyncio.to_thread(robot.MovePose, *SAFE_POINT)

        await ensure_robot_status(robot)
        logger.info("Successfully completed wafer drop sequence")
        return {
            "status": "success",
            "message": f"Drop sequence completed for wafers {start+1} to {end}",
        }
    except Exception as e:
        logger.error(f"Error in drop sequence: {e}")
        raise


async def carousel_wafer_sequence(
    robot_manager: RobotManager, start: int = 0, end: int = 11
):
    """Execute the sequence to move wafers from baking tray to carousel."""
    try:
        logger.info(f"Starting carousel sequence for wafers {start+1} to {end}")
        robot = robot_manager.meca_robot
        await ensure_robot_status(robot)

        # Set configuration at start
        await asyncio.to_thread(robot.SetConf, 1, 1, -1)
        await asyncio.to_thread(robot.Delay, 3)

        for i in range(start, end):
            logger.info(f"Processing wafer {i+1} from baking tray to carousel")
            
            # Add delay for each new carousel
            if (i + 1) % 11 == 1 and i >= 1:
                await asyncio.to_thread(robot.Delay, 5)
                
            # Open gripper and prepare for pickup
            await asyncio.to_thread(robot.GripperOpen)
            await asyncio.to_thread(robot.Delay, 1)
            await asyncio.to_thread(robot.SetJointVel, SPEED)

            # Move to above baking tray position
            above_baking = copy.deepcopy(FIRST_BAKING_TRAY)
            above_baking[0] += GAP_WAFERS * i
            above_baking[2] += 27.558
            await asyncio.to_thread(robot.MovePose, *above_baking)

            # Move to baking tray position and grab wafer
            await asyncio.to_thread(robot.SetJointVel, ALIGN_SPEED)
            await asyncio.to_thread(robot.SetBlending, 0)
            baking_tray = copy.deepcopy(FIRST_BAKING_TRAY)
            baking_tray[0] += GAP_WAFERS * i
            await asyncio.to_thread(robot.MovePose, *baking_tray)
            await asyncio.to_thread(robot.Delay, 0.5)
            await asyncio.to_thread(robot.GripperClose)
            await asyncio.to_thread(robot.Delay, 0.5)

            # Start movement path to carousel
            await asyncio.to_thread(robot.SetBlending, 100)
            move1 = copy.deepcopy(FIRST_BAKING_TRAY)
            move1[0] += GAP_WAFERS * i - 0.7
            move1[2] += 2.8
            await asyncio.to_thread(robot.MovePose, *move1)

            await asyncio.to_thread(robot.SetJointVel, SPEED)
            move2 = copy.deepcopy(FIRST_BAKING_TRAY)
            move2[0] += GAP_WAFERS * i - 2.1
            move2[2] += 6
            await asyncio.to_thread(robot.MovePose, *move2)

            move3 = copy.deepcopy(FIRST_BAKING_TRAY)
            move3[0] += GAP_WAFERS * i - 7.7
            move3[2] += 22
            await asyncio.to_thread(robot.MovePose, *move3)

            move4 = copy.deepcopy(FIRST_BAKING_TRAY)
            move4[0] += GAP_WAFERS * i - 9.7
            move4[2] += 32.058
            await asyncio.to_thread(robot.MovePose, *move4)
            await asyncio.to_thread(robot.Delay, 0.5)

            # Through photogate
            await asyncio.to_thread(robot.SetBlending, 80)
            await asyncio.to_thread(robot.MovePose, *T_PHOTOGATE)
            await asyncio.to_thread(robot.MovePose, *C_PHOTOGATE)

            # Y Away positions
            move7 = copy.deepcopy(CAROUSEL)
            move7[1] += 31.0000
            move7[2] += 18.0000
            await asyncio.to_thread(robot.MovePose, *move7)
            
            await asyncio.to_thread(robot.SetBlending, 0)
            await asyncio.to_thread(robot.Delay, 1)
            await asyncio.to_thread(robot.SetJointVel, ENTRY_SPEED)
            
            move8 = copy.deepcopy(CAROUSEL)
            move8[1] += 2.0000
            move8[2] += 14.0000
            await asyncio.to_thread(robot.MovePose, *move8)

            # Above carousel positions - staged approach
            Above_Carousel1 = copy.deepcopy(CAROUSEL)
            Above_Carousel1[2] += 14.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel1)
            
            Above_Carousel2 = copy.deepcopy(CAROUSEL)
            Above_Carousel2[2] += 8.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel2)
            
            Above_Carousel3 = copy.deepcopy(CAROUSEL)
            Above_Carousel3[2] += 2.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel3)

            # Carousel position - release wafer
            await asyncio.to_thread(robot.MovePose, *CAROUSEL)
            await asyncio.to_thread(robot.Delay, 0.5)
            await asyncio.to_thread(robot.MoveGripper, 2.9)
            await asyncio.to_thread(robot.Delay, 0.5)
            
            # Exit carousel
            await asyncio.to_thread(robot.SetJointVel, EMPTY_SPEED)
            
            Above_Carousel4 = copy.deepcopy(CAROUSEL)
            Above_Carousel4[2] += 2.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel4)
            
            Above_Carousel5 = copy.deepcopy(CAROUSEL)
            Above_Carousel5[2] += 8.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel5)
            
            move10 = copy.deepcopy(CAROUSEL)
            move10[2] += 14.0000
            await asyncio.to_thread(robot.MovePose, *move10)
            
            move11 = copy.deepcopy(CAROUSEL)
            move11[1] += 2.0000
            move11[2] += 18.0000
            await asyncio.to_thread(robot.MovePose, *move11)
            
            move12 = copy.deepcopy(CAROUSEL)
            move12[1] += 31.0000
            move12[2] += 18.0000
            await asyncio.to_thread(robot.MovePose, *move12)

            # Return to safe point
            await asyncio.to_thread(robot.MovePose, *CAROUSEL_SAFEPOINT)
            await asyncio.to_thread(robot.SetBlending, 100)

        await ensure_robot_status(robot)
        logger.info("Successfully completed carousel placement sequence")
        return {
            "status": "success",
            "message": f"Moved wafers {start+1} to {end} from baking tray to carousel",
        }
    except Exception as e:
        logger.error(f"Error in carousel sequence: {e}")
        raise


async def empty_carousel_sequence(
    robot_manager: RobotManager, start: int = 0, end: int = 11
):
    """Execute the sequence to move wafers from carousel back to baking tray."""
    try:
        logger.info(f"Starting empty-carousel sequence for wafers {start+1} to {end}")
        robot = robot_manager.meca_robot
        await ensure_robot_status(robot)

        for i in range(start, end):
            logger.info(f"Processing wafer {i+1} from carousel to baking tray")
            
            # Add delay for each new carousel batch
            if (i + 1) % 11 == 1:
                await asyncio.to_thread(robot.Delay, 7.5)
            else:
                await asyncio.to_thread(robot.Delay, 1)

            # Open gripper and prepare to pick up wafer from carousel
            await asyncio.to_thread(robot.GripperOpen)
            await asyncio.to_thread(robot.Delay, 1)

            # First move to Y-away positions
            move12_rev = copy.deepcopy(CAROUSEL)
            move12_rev[1] += 31.0000
            move12_rev[2] += 18.0000
            await asyncio.to_thread(robot.MovePose, *move12_rev)
            
            move11_rev = copy.deepcopy(CAROUSEL)
            move11_rev[1] += 2.0000
            move11_rev[2] += 18.0000
            await asyncio.to_thread(robot.MovePose, *move11_rev)
            
            move10_rev = copy.deepcopy(CAROUSEL)
            move10_rev[2] += 14.0000
            await asyncio.to_thread(robot.MovePose, *move10_rev)
            
            # Prepare to pick up from carousel
            await asyncio.to_thread(robot.SetBlending, 0)
            await asyncio.to_thread(robot.SetJointVel, ENTRY_SPEED)
            await asyncio.to_thread(robot.MoveGripper, 3.7)
            await asyncio.to_thread(robot.Delay, 0.5)
            
            # Staged approach to carousel
            Above_Carousel5_Rev = copy.deepcopy(CAROUSEL)
            Above_Carousel5_Rev[2] += 8.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel5_Rev)
            
            Above_Carousel4_Rev = copy.deepcopy(CAROUSEL)
            Above_Carousel4_Rev[2] += 2.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel4_Rev)
            
            # Grab wafer from carousel
            await asyncio.to_thread(robot.MovePose, *CAROUSEL)
            await asyncio.to_thread(robot.Delay, 0.5)
            await asyncio.to_thread(robot.GripperClose)
            await asyncio.to_thread(robot.SetJointVel, ALIGN_SPEED)
            await asyncio.to_thread(robot.Delay, 0.5)
            
            # Staged exit from carousel
            Above_Carousel3_Rev = copy.deepcopy(CAROUSEL)
            Above_Carousel3_Rev[2] += 2.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel3_Rev)
            
            Above_Carousel2_Rev = copy.deepcopy(CAROUSEL)
            Above_Carousel2_Rev[2] += 8.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel2_Rev)
            
            Above_Carousel1_Rev = copy.deepcopy(CAROUSEL)
            Above_Carousel1_Rev[2] += 14.0000
            await asyncio.to_thread(robot.MovePose, *Above_Carousel1_Rev)
            
            # Move through Y-away positions
            move8_rev = copy.deepcopy(CAROUSEL)
            move8_rev[1] += 2.0000
            move8_rev[2] += 14.0000
            await asyncio.to_thread(robot.MovePose, *move8_rev)
            await asyncio.to_thread(robot.Delay, 0.5)
            await asyncio.to_thread(robot.SetBlending, 80)
            await asyncio.to_thread(robot.SetJointVel, SPEED)
            
            move7_rev = copy.deepcopy(CAROUSEL)
            move7_rev[1] += 31
            move7_rev[2] += 18.1000
            await asyncio.to_thread(robot.MovePose, *move7_rev)
            
            # Through photogate
            await asyncio.to_thread(robot.MovePose, *C_PHOTOGATE)
            await asyncio.to_thread(robot.MovePose, *T_PHOTOGATE)
            await asyncio.to_thread(robot.Delay, 0.5)
            
            # Approach baking tray
            move4_rev = copy.deepcopy(FIRST_BAKING_TRAY)
            move4_rev[0] += GAP_WAFERS * i - 9.7
            move4_rev[1] += 0.3
            move4_rev[2] += 32.058
            await asyncio.to_thread(robot.MovePose, *move4_rev)
            
            await asyncio.to_thread(robot.SetJointVel, ALIGN_SPEED)
            await asyncio.to_thread(robot.Delay, 0.5)
            await asyncio.to_thread(robot.SetBlending, 100)
            
            move3_rev = copy.deepcopy(FIRST_BAKING_TRAY)
            move3_rev[0] += GAP_WAFERS * i - 7.7
            move3_rev[1] += 0.3
            move3_rev[2] += 22
            await asyncio.to_thread(robot.MovePose, *move3_rev)
            
            move2_rev = copy.deepcopy(FIRST_BAKING_TRAY)
            move2_rev[0] += GAP_WAFERS * i - 2.1
            move2_rev[1] += 0.3
            move2_rev[2] += 6
            await asyncio.to_thread(robot.MovePose, *move2_rev)
            
            move1_rev = copy.deepcopy(FIRST_BAKING_TRAY)
            move1_rev[0] += GAP_WAFERS * i - 0.7
            move1_rev[1] += 0.3
            move1_rev[2] += 2.8
            await asyncio.to_thread(robot.MovePose, *move1_rev)
            await asyncio.to_thread(robot.Delay, 1)
            
            # Release wafer to baking tray
            await asyncio.to_thread(robot.GripperOpen)
            await asyncio.to_thread(robot.Delay, 0.5)
            
            above_baking_rev = copy.deepcopy(FIRST_BAKING_TRAY)
            above_baking_rev[0] += GAP_WAFERS * i
            above_baking_rev[2] += 22.058
            await asyncio.to_thread(robot.MovePose, *above_baking_rev)
            
            # Return to safe point
            await asyncio.to_thread(robot.SetJointVel, EMPTY_SPEED)
            await asyncio.to_thread(robot.Delay, 0.2)
            await asyncio.to_thread(robot.SetBlending, 100)
            await asyncio.to_thread(robot.MovePose, *CAROUSEL_SAFEPOINT)

        await ensure_robot_status(robot)
        logger.info("Successfully completed empty-carousel sequence")
        return {
            "status": "success",
            "message": f"Moved wafers {start+1} to {end} from carousel to baking tray",
        }
    except Exception as e:
        logger.error(f"Error in empty-carousel sequence: {e}")
        raise

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------


@router.post("/pickup")
async def create_pickup(
    data: dict = Body(default={}),
    robot_manager: RobotManager = Depends(get_robot_manager),
):
    try:
        await ensure_meca_connected(robot_manager)
        start = data.get("start", 0)
        count = data.get("count", 5)
        end = min(start + count, total_wafers)
        await pickup_wafer_sequence(robot_manager, start, end)
        if end >= total_wafers or data.get("is_last_batch", False):
            await return_robot_to_home(robot_manager.meca_robot, EMPTY_SPEED)
            logger.info("Completed pickup sequence, robot returned to home")
        return {
            "status": "success",
            "message": f"Pickup sequence completed for wafers {start+1} to {end}",
        }
    except Exception as e:
        logger.error(f"Error creating pickup sequence: {e}")
        await attempt_robot_recovery(robot_manager.meca_robot)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/drop")
async def create_drop(
    data: dict = Body(default={}),
    robot_manager: RobotManager = Depends(get_robot_manager),
):
    try:
        await ensure_meca_connected(robot_manager)
        start = data.get("start", 0)
        count = data.get("count", 5)
        end = min(start + count, total_wafers)
        await drop_wafer_sequence(robot_manager, start, end)
        if end >= total_wafers or data.get("is_last_batch", False):
            await return_robot_to_home(robot_manager.meca_robot, EMPTY_SPEED)
            logger.info("Completed drop sequence, robot returned to home")
        return {
            "status": "success",
            "message": f"Drop sequence completed for wafers {start+1} to {end}",
        }
    except Exception as e:
        logger.error(f"Error creating drop sequence: {e}")
        await attempt_robot_recovery(robot_manager.meca_robot)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/carousel")
async def create_carousel_sequence(
    data: dict = Body(default={}),
    robot_manager: RobotManager = Depends(get_robot_manager),
):
    try:
        await ensure_meca_connected(robot_manager)
        start = data.get("start", 0)
        count = data.get("count", 11)
        end = min(start + count, total_wafers)
        await carousel_wafer_sequence(robot_manager, start, end)
        return {
            "status": "success",
            "message": f"Carousel placement sequence completed for wafers {start+1} to {end}",
        }
    except Exception as e:
        logger.error(f"Error creating carousel sequence: {e}")
        await attempt_robot_recovery(robot_manager.meca_robot)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/empty-carousel")
async def create_empty_carousel_sequence(
    data: dict = Body(default={}),
    robot_manager: RobotManager = Depends(get_robot_manager),
):
    try:
        await ensure_meca_connected(robot_manager)
        start = data.get("start", 0)
        count = data.get("count", 11)
        end = min(start + count, total_wafers)
        await empty_carousel_sequence(robot_manager, start, end)
        return {
            "status": "success",
            "message": f"Empty-carousel sequence completed for wafers {start+1} to {end}",
        }
    except Exception as e:
        logger.error(f"Error creating empty-carousel sequence: {e}")
        await attempt_robot_recovery(robot_manager.meca_robot)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-batch")
async def process_wafer_batch(
    data: dict = Body(default={}),
    robot_manager: RobotManager = Depends(get_robot_manager),
):
    try:
        from config.meca_config import (
            total_wafers,
            wafers_per_cycle,
            wafers_per_carousel,
        )

        await ensure_meca_connected(robot_manager)
        total_wafers_param = data.get("total_wafers", total_wafers)
        wafers_per_cycle_param = data.get("wafers_per_cycle", wafers_per_cycle)
        wafers_per_carousel_param = data.get("wafers_per_carousel", wafers_per_carousel)

        for start in range(0, total_wafers_param, wafers_per_cycle_param):
            end = min(start + wafers_per_cycle_param, total_wafers_param)
            logger.info(f"Picking up wafers {start+1} to {end}")
            await pickup_wafer_sequence(robot_manager, start, end)
            logger.info(f"Dropping wafers {start+1} to {end}")
            await drop_wafer_sequence(robot_manager, start, end)

        for start in range(0, total_wafers_param, wafers_per_carousel_param):
            end = min(start + wafers_per_carousel_param, total_wafers_param)
            logger.info(f"Moving wafers {start+1} to {end} to carousel")
            await carousel_wafer_sequence(robot_manager, start, end)
            logger.info(f"Emptying carousel for wafers {start+1} to {end}")
            await empty_carousel_sequence(robot_manager, start, end)
            logger.info("Returning to home position")
            robot = robot_manager.meca_robot
            await asyncio.to_thread(robot.SetJointVel, EMPTY_SPEED)
            await asyncio.to_thread(robot.MoveJoints, 0, 0, 0, 0, 0, 0)
            await asyncio.to_thread(robot.WaitIdle)

        return {
            "status": "success",
            "message": f"Completed batch processing for all {total_wafers_param} wafers",
        }
    except Exception as e:
        logger.error(f"Error in batch processing: {e}")
        await attempt_robot_recovery(robot_manager.meca_robot)
        raise HTTPException(status_code=500, detail=str(e))
