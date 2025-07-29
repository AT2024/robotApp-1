#!/usr/bin/env python3
"""
Direct test of mecademicpy robot connection.
This script tests the robot connection outside the application to isolate the issue.
"""

import time
import sys
import traceback

try:
    from mecademicpy.robot import Robot as MecademicRobot
    print("✅ mecademicpy library imported successfully")
except ImportError as e:
    print(f"❌ Failed to import mecademicpy: {e}")
    sys.exit(1)

def test_robot_connection():
    """Test basic robot connection and activation"""
    robot = None
    
    try:
        print("\n🔄 Testing MECA Robot Connection...")
        print("=" * 50)
        
        # Create robot instance
        print("1. Creating robot instance...")
        robot = MecademicRobot()
        print("   ✅ Robot instance created")
        
        # Connect to robot
        print("2. Connecting to robot at 192.168.0.100...")
        robot.Connect(address='192.168.0.100', port=10000, timeout=30)
        print("   ✅ Connected to robot")
        
        # Get robot info before activation
        print("3. Getting robot information...")
        try:
            # Try to get basic status
            if hasattr(robot, 'GetStatusRobot'):
                status = robot.GetStatusRobot()
                print(f"   📊 Robot status: {status}")
            
            if hasattr(robot, 'GetRobotInfo'):
                info = robot.GetRobotInfo()
                print(f"   📋 Robot info: {info}")
                
        except Exception as info_error:
            print(f"   ⚠️ Could not get robot info: {info_error}")
        
        # Test activation
        print("4. Testing robot activation...")
        try:
            robot.ActivateRobot()
            print("   ✅ Robot activation successful!")
            
            # Wait a moment for activation to complete
            time.sleep(2)
            
            # Check if activation was successful
            if hasattr(robot, 'GetStatusRobot'):
                status = robot.GetStatusRobot()
                print(f"   📊 Post-activation status: {status}")
            
        except Exception as activation_error:
            print(f"   ❌ Robot activation failed: {type(activation_error).__name__}: {activation_error}")
            print("   📋 Full error traceback:")
            traceback.print_exc()
            return False
        
        # Test basic movement (if activation worked)
        print("5. Testing basic robot operations...")
        try:
            if hasattr(robot, 'Home'):
                print("   🏠 Attempting to home robot...")
                robot.Home()
                print("   ✅ Home command sent")
                
        except Exception as home_error:
            print(f"   ⚠️ Home command failed: {home_error}")
        
        print("\n🎉 Robot test completed successfully!")
        return True
        
    except Exception as main_error:
        print(f"\n❌ Connection test failed: {type(main_error).__name__}: {main_error}")
        print("📋 Full error traceback:")
        traceback.print_exc()
        return False
        
    finally:
        # Cleanup
        if robot:
            try:
                print("\n🔧 Cleaning up connection...")
                if hasattr(robot, 'Disconnect'):
                    robot.Disconnect()
                    print("   ✅ Disconnected from robot")
            except Exception as cleanup_error:
                print(f"   ⚠️ Cleanup error: {cleanup_error}")

def check_library_info():
    """Check mecademicpy library version and info"""
    print("\n📚 Library Information:")
    print("=" * 50)
    
    try:
        import mecademicpy
        if hasattr(mecademicpy, '__version__'):
            print(f"mecademicpy version: {mecademicpy.__version__}")
        else:
            print("mecademicpy version: Unknown")
            
        # Check available methods
        robot = MecademicRobot()
        methods = [method for method in dir(robot) if not method.startswith('_')]
        print(f"Available methods: {len(methods)}")
        print(f"Key methods: {[m for m in methods if m in ['Connect', 'ActivateRobot', 'Home', 'GetStatusRobot']]}")
        
    except Exception as e:
        print(f"Could not get library info: {e}")

if __name__ == "__main__":
    print("🤖 MECA Robot Direct Connection Test")
    print("=" * 50)
    
    # Check library info first
    check_library_info()
    
    # Run connection test
    success = test_robot_connection()
    
    if success:
        print("\n✅ All tests passed! Robot connection is working.")
        sys.exit(0)
    else:
        print("\n❌ Tests failed. Check the error messages above.")
        sys.exit(1)