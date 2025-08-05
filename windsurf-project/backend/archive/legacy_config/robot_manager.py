# # robot_manager.py
# from mecademicpy.robot import Robot
# import requests
# import time
# import asyncio
# import logging
# import os
# from typing import Dict, Any, Optional, List
# from .meca_config import meca_config
# from .ot2_config import ot2_config
# from utils.logger import get_logger
# import json

# logger = get_logger("robot_manager")


# class RobotManager:
#     def __init__(self, websocket_server):
#         # Store configurations as instance attributes for easy access
#         self.meca_config = meca_config
#         self.ot2_config = ot2_config
#         self.websocket_server = websocket_server

#         # Initialize robot instances and connection parameters
#         self.meca_robot = Robot()
#         self.meca_ip = meca_config["ip"]
#         self.ot2_ip = ot2_config["ip"]
#         self.ot2_port = ot2_config["port"]

#         # Initialize connection states
#         self.meca_connected = False
#         self.arduino_connected = False
#         self.ot2_connected = False
#         self.monitoring = False

#         # Initialize the status tracking dictionary
#         self.status = {
#             "meca": "disconnected",
#             "arduino": "disconnected",
#             "ot2": "disconnected",
#             "backend": "disconnected",
#         }

#         # Initialize the previous status tracking dictionary
#         self.previous_status = {
#             "meca": "disconnected",
#             "arduino": "disconnected",
#             "ot2": "disconnected",
#             "backend": "disconnected",
#         }

#         # Initialize status tracking variables
#         self._status_callbacks = []
#         self.last_logged_status = None
#         self.log_interval = 300  # Log status every 5 minutes
#         self.last_log_time = time.time()

#         logger.info("Robot Manager initialized with configurations")
#         # logger.info(f"OT2 Config loaded: IP={self.ot2_ip}, Port={self.ot2_port}")

#     def get_status(self):
#         """
#         Get the current status of all robots.

#         Returns:
#             dict: A dictionary containing the status of all robots and the backend.
#         """
#         return {
#             "backend": self.status["backend"],
#             "meca": self.status["meca"],
#             "arduino": "connected" if self.arduino_connected else "disconnected",
#             "ot2": self.status["ot2"],
#         }

#     async def initialize_robots(self):
#         """Initialize all robots in the system with proper error handling."""
#         meca_success = arduino_success = ot2_success = False

#         try:
#             # Clean up any existing Meca connection
#             if self.meca_connected:
#                 logger.warning("Meca robot already connected. Disconnecting first.")
#                 await asyncio.to_thread(self.meca_robot.Disconnect)

#             # Initialize each robot system independently
#             try:
#                 await self._initialize_meca()
#                 meca_success = True
#             except Exception as e:
#                 logger.error(f"Failed to connect to Meca robot: {e}")
#                 self.meca_connected = False
#                 self.status["meca"] = "disconnected"
#                 await self.send_status_update()

#             try:
#                 await self._initialize_arduino()
#                 arduino_success = True
#             except Exception as e:
#                 logger.error(f"Failed to connect to Arduino: {e}")
#                 self.arduino_connected = False
#                 self.status["arduino"] = "disconnected"
#                 await self.send_status_update()

#             try:
#                 await self._initialize_ot2()
#                 ot2_success = True
#             except Exception as e:
#                 logger.error(f"Failed to connect to OT2: {e}")
#                 self.ot2_connected = False
#                 self.status["ot2"] = "disconnected"
#                 await self.send_status_update()

#             # Update backend status based on at least one successful connection
#             if any([meca_success, arduino_success, ot2_success]):
#                 self.status["backend"] = "connected"
#             else:
#                 self.status["backend"] = "partial"

#             await self.send_status_update()
#             logger.info(
#                 f"Robot initialization completed. Meca: {meca_success}, Arduino: {arduino_success}, OT2: {ot2_success}"
#             )

#         except Exception as e:
#             logger.error(f"Unexpected error initializing robots: {e}")
#             self.status["backend"] = "disconnected"
#             await self.send_status_update()

