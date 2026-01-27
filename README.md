# Windsurf Robotics Application

## Overview

The Windsurf Robotics Application is a system designed to automate laboratory processes using a combination of robotic hardware and software control. It integrates a Mecademic robot, an Opentrons OT-2 liquid handling robot, and an Arduino-controlled system to perform complex tasks. The application consists of a backend (written in Python) that manages the robots and a frontend (likely written in JavaScript) that provides a user interface for controlling the system.

## Branches

- **main**: The main branch to run the app.
- **frontend**: Branch for frontend development.
- **backend**: Branch for backend development.
- **test**: Branch for testing and checking things.

## Getting Started

1.  **Clone the repository:**

    ```sh
    git clone <repository-url>
    ```

2.  **Checkout the desired branch:**

    ```sh
    git checkout <branch-name>
    ```

## Backend Setup

1.  **Navigate to the backend directory:**

    ```sh
    cd windsurf-project/backend
    ```

2.  **Create a virtual environment (recommended):**

    ```sh
    python -m venv venv
    ```

3.  **Activate the virtual environment:**

    *   On Windows:

        ```sh
        venv\Scripts\activate
        ```

    *   On macOS and Linux:

        ```sh
        source venv/bin/activate
        ```

4.  **Install dependencies:**

    ```sh
    pip install -r requirements.txt
    ```

5.  **Configure the robots:**

    *   Edit the configuration files in the `windsurf-project/backend/config/` directory:
        *   `meca_config.py`: Configure the Mecademic robot's IP address, port, and motion parameters.
        *   `ot2_config.py`: Configure the OT-2 robot's IP address, port, and experiment-specific parameters.

6.  **Database Setup:**

    *   Set up an SQL database (e.g., MySQL, PostgreSQL) and configure the connection details in the backend.
    *   Create the following tables based on the schema described below:
        *   `Robots`: Stores robot status and connection information.
        *   `MecaConfig`: Stores Mecademic robot configuration parameters.
        *   `OT2Config`: Stores OT-2 robot configuration parameters.
        *   `BakingTrays`: Stores information about baking trays.
        *   `Carousels`: Stores information about carousel slots.
        *   `Wafers`: Stores information about individual wafers.

    **Database Schema:**

    *   **Robots Table:**

        *   `id` (INT, PRIMARY KEY): Unique identifier for the robot.
        *   `name` (VARCHAR): Robot name ('meca', 'ot2', 'arduino').
        *   `status` (VARCHAR): Current status ('connected', 'disconnected', etc.).
        *   `ip` (VARCHAR): IP address.
        *   `port` (INT): Port number.

    *   **MecaConfig Table:**

        *   `id` (INT, PRIMARY KEY): Unique identifier for the configuration.
        *   `acc` (INT): Acceleration.
        *   `empty_speed` (INT): Speed when empty.
        *   `wafer_speed` (INT): Speed for wafers.
        *   `speed` (INT): General speed.
        *   `align_speed` (INT): Alignment speed.
        *   `entry_speed` (INT): Entry speed.
        *   `force` (INT): Force applied.
        *   `close_width` (FLOAT): Width when closing.
        *   `total_wafers` (INT): Total number of wafers.
        *   `wafers_per_cycle` (INT): Wafers per cycle.
        *   `wafers_per_carousel` (INT): Wafers per carousel.
        *   `first_wafer` (TEXT): JSON string representing the first wafer position.
        *   `gen_drop` (TEXT): JSON string representing generator drop locations.
        *   `carousel` (TEXT): JSON string representing carousel position.
        *   `safe_point` (TEXT): JSON string representing safe point.
        *   `carousel_safe_point` (TEXT): JSON string representing carousel safe point.
        *   `t_photogate` (TEXT): JSON string representing top photogate position.
        *   `c_photogate` (TEXT): JSON string representing center photogate position.
        *   `gap_wafers` (FLOAT)

    *   **OT2Config Table:**

        *   `id` (INT, PRIMARY KEY): Unique identifier for the configuration.
        *   `num_of_generators` (INT): Number of generators.
        *   `radioactive_vol` (FLOAT): Radioactive volume.
        *   `sds_vol` (FLOAT): SDS volume.
        *   `cur` (INT): CUR parameter.
        *   `sds_lct` (TEXT): JSON string for SDS location.
        *   `radioactive_lct` (TEXT): JSON string for radioactive location.
        *   `generators_locations` (TEXT): JSON string for generator locations.
        *   `home_lct` (TEXT): JSON string for home location.
        *   `temp_lct` (TEXT): JSON string for temperature location.
        *   `hight_home_lct` (TEXT): JSON string for high home location.
        *   `hight_temp_lct` (TEXT): JSON string for high temperature location.
        *   `tip_location` (VARCHAR): Tip location.
        *   `check_lct` (TEXT): JSON string
        *   `st_lct` (TEXT): JSON string
        *   `sec_lct` (TEXT): JSON string

    *   **BakingTrays Table:**

        *   `id` (INT, PRIMARY KEY): Unique identifier (likely the `serial_baking_trey`).
        *   `status` (BOOLEAN): Tray status (e.g., in use, available).

    *   **Carousels Table:**

        *   `id` (INT, PRIMARY KEY): Unique identifier for the carousel entry.
        *   `serial_baking_trey` (INT, FOREIGN KEY referencing BakingTrays.id): The baking tray serial number.
        *   `carousel_time` (DATETIME): Time the tray was placed on the carousel.
        *   `in_use` (BOOLEAN): Indicates if the carousel slot is in use.

    *   **Wafers Table:**

        *   `id` (INT, PRIMARY KEY): Unique identifier (likely the `wafer_serial`).
        *   `tray_serial` (INT, FOREIGN KEY referencing BakingTrays.id): The baking tray serial number.
        *   `radioactive_number` (VARCHAR): Identifier for radioactive material.
        *   `spreading_time` (DATETIME): Time of spreading.
        *   `generator` (VARCHAR): Which generator was used.
        *   `location_tray` (VARCHAR): Location on the tray.
        *   `location_carousel` (VARCHAR): Location on the carousel.
        *   `robot_ot2_id` (INT, FOREIGN KEY referencing Robots.id): Reference to the OT-2 robot.
        *   `robot_meca_id` (INT, FOREIGN KEY referencing Robots.id): Reference to the Meca robot.

    *   **Logs Table:**

        *   `id` (INT, PRIMARY KEY): Unique identifier for the log entry.
        *   `timestamp` (DATETIME): Date and time of the log entry.
        *   `logger_name` (VARCHAR): Name of the logger (e.g., "robot_manager").
        *   `level` (VARCHAR): Log level (e.g., "INFO", "ERROR", "WARNING").
        *   `message` (TEXT): The log message itself.

7.  **Run the backend:**

    ```sh
    python main.py
    ```

## Frontend Setup

1.  **Navigate to the frontend directory:**

    ```sh
    cd windsurf-project/frontend
    ```

2.  **Install dependencies:**

    ```sh
    npm install
    ```

3.  **Configure the frontend:**

    *   Edit the environment variables in the `.env` files to point to the correct backend URL.

4.  **Run the frontend:**

    ```sh
    npm run dev
    ```

## Configuration

*   **Robot Configurations:** The robot configurations are located in the `windsurf-project/backend/config/` directory. Edit these files to match your robot setup.
*   **API Keys:** If any external APIs are used, configure the API keys in the appropriate configuration files or environment variables.

## Running the Application

1.  Start the backend server.
2.  Start the frontend development server.
3.  Access the application in your browser at `http://localhost:3002`.
