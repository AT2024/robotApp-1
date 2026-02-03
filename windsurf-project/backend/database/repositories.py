from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from .models import Robot, Config, ProcessLog, ThoriumVial, Wafer, BakingTray, Carousel
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import os
import json

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
            logger.debug(f"Created robot '{name}' with ID {robot.id}")
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
                logger.debug(f"Updated robot ID {robot_id} with name '{name}'")
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
                logger.debug(f"Deleted robot ID {robot_id}")
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
            logger.debug(f"Created config for robot ID {robot_id}, param '{param}', value '{value}'")
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
                logger.debug(f"Updated config for robot ID {robot_id}, param '{param}', value '{value}'")
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
                logger.debug(f"Deleted config for robot ID {robot_id}, param '{param}'")
                return True
            return False
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error deleting config: {str(e)}")
            raise

# ProcessLog Repository with full CRUD operations
class ProcessLogRepository:
    @staticmethod
    def create(db: Session, wafer_id: int, robot_id: int, process_type: str, cycle_number: int):
        """Create a new process log entry."""
        try:
            process_log = ProcessLog(
                wafer_id=wafer_id,
                robot_id=robot_id,
                process_type=process_type,
                cycle_number=cycle_number
            )
            db.add(process_log)
            db.commit()
            db.refresh(process_log)
            logger.debug(f"Created process log: wafer={wafer_id}, robot={robot_id}, type={process_type}")
            return process_log
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error creating process log: {str(e)}")
            raise

    @staticmethod
    def get_by_id(db: Session, log_id: int):
        """Get a process log by ID."""
        return db.query(ProcessLog).filter(ProcessLog.id == log_id).first()

    @staticmethod
    def get_by_wafer(db: Session, wafer_id: int):
        """Get all process logs for a specific wafer."""
        return db.query(ProcessLog).filter(ProcessLog.wafer_id == wafer_id).order_by(ProcessLog.created_at.desc()).all()

    @staticmethod
    def get_by_robot(db: Session, robot_id: int, limit: int = 100):
        """Get all process logs for a specific robot."""
        return db.query(ProcessLog).filter(ProcessLog.robot_id == robot_id).order_by(ProcessLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_recent(db: Session, limit: int = 50):
        """Get most recent process logs."""
        return db.query(ProcessLog).order_by(ProcessLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_count(db: Session) -> int:
        """Get total count of process logs."""
        return db.query(func.count(ProcessLog.id)).scalar() or 0

    @staticmethod
    def get_older_than(db: Session, days: int, limit: int = 1000) -> List[ProcessLog]:
        """
        Get process logs older than specified days.

        Args:
            db: Database session
            days: Age threshold in days
            limit: Maximum records to return

        Returns:
            List of ProcessLog entries older than threshold
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        return db.query(ProcessLog).filter(
            ProcessLog.created_at < cutoff_date
        ).order_by(ProcessLog.created_at.asc()).limit(limit).all()

    @staticmethod
    def archive_logs(
        db: Session,
        logs: List[ProcessLog],
        archive_dir: str
    ) -> str:
        """
        Archive process logs to JSON file.

        Args:
            db: Database session
            logs: List of ProcessLog entries to archive
            archive_dir: Directory to write archive files

        Returns:
            Path to created archive file
        """
        if not logs:
            return ""

        os.makedirs(archive_dir, exist_ok=True)

        # Group by month for archive filename
        first_log = min(logs, key=lambda x: x.created_at)
        archive_month = first_log.created_at.strftime("%Y%m")
        archive_path = os.path.join(archive_dir, f"processlog_{archive_month}.json")

        # Convert logs to serializable format
        log_data = []
        for log in logs:
            log_data.append({
                "id": log.id,
                "wafer_id": log.wafer_id,
                "robot_id": log.robot_id,
                "process_type": log.process_type,
                "cycle_number": log.cycle_number,
                "created_at": log.created_at.isoformat() if log.created_at else None
            })

        # Append to existing archive or create new
        existing_data = []
        if os.path.exists(archive_path):
            try:
                with open(archive_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        existing_data.extend(log_data)

        with open(archive_path, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, indent=2, default=str)

        logger.info(f"Archived {len(log_data)} process logs to {archive_path}")
        return archive_path

    @staticmethod
    def delete_logs(db: Session, log_ids: List[int]) -> int:
        """
        Delete process logs by ID.

        Args:
            db: Database session
            log_ids: List of log IDs to delete

        Returns:
            Number of logs deleted
        """
        if not log_ids:
            return 0

        try:
            deleted = db.query(ProcessLog).filter(
                ProcessLog.id.in_(log_ids)
            ).delete(synchronize_session='fetch')
            db.commit()
            logger.debug(f"Deleted {deleted} process logs")
            return deleted
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error deleting process logs: {str(e)}")
            raise

    @staticmethod
    def cleanup_old_logs(
        db: Session,
        retention_days: int = 90,
        max_count: int = 100000,
        archive_dir: Optional[str] = None,
        batch_size: int = 1000
    ) -> Dict[str, Any]:
        """
        Clean up old process logs with combined time and count retention.

        Strategy:
        1. Archive logs older than retention_days
        2. If still over max_count, archive oldest until under limit
        3. Delete archived records from database

        Args:
            db: Database session
            retention_days: Delete logs older than this (default 90)
            max_count: Maximum records to keep (default 100000)
            archive_dir: Directory for archives (default logs/archive/)
            batch_size: Process in batches of this size

        Returns:
            Summary of cleanup operation
        """
        if archive_dir is None:
            archive_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'logs', 'archive'
            )

        result = {
            "archived_count": 0,
            "deleted_count": 0,
            "archive_files": [],
            "initial_count": 0,
            "final_count": 0
        }

        try:
            result["initial_count"] = ProcessLogRepository.get_count(db)

            # Phase 1: Archive logs older than retention_days
            old_logs = ProcessLogRepository.get_older_than(db, retention_days, batch_size)
            while old_logs:
                archive_path = ProcessLogRepository.archive_logs(db, old_logs, archive_dir)
                if archive_path and archive_path not in result["archive_files"]:
                    result["archive_files"].append(archive_path)

                log_ids = [log.id for log in old_logs]
                deleted = ProcessLogRepository.delete_logs(db, log_ids)
                result["archived_count"] += len(old_logs)
                result["deleted_count"] += deleted

                # Get next batch
                old_logs = ProcessLogRepository.get_older_than(db, retention_days, batch_size)

            # Phase 2: If still over max_count, archive oldest
            current_count = ProcessLogRepository.get_count(db)
            while current_count > max_count:
                excess = current_count - max_count
                batch_to_archive = min(excess, batch_size)

                # Get oldest logs
                oldest_logs = db.query(ProcessLog).order_by(
                    ProcessLog.created_at.asc()
                ).limit(batch_to_archive).all()

                if not oldest_logs:
                    break

                archive_path = ProcessLogRepository.archive_logs(db, oldest_logs, archive_dir)
                if archive_path and archive_path not in result["archive_files"]:
                    result["archive_files"].append(archive_path)

                log_ids = [log.id for log in oldest_logs]
                deleted = ProcessLogRepository.delete_logs(db, log_ids)
                result["archived_count"] += len(oldest_logs)
                result["deleted_count"] += deleted

                current_count = ProcessLogRepository.get_count(db)

            result["final_count"] = ProcessLogRepository.get_count(db)
            logger.info(
                f"ProcessLog cleanup: archived={result['archived_count']}, "
                f"deleted={result['deleted_count']}, "
                f"count {result['initial_count']} -> {result['final_count']}"
            )

            return result

        except Exception as e:
            logger.error(f"Error during ProcessLog cleanup: {e}")
            raise


# Wafer Repository with full CRUD operations
class WaferRepository:
    # Valid wafer status values
    VALID_STATUSES = ["created", "picked", "dropped", "completed", "failed"]

    @staticmethod
    def create(db: Session, wafer_pos: int, status: str = "created", tray_id: int = None, carousel_id: int = None, meca_id: int = None, ot2_id: int = None, thorium_id: int = None):
        """Create a new wafer record."""
        try:
            wafer = Wafer(
                wafer_pos=wafer_pos,
                status=status,
                tray_id=tray_id,
                carousel_id=carousel_id,
                meca_id=meca_id,
                ot2_id=ot2_id,
                thorium_id=thorium_id
            )
            db.add(wafer)
            db.commit()
            db.refresh(wafer)
            logger.debug(f"Created wafer: pos={wafer_pos}, status={status}, id={wafer.id}")
            return wafer
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error creating wafer: {str(e)}")
            raise

    @staticmethod
    def get_by_id(db: Session, wafer_id: int):
        """Get a wafer by ID."""
        return db.query(Wafer).filter(Wafer.id == wafer_id).first()

    @staticmethod
    def get_by_position(db: Session, wafer_pos: int):
        """Get a wafer by position number."""
        return db.query(Wafer).filter(Wafer.wafer_pos == wafer_pos).first()

    @staticmethod
    def get_by_status(db: Session, status: str):
        """Get all wafers with a specific status."""
        return db.query(Wafer).filter(Wafer.status == status).order_by(Wafer.wafer_pos).all()

    @staticmethod
    def get_current_processing(db: Session):
        """Get the currently processing wafer (status='picked')."""
        return db.query(Wafer).filter(Wafer.status == "picked").order_by(Wafer.updated_at.desc()).first()

    @staticmethod
    def get_in_progress(db: Session):
        """Get all wafers currently being processed (not created, not completed, not failed)."""
        return db.query(Wafer).filter(
            Wafer.status.in_(["picked", "dropped"])
        ).order_by(Wafer.wafer_pos).all()

    @staticmethod
    def update_status(db: Session, wafer_id: int, status: str):
        """Update a wafer's status."""
        if status not in WaferRepository.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {WaferRepository.VALID_STATUSES}")
        try:
            wafer = db.query(Wafer).filter(Wafer.id == wafer_id).first()
            if wafer:
                old_status = wafer.status
                wafer.status = status
                wafer.updated_at = datetime.now()
                db.commit()
                db.refresh(wafer)
                logger.info(f"Updated wafer {wafer_id} status: {old_status} -> {status}")
                return wafer
            return None
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error updating wafer status: {str(e)}")
            raise

    @staticmethod
    def update_status_by_position(db: Session, wafer_pos: int, status: str):
        """Update a wafer's status by position number."""
        if status not in WaferRepository.VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}. Must be one of {WaferRepository.VALID_STATUSES}")
        try:
            wafer = db.query(Wafer).filter(Wafer.wafer_pos == wafer_pos).first()
            if wafer:
                old_status = wafer.status
                wafer.status = status
                wafer.updated_at = datetime.now()
                db.commit()
                db.refresh(wafer)
                logger.info(f"Updated wafer pos={wafer_pos} status: {old_status} -> {status}")
                return wafer
            return None
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error updating wafer status by position: {str(e)}")
            raise

    @staticmethod
    def get_or_create(db: Session, wafer_pos: int, **kwargs):
        """Get existing wafer by position or create new one."""
        wafer = WaferRepository.get_by_position(db, wafer_pos)
        if wafer:
            return wafer, False  # (wafer, created)
        wafer = WaferRepository.create(db, wafer_pos, **kwargs)
        return wafer, True

    @staticmethod
    def get_all(db: Session, skip: int = 0, limit: int = 100):
        """Get all wafers with pagination."""
        return db.query(Wafer).order_by(Wafer.wafer_pos).offset(skip).limit(limit).all()

    @staticmethod
    def delete(db: Session, wafer_id: int):
        """Delete a wafer."""
        try:
            wafer = db.query(Wafer).filter(Wafer.id == wafer_id).first()
            if wafer:
                db.delete(wafer)
                db.commit()
                logger.debug(f"Deleted wafer ID {wafer_id}")
                return True
            return False
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error deleting wafer: {str(e)}")
            raise


class ThoriumVialRepository:
    @staticmethod
    def create(db: Session, vial_serial_number: str, initial_volume: float, current_volume: float = None):
        """Create a new thorium vial record."""
        try:
            vial = ThoriumVial(
                vial_serial_number=vial_serial_number,
                initial_volume=initial_volume,
                current_volume=current_volume or initial_volume
            )
            db.add(vial)
            db.commit()
            db.refresh(vial)
            logger.debug(f"Created thorium vial: {vial_serial_number}")
            return vial
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error creating thorium vial: {str(e)}")
            raise

    @staticmethod
    def get_by_id(db: Session, vial_id: int):
        """Get a thorium vial by ID."""
        return db.query(ThoriumVial).filter(ThoriumVial.id == vial_id).first()

    @staticmethod
    def get_by_serial(db: Session, serial_number: str):
        """Get a thorium vial by serial number."""
        return db.query(ThoriumVial).filter(ThoriumVial.vial_serial_number == serial_number).first()


class BakingTrayRepository:
    @staticmethod
    def create(db: Session, tray_serial_number: str, capacity: int = 55):
        """Create a new baking tray record."""
        try:
            tray = BakingTray(
                tray_serial_number=tray_serial_number,
                capacity=capacity
            )
            db.add(tray)
            db.commit()
            db.refresh(tray)
            logger.debug(f"Created baking tray: {tray_serial_number}")
            return tray
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error creating baking tray: {str(e)}")
            raise

    @staticmethod
    def get_by_id(db: Session, tray_id: int):
        """Get a baking tray by ID."""
        return db.query(BakingTray).filter(BakingTray.id == tray_id).first()

    @staticmethod
    def get_by_serial(db: Session, serial_number: str):
        """Get a baking tray by serial number."""
        return db.query(BakingTray).filter(BakingTray.tray_serial_number == serial_number).first()


class CarouselRepository:
    @staticmethod
    def create(db: Session, carousel_serial_number: str, tray_id: int = None):
        """Create a new carousel record."""
        try:
            carousel = Carousel(
                carousel_serial_number=carousel_serial_number,
                tray_id=tray_id
            )
            db.add(carousel)
            db.commit()
            db.refresh(carousel)
            logger.debug(f"Created carousel: {carousel_serial_number}")
            return carousel
        except SQLAlchemyError as e:
            db.rollback()
            logger.error(f"Database error creating carousel: {str(e)}")
            raise

    @staticmethod
    def get_by_id(db: Session, carousel_id: int):
        """Get a carousel by ID."""
        return db.query(Carousel).filter(Carousel.id == carousel_id).first()

    @staticmethod
    def get_by_serial(db: Session, serial_number: str):
        """Get a carousel by serial number."""
        return db.query(Carousel).filter(Carousel.carousel_serial_number == serial_number).first()