#     async def _initialize_meca(self):
#         """Initialize the Mecademic robot with proper error handling."""
#         try:
#             logger.info(f"Attempting to connect to Meca robot at {self.meca_ip}")

#             # Ensure clean connection state
#             if await asyncio.to_thread(self.meca_robot.IsConnected):
#                 logger.info("Robot is connected; performing clean disconnect")
#                 await asyncio.to_thread(self.meca_robot.Disconnect)
#                 await asyncio.sleep(2)

#             # Connect to the robot with offline mode disabled and monitoring enabled
#             await asyncio.to_thread(
#                 lambda: self.meca_robot.Connect(
#                     self.meca_ip,
#                     offline_mode=False,
#                     monitor_mode=False,  # Changed to False to allow commands
#                     disconnect_on_exception=False,
#                 )
#             )

#             # Verify connection
#             if not await asyncio.to_thread(self.meca_robot.IsConnected):
#                 raise Exception("Connection verification failed")

#             # Check and handle robot status
#             status = await asyncio.to_thread(self.meca_robot.GetStatusRobot)
#             if hasattr(status, "error_status") and status.error_status:
#                 logger.info("Resetting error state")
#                 await asyncio.to_thread(self.meca_robot.ResetError)

#             # Check activation and homing status safely
#             robot_activated = await asyncio.to_thread(
#                 lambda: getattr(self.meca_robot, "IsActivated", lambda: False)()
#             )
#             robot_homed = await asyncio.to_thread(
#                 lambda: getattr(self.meca_robot, "IsHomed", lambda: False)()
#             )

#             if not robot_activated or not robot_homed:
#                 logger.info("Robot needs activation/homing")
#                 if hasattr(self.meca_robot, "ActivateAndHome"):
#                     await asyncio.to_thread(self.meca_robot.ActivateAndHome)
#                 else:
#                     # Fallback to separate activate and home commands
#                     if hasattr(self.meca_robot, "Activate"):
#                         await asyncio.to_thread(self.meca_robot.Activate)
#                     if hasattr(self.meca_robot, "Home"):
#                         await asyncio.to_thread(self.meca_robot.Home)

#             # Configure robot parameters
#             await asyncio.to_thread(self.meca_robot.SetJointVel, 50)
#             await asyncio.to_thread(self.meca_robot.SetGripperForce, 100)

#             # Update status and notify
#             self.meca_connected = True
#             self.status["meca"] = "connected"
#             logger.info("Meca robot initialization completed successfully")
#             await self.send_status_update()

#         except Exception as e:
#             logger.error(f"Error in Meca initialization: {e}")
#             self.meca_connected = False
#             self.status["meca"] = "disconnected"
#             try:
#                 await asyncio.to_thread(self.meca_robot.Disconnect)
#             except:
#                 pass
#             await self.send_status_update()

#     async def _initialize_arduino(self):
#         """Initialize Arduino connection with proper error handling."""
#         try:
#             logger.info("Attempting to connect to Arduino...")
#             # Add your Arduino initialization logic here
#             self.arduino_connected = True
#             self.status["arduino"] = "connected"
#             logger.info("Arduino initialized successfully")
#             await self.send_status_update()
#         except Exception as e:
#             logger.error(f"Failed to connect to Arduino: {e}")
#             self.arduino_connected = False
#             self.status["arduino"] = "disconnected"
#             await self.send_status_update()
#             raise

#     async def _initialize_ot2(self):
#         """Initialize OT2 connection with proper error handling."""
#         try:
#             status = await self._check_ot2_status()
#             self.ot2_connected = status == "connected"
#             self.status["ot2"] = status

#             logger.info(
#                 f"OT2 robot initialization complete. Connected: {self.ot2_connected}"
#             )
#             await self.send_status_update()

#         except Exception as e:
#             logger.error(f"Error initializing OT2: {e}")
#             self.ot2_connected = False
#             self.status["ot2"] = "disconnected"
#             await self.send_status_update()
#             raise

#     async def update_status(self):
#         """Update and broadcast the status of all robots only when changes occur."""
#         try:
#             new_status = {
#                 "backend": "connected",
#                 "meca": await self._check_meca_status(),
#                 "arduino": "connected" if self.arduino_connected else "disconnected",
#                 "ot2": await self._check_ot2_status(),
#             }

