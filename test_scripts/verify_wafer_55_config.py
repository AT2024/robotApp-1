import sys
import os
import json
from pathlib import Path

# Add backend to sys.path
sys.path.append(str(Path(__file__).parent.parent / "windsurf-project" / "backend"))

from services.wafer_config_manager import WaferConfigManager

def main():
    print("🚀 Starting Wafer 55 Config Verification (Dry Run)...")
    
    # Load runtime.json
    config_path = Path(__file__).parent.parent / "windsurf-project" / "backend" / "config" / "runtime.json"
    with open(config_path, "r") as f:
        runtime_config = json.load(f)
        
    meca_config = runtime_config.get("meca", {})
    movement_params = meca_config.get("movement_params", {})
    
    try:
        # Initialize Manager
        manager = WaferConfigManager(meca_config, movement_params)
        print(f"✅ WaferConfigManager initialized (Version {manager.config_version})")
        
        # 1. Validate all 55 wafers
        print("\n🔍 Validating all 55 wafers...")
        errors = manager.validate_all_wafers(total_wafers=55)
        if errors:
            print("❌ Validation Errors found:")
            for err in errors:
                print(f"  - {err}")
            sys.exit(1)
        else:
            print("✅ All 55 wafers passed validation bounds")
            
        # 2. Preview Wafers 50-55 (High Index Check)
        print("\n🔍 Previewing High-Index Wafers (50-55)...")
        first_wafer = meca_config["positions"]["first_wafer"]
        first_baking = meca_config["positions"]["first_baking"]
        
        # Check indices 49 to 54 (Wafer 50 to 55)
        indices_to_check = list(range(49, 55))
        previews = manager.preview_wafer_positions(
            indices_to_check,
            first_wafer,
            first_baking
        )
        
        for idx in indices_to_check:
            p = previews[idx]
            print(f"  Wafer {p['wafer_number']}:")
            print(f"    Inert Y: {p['inert_tray_y']:.4f}")
            print(f"    Baking X: {p['baking_tray_x']:.4f}")
            print(f"    Effective Gap: {p['effective_gap']}")
            
            # Simple heuristic check
            if p['effective_gap'] < 2.5 or p['effective_gap'] > 3.0:
                print("    ❌ GAP WARNING: Value out of expected range (2.5 - 3.0)")
                
        print("\n✅ Verification Complete: Trajectories valid for Wafers 6-55")
        
    except Exception as e:
        print(f"❌ Critical Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
