from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from .db_config import Base
from datetime import datetime

class Robot(Base):
    __tablename__ = "ROBOT"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(25))
    
    # Relationships
    configs = relationship("Config", back_populates="robot", cascade="all, delete-orphan")
    process_logs = relationship("ProcessLog", back_populates="robot", cascade="all, delete-orphan")
    wafers_meca = relationship("Wafer", foreign_keys="[Wafer.meca_id]", back_populates="meca_robot", cascade="all, delete-orphan")
    wafers_ot2 = relationship("Wafer", foreign_keys="[Wafer.ot2_id]", back_populates="ot2_robot", cascade="all, delete-orphan")

class Config(Base):
    __tablename__ = "CONFIG"
    
    id = Column(Integer, ForeignKey("ROBOT.id"), primary_key=True)
    param = Column(String(255), primary_key=True)
    value = Column(String(255))
    
    # Relationships
    robot = relationship("Robot", back_populates="configs")

class ProcessLog(Base):
    __tablename__ = "PROCESSLOG"
    
    id = Column(Integer, primary_key=True, index=True)
    wafer_id = Column(Integer, ForeignKey("WAFER.id"))
    robot_id = Column(Integer, ForeignKey("ROBOT.id"))
    process_type = Column(String(255))
    cycle_number = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    wafer = relationship("Wafer", back_populates="process_logs")
    robot = relationship("Robot", back_populates="process_logs")
    
    # Strategic indexes for performance optimization
    __table_args__ = (
        # Index for querying logs by wafer and creation time (common query pattern)
        Index('idx_processlog_wafer_created', 'wafer_id', 'created_at'),
        # Index for querying logs by robot and process type (monitoring/analytics)
        Index('idx_processlog_robot_type', 'robot_id', 'process_type'),
        # Index for time-based queries (recent activities)
        Index('idx_processlog_created_at', 'created_at'),
        # Composite index for complex queries
        Index('idx_processlog_wafer_robot_created', 'wafer_id', 'robot_id', 'created_at'),
    )

class ThoriumVial(Base):
    __tablename__ = "THORIUM_VIAL"
    
    id = Column(Integer, primary_key=True, index=True)
    vial_serial_number = Column(String(50), unique=True, index=True)
    initial_volume = Column(Float)
    current_volume = Column(Float)
    opening_time = Column(DateTime, default=datetime.now)
    
    # Relationships
    wafers = relationship("Wafer", back_populates="thorium_vial", cascade="all, delete-orphan")

class Wafer(Base):
    __tablename__ = "WAFER"
    
    id = Column(Integer, primary_key=True, index=True)
    tray_id = Column(Integer, ForeignKey("BAKING_TRAY.id"))
    carousel_id = Column(Integer, ForeignKey("CAROUSEL.id"))
    meca_id = Column(Integer, ForeignKey("ROBOT.id"))
    ot2_id = Column(Integer, ForeignKey("ROBOT.id"))
    thorium_id = Column(Integer, ForeignKey("THORIUM_VIAL.id"))
    wafer_pos = Column(Integer)
    status = Column(String(50), default="created")  # Add status tracking
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)  # Add update tracking
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    tray = relationship("BakingTray", back_populates="wafers")
    carousel = relationship("Carousel", back_populates="wafers")
    meca_robot = relationship("Robot", foreign_keys=[meca_id], back_populates="wafers_meca")
    ot2_robot = relationship("Robot", foreign_keys=[ot2_id], back_populates="wafers_ot2")
    thorium_vial = relationship("ThoriumVial", back_populates="wafers")
    process_logs = relationship("ProcessLog", back_populates="wafer", cascade="all, delete-orphan")
    
    # Strategic indexes for performance optimization
    __table_args__ = (
        # Index for querying wafers by status and update time
        Index('idx_wafer_status_updated', 'status', 'updated_at'),
        # Index for tray-based queries
        Index('idx_wafer_tray_pos', 'tray_id', 'wafer_pos'),
        # Index for carousel operations
        Index('idx_wafer_carousel_created', 'carousel_id', 'created_at'),
        # Index for robot-based queries
        Index('idx_wafer_meca_status', 'meca_id', 'status'),
        Index('idx_wafer_ot2_status', 'ot2_id', 'status'),
    )

class BakingTray(Base):
    __tablename__ = "BAKING_TRAY"
    
    id = Column(Integer, primary_key=True, index=True)
    tray_serial_number = Column(String(50), unique=True, index=True)
    in_use = Column(Boolean, default=False)
    capacity = Column(Integer, default=55)
    next_pos = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)
    
    # Relationships
    wafers = relationship("Wafer", back_populates="tray", cascade="all, delete-orphan")
    carousels = relationship("Carousel", back_populates="tray", cascade="all, delete-orphan")

class Carousel(Base):
    __tablename__ = "CAROUSEL"
    
    id = Column(Integer, primary_key=True, index=True)
    carousel_serial_number = Column(String(50), unique=True, index=True)
    tray_id = Column(Integer, ForeignKey("BAKING_TRAY.id"))
    carousel_time = Column(DateTime, default=datetime.now)
    in_use = Column(Boolean, default=False)
    
    # Relationships
    tray = relationship("BakingTray", back_populates="carousels")
    wafers = relationship("Wafer", back_populates="carousel", cascade="all, delete-orphan")