#             # Check if any status has changed
#             status_changed = False
#             for device, state in new_status.items():
#                 if state != self.previous_status.get(device):
#                     status_changed = True
#                     logger.info(
#                         f"Status change detected for {device}: {self.previous_status.get(device)} -> {state}"
#                     )
#                     # Send individual status updates for changed components
#                     await self.websocket_server.broadcast(
#                         {
#                             "type": "status_update",
#                             "data": {"type": device, "status": state},
#                         }
#                     )

#             if status_changed:
#                 logger.info(f"Updated robot status: {new_status}")
#                 self.previous_status = new_status.copy()
#                 self.status = new_status

#         except Exception as e:
#             logger.error(f"Error updating status: {e}")

#     async def monitor_robots(self):
#         """Continuously monitor robot status with reduced frequency."""
#         try:
#             self.monitoring = True
#             while self.monitoring:
#                 try:
#                     # Check each robot status independently
#                     try:
#                         meca_status = await self._check_meca_status()
#                         self.status["meca"] = meca_status
#                     except Exception as e:
#                         logger.error(f"Error checking Meca status: {e}")

#                     try:
#                         # Arduino status check
#                         self.status["arduino"] = (
#                             "connected" if self.arduino_connected else "disconnected"
#                         )
#                     except Exception as e:
#                         logger.error(f"Error checking Arduino status: {e}")

#                     try:
#                         ot2_status = await self._check_ot2_status()
#                         self.status["ot2"] = ot2_status
#                     except Exception as e:
#                         logger.error(f"Error checking OT2 status: {e}")

#                     # Send status updates only for changes
#                     await self.update_status()

#                     # Check status every 30 seconds
#                     await asyncio.sleep(30)
#                 except Exception as e:
#                     logger.error(f"Error in monitor_robots loop: {e}")
#                     await asyncio.sleep(30)
#         except Exception as e:
#             logger.error(f"Monitor robots task failed: {e}")
#         finally:
#             self.monitoring = False
#             logger.info("Robot monitoring stopped")

#     async def _check_meca_status(self) -> str:
#         """Check Mecademic robot connection status with reduced logging."""
#         try:
#             loop = asyncio.get_event_loop()
#             if not await loop.run_in_executor(None, self.meca_robot.IsConnected):
#                 # Only log reconnection attempt once
#                 if self.previous_status["meca"] == "connected":
#                     logger.info(
#                         "Robot reports as disconnected, attempting reconnect..."
#                     )

#                 await loop.run_in_executor(
#                     None, lambda: self.meca_robot.Connect(self.meca_ip, False)
#                 )

#                 if not await loop.run_in_executor(None, self.meca_robot.IsConnected):
#                     self.meca_connected = False
#                     return "disconnected"

#             status_response = await loop.run_in_executor(
#                 None, self.meca_robot.GetStatusRobot
#             )
#             if status_response is not None:
#                 self.meca_connected = True
#                 return "connected"

#             self.meca_connected = False
#             return "disconnected"
#         except Exception as e:
#             # Only log error if this is a new disconnection
#             if self.previous_status["meca"] == "connected":
#                 logger.error(f"Error in Mecademic status check: {e}")
#             self.meca_connected = False
#             return "disconnected"

#     async def _check_ot2_status(self) -> str:
#         """Check OT2 robot connection status."""
#         try:
#             url = f"http://{self.ot2_ip}:{self.ot2_port}/health"
#             logger.info(f"Checking OT2 status at: {url}")

#             headers = {
#                 "Accept": "application/json",
#                 "Content-Type": "application/json",
#                 "Opentrons-Version": "2",  # Add the required version header
#             }

#             response = requests.get(url, headers=headers, timeout=5)
#             logger.info(f"OT2 health check response: Status={response.status_code}")

#             # Both 200 and 422 indicate the robot is connected
#             is_connected = response.status_code in [200, 422]

#             if is_connected:
#                 try:
#                     response_content = response.json()
#                     # logger.info(f"OT2 status details: {response_content}")
#                 except:
#                     logger.info("Could not parse response content")

