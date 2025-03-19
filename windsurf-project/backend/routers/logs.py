"""
Router for log management endpoints.
"""
from fastapi import APIRouter, HTTPException
from typing import List, Optional
import os
from datetime import datetime
from utils.logger import get_logger

router = APIRouter()
logger = get_logger("logs_router")

LOGS_DIR = "logs"

@router.get("/files")
async def get_log_files() -> List[str]:
    """Get list of available log files."""
    try:
        if not os.path.exists(LOGS_DIR):
            return []
        return [f for f in os.listdir(LOGS_DIR) if f.endswith('.log')]
    except Exception as e:
        logger.error(f"Error getting log files: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/content/{filename}")
async def get_log_content(filename: str, lines: Optional[int] = None):
    """Get content of a specific log file."""
    try:
        file_path = os.path.join(LOGS_DIR, filename)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Log file '{filename}' not found")
        
        with open(file_path, 'r') as f:
            if lines:
                # Read last N lines if specified
                content = list(f.readlines())[-lines:]
            else:
                content = f.readlines()
        
        return {"status": "success", "data": content}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading log file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files/{filename}")
async def delete_log_file(filename: str):
    """Delete a specific log file."""
    try:
        file_path = os.path.join(LOGS_DIR, filename)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Log file '{filename}' not found")
        
        os.remove(file_path)
        return {"status": "success", "message": f"Log file '{filename}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting log file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files")
async def clear_logs(days: Optional[int] = None):
    """Clear all logs or logs older than specified days."""
    try:
        if not os.path.exists(LOGS_DIR):
            return {"status": "success", "message": "No logs to clear"}

        files_deleted = 0
        for filename in os.listdir(LOGS_DIR):
            if not filename.endswith('.log'):
                continue

            file_path = os.path.join(LOGS_DIR, filename)
            if days:
                # Check file age
                file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                age = (datetime.now() - file_time).days
                if age <= days:
                    continue

            os.remove(file_path)
            files_deleted += 1

        return {
            "status": "success",
            "message": f"Cleared {files_deleted} log files",
            "files_deleted": files_deleted
        }
    except Exception as e:
        logger.error(f"Error clearing logs: {e}")
        raise HTTPException(status_code=500, detail=str(e))
