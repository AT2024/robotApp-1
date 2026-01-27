from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from .models import Robot, Config, ProcessLog, ThoriumVial, Wafer, BakingTray, Carousel
from datetime import datetime

from utils.logger import get_logger

logger = get_logger("repositories")

class RobotRepository:
    @staticmethod
    def create_robot(db: Session, name: str):
        """Create a new robot record."""
        try:
            robot = Robot(name=name)
            db.add(robot)
            db.commit()
            db.refresh(robot)
            logger.info(f"Created robot '{name}' with ID {robot.id}")
            return robot
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error creating robot: {str(e)}")
            raise
    
    @staticmethod
    def get_robot_by_id(db: Session, robot_id: int):
        """Get a robot by ID."""
        return db.query(Robot).filter(Robot.id == robot_id).first()
    
    @staticmethod
    def get_robot_by_name(db: Session, name: str):
        """Get a robot by name."""
        return db.query(Robot).filter(Robot.name == name).first()
    
    @staticmethod
    def get_all_robots(db: Session, skip: int = 0, limit: int = 100):
        """Get all robots with pagination."""
        return db.query(Robot).offset(skip).limit(limit).all()
    
    @staticmethod
    def update_robot(db: Session, robot_id: int, name: str):
        """Update a robot's name."""
        try:
            robot = db.query(Robot).filter(Robot.id == robot_id).first()
            if robot:
                robot.name = name
                db.commit()
                db.refresh(robot)
                logger.info(f"Updated robot ID {robot_id} with name '{name}'")
                return robot
            return None
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error updating robot: {str(e)}")
            raise
    
    @staticmethod
    def delete_robot(db: Session, robot_id: int):
        """Delete a robot."""
        try:
            robot = db.query(Robot).filter(Robot.id == robot_id).first()
            if robot:
                db.delete(robot)
                db.commit()
                logger.info(f"Deleted robot ID {robot_id}")
                return True
            return False
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error deleting robot: {str(e)}")
            raise

class ConfigRepository:
    @staticmethod
    def create_config(db: Session, robot_id: int, param: str, value: str):
        """Create a new configuration parameter."""
        try:
            config = Config(id=robot_id, param=param, value=value)
            db.add(config)
            db.commit()
            db.refresh(config)
            logger.info(f"Created config for robot ID {robot_id}, param '{param}', value '{value}'")
            return config
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error creating config: {str(e)}")
            raise
    
    @staticmethod
    def get_robot_configs(db: Session, robot_id: int):
        """Get all configuration parameters for a robot."""
        return db.query(Config).filter(Config.id == robot_id).all()
    
    @staticmethod
    def get_config_value(db: Session, robot_id: int, param: str):
        """Get a specific configuration parameter value."""
        config = db.query(Config).filter(Config.id == robot_id, Config.param == param).first()
        return config.value if config else None
    
    @staticmethod
    def update_config(db: Session, robot_id: int, param: str, value: str):
        """Update a configuration parameter value."""
        try:
            config = db.query(Config).filter(Config.id == robot_id, Config.param == param).first()
            if config:
                config.value = value
                db.commit()
                db.refresh(config)
                logger.info(f"Updated config for robot ID {robot_id}, param '{param}', value '{value}'")
                return config
            # If not found, create a new config
            return ConfigRepository.create_config(db, robot_id, param, value)
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error updating config: {str(e)}")
            raise
    
    @staticmethod
    def delete_config(db: Session, robot_id: int, param: str):
        """Delete a configuration parameter."""
        try:
            config = db.query(Config).filter(Config.id == robot_id, Config.param == param).first()
            if config:
                db.delete(config)
                db.commit()
                logger.info(f"Deleted config for robot ID {robot_id}, param '{param}'")
                return True
            return False
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error deleting config: {str(e)}")
            raise

# Similarly, implement repositories for other models:
class ProcessLogRepository:
    # Add CRUD methods for ProcessLog
    pass

class ThoriumVialRepository:
    # Add CRUD methods for ThoriumVial
    pass

class WaferRepository:
    # Add CRUD methods for Wafer
    pass

class BakingTrayRepository:
    # Add CRUD methods for BakingTray
    pass

class CarouselRepository:
    # Add CRUD methods for Carousel
    pass