#                 if self.previous_status.get("ot2") != "connected":
#                     logger.info("OT2 connection established")

#                 self.ot2_connected = True
#                 return "connected"

#             logger.error(f"Unexpected OT2 status code: {response.status_code}")
#             self.ot2_connected = False
#             return "disconnected"

#         except Exception as e:
#             if self.previous_status.get("ot2") == "connected":
#                 logger.error(f"Error checking OT2 status: {e}")
#             self.ot2_connected = False
#             return "disconnected"

#     async def send_status_update(self):
#         """Send status updates to connected clients."""
#         try:
#             for key, value in self.status.items():
#                 message = {
#                     "type": "status_update",
#                     "data": {
#                         "type": key,
#                         "status": value.lower(),
#                     },
#                 }
#                 logger.info(f"Sending status update: {message}")
#                 await self.websocket_server.broadcast(message)
#         except Exception as e:
#             logger.error(f"Error sending status update: {e}")

#     def register_status_callback(self, callback):
#         """Register a callback for status updates."""
#         if callback not in self._status_callbacks:
#             self._status_callbacks.append(callback)
#             logger.info(
#                 f"Registered new status callback. Total callbacks: {len(self._status_callbacks)}"
#             )

#     def unregister_status_callback(self, callback):
#         """Remove a registered status callback."""
#         if callback in self._status_callbacks:
#             self._status_callbacks.remove(callback)
#             logger.info(
#                 f"Unregistered status callback. Remaining callbacks: {len(self._status_callbacks)}"
#             )

#     async def _notify_status_callbacks(self, status_update):
#         """Notify all registered callbacks about a status change."""
#         for callback in self._status_callbacks:
#             try:
#                 await callback(status_update)
#             except Exception as e:
#                 logger.error(f"Error in status callback: {e}")

#     async def emergency_stop(self, robots=None):
#         """Execute emergency stop for specified robots or all robots."""
#         try:
#             if not robots:
#                 robots = {
#                     "meca": self.meca_connected,
#                     "ot2": self.ot2_connected,
#                     "arduino": self.arduino_connected,
#                 }

#             if robots.get("meca") and self.meca_connected:
#                 try:
#                     if hasattr(self.meca_robot, "DeactivateRobot"):
#                         await asyncio.to_thread(self.meca_robot.DeactivateRobot)
#                     await asyncio.to_thread(self.meca_robot.Disconnect)
#                     self.meca_connected = False
#                     logger.info("Meca robot emergency stop executed")
#                 except Exception as e:
#                     logger.error(f"Error during Meca robot emergency stop: {e}")

#             if robots.get("ot2") and self.ot2_connected:
#                 try:
#                     await self._send_ot2_command(
#                         {"command": "pause", "message": "Emergency stop activated"}
#                     )
#                     logger.info("OT2 robot emergency stop executed")
#                 except Exception as e:
#                     logger.error(f"Error during OT2 robot emergency stop: {e}")

#             if robots.get("arduino") and self.arduino_connected:
#                 try:
#                     # Implement Arduino emergency stop
#                     self.arduino_connected = False
#                     logger.info("Arduino emergency stop executed")
#                 except Exception as e:
#                     logger.error(f"Error during Arduino emergency stop: {e}")

#             await self.send_status_update()
#             logger.info("Emergency stop procedure completed")

#         except Exception as e:
#             logger.error(f"Error during emergency stop procedure: {e}")
#             raise

#     async def shutdown(self):
#         """Perform clean shutdown of all robots."""
#         try:
#             await self.emergency_stop()
#             self.monitoring = False
#             logger.info("RobotManager shutdown completed successfully")
#         except Exception as e:
#             logger.error(f"Error during RobotManager shutdown: {e}")
#             raise

#     # This is the part of robot_manager.py that needs to be updated
#     # Replace the relevant section of your run_ot2_protocol_direct method with this code

#     async def run_ot2_protocol_direct(self, data: dict = None):
#         """Execute an OT-2 protocol by following the proper API workflow.
#         This implementation uses the exact format expected by the OT2 API.
#         """
#         try:
#             logger.info("Starting OT2 protocol with direct protocol runner")

