#!/usr/bin/env python3
"""
Mecademic Robot Connection Diagnostics Tool

This standalone script tests connectivity to the Mecademic robot
and provides troubleshooting recommendations.

Usage:
    python test_robot_connectivity.py [robot_ip]
    
Example:
    python test_robot_connectivity.py 192.168.0.100
"""

import asyncio
import time
import sys
import subprocess
from typing import List, Tuple

async def test_ping(host: str) -> Tuple[bool, float, str]:
    """Test ping connectivity"""
    print(f"🔍 Testing ping to {host}...")
    ping_start = time.time()
    
    try:
        # Try Linux/Mac ping first
        try:
            ping_result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    'ping', '-c', '1', host,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                ),
                timeout=5.0
            )
        except FileNotFoundError:
            # Try Windows ping
            ping_result = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    'ping', '-n', '1', host,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                ),
                timeout=5.0
            )
        
        stdout, stderr = await ping_result.communicate()
        ping_duration = time.time() - ping_start
        
        if ping_result.returncode == 0:
            return True, ping_duration, "SUCCESS"
        else:
            return False, ping_duration, stderr.decode().strip()
            
    except Exception as e:
        ping_duration = time.time() - ping_start
        return False, ping_duration, str(e)

async def test_port(host: str, port: int) -> Tuple[bool, float, str]:
    """Test TCP port connectivity"""
    try:
        port_start = time.time()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=3.0
        )
        port_duration = time.time() - port_start
        
        if writer:
            writer.close()
            await writer.wait_closed()
        
        return True, port_duration, "OPEN"
        
    except asyncio.TimeoutError:
        port_duration = time.time() - port_start
        return False, port_duration, "TIMEOUT"
    except ConnectionRefusedError:
        port_duration = time.time() - port_start
        return False, port_duration, "CLOSED"
    except Exception as e:
        port_duration = time.time() - port_start
        return False, port_duration, str(e)

async def main():
    """Main diagnostic function"""
    # Get robot IP from command line or use default
    robot_ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.100"
    
    print("=" * 60)
    print("🤖 MECADEMIC ROBOT CONNECTION DIAGNOSTICS")
    print("=" * 60)
    print(f"Target Robot: {robot_ip}")
    print()
    
    # Test ping connectivity
    ping_success, ping_time, ping_msg = await test_ping(robot_ip)
    if ping_success:
        print(f"✅ Ping: SUCCESS ({ping_time:.3f}s)")
    else:
        print(f"❌ Ping: FAILED ({ping_time:.3f}s) - {ping_msg}")
        print("🚨 CRITICAL: Robot is not reachable on network!")
        print("   - Check robot power")
        print("   - Check network cables")
        print("   - Verify IP address")
        return
    
    print()
    
    # Test common robot ports
    ports_to_test = [
        (10000, "Mecademic Control Port"),
        (10001, "Mecademic Monitor Port"),
        (10002, "Mecademic Additional Port"),
        (80, "HTTP Web Interface"),
        (8080, "Alternative HTTP"),
        (23, "Telnet"),
        (443, "HTTPS")
    ]
    
    print("🔍 Testing Robot Ports:")
    print("-" * 40)
    
    open_ports = []
    closed_ports = []
    
    for port, description in ports_to_test:
        success, duration, status = await test_port(robot_ip, port)
        if success:
            print(f"✅ Port {port:5d}: {status:8s} ({duration:.3f}s) - {description}")
            open_ports.append((port, description))
        else:
            print(f"❌ Port {port:5d}: {status:8s} ({duration:.3f}s) - {description}")
            closed_ports.append((port, description))
    
    print()
    print("=" * 60)
    print("📊 DIAGNOSTIC RESULTS")
    print("=" * 60)
    
    if open_ports:
        print(f"✅ Open Ports ({len(open_ports)}):")
        for port, desc in open_ports:
            print(f"   - {port}: {desc}")
        print()
    
    if closed_ports:
        print(f"❌ Closed/Timeout Ports ({len(closed_ports)}):")
        for port, desc in closed_ports:
            print(f"   - {port}: {desc}")
        print()
    
    # Provide specific recommendations
    print("🛠️ TROUBLESHOOTING RECOMMENDATIONS:")
    print("-" * 40)
    
    if not any(port == 10000 for port, _ in open_ports):
        print("🚨 CRITICAL: Control port 10000 is closed!")
        print("   This is the main issue preventing robot communication.")
        print()
        print("📋 STEPS TO FIX:")
        print("   1. Check robot LED status (should show ready/active)")
        print("   2. Access robot web interface:")
        if any(port == 80 for port, _ in open_ports):
            print(f"      ✅ Try: http://{robot_ip}")
        else:
            print(f"      ❌ Web interface also unavailable at http://{robot_ip}")
        print("   3. Restart robot control software:")
        print("      - Look for 'Restart Control Software' in web interface")
        print("      - Or power cycle the robot completely")
        print("   4. Check robot firmware version")
        print("   5. Contact robot manufacturer if issue persists")
    
    elif any(port == 10000 for port, _ in open_ports):
        print("✅ Control port 10000 is working!")
        print("   The robot control software is running properly.")
        print("   Check your application configuration and logs.")
    
    print()
    print("📞 Additional Support:")
    print("   - Robot Manual: Check manufacturer documentation")
    print("   - Network Tools: Use ping, telnet, or nmap for deeper analysis")
    print("   - Robot Logs: Check robot's internal logs if accessible")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Diagnostic cancelled by user")
    except Exception as e:
        print(f"\n❌ Diagnostic failed: {e}")