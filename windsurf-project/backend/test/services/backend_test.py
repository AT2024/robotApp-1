# backend_test.py
import asyncio
import websockets
import requests
import json
from datetime import datetime

BACKEND_HTTP_URL = "http://localhost:8000"
BACKEND_WS_URL = "ws://localhost:8000/ws"

def log_message(message, status="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {status}: {message}")

async def test_websocket_connection():
    """Test WebSocket connectivity and message handling"""
    try:
        log_message("Testing WebSocket connection...")
        async with websockets.connect(BACKEND_WS_URL) as websocket:
            log_message("WebSocket connected successfully")
            
            # Test message sending
            test_message = {"type": "get_status"}
            await websocket.send(json.dumps(test_message))
            log_message("Sent test message")
            
            # Wait for response
            response = await websocket.recv()
            log_message(f"Received response: {response}")
            
            return True
    except Exception as e:
        log_message(f"WebSocket connection failed: {str(e)}", "ERROR")
        return False

def test_http_endpoints():
    """Test various HTTP endpoints"""
    endpoints = {
        "health": "/health",
        "meca_status": "/api/meca/status",
        "ot2_status": "/api/ot2/status",
        "arduino_status": "/api/arduino/status"
    }
    
    results = {}
    for name, endpoint in endpoints.items():
        try:
            response = requests.get(f"{BACKEND_HTTP_URL}{endpoint}")
            status = "SUCCESS" if response.status_code == 200 else "FAILED"
            results[name] = {
                "status": status,
                "status_code": response.status_code,
                "response": response.json() if response.status_code == 200 else None
            }
            log_message(f"Endpoint {name}: {status}")
        except requests.exceptions.RequestException as e:
            log_message(f"Failed to connect to {name} endpoint: {str(e)}", "ERROR")
            results[name] = {
                "status": "ERROR",
                "error": str(e)
            }
    
    return results

def check_server_process():
    """Check if the server process is running"""
    import psutil
    
    server_processes = []
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'python' in proc.info['name'].lower():
                cmdline = ' '.join(proc.info['cmdline'] or [])
                if 'uvicorn' in cmdline or 'fastapi' in cmdline:
                    server_processes.append({
                        'pid': proc.info['pid'],
                        'cmdline': cmdline
                    })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    return server_processes

async def run_tests():
    """Run all backend tests"""
    log_message("Starting backend tests...")
    
    # Check server process
    log_message("Checking server process...")
    server_processes = check_server_process()
    if server_processes:
        log_message(f"Found {len(server_processes)} server processes:")
        for proc in server_processes:
            log_message(f"PID: {proc['pid']}, Command: {proc['cmdline']}")
    else:
        log_message("No server process found", "WARNING")
    
    # Test HTTP endpoints
    log_message("\nTesting HTTP endpoints...")
    http_results = test_http_endpoints()
    
    # Test WebSocket
    log_message("\nTesting WebSocket connection...")
    ws_success = await test_websocket_connection()
    
    # Print summary
    log_message("\n=== Test Summary ===")
    log_message(f"Server Process: {'Found' if server_processes else 'Not Found'}")
    log_message(f"WebSocket: {'Success' if ws_success else 'Failed'}")
    log_message("HTTP Endpoints:")
    for endpoint, result in http_results.items():
        status = result['status']
        log_message(f"  - {endpoint}: {status}")

if __name__ == "__main__":
    # Run all tests
    asyncio.run(run_tests())