#             # Check OT-2 connection status first
#             if not self.ot2_connected:
#                 status = await self._check_ot2_status()
#                 if status != "connected":
#                     raise Exception("OT2 robot is not connected")

#             # Step 1: Read the protocol file
#             protocol_path = os.path.join(
#                 os.path.dirname(os.path.dirname(__file__)),
#                 "protocols",
#                 "ot2Protocole.py",
#             )

#             if not os.path.exists(protocol_path):
#                 raise Exception(f"Protocol file not found at: {protocol_path}")

#             with open(protocol_path, "r") as f:
#                 protocol_content = f.read()

#             # Add a timestamp as a comment without breaking indentation
#             timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
#             protocol_content = f"# Generated at: {timestamp}\n{protocol_content}"

#             # Prepare protocol parameters
#             parameters = {
#                 "NUM_OF_GENERATORS": self.ot2_config["NUM_OF_GENERATORS"],
#                 "radioactive_VOL": self.ot2_config["radioactive_VOL"],
#                 "SDS_VOL": self.ot2_config["SDS_VOL"],
#                 "CUR": self.ot2_config["CUR"],
#                 "sds_lct": self.ot2_config["sds_lct"],
#                 "thorium_lct": self.ot2_config["radioactive_lct"],
#                 "generators_locations": self.ot2_config["generators_locations"],
#                 "home_lct": self.ot2_config["home_lct"],
#                 "temp_lct": self.ot2_config["temp_lct"],
#                 "hight_home_lct": self.ot2_config["hight_home_lct"],
#                 "hight_temp_lct": self.ot2_config["hight_temp_lct"],
#                 "tip_location": self.ot2_config["tip_location"],
#                 "check_lct": self.ot2_config["check_lct"],
#                 "st_lct": self.ot2_config["st_lct"],
#                 "sec_lct": self.ot2_config["sec_lct"],
#             }

#             # Include any additional parameters passed as arguments
#             if data and isinstance(data, dict):
#                 for key, value in data.items():
#                     parameters[key] = value

#             # Create the JSON payload in the EXACT format expected by the OT2 API
#             # This is the critical part - the OT2 API is very specific about format
#             protocol_data = {
#                 "labwareDefinitions": {},
#                 "pipetteDefinitions": {},
#                 "designerApplication": {
#                     "name": "opentrons/protocol-designer",
#                     "version": "5.1.0",
#                 },
#                 "metadata": {
#                     "protocolName": f"Custom Protocol {timestamp}",
#                     "author": "System",
#                     "description": "Generated protocol",
#                     "apiLevel": "2.11",
#                 },
#                 "defaultValues": {"forecastLabwareReagents": False},
#                 "parameters": parameters,  # Here are our parameters
#                 "commands": [],
#             }

#             # Convert to a JSON string
#             protocol_json_str = json.dumps(protocol_data)

#             # CRITICAL: This is the exact format expected by the OT2 API for multipart form upload
#             protocols_url = f"http://{self.ot2_ip}:{self.ot2_port}/protocols"
#             headers = {"Accept": "application/json", "Opentrons-Version": "2"}

#             logger.info(f"Submitting protocol to OT2 at: {protocols_url}")
#             logger.info(
#                 f"Protocol parameters: {json.dumps(parameters, default=str, indent=2)}"
#             )

#             # Create a multipart form with files and payload in the specified format
#             files = [
#                 ("files", ("protocol.py", protocol_content, "text/plain")),
#             ]
#             form_data = {"data": ("", protocol_json_str, "application/json")}

#             # Submit the protocol using multipart form-data
#             logger.info(
#                 "Submitting as multipart form-data with separate files and data parts"
#             )
#             response = await asyncio.to_thread(
#                 lambda: requests.post(
#                     protocols_url,
#                     headers=headers,
#                     files=files,
#                     data=form_data,
#                     timeout=60,
#                 )
#             )

#             # Log the complete response for debugging
#             logger.info(f"Protocol submission response status: {response.status_code}")
#             logger.info(f"Protocol submission response: {response.text}")

