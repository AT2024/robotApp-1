from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL", "mysql+pymysql://user:password@localhost/windsurf"
)

# Async database URL (convert mysql+pymysql to mysql+aiomysql for async)
ASYNC_DATABASE_URL = DATABASE_URL.replace("mysql+pymysql://", "mysql+aiomysql://")

# Create SQLAlchemy engine with optimized connection pooling
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # Verify connections before using
    pool_recycle=3600,       # Recycle connections after 1 hour
    pool_size=20,            # Number of persistent connections
    max_overflow=30,         # Additional connections when pool is full
    pool_timeout=30,         # Timeout when getting connection from pool
    echo=False               # Set to True for SQL query logging
)

# Async engine with connection pooling for performance
async_engine = create_async_engine(
    ASYNC_DATABASE_URL,
    pool_pre_ping=True,      # Verify connections before using
    pool_recycle=3600,       # Recycle connections after 1 hour
    pool_size=15,            # Number of persistent connections (smaller for async)
    max_overflow=25,         # Additional connections when pool is full
    pool_timeout=30,         # Timeout when getting connection from pool
    echo=False               # Set to True for SQL query logging
)

# Session factories
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Base class for all models
Base = declarative_base()

# Database session dependencies
def get_db():
    """Synchronous database session dependency"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def get_async_db():
    """Asynchronous database session dependency"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# Database health check
async def check_database_health():
    """Check database connection health"""
    try:
        async with AsyncSessionLocal() as session:
            # Simple query to test connection
            result = await session.execute("SELECT 1")
            return {"healthy": True, "connection": "async"}
    except Exception as e:
        return {"healthy": False, "error": str(e), "connection": "async"}

# Connection pool statistics
def get_connection_pool_stats():
    """Get connection pool statistics"""
    pool = engine.pool
    async_pool = async_engine.pool
    
    return {
        "sync_pool": {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "invalid": pool.invalid()
        },
        "async_pool": {
            "size": async_pool.size(),
            "checked_in": async_pool.checkedin(),
            "checked_out": async_pool.checkedout(),
            "overflow": async_pool.overflow(),
            "invalid": async_pool.invalid()
        }
    }