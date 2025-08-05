#!/usr/bin/env python3
import asyncio
import json
import time
import subprocess
import sys

async def test_protocol_execution():
    """Test OT2 protocol execution using subprocess curl to simulate WebSocket"""
    print("🧪 Testing OT2 Protocol Execution with New Dual-Structure Upload Format")
    print("=" * 70)
    
    # Simulate WebSocket message by directly calling the backend through the protocol service
    # This will test our dual-structure upload fix
    
    command = [
        "docker", "exec", "robotics-backend", 
        "python", "-c", """
import asyncio
import sys
import os
sys.path.append('/app')

async def test_protocol():
    try:
        from services.ot2_service import OT2Service, ProtocolConfig
        from core.settings import get_settings
        from core.state_manager import AtomicStateManager
        from core.resource_lock import ResourceLockManager
        from pathlib import Path
        
        print('🔧 Initializing OT2 Service for testing...')
        
        # Initialize required components
        settings = get_settings()
        state_manager = AtomicStateManager()
        lock_manager = ResourceLockManager()
        
        # Create OT2 service
        ot2_service = OT2Service(
            robot_id='ot2',
            settings=settings,
            state_manager=state_manager,
            lock_manager=lock_manager
        )
        
        # Start the service
        await ot2_service._on_start()
        
        print('✅ OT2 Service initialized successfully')
        
        # Create protocol config
        protocol_config = ProtocolConfig(
            protocol_name='Test_Dual_Structure_Protocol',
            protocol_file='/app/protocols/ot2Protocole.py',
            parameters={
                'NUM_OF_GENERATORS': 5,
                'radioactive_VOL': 6.6,
                'SDS_VOL': 1.0
            },
            labware_setup={}
        )
        
        print('🧬 Starting protocol execution with dual-structure format...')
        
        # Execute protocol using our new dual-structure format
        result = await ot2_service.execute_protocol(protocol_config, monitor_progress=False)
        
        if result.success:
            print('✅ PROTOCOL EXECUTION SUCCESSFUL!')
            print(f'📊 Result: {result.data}')
            print('🎉 Dual-structure upload format is working!')
        else:
            print('❌ PROTOCOL EXECUTION FAILED')
            print(f'💥 Error: {result.error}')
            
        await ot2_service._on_stop()
        
    except Exception as e:
        print(f'💥 CRITICAL ERROR: {e}')
        import traceback
        traceback.print_exc()

asyncio.run(test_protocol())
"""
    ]
    
    print("🚀 Executing test inside backend container...")
    print("-" * 50)
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        print("STDOUT:")
        print(result.stdout)
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        print(f"Return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("⏰ Test timed out after 5 minutes")
    except Exception as e:
        print(f"❌ Test execution failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_protocol_execution())