#             # Handle non-success responses
#             if response.status_code >= 400:
#                 raise Exception(
#                     f"Protocol submission failed with status {response.status_code}: {response.text}"
#                 )

#             # Extract the protocol ID from the response
#             try:
#                 response_json = response.json()
#                 protocol_id = None

#                 # Try different paths for protocol ID
#                 if "data" in response_json:
#                     data_obj = response_json["data"]
#                     if isinstance(data_obj, dict) and "id" in data_obj:
#                         protocol_id = data_obj["id"]
#                     elif (
#                         isinstance(data_obj, list)
#                         and len(data_obj) > 0
#                         and "id" in data_obj[0]
#                     ):
#                         protocol_id = data_obj[0]["id"]

#                 if not protocol_id:
#                     raise Exception(
#                         f"No protocol ID found in response: {response_json}"
#                     )

#             except Exception as e:
#                 logger.error(f"Error parsing protocol response: {e}")
#                 raise Exception(
#                     f"Failed to parse protocol submission response: {str(e)}"
#                 )

#             logger.info(f"Protocol submitted successfully with ID: {protocol_id}")

#             # Step 3: Wait for protocol analysis to complete
#             logger.info("Waiting for protocol analysis to complete...")
#             analysis_result = await self._wait_for_analysis(protocol_id, headers)

#             if not analysis_result:
#                 logger.error("Protocol analysis failed")
#                 raise Exception(
#                     "Protocol analysis failed, cannot proceed with run creation"
#                 )

#             # Force a small delay to ensure the protocol is fully ready
#             await asyncio.sleep(2)

#             # Step 4: Create a run using the correct endpoint format
#             run_create_url = f"http://{self.ot2_ip}:{self.ot2_port}/runs"
#             run_create_data = {"data": {"protocolId": protocol_id}}

#             logger.info(f"Creating run for protocol {protocol_id}")
#             run_response = await asyncio.to_thread(
#                 lambda: requests.post(
#                     run_create_url,
#                     headers=headers,
#                     json=run_create_data,
#                     timeout=30,
#                 )
#             )

#             # Log the complete run creation response
#             logger.info(f"Run creation status: {run_response.status_code}")
#             logger.info(f"Run creation response: {run_response.text}")

#             if run_response.status_code >= 400:
#                 error_msg = f"Run creation failed with status {run_response.status_code}: {run_response.text}"
#                 logger.error(error_msg)
#                 raise Exception(error_msg)

#             # Extract the run ID with careful handling
#             try:
#                 run_json = run_response.json()
#                 run_id = None

#                 # Try different paths for run ID
#                 if "data" in run_json:
#                     data_obj = run_json["data"]
#                     if isinstance(data_obj, dict) and "id" in data_obj:
#                         run_id = data_obj["id"]
#                     elif (
#                         isinstance(data_obj, list)
#                         and len(data_obj) > 0
#                         and "id" in data_obj[0]
#                     ):
#                         run_id = data_obj[0]["id"]

#                 if not run_id:
#                     raise Exception(f"No run ID found in response: {run_json}")

#             except Exception as e:
#                 logger.error(f"Error extracting run ID: {e}")
#                 raise Exception(f"Failed to extract run ID: {str(e)}")

#             logger.info(f"Run created successfully with ID: {run_id}")

#             # Step 5: Start the run with play action
#             play_url = f"http://{self.ot2_ip}:{self.ot2_port}/runs/{run_id}/actions"
#             play_data = {"data": {"actionType": "play"}}

#             logger.info(f"Starting run {run_id}")
#             play_response = await asyncio.to_thread(
#                 lambda: requests.post(
#                     play_url,
#                     headers=headers,
#                     json=play_data,
#                     timeout=30,
#                 )
#             )

#             logger.info(f"Play command status: {play_response.status_code}")
#             logger.info(f"Play command response: {play_response.text}")

#             if play_response.status_code >= 400:
#                 error_msg = f"Play command failed with status {play_response.status_code}: {play_response.text}"
#                 logger.error(error_msg)
#                 raise Exception(error_msg)

