from sqlalchemy.orm import Session
from database.models import Robot as DbRobot, Config as DbConfig
from database.repositories import RobotRepository, ConfigRepository
import logging

logger = logging.getLogger(__name__)

class Robot:
    def __init__(self, id=None, name=None, db_session=None):
        """
        Initialize Robot object according to the database schema
        
        Args:
            id (int): Primary key id for the robot
            name (str): Name of the robot (up to 25 chars)
            db_session (Session): SQLAlchemy database session
        """
        self.id = id
        self.name = name
        self._db_session = db_session
        
        # Relationships
        self._config = None  # One-to-one with Config
        self._process_logs = []  # One-to-many with ProcessLog
        self._wafers = []  # One-to-many with Wafer (for both MECA and OT2)
        
    def __repr__(self):
        return f"Robot(id={self.id}, name={self.name})"
    
    @property
    def config(self):
        """Returns the configuration for this robot"""
        # If we have a database session, fetch from the database
        if self._db_session and self.id:
            config_entries = ConfigRepository.get_robot_configs(self._db_session, self.id)
            # Convert to a dictionary for easier access
            return {entry.param: entry.value for entry in config_entries}
        return self._config
        
    @config.setter
    def config(self, config):
        """Sets the configuration for this robot"""
        self._config = config
        
        # If we have a database session, save to the database
        if self._db_session and self.id:
            for param, value in config.items():
                ConfigRepository.update_config(
                    self._db_session, self.id, param, str(value)
                )
        
    @property
    def process_logs(self):
        """Returns list of process logs for this robot"""
        # If we have a database session, fetch from database
        if self._db_session and self.id:
            from database.repositories import ProcessLogRepository
            return ProcessLogRepository.get_logs_by_robot(self._db_session, self.id)
        return self._process_logs
        
    @property
    def wafers(self):
        """Returns list of wafers processed by this robot"""
        # If we have a database session, fetch from database
        if self._db_session and self.id:
            from database.repositories import WaferRepository
            return WaferRepository.get_wafers_by_robot(self._db_session, self.id)
        return self._wafers
        
    def add_process_log(self, process_log):
        """
        Associates a process log with this robot
        
        Args:
            process_log: ProcessLog object to be associated
        """
        process_log.robot_id = self.id
        self._process_logs.append(process_log)
        
        # If we have a database session, save to database
        if self._db_session and self.id:
            from database.repositories import ProcessLogRepository
            ProcessLogRepository.create_process_log(
                self._db_session,
                process_log.wafer_id,
                self.id,
                process_log.process_type,
                process_log.cycle_number
            )
        
    def add_wafer(self, wafer, robot_type="MECA"):
        """
        Associates a wafer with this robot
        
        Args:
            wafer: Wafer object to be associated
            robot_type (str): Type of robot ("MECA" or "OT2")
        """
        if robot_type == "MECA":
            wafer.meca_id = self.id
        elif robot_type == "OT2":
            wafer.ot2_id = self.id
        else:
            raise ValueError("Robot type must be either 'MECA' or 'OT2'")
            
        self._wafers.append(wafer)
        
        # If we have a database session, update the wafer in the database
        if self._db_session and self.id and wafer.id:
            from database.repositories import WaferRepository
            WaferRepository.update_wafer_robot(
                self._db_session, wafer.id, self.id, robot_type
            )
    
    def save(self):
        """Save this robot to the database"""
        if not self._db_session:
            logger.warning("Cannot save robot: no database session provided")
            return False
            
        try:
            if self.id:
                # Update existing robot
                robot = RobotRepository.update_robot(
                    self._db_session, self.id, self.name
                )
            else:
                # Create new robot
                robot = RobotRepository.create_robot(
                    self._db_session, self.name
                )
                self.id = robot.id
                
            return True
        except Exception as e:
            logger.error(f"Error saving robot: {e}")
            return False
        
    @classmethod
    def from_db_model(cls, db_model, db_session=None):
        """Create a Robot object from a database model"""
        robot = cls(
            id=db_model.id,
            name=db_model.name,
            db_session=db_session
        )
        return robot
        
    @staticmethod
    def get_by_id(robot_id, db_session=None):
        """
        Static method to retrieve robot by ID
        
        Args:
            robot_id (int): ID of robot to retrieve
            db_session (Session): SQLAlchemy database session
            
        Returns:
            Robot object or None if not found
        """
        if db_session:
            db_robot = RobotRepository.get_robot_by_id(db_session, robot_id)
            if db_robot:
                return Robot.from_db_model(db_robot, db_session)
                
        # Placeholder implementation for backwards compatibility
        return None
        
    @staticmethod
    def get_all(db_session=None, skip=0, limit=100):
        """
        Get all robots
        
        Args:
            db_session (Session): SQLAlchemy database session
            skip (int): Number of records to skip
            limit (int): Maximum number of records to return
            
        Returns:
            List of Robot objects
        """
        if db_session:
            db_robots = RobotRepository.get_all_robots(db_session, skip, limit)
            return [Robot.from_db_model(db_robot, db_session) for db_robot in db_robots]
            
        # Placeholder implementation for backwards compatibility
        return []