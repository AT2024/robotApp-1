# Software Requirements Specification (SRS) for Windsurf Project

## 1. Introduction

### 1.1. Purpose

This document specifies the software requirements for the Windsurf project, a laboratory automation system designed to streamline and automate various experimental processes. It outlines the system's functionalities, performance criteria, and interfaces, providing a comprehensive guide for developers, testers, and stakeholders.

### 1.2. Scope

The Windsurf project aims to automate laboratory processes using a robotic system. This includes managing robotic arms (Meca), liquid handling robots (OT2), and carousel systems. The software provides a user interface to configure and monitor these processes, enhancing efficiency and reproducibility in experimental workflows. The system automates liquid handling tasks, including:

*   Cherrypicking from coordinates
*   Aspiration and dispensing of liquids
*   Tip management
*   Position-based operations
*   Network communication

### 1.3. Definitions

*   **OT-2**: Opentrons OT-2 robot
*   **Protocol**: Sequence of commands for the OT-2
*   **Pipette**: Liquid handling instrument
*   **Labware**: Containers for liquids
*   **Meca**: Denotes the robotic arm system used in the project.
*   **Carousel**: Refers to the automated carousel system for sample management.

### 1.4. Intended Audience

This document is intended for the following audience:

*   Software developers
*   Test engineers
*   Project managers
*   Stakeholders
*   Laboratory technicians
*   Research scientists
*   Automation engineers

## 2. Overall Description

### 2.1. Product Perspective

The Windsurf project is a client-server architecture designed to provide a comprehensive laboratory automation solution. It comprises the following components:

*   **Backend**: A Python-based server responsible for protocol execution, robotic system control, and data management.
*   **Frontend**: A user interface built with React, providing users with the ability to configure experiments, monitor system status, and analyze results.
*   **OT-2 Robot**: The Opentrons OT-2 robotic platform for precise liquid handling operations.
*   **Meca Robotic Arm**: The robotic arm system used for sample manipulation and transfer.
*   **Carousel System**: An automated carousel system for sample storage and retrieval.

### 2.2. Product Functions

The software provides the following functions:

*   **Protocol Execution**: Executes liquid handling protocols on the OT-2 robot, managing pipettes, labware, and tips.
*   **Configuration Management**: Loads configurations from multiple sources, validates parameters, and manages protocol parameters.
*   **Position Control**: Enables precise location-based operations and safe movement between points for both the OT-2 robot and the Meca robotic arm.
*   **Network Communication**: Facilitates TCP/IP communication and protocol API integration.
*   **Robotic System Control**: Manages and controls the Meca robotic arm and the carousel system.
*   **Real-time Monitoring**: Provides real-time status updates of all robotic systems and experimental processes.
*   **Logging and Reporting**: Logs all system events and user actions for auditing and debugging purposes.
*   **User Authentication and Authorization**: Secures the system with user authentication and authorization mechanisms.

### 2.3. User Characteristics

The users of this software are laboratory technicians and scientists with varying levels of technical expertise. The user interface should be intuitive and easy to use, providing clear guidance and feedback throughout the experimental workflow.

### 2.4. Operating Environment

The software operates in a laboratory environment and requires a stable network connection to communicate with the robotic systems. The backend is implemented in Python, and the frontend is built with React. The system is designed to run on standard laboratory computers with the following specifications:

*   Operating System: Windows 10 or later
*   Processor: Intel Core i5 or equivalent
*   Memory: 8 GB RAM
*   Storage: 100 GB free disk space

### 2.5. Design and Implementation Constraints

*   The software must be compatible with existing robotic systems.
*   The software must adhere to laboratory safety standards.
*   The software must be scalable and maintainable.
*   The software must be designed with a modular architecture to allow for future expansion and integration of new robotic systems.
*   The software must be thoroughly tested to ensure reliability and accuracy.

### 2.6. Assumptions and Dependencies

*   The robotic systems are properly calibrated and maintained.
*   The network connection is stable and reliable.
*   The necessary software libraries and dependencies are installed.
*   The Opentrons OT-2 robot is running the latest firmware version.
*   The Meca robotic arm is properly configured and connected to the system.
*   The carousel system is functioning correctly and accessible via the network.

## 3. Specific Requirements

### 3.1. Functional Requirements

#### 3.1.1. Protocol Execution

*   The system shall execute Opentrons protocol API v2.11.
*   The system shall support multiple pipettes.
*   The system shall handle different labware types.
*   The system shall perform aspiration and dispensing operations.
*   The system shall allow users to define and execute protocols for the OT-2 robot.
*   The system shall provide real-time status updates of the OT-2 robot.

#### 3.1.2. Configuration

*   The system shall load configuration from multiple sources:
    *   Protocol parameters
    *   Python configuration files
    *   JSON files
*   The system shall validate required parameters.
*   The system shall log configuration parameters.
*   The system shall allow users to configure the OT2 liquid handling robot.

#### 3.1.3. Liquid Handling

*   The system shall provide precise volume control.
*   The system shall handle multiple liquid types (radioactive, SDS).
*   The system shall manage tips.
*   The system shall ensure safe movement between positions.

#### 3.1.4. Position Control

*   The system shall support coordinate-based positioning.
*   The system shall ensure safe movement between points.
*   The system shall manage home position.
*   The system shall handle temporary positions.
*   The system shall allow users to control the Meca robotic arm.

#### 3.1.5. Robotic System Control