#             logger.info(f"Run {run_id} started successfully")

#             # Set up a background task to monitor the run
#             asyncio.create_task(self._monitor_run(run_id, headers))

#             return {
#                 "runId": run_id,
#                 "status": "running",
#                 "message": "Protocol execution initiated",
#                 "protocolId": protocol_id,
#             }

#         except Exception as e:
#             logger.error(f"Error starting OT2 protocol: {e}")
#             raise Exception(f"Failed to start OT2 protocol: {str(e)}")

#     async def _wait_for_analysis(self, protocol_id: str, headers: Dict) -> bool:
#         """Wait for protocol analysis to complete and return whether it was successful.

#         Args:
#             protocol_id: The ID of the protocol to check
#             headers: The HTTP headers to use for requests

#         Returns:
#             bool: True if analysis completed successfully, False otherwise
#         """
#         max_attempts = 15  # Try for up to 30 seconds (15 * 2)
#         for attempt in range(max_attempts):
#             analysis_url = (
#                 f"http://{self.ot2_ip}:{self.ot2_port}/protocols/{protocol_id}"
#             )

#             try:
#                 analysis_response = await asyncio.to_thread(
#                     lambda: requests.get(analysis_url, headers=headers, timeout=10)
#                 )

#                 if analysis_response.status_code == 200:
#                     data = analysis_response.json().get("data", {})
#                     analysis_summaries = data.get("analysisSummaries", [])

#                     if analysis_summaries:
#                         status = analysis_summaries[0].get("status", "")
#                         logger.info(f"Protocol analysis status: {status}")

#                         # Check for various status possibilities
#                         if status in ["succeeded", "success"]:
#                             logger.info("Protocol analysis succeeded")
#                             return True
#                         elif status in ["failed", "error"]:
#                             logger.error("Protocol analysis failed")
#                             # Fetch and log detailed analysis errors
#                             if "errors" in analysis_summaries[0]:
#                                 logger.error(
#                                     f"Analysis errors: {json.dumps(analysis_summaries[0]['errors'], indent=2)}"
#                                 )
#                             return False
#                         elif status == "completed":
#                             # The OT2 API uses "completed" as the final state
#                             # Now check if there's a valid analysis result in the response
#                             if (
#                                 "errors" in analysis_summaries[0]
#                                 and analysis_summaries[0]["errors"]
#                             ):
#                                 logger.error(
#                                     f"Protocol analysis completed with errors: {analysis_summaries[0]['errors']}"
#                                 )
#                                 return False

#                             # Additional check: if the protocol is valid, it will have analyzedAt field
#                             if "analyzedAt" in data:
#                                 logger.info("Protocol analysis completed successfully")
#                                 return True

#                             # If we've seen "completed" status multiple times, assume it's done
#                             if attempt >= 2:  # Seen "completed" at least 3 times
#                                 logger.info(
#                                     "Protocol analysis appears complete after multiple checks"
#                                 )
#                                 return True
#                 else:
#                     logger.warning(
#                         f"Failed to check analysis status: {analysis_response.status_code}"
#                     )
#                     logger.warning(f"Response: {analysis_response.text}")

#             except Exception as e:
#                 logger.error(f"Error checking analysis status: {e}")

#             await asyncio.sleep(2)  # Wait 2 seconds before checking again

#         # If we've been polling for a while and keep seeing "completed", assume it's ready
#         logger.info(
#             "Timed out waiting for analysis status change - proceeding with run creation"
#         )
#         return True  # Proceed anyway after max attempts

#     async def _monitor_run(self, run_id: str, headers: Dict) -> None:
#         """Monitor the run progress in a background task and capture detailed error information if it fails.

#         Args:
#             run_id: The ID of the run to monitor
#             headers: The HTTP headers to use for requests
#         """
#         try:
#             max_attempts = 30  # Check status for 5 minutes (10s interval)
#             for attempt in range(max_attempts):
#                 await asyncio.sleep(10)  # Check every 10 seconds
#                 status_url = f"http://{self.ot2_ip}:{self.ot2_port}/runs/{run_id}"

