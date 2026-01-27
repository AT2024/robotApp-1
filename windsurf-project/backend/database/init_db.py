from .db_config import engine, Base, SessionLocal
from .models import Robot, Config, ProcessLog, ThoriumVial, Wafer, BakingTray, Carousel
from core.settings import get_settings

from utils.logger import get_logger

logger = get_logger("init_db")


def init_db():
    """Create all tables in the database."""
    try:
        logger.info("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise


def seed_initial_data():
    """Seed the database with initial data if needed."""
    try:
        db = SessionLocal()

        # Check if we already have data
        existing_robots = db.query(Robot).count()
        if existing_robots > 0:
            logger.info("Database already contains data, skipping seed")
            return

        # Example: Create initial robots
        meca_robot = Robot(name="MECA")
        ot2_robot = Robot(name="OT2")

        db.add(meca_robot)
        db.add(ot2_robot)
        db.commit()

        # Refresh to get IDs
        db.refresh(meca_robot)
        db.refresh(ot2_robot)

        # Get settings for configuration values
        settings = get_settings()

        # Example: Add some configurations
        # For MECA robot
        meca_configs = [
            Config(id=meca_robot.id, param="ip", value=str(settings.meca_ip)),
            Config(id=meca_robot.id, param="port", value=str(settings.meca_port)),
        ]

        # For OT2 robot
        ot2_configs = [
            Config(id=ot2_robot.id, param="ip", value=str(settings.ot2_ip)),
            Config(id=ot2_robot.id, param="port", value=str(settings.ot2_port)),
        ]

        db.add_all(meca_configs + ot2_configs)
        db.commit()

        logger.info("Initial data seeded successfully")
    except Exception as e:
        logger.error(f"Error seeding initial data: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def init_and_seed_db():
    """Initialize and seed the database."""
    init_db()
    seed_initial_data()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_and_seed_db()