*   The system shall allow users to control the Meca robotic arm.
*   The system shall allow users to monitor the carousel system.
*   The system shall provide real-time status updates of the Meca robotic arm and the carousel system.

#### 3.1.6. Logging and Reporting

*   The system shall log all system events and user actions.
*   The system shall generate reports on experimental results and system performance.

#### 3.1.7. User Authentication and Authorization

*   The system shall provide a user authentication mechanism.
*   The system shall provide role-based access control to protect sensitive data and prevent unauthorized access.

### 3.2. Non-Functional Requirements

#### 3.2.1. Performance

*   The system shall provide real-time protocol execution.
*   The system shall ensure sub-millimeter positioning accuracy.
*   The system shall enable quick tip changes.
*   The system shall provide efficient liquid handling.
*   The system shall be responsive and provide feedback to the user within 2 seconds.

#### 3.2.2. Reliability

*   The system shall provide error handling.
*   The system shall ensure safe operation.
*   The system shall validate parameters.
*   The system shall provide logging for debugging.
*   The system shall be available 99% of the time.

#### 3.2.3. Maintainability

*   The system shall have a modular code structure.
*   The system shall have clear documentation.
*   The system shall be configuration-based.
*   The system shall allow easy parameter modification.
*   The system shall be designed for easy maintenance and updates.

#### 3.2.4. Security

*   The system shall be secure and protect sensitive data.
*   The system shall comply with relevant data privacy regulations.

### 3.3. External Interfaces

#### 3.3.1. User Interfaces

*   The system shall provide a configuration interface.
*   The system shall provide status monitoring.
*   The system shall provide error reporting.
*   The system shall provide a web-based user interface.

#### 3.3.2. Hardware Interfaces

*   The system shall control the OT-2 Robot.
*   The system shall control the Pipette.
*   The system shall detect Labware.
*   The system shall interface with the Meca robotic arm.
*   The system shall interface with the carousel system.

#### 3.3.3. Software Interfaces

*   The system shall use the Opentrons protocol API.
*   The system shall use network communication.
*   The system shall use configuration files.
*   The system shall use a well-defined API for external integrations.

### 3.4. Data Management

The system shall upload data to an SQL database. The database structure is as follows:

*   **ROBOT**:
    *   id: INT PK
    *   name: CHAR(25)
*   **CONFIG**:
    *   id: INT PK, FK (from robot id)
    *   param: VARCHAR(255)
    *   value: VARCHAR(255)
*   **PROCESSLOG**:
    *   id: INT PK
    *   wafer_id: INT FK
    *   robot_id: INT FK
    *   process_type: VARCHAR(255)
    *   cycle_number: INT
*   **THORIUM_VIAL**:
    *   id: INT PK
    *   vial_serial_number: VARCHAR(50)
    *   initial_volume: FLOAT
    *   current_volume: FLOAT
    *   opening_time: DATETIME
*   **WAFER**:
    *   id: INT PK
    *   tray_id: INT FK
    *   carousel_id: INT FK
    *   meca_id: INT FK
    *   ot2_id: INT FK
    *   thorium_id: INT FK
    *   wafer_pos: INT (1-55)
*   **BAKING_TRAY**:
    *   id: INT PK
    *   tray_serial_number: VARCHAR(50)
    *   in_use: BOOLEAN
    *   capacity: INT DEFAULT 55
    *   next_pos: INT (Counter 1-55)
*   **CAROUSEL**:
    *   id: INT PK
    *   carousel_serial_number: VARCHAR(50)
    *   tray_id: INT FK
    *   carousel_time: DATETIME
    *   in_use: BOOLEAN

## 4. System Features

### 4.1. Cherrypicking from Coordinates

*   The system shall support multiple generators.
*   The system shall provide precise coordinate-based operations.
*   The system shall ensure safe movement between points.
*   The system shall provide volume control.

### 4.2. Liquid Handling

*   The system shall handle multiple liquid types (radioactive, SDS).
*   The system shall provide precise volume control.
*   The system shall perform aspiration and dispensing.
*   The system shall manage tips.

### 4.3. Position Management

*   The system shall manage home position.
*   The system shall handle temporary positions.
*   The system shall manage generator locations.
*   The system shall ensure safe movement paths.

## 5. Requirements Traceability

Each requirement is traceable to specific functions in the system:

*   Protocol execution: `run`, `execute_protocol`
*   Configuration: `load_config`, `ensure_required_parameters`
*   Position control: `create_lct_point`, `safe_move`

## 6. Appendix

### 6.1. Configuration Parameters

The following configuration parameters are used in the system:

```python
{
    "NUM_OF_GENERATORS": int,  # Number of generators used in the experiment
    "radioactive_VOL": float,   # Volume of radioactive liquid
    "SDS_VOL": float,           # Volume of SDS liquid
    "CUR": int,                # Current value
    "sds_lct": [int, int, int],    # Location of SDS liquid
    "radioactive_lct": [int, int, int], # Location of radioactive liquid
    "generators_locations": [[int, int, int]], # Locations of generators
    "home_lct": [int, int, int],   # Home location
    "temp_lct": [int, int, int],   # Temporary location
    "hight_home_lct": [int, int, int], # Height of home location
    "hight_temp_lct": [int, int, int], # Height of temporary location
    "tip_location": str,        # Location of tips
    "check_lct": [int, int, int],   # Location for checking
    "st_lct": [int, int, int],    # Starting location
    "sec_lct": [int, int, int],    # Secondary location
    "ip": str,                 # IP address of the robot
    "port": int                # Port number of the robot
}
