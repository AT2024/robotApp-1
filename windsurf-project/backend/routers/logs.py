"""
Router for log management endpoints.

Provides endpoints for:
- Listing and reading log files
- Searching logs by pattern, correlation_id, wafer_id, level
- Tracing operations by correlation ID
- Log statistics
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional, Dict, Any
import os
import re
import json
from datetime import datetime
from collections import Counter
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


def _parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Parse a log line into structured data.
    Handles both text format and JSON format.

    Args:
        line: Raw log line

    Returns:
        Parsed log entry or None if parsing fails
    """
    line = line.strip()
    if not line:
        return None

    # Try JSON format first
    if line.startswith('{'):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            pass

    # Parse text format: timestamp - logger - level - func:line - message
    # Example: 2026-01-29 10:15:32,123 - meca_service - INFO - execute_pickup:123 - Message
    text_pattern = r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - (\w+) - (\w+):(\d+) - (.*)$'
    match = re.match(text_pattern, line)
    if match:
        return {
            "timestamp": match.group(1),
            "logger": match.group(2),
            "level": match.group(3),
            "func": match.group(4),
            "line": int(match.group(5)),
            "message": match.group(6),
            "raw": line
        }

    # Simpler text format: timestamp - logger - level - message
    simple_pattern = r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) - (\w+) - (\w+) - (.*)$'
    match = re.match(simple_pattern, line)
    if match:
        return {
            "timestamp": match.group(1),
            "logger": match.group(2),
            "level": match.group(3),
            "message": match.group(4),
            "raw": line
        }

    # Return raw line if parsing fails
    return {"raw": line}