#                 try:
#                     status_response = await asyncio.to_thread(
#                         lambda: requests.get(status_url, headers=headers, timeout=10)
#                     )

#                     if status_response.status_code == 200:
#                         status_data = status_response.json().get("data", {})
#                         current_status = status_data.get("status", "unknown")
#                         logger.info(
#                             f"Run status check ({attempt + 1}/{max_attempts}): {current_status}"
#                         )

#                         # Check for errors if the run failed
#                         if current_status == "failed":
#                             logger.error(
#                                 "Protocol run failed. Retrieving detailed error information..."
#                             )

#                             # Get commands to see which one failed
#                             commands_url = f"http://{self.ot2_ip}:{self.ot2_port}/runs/{run_id}/commands"
#                             commands_response = await asyncio.to_thread(
#                                 lambda: requests.get(
#                                     commands_url, headers=headers, timeout=10
#                                 )
#                             )

#                             if commands_response.status_code == 200:
#                                 commands = commands_response.json().get("data", [])
#                                 # Find the failed command
#                                 failed_command = None
#                                 for cmd in commands:
#                                     if cmd.get("status") == "failed":
#                                         failed_command = cmd
#                                         break

#                                 if failed_command:
#                                     logger.error(
#                                         f"Failed command: {json.dumps(failed_command, indent=2)}"
#                                     )
#                                     # Get error details
#                                     error_id = (
#                                         failed_command.get("error", {}).get("id")
#                                         if isinstance(failed_command.get("error"), dict)
#                                         else None
#                                     )
#                                     if error_id:
#                                         error_url = f"http://{self.ot2_ip}:{self.ot2_port}/runs/{run_id}/errors/{error_id}"
#                                         error_response = await asyncio.to_thread(
#                                             lambda: requests.get(
#                                                 error_url, headers=headers, timeout=10
#                                             )
#                                         )
#                                         if error_response.status_code == 200:
#                                             error_details = error_response.json().get(
#                                                 "data", {}
#                                             )
#                                             logger.error(
#                                                 f"Error details: {json.dumps(error_details, indent=2)}"
#                                             )
#                             else:
#                                 logger.error(
#                                     f"Failed to get commands: {commands_response.status_code}"
#                                 )

#                         if current_status in [
#                             "succeeded",
#                             "stopped",
#                             "failed",
#                             "finishing",
#                         ]:
#                             # Log the final run details for debugging
#                             try:
#                                 logger.info(
#                                     f"Run completed with status: {current_status}"
#                                 )
#                                 logger.info(
#                                     f"Final run data: {json.dumps(status_data, indent=2)}"
#                                 )
#                             except:
#                                 logger.info(
#                                     f"Run completed with status: {current_status}"
#                                 )

#                             # Notify the clients about completion
#                             if self.websocket_server:
#                                 await self.websocket_server.broadcast(
#                                     {
#                                         "type": "status_update",
#                                         "data": {
#                                             "type": "ot2",
#                                             "status": (
#                                                 "complete"
#                                                 if current_status == "succeeded"
#                                                 else "error"
#                                             ),
#                                             "runId": run_id,
#                                             "runStatus": current_status,
#                                         },
#                                     }
#                                 )
#                             break
#                     else:
#                         logger.warning(
#                             f"Failed to get run status: {status_response.status_code}"
#                         )
#                         logger.warning(f"Response: {status_response.text}")

#                 except Exception as e:
#                     logger.error(f"Error checking run status: {e}")

#         except Exception as e:
#             logger.error(f"Error monitoring run: {e}")

#     async def create_pickup(self):
#         """Prepare robot for pickup sequence."""
#         logger.info("Starting Meca pickup sequence")
#         try:
#             if not self.meca_connected:
#                 logger.info("Meca robot disconnected, attempting to reconnect...")
#                 await self._initialize_meca()
#                 if not self.meca_connected:
#                     raise Exception("Failed to connect to Meca robot")

#             # We'll let the meca.py module handle the actual sequence
#             # Just return success if robot is ready
#             return {"status": "success", "message": "Robot ready for pickup"}

#         except Exception as e:
#             logger.error(f"Error preparing for pickup sequence: {e}")
#             raise
