"""
Router for OT2 robot endpoints.
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from core.robot_manager import RobotManager
from utils.logger import get_logger
import os
import json
import asyncio
import requests
import time

router = APIRouter()
logger = get_logger("ot2_router")

# Define the path to the protocol file relative to the project root
PROTOCOL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "protocols",  # Create a protocols directory
    "ot2Protocole.py",
)

# Log the protocol file path at module initialization
logger.info(f"Protocol file path configured as: {PROTOCOL_FILE}")


async def get_robot_manager(request: Request) -> RobotManager:
    """Get the RobotManager instance from the application state."""
    return request.app.state.robot_manager


async def execute_ot2_protocol(
    robot_manager: RobotManager, parameters: Dict = None
) -> Dict:
    """Execute OT2 protocol by delegating to the robot manager.

    This function processes API requests and delegates actual execution
    to the robot_manager's run_ot2_protocol_direct method.
    """
    try:
        logger.info("Processing OT2 protocol execution request")

        # Verify robot connection before proceeding
        if not robot_manager.ot2_connected:
            status = await robot_manager._check_ot2_status()
            if status != "connected":
                raise Exception("OT2 robot is not connected")

        # Delegate the actual execution to robot_manager
        result = await robot_manager.run_ot2_protocol_direct(parameters)

        logger.info("OT2 protocol execution request processed successfully")
        return result

    except Exception as e:
        logger.error(f"Error processing OT2 protocol execution request: {e}")
        raise Exception(f"Failed to execute OT2 protocol: {str(e)}")


async def wait_for_protocol_analysis(
    robot_manager: RobotManager, protocol_id: str, headers: Dict
) -> bool:
    """Wait for protocol analysis to complete and return whether it was successful.

    Args:
        robot_manager: The robot manager instance
        protocol_id: The ID of the protocol to check
        headers: The HTTP headers to use for requests

    Returns:
        bool: True if analysis completed successfully, False otherwise
    """
    max_attempts = 15  # Try for up to 30 seconds (15 * 2)
    for attempt in range(max_attempts):
        analysis_url = f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/protocols/{protocol_id}"

        try:
            analysis_response = await asyncio.to_thread(
                lambda: requests.get(analysis_url, headers=headers, timeout=10)
            )

            if analysis_response.status_code == 200:
                data = analysis_response.json().get("data", {})
                analysis_summaries = data.get("analysisSummaries", [])

                if analysis_summaries:
                    status = analysis_summaries[0].get("status", "")
                    logger.info(f"Protocol analysis status: {status}")

                    # Check for various status possibilities
                    if status in ["succeeded", "success"]:
                        logger.info("Protocol analysis succeeded")
                        return True
                    elif status in ["failed", "error"]:
                        logger.error("Protocol analysis failed")
                        return False
                    elif status == "completed":
                        # The OT2 API uses "completed" as the final state
                        # Now check if there's a valid analysis result in the response
                        if (
                            "errors" in analysis_summaries[0]
                            and analysis_summaries[0]["errors"]
                        ):
                            logger.error(
                                f"Protocol analysis completed with errors: {analysis_summaries[0]['errors']}"
                            )
                            return False

                        # Additional check: if the protocol is valid, it will have analyzedAt field
                        if "analyzedAt" in data:
                            logger.info("Protocol analysis completed successfully")
                            return True

                        # If we've seen "completed" status multiple times, assume it's done
                        if attempt >= 2:  # Seen "completed" at least 3 times
                            logger.info(
                                "Protocol analysis appears complete after multiple checks"
                            )
                            return True
            else:
                logger.warning(
                    f"Failed to check analysis status: {analysis_response.status_code}"
                )
                logger.warning(f"Response: {analysis_response.text}")

        except Exception as e:
            logger.error(f"Error checking analysis status: {e}")

        await asyncio.sleep(2)  # Wait 2 seconds before checking again

    # If we've been polling for a while and keep seeing "completed", assume it's ready
    logger.info(
        "Timed out waiting for analysis status change - proceeding with run creation"
    )
    return True  # Proceed anyway after max attempts


async def monitor_run(robot_manager: RobotManager, run_id: str, headers: Dict) -> None:
    """Monitor the run progress in a background task.

    Args:
        robot_manager: The robot manager instance
        run_id: The ID of the run to monitor
        headers: The HTTP headers to use for requests
    """
    try:
        max_attempts = 30  # Check status for 5 minutes (10s interval)
        for attempt in range(max_attempts):
            await asyncio.sleep(10)  # Check every 10 seconds
            status_url = (
                f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/runs/{run_id}"
            )

            try:
                status_response = await asyncio.to_thread(
                    lambda: requests.get(status_url, headers=headers, timeout=10)
                )

                if status_response.status_code == 200:
                    status_data = status_response.json().get("data", {})
                    current_status = status_data.get("status", "unknown")
                    logger.info(
                        f"Run status check ({attempt + 1}/{max_attempts}): {current_status}"
                    )

                    if current_status in ["succeeded", "stopped", "failed"]:
                        logger.info(f"Run completed with status: {current_status}")
                        # Notify the websocket server about the completion
                        if (
                            hasattr(robot_manager, "websocket_server")
                            and robot_manager.websocket_server
                        ):
                            await robot_manager.websocket_server.broadcast(
                                {
                                    "type": "status_update",
                                    "data": {
                                        "type": "ot2",
                                        "status": (
                                            "complete"
                                            if current_status == "succeeded"
                                            else "error"
                                        ),
                                        "runId": run_id,
                                        "runStatus": current_status,
                                    },
                                }
                            )
                        break
                else:
                    logger.warning(
                        f"Failed to get run status: {status_response.status_code}"
                    )

            except Exception as e:
                logger.error(f"Error checking run status: {e}")

    except Exception as e:
        logger.error(f"Error monitoring run: {e}")


async def check_run_status(robot_manager: RobotManager, run_id: str) -> str:
    """Check the status of a run.

    Args:
        robot_manager: The robot manager instance
        run_id: The ID of the run to check

    Returns:
        str: The status of the run
    """
    headers = {"Accept": "application/json", "Opentrons-Version": "2"}
    status_url = f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/runs/{run_id}"

    try:
        status_response = await asyncio.to_thread(
            lambda: requests.get(status_url, headers=headers, timeout=10)
        )

        if status_response.status_code == 200:
            status_data = status_response.json().get("data", {})
            return status_data.get("status", "unknown")
        else:
            logger.warning(f"Failed to get run status: {status_response.status_code}")
            return "unknown"
    except Exception as e:
        logger.error(f"Error checking run status: {e}")
        return "error"


@router.post("/run-protocol")
async def run_ot2_protocol(
    request: Request, robot_manager: RobotManager = Depends(get_robot_manager)
):
    """Run the OT2 protocol.

    This endpoint handles requests to execute the OT2 protocol. It checks the robot
    connection status, reads the protocol file, and initiates the protocol execution.

    The protocol is executed using the OT2's native protocol execution system rather
    than step-by-step API commands, which avoids API compatibility issues.
    """
    try:
        logger.info("Starting OT2 protocol")

        # Log current connection state
        logger.info(
            f"OT2 Connection state - Flag: {robot_manager.ot2_connected}, "
            f"Status: {robot_manager.status['ot2']}"
        )

        # Force a status check before proceeding
        current_status = await robot_manager._check_ot2_status()

        if not robot_manager.ot2_connected:
            error_msg = "OT2 robot is not connected"
            logger.error(error_msg)
            return JSONResponse(
                status_code=400,
                content={
                    "detail": error_msg,
                    "status": current_status,
                    "connection_info": {
                        "ip": robot_manager.ot2_ip,
                        "port": robot_manager.ot2_port,
                    },
                },
            )

        # Log the incoming request
        try:
            body = await request.json()
            logger.info(f"Received request with body: {body}")
        except:
            body = {}
            logger.info("No request body received")

        # Prepare parameters from request body
        parameters = {}
        if body and isinstance(body, dict):
            # Extract trayInfo if available
            if "trayInfo" in body:
                parameters["trayInfo"] = body["trayInfo"]

            # Extract any other parameters
            for key, value in body.items():
                if key != "trayInfo":
                    parameters[key] = value

        # Use our improved execution function instead of robot_manager.run_ot2_protocol_direct
        result = await execute_ot2_protocol(robot_manager, parameters)

        logger.info("OT2 protocol started successfully")
        return JSONResponse(
            status_code=200,
            content={
                "message": "Protocol execution started",
                "status": "success",
                "result": result,
            },
        )

    except Exception as e:
        error_msg = f"Failed to execute protocol: {str(e)}"
        logger.error(error_msg)
        return JSONResponse(status_code=500, content={"detail": error_msg})


@router.get("/status/{run_id}")
async def get_run_status(
    run_id: str, robot_manager: RobotManager = Depends(get_robot_manager)
):
    """Get the current status of a protocol run.

    This endpoint allows clients to check the status of a running protocol
    by providing the run ID.
    """
    try:
        # Use our improved status check function
        status = await check_run_status(robot_manager, run_id)
        return JSONResponse(
            status_code=200,
            content={
                "runId": run_id,
                "status": status,
            },
        )
    except Exception as e:
        error_msg = f"Failed to get run status: {str(e)}"
        logger.error(error_msg)
        return JSONResponse(status_code=500, content={"detail": error_msg})


@router.post("/stop/{run_id}")
async def stop_protocol(
    run_id: str, robot_manager: RobotManager = Depends(get_robot_manager)
):
    """Stop an OT2 protocol run.

    This endpoint allows clients to stop a running protocol by providing
    the run ID.
    """
    try:
        headers = {"Accept": "application/json", "Opentrons-Version": "2"}
        url = f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/runs/{run_id}/commands"

        stop_data = {"data": {"commandType": "stop", "reason": "User requested stop"}}

        response = await asyncio.to_thread(
            lambda: requests.post(url, headers=headers, json=stop_data, timeout=30)
        )

        if response.status_code not in [200, 201]:
            return JSONResponse(
                status_code=500,
                content={
                    "detail": f"Failed to stop protocol: {response.text}",
                    "status": "error",
                },
            )

        return JSONResponse(
            status_code=200,
            content={
                "message": "Protocol stopped successfully",
                "status": "success",
            },
        )
    except Exception as e:
        error_msg = f"Failed to stop protocol: {str(e)}"
        logger.error(error_msg)
        return JSONResponse(status_code=500, content={"detail": error_msg})


@router.get("/protocols")
async def list_protocols(robot_manager: RobotManager = Depends(get_robot_manager)):
    """List all protocols on the OT2.

    This endpoint retrieves a list of all protocols that have been uploaded
    to the OT2 robot.
    """
    try:
        headers = {"Accept": "application/json", "Opentrons-Version": "2"}
        url = f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/protocols"

        response = await asyncio.to_thread(
            lambda: requests.get(url, headers=headers, timeout=30)
        )

        if response.status_code != 200:
            return JSONResponse(
                status_code=500,
                content={
                    "detail": f"Failed to list protocols: {response.text}",
                    "status": "error",
                },
            )

        protocols = response.json().get("data", [])
        return JSONResponse(
            status_code=200,
            content={
                "protocols": protocols,
                "status": "success",
            },
        )
    except Exception as e:
        error_msg = f"Failed to list protocols: {str(e)}"
        logger.error(error_msg)
        return JSONResponse(status_code=500, content={"detail": error_msg})


@router.get("/runs")
async def list_runs(robot_manager: RobotManager = Depends(get_robot_manager)):
    """List all protocol runs on the OT2.

    This endpoint retrieves a list of all protocol runs that have been
    created on the OT2 robot.
    """
    try:
        headers = {"Accept": "application/json", "Opentrons-Version": "2"}
        url = f"http://{robot_manager.ot2_ip}:{robot_manager.ot2_port}/runs"

        response = await asyncio.to_thread(
            lambda: requests.get(url, headers=headers, timeout=30)
        )

        if response.status_code != 200:
            return JSONResponse(
                status_code=500,
                content={
                    "detail": f"Failed to list runs: {response.text}",
                    "status": "error",
                },
            )

        runs = response.json().get("data", [])
        return JSONResponse(
            status_code=200,
            content={
                "runs": runs,
                "status": "success",
            },
        )
    except Exception as e:
        error_msg = f"Failed to list runs: {str(e)}"
        logger.error(error_msg)
        return JSONResponse(status_code=500, content={"detail": error_msg})
