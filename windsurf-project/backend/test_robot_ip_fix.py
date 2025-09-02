#!/usr/bin/env python3
"""
Test to verify the robot IP configuration fix.
This tests basic connectivity to the actual robot IP.
"""

import asyncio
import socket
import sys
import os
import time

def test_tcp_connection(host, port, timeout=5.0):
    """Test basic TCP connectivity to robot"""
    print(f"Testing TCP connection to {host}:{port}...")
    
    try:
        # Create a socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        start_time = time.time()
        result = sock.connect_ex((host, port))
        duration = time.time() - start_time
        
        sock.close()
        
        if result == 0:
            print(f"✅ SUCCESS: Connected to {host}:{port} in {duration:.3f}s")
            return True
        else:
            print(f"❌ FAILED: Could not connect to {host}:{port} (error {result})")
            return False
            
    except socket.timeout:
        print(f"❌ TIMEOUT: Connection to {host}:{port} timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"❌ ERROR: Connection failed with error: {e}")
        return False

def test_robot_ip_configuration():
    """Test the robot IP configuration"""
    print("=" * 60)
    print("ROBOT IP CONFIGURATION TEST")
    print("=" * 60)
    
    # Configuration from .env
    ROBOT_IP = "192.168.0.100"
    CONTROL_PORT = 10000
    MONITOR_PORT = 10001
    OLD_WSL2_IP = "172.31.64.1"
    
    print(f"Robot IP: {ROBOT_IP}")
    print(f"Control Port: {CONTROL_PORT}")
    print(f"Monitor Port: {MONITOR_PORT}")
    print()
    
    # Test connectivity to actual robot
    print("1. Testing connection to ACTUAL robot IP...")
    control_ok = test_tcp_connection(ROBOT_IP, CONTROL_PORT)
    monitor_ok = test_tcp_connection(ROBOT_IP, MONITOR_PORT)
    
    print()
    print("2. Testing old WSL2 bridge IP (should fail)...")
    old_control_ok = test_tcp_connection(OLD_WSL2_IP, CONTROL_PORT, timeout=2.0)
    
    print()
    print("=" * 60)
    
    if control_ok and monitor_ok:
        print("✅ ROBOT IP FIX SUCCESSFUL!")
        print("- Robot is reachable at correct IP address")
        print("- Both control and monitor ports are accessible")
        print("- Native driver should now connect successfully")
        print("- Pickup sequences should work after restart!")
        
        print("\nNow restart your backend - the robot should connect!")
        return True
        
    elif not control_ok and not monitor_ok:
        print("❌ ROBOT NOT REACHABLE")
        print("Possible issues:")
        print("- Robot is powered off")
        print("- Robot is not on network 192.168.0.100")
        print("- Network connectivity issues")
        print("- Robot control software not running")
        
        if not old_control_ok:
            print("- WSL2 bridge is also not working (expected)")
            
        return False
    else:
        print("⚠️ PARTIAL CONNECTION")
        print("- Some ports reachable, others not")
        print("- Check robot control software status")
        return False

if __name__ == "__main__":
    success = test_robot_ip_configuration()
    sys.exit(0 if success else 1)