#!/usr/bin/env python3
"""
WSL2 Network Fix Verification Script

This script tests the WSL2 port forwarding solution for Mecademic robot connectivity.

Run AFTER setting up Windows port forwarding:
1. Run PowerShell as Admin
2. Execute the port forwarding commands
3. Run this script to verify the fix

Usage:
    python3 test_wsl2_fix.py
"""

import asyncio
import time
import socket

async def test_connection(host: str, port: int, timeout: float = 5.0):
    """Test TCP connection to host:port"""
    try:
        print(f"🔍 Testing connection to {host}:{port} (timeout: {timeout}s)...")
        start_time = time.time()
        
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout
        )
        
        duration = time.time() - start_time
        
        if writer:
            writer.close()
            await writer.wait_closed()
        
        print(f"✅ SUCCESS: Connected to {host}:{port} in {duration:.3f}s")
        return True, duration
        
    except asyncio.TimeoutError:
        duration = time.time() - start_time
        print(f"❌ TIMEOUT: Connection to {host}:{port} failed after {duration:.3f}s")
        return False, duration
    except ConnectionRefusedError:
        duration = time.time() - start_time
        print(f"❌ REFUSED: Connection to {host}:{port} refused after {duration:.3f}s")
        return False, duration
    except Exception as e:
        duration = time.time() - start_time
        print(f"❌ ERROR: Connection to {host}:{port} failed: {e}")
        return False, duration

def get_network_info():
    """Get current network configuration"""
    try:
        # Get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except:
        return "Unknown"

async def main():
    """Main test function"""
    print("=" * 70)
    print("🔧 WSL2 MECADEMIC ROBOT NETWORK FIX VERIFICATION")
    print("=" * 70)
    
    # Show network info
    local_ip = get_network_info()
    print(f"📍 WSL2 IP: {local_ip}")
    print(f"📍 Target: Windows Host Gateway (should forward to robot)")
    print()
    
    # Test targets
    windows_host = "172.31.64.1"  # Windows host gateway
    original_robot = "192.168.0.100"  # Original robot IP
    
    print("🧪 TESTING WSL2 PORT FORWARDING FIX:")
    print("-" * 50)
    
    # Test Windows host forwarding (the fix)
    print(f"\n1️⃣ Testing Windows Host Port Forwarding:")
    host_10000, host_time_10000 = await test_connection(windows_host, 10000)
    host_10001, host_time_10001 = await test_connection(windows_host, 10001)
    
    # Test direct robot access (should still fail)
    print(f"\n2️⃣ Testing Direct Robot Access (expected to fail):")
    direct_10000, direct_time_10000 = await test_connection(original_robot, 10000, timeout=3.0)
    direct_10001, direct_time_10001 = await test_connection(original_robot, 10001, timeout=3.0)
    
    # Results summary
    print("\n" + "=" * 70)
    print("📊 TEST RESULTS SUMMARY")
    print("=" * 70)
    
    if host_10000 and host_10001:
        print("✅ PORT FORWARDING WORKING!")
        print("   - Windows host successfully forwards robot ports")
        print("   - WSL2 can now communicate with Mecademic robot")
        print("   - Robot should appear as 'connected' in application")
        print()
        print("🚀 NEXT STEPS:")
        print("   1. Restart the robotics application")
        print("   2. Check logs for successful robot connection") 
        print("   3. Test robot activation and pickup sequences")
        
    elif host_10000 or host_10001:
        print("⚠️ PARTIAL SUCCESS:")
        print(f"   - Port 10000: {'✅ OK' if host_10000 else '❌ FAIL'}")
        print(f"   - Port 10001: {'✅ OK' if host_10001 else '❌ FAIL'}")
        print()
        print("🔧 ACTION NEEDED:")
        print("   - Check Windows port forwarding commands")
        print("   - Verify Windows firewall rules")
        print("   - Ensure PowerShell was run as Administrator")
        
    else:
        print("❌ PORT FORWARDING NOT WORKING:")
        print("   - No robot ports accessible through Windows host")
        print()
        print("🚨 TROUBLESHOOTING:")
        print("   1. Run PowerShell as Administrator")
        print("   2. Execute all port forwarding commands")
        print("   3. Check Windows Firewall settings")
        print("   4. Verify robot is powered and on network")
        print("   5. Try alternative WSL2 bridge networking mode")
    
    # Show direct access results
    if not direct_10000 and not direct_10001:
        print(f"\n✅ Expected: Direct robot access blocked (WSL2 isolation)")
    else:
        print(f"\n⚠️ Unexpected: Direct robot access working (check network config)")
    
    print("\n📞 For additional help:")
    print("   - Check WSL2 networking documentation")  
    print("   - Consider bridge networking mode for permanent solution")
    print("   - Contact support if issues persist")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Test cancelled by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")