def _search_log_file(
    file_path: str,
    pattern: Optional[str] = None,
    correlation_id: Optional[str] = None,
    wafer_id: Optional[int] = None,
    level: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Search a log file with filters.

    Args:
        file_path: Path to log file
        pattern: Regex pattern to match in message
        correlation_id: Filter by correlation ID
        wafer_id: Filter by wafer ID
        level: Filter by log level
        limit: Maximum results

    Returns:
        List of matching log entries
    """
    results = []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if len(results) >= limit:
                    break

                entry = _parse_log_line(line)
                if entry is None:
                    continue

                # Apply filters
                if pattern:
                    message = entry.get("message", entry.get("raw", ""))
                    if not re.search(pattern, message, re.IGNORECASE):
                        continue

                if correlation_id:
                    if entry.get("correlation_id") != correlation_id:
                        # Also check message for correlation ID (text format)
                        if correlation_id not in entry.get("message", ""):
                            continue

                if wafer_id is not None:
                    entry_wafer = entry.get("wafer_id")
                    if entry_wafer != wafer_id:
                        # Also check message for wafer references
                        if f"wafer={wafer_id}" not in entry.get("message", "").lower():
                            if f"wafer {wafer_id}" not in entry.get("message", "").lower():
                                continue

                if level:
                    if entry.get("level", "").upper() != level.upper():
                        continue

                results.append(entry)

    except Exception as e:
        logger.warning(f"Error searching log file {file_path}: {e}")

    return results


@router.get("/search")
async def search_logs(
    pattern: Optional[str] = Query(None, description="Regex pattern to search in log messages"),
    correlation_id: Optional[str] = Query(None, description="Filter by correlation ID"),
    wafer_id: Optional[int] = Query(None, description="Filter by wafer ID"),
    level: Optional[str] = Query(None, description="Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"),
    filename: Optional[str] = Query(None, description="Specific log file to search (default: all)"),
    limit: int = Query(100, description="Maximum number of results", ge=1, le=1000)
) -> Dict[str, Any]:
    """
    Search logs with optional filters.

    Supports searching by:
    - pattern: Regex pattern matching in log messages
    - correlation_id: Filter by operation correlation ID
    - wafer_id: Filter by wafer being processed
    - level: Filter by log level
    """
    try:
        if not os.path.exists(LOGS_DIR):
            return {"status": "success", "data": [], "count": 0}

        # Determine which files to search
        if filename:
            files = [os.path.join(LOGS_DIR, filename)]
            if not os.path.exists(files[0]):
                raise HTTPException(status_code=404, detail=f"Log file '{filename}' not found")
        else:
            files = [
                os.path.join(LOGS_DIR, f)
                for f in os.listdir(LOGS_DIR)
                if f.endswith('.log')
            ]

        all_results = []
        for file_path in files:
            results = _search_log_file(
                file_path,
                pattern=pattern,
                correlation_id=correlation_id,
                wafer_id=wafer_id,
                level=level,
                limit=limit - len(all_results)
            )
            all_results.extend(results)
            if len(all_results) >= limit:
                break

        return {
            "status": "success",
            "data": all_results[:limit],
            "count": len(all_results),
            "filters": {
                "pattern": pattern,
                "correlation_id": correlation_id,
                "wafer_id": wafer_id,
                "level": level,
                "filename": filename
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trace/{correlation_id}")
async def trace_operation(
    correlation_id: str,
    limit: int = Query(500, description="Maximum number of log entries", ge=1, le=2000)
) -> Dict[str, Any]:
    """
    Get all log entries for a specific correlation ID.

    Useful for tracing an entire operation (pickup, drop, carousel)
    from start to finish across all services.
    """
    try:
        result = await search_logs(correlation_id=correlation_id, limit=limit)
        return {
            "status": "success",
            "correlation_id": correlation_id,
            "data": result["data"],
            "count": result["count"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error tracing operation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/wafer/{wafer_id}/logs")
async def get_wafer_logs(
    wafer_id: int,
    limit: int = Query(200, description="Maximum number of log entries", ge=1, le=1000)
) -> Dict[str, Any]:
    """
    Get all log entries related to a specific wafer.

    Returns logs mentioning the wafer ID across all log files.
    """
    try:
        result = await search_logs(wafer_id=wafer_id, limit=limit)
        return {
            "status": "success",
            "wafer_id": wafer_id,
            "data": result["data"],
            "count": result["count"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting wafer logs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_log_stats() -> Dict[str, Any]:
    """
    Get statistics about log files.

    Returns:
    - Total size of all log files
    - Count by log level
    - Recent error count
    """
    try:
        if not os.path.exists(LOGS_DIR):
            return {
                "status": "success",
                "data": {
                    "total_size_bytes": 0,
                    "file_count": 0,
                    "files": []
                }
            }

        file_stats = []
        total_size = 0
        level_counts: Counter = Counter()

        for filename in os.listdir(LOGS_DIR):
            if not filename.endswith('.log'):
                continue

            file_path = os.path.join(LOGS_DIR, filename)
            size = os.path.getsize(file_path)
            mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            total_size += size

            # Count log levels (sample first 1000 lines for performance)
            file_level_counts: Counter = Counter()
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f):
                        if i >= 1000:
                            break
                        entry = _parse_log_line(line)
                        if entry and "level" in entry:
                            file_level_counts[entry["level"]] += 1
            except Exception:
                pass

            level_counts.update(file_level_counts)

            file_stats.append({
                "filename": filename,
                "size_bytes": size,
                "size_human": _format_size(size),
                "modified": mtime.isoformat(),
                "level_counts": dict(file_level_counts)
            })

        return {
            "status": "success",
            "data": {
                "total_size_bytes": total_size,
                "total_size_human": _format_size(total_size),
                "file_count": len(file_stats),
                "level_counts": dict(level_counts),
                "files": file_stats
            }
        }

    except Exception as e:
        logger.error(f"Error getting log stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


@router.post("/processlog/cleanup")
async def run_processlog_cleanup(
    retention_days: int = Query(90, description="Keep logs newer than this many days", ge=1, le=365),
    max_count: int = Query(100000, description="Maximum records to keep", ge=1000, le=1000000)
) -> Dict[str, Any]:
    """
    Manually trigger ProcessLog database cleanup.

    Archives old logs to JSON files and removes them from the database.
    Uses combined time and count-based retention:
    1. Archive logs older than retention_days
    2. If still over max_count, archive oldest until under limit
    """
    try:
        from database.database import get_db
        from database.repositories import ProcessLogRepository

        archive_dir = os.getenv('ROBOTICS_PROCESSLOG_ARCHIVE_DIR', 'logs/archive/')

        db = next(get_db())
        try:
            result = ProcessLogRepository.cleanup_old_logs(
                db,
                retention_days=retention_days,
                max_count=max_count,
                archive_dir=archive_dir
            )
            return {
                "status": "success",
                "data": result,
                "message": f"Cleanup completed: archived {result['archived_count']} records"
            }
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error running ProcessLog cleanup: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/processlog/stats")
async def get_processlog_stats() -> Dict[str, Any]:
    """
    Get statistics about ProcessLog database table.

    Returns record count and size information.
    """
    try:
        from database.database import get_db
        from database.repositories import ProcessLogRepository

        db = next(get_db())
        try:
            count = ProcessLogRepository.get_count(db)
            recent = ProcessLogRepository.get_recent(db, limit=1)

            result = {
                "total_count": count,
                "oldest_log": None,
                "newest_log": None
            }

            if recent:
                result["newest_log"] = recent[0].created_at.isoformat() if recent[0].created_at else None

            # Get oldest log
            from database.models import ProcessLog
            oldest = db.query(ProcessLog).order_by(ProcessLog.created_at.asc()).first()
            if oldest and oldest.created_at:
                result["oldest_log"] = oldest.created_at.isoformat()

            return {"status": "success", "data": result}
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error getting ProcessLog stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
