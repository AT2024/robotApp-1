from opentrons import protocol_api
from opentrons.types import Point, Location
import os
import json
import importlib.util

# Metadata for the protocol
metadata = {
    "protocolName": "Cherrypicking from Coordinates",
    "author": "Nick <amitaik@alphatau.com>",
    "source": "Custom Protocol Request",
    "apiLevel": "2.11",  
}

def run(protocol: protocol_api.ProtocolContext):
    """
    Main function to execute the OT-2 protocol using parameters from config.
    
    This protocol exactly replicates the functionality of work.py but uses
    external configuration rather than hardcoded values.
    
    Parameters:
    - protocol: The Opentrons protocol context.
    """
    protocol.comment("Starting protocol execution")
    
    # Load the configuration from external source
    config = load_config(protocol)
    
    # Execute the protocol using the loaded config
    execute_protocol(protocol, config)
    
    protocol.comment("Protocol completed successfully")


def load_config(protocol):
    """
    Load configuration from external file or protocol parameters.
    
    This function attempts to load configuration from:
    1. Protocol parameters (most likely source in production)
    2. ot2_config.py (Python module)
    3. parameters.json (JSON file)
    
    It prioritizes protocol parameters for normal operation.
    """
    config = None
    
    # First try: Look for parameters directly in the protocol context
    try:
        protocol.comment("Checking for protocol parameters...")
        
        if hasattr(protocol, "parameters") and protocol.parameters:
            protocol.comment("Found parameters in protocol.parameters")
            config = protocol.parameters
        elif hasattr(protocol, "_protocol_json") and isinstance(protocol._protocol_json, dict):
            if "parameters" in protocol._protocol_json:
                protocol.comment("Found parameters in _protocol_json.parameters")
                config = protocol._protocol_json["parameters"]
            elif "metadata" in protocol._protocol_json and "parameters" in protocol._protocol_json["metadata"]:
                protocol.comment("Found parameters in _protocol_json.metadata.parameters")
                config = protocol._protocol_json["metadata"]["parameters"]
    except Exception as e:
        protocol.comment(f"Error checking protocol parameters: {str(e)}")
    
    # Second try: Import external Python module if protocol parameters not found
    if not config:
        try:
            protocol.comment("Attempting to load external Python configuration...")
            try:
                from ot2_config import ot2_config
                protocol.comment("Successfully imported ot2_config.py directly")
                config = ot2_config
            except ImportError:
                protocol.comment("Direct import failed, checking possible paths...")
        except Exception as e:
            protocol.comment(f"Error importing config module: {str(e)}")
    
    # Third try: Load JSON file if neither protocol parameters nor Python module found
    if not config:
        try:
            protocol.comment("Attempting to load JSON configuration...")
            possible_json_paths = [
                "parameters.json",
                "/data/user_storage/parameters.json",
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "parameters.json")
            ]
            
            for json_path in possible_json_paths:
                try:
                    if os.path.exists(json_path):
                        protocol.comment(f"Found JSON config at: {json_path}")
                        with open(json_path, 'r') as file:
                            config = json.load(file)
                            protocol.comment("Successfully loaded parameters.json")
                            break
                except Exception:
                    continue
        except Exception as e:
            protocol.comment(f"Error loading JSON config: {str(e)}")
    
    # If still no config, use minimal defaults
    if not config:
        protocol.comment("WARNING: No parameters found, using minimal defaults")
        config = {
            "NUM_OF_GENERATORS": 5,
            "radioactive_VOL": 6.6,
            "SDS_VOL": 1.0,
            "tip_location": "1"
        }
    
    # Ensure all required parameters exist
    ensure_required_parameters(protocol, config)
    
    # Log the configuration
    log_config(protocol, config)
    
    return config


def ensure_required_parameters(protocol, config):
    """Ensure all required parameters exist in the config."""
    # Define minimal defaults only for essential parameters
    minimal_defaults = {
        "NUM_OF_GENERATORS": 5,
        "radioactive_VOL": 6.6,
        "SDS_VOL": 1.0,
        "CUR": 2,
        "tip_location": "1",
        "sds_lct": [287.0, 226.0, 40.0],
        "generators_locations": [
            [4.0, 93.0, 133.0],
            [4.0, 138.0, 133.0],
            [4.0, 183.0, 133.0],
            [4.0, 228.0, 133.0],
            [4.0, 273.0, 133.0],
        ],
        "home_lct": [350.0, 350.0, 147.0],
        "temp_lct": [8.0, 350.0, 147.0],
        "hight_home_lct": [302.0, 302.0, 147.0],
        "hight_temp_lct": [8.0, 228.0, 147.0],
    }
    
    # Check for missing required parameters and add defaults only if needed
    for key, default_value in minimal_defaults.items():
        if key not in config:
            protocol.comment(f"WARNING: Missing required parameter '{key}', using default value")
            config[key] = default_value
    
    # Handle the thorium/radioactive location naming
    if "radioactive_lct" not in config and "thorium_lct" in config:
        config["radioactive_lct"] = config["thorium_lct"]
    elif "thorium_lct" not in config and "radioactive_lct" in config:
        config["thorium_lct"] = config["radioactive_lct"]
    elif "radioactive_lct" not in config and "thorium_lct" not in config:
        protocol.comment("WARNING: Missing radioactive location, using default")
        config["radioactive_lct"] = [354.0, 225.0, 40.0]
        config["thorium_lct"] = [354.0, 225.0, 40.0]


def log_config(protocol, config):
    """Log key configuration parameters for debugging."""
    protocol.comment("=== Configuration Summary ===")
    protocol.comment(f"NUM_OF_GENERATORS: {config.get('NUM_OF_GENERATORS')}")
    protocol.comment(f"radioactive_VOL: {config.get('radioactive_VOL')}")
    protocol.comment(f"SDS_VOL: {config.get('SDS_VOL')}")
    protocol.comment(f"Tip location: {config.get('tip_location')}")
    if 'trayNumber' in config:
        protocol.comment(f"Tray Number: {config.get('trayNumber')}")
    if 'vialNumber' in config:
        protocol.comment(f"Vial Number: {config.get('vialNumber')}")
    protocol.comment("==============================")


def execute_protocol(protocol, config):
    """
    Execute the full protocol sequence based on the work.py reference.
    
    This function maintains the exact same execution flow as work.py but uses
    the provided configuration instead of hardcoded values.
    """
    # Initialize required objects
    tiprack, copyTiprack, p1, p2 = init_objects(protocol, config)
    
    # Create location points
    firs_home, first_temp, home_point, sds, temp_point, thorium = create_lct_point(config)
    
    # Pick up tips - using Fake_pick_up to match work.py
    fake_pick_up(protocol, copyTiprack, p1, p2)
    
    # Move to home position
    protocol.comment("Moving to home position")
    p1.move_to(home_point)
    
    # Calculate dispensing volumes
    dispense_amount = [config["SDS_VOL"]]
    calculate_vol(protocol, dispense_amount, config)
    
    # Calculate thorium volume for first iteration
    thorium_vol_aspirate = dispense_amount[1] * config["NUM_OF_GENERATORS"]
    
    # Execute first iteration
    first_iteration(
        protocol,
        dispense_amount,
        home_point,
        p1,
        p2,
        sds,
        temp_point,
        thorium,
        thorium_vol_aspirate,
        config
    )
    
    # Execute second iteration
    second_iteration(protocol, dispense_amount, home_point, p1, p2, temp_point, thorium, config)
    
    # Drop tips at the end
    drop_tips(protocol, p1, p2)


def init_objects(protocol, config):
    """Initialize labware and instruments."""
    protocol.comment("Loading labware and instruments")
    tiprack = protocol.load_labware("opentrons_96_tiprack_20ul", config["tip_location"])
    copyTiprack = protocol.load_labware("opentrons_96_tiprack_20ul", "11")
    p1 = protocol.load_instrument("p20_single_gen2", "left", tip_racks=[tiprack])
    p2 = protocol.load_instrument("p20_single_gen2", "right", tip_racks=[tiprack])
    return tiprack, copyTiprack, p1, p2


def fake_pick_up(protocol, copyTiprack, p1, p2):
    """Pick up tips from fixed positions in copyTiprack."""
    protocol.comment("Picking up tips from copyTiprack (wells 89 and 90)")
    p1.pick_up_tip(copyTiprack.wells()[89])
    p2.pick_up_tip(copyTiprack.wells()[90])


def real_pick_up(protocol, tiprack, p1, p2, config):
    """Alternative method to pick up tips using CUR index."""
    cur_index = int(config["CUR"])
    protocol.comment(f"Picking up tips from tiprack (wells {cur_index} and {cur_index+1})")
    p1.pick_up_tip(tiprack.wells()[cur_index])
    p2.pick_up_tip(tiprack.wells()[cur_index + 1])


def drop_tips(protocol, p1, p2):
    """Drop tips from both pipettes."""
    protocol.comment("Dropping tips")
    p1.drop_tip()
    p2.drop_tip()


def second_iteration(protocol, dispense_amount, home_point, p1, p2, temp_point, thorium, config):
    """
    Perform the second iteration of dispensing.
    
    This exactly matches the work.py Second_iteration function behavior.
    """
    if len(dispense_amount) > 2:
        protocol.comment("Starting Second_iteration")
        index = 0
        
        # Aspirate with p1
        thorium_vol_aspirate = dispense_amount[2] * config["NUM_OF_GENERATORS"]
        protocol.comment(f"Aspirating {thorium_vol_aspirate}µL with p1")
        p1.aspirate(thorium_vol_aspirate, thorium)
        
        # Check if we need to use p2 as well
        p2_in_use = False
        if len(dispense_amount) > 3:
            thorium_vol_aspirate_p2 = dispense_amount[3] * config["NUM_OF_GENERATORS"]
            protocol.comment(f"Aspirating {thorium_vol_aspirate_p2}µL with p2")
            p2.aspirate(thorium_vol_aspirate_p2, thorium)
            p2_in_use = True

        # Safely move to prepare for dispensing
        safe_move(p1, home_point, temp_point)

        # Dispense to each generator location
        for val in config["generators_locations"]:
            if index == config["NUM_OF_GENERATORS"]:
                break
                
            # Create destination points
            dest1 = Location(Point(float(val[0]), float(val[1]), float(val[2])), None)
            dest2 = Location(Point(float(val[0]) + 1, float(val[1]), float(val[2])), None)
            
            # Dispense to position 1
            protocol.comment(f"Dispensing {dispense_amount[2]}µL to generator {index+1}")
            p1.dispense(dispense_amount[2], dest1)
            
            # Conditionally dispense to position 2
            if p2_in_use:
                protocol.comment(f"Dispensing {dispense_amount[3]}µL with p2")
                p2.dispense(dispense_amount[3], dest2)
            else:
                # If not using p2, just move p1 to position
                dest = Location(Point(float(val[0]), float(val[1]), 145), None)
                p1.move_to(dest)
                
            # Move to next position
            p1.move_to(Location(Point(float(val[0]) + 1, float(val[1]), 145), None))
            index += 1
            
        # Safely move back
        safe_move(p1, temp_point, home_point)
        
        # Blow out to remove any remaining liquid
        protocol.comment("Blowing out remaining liquid")
        p1.blow_out(thorium)
        p2.blow_out(thorium)


def first_iteration(
    protocol, dispense_amount, home_point, p1, p2, sds, temp_point, thorium, thorium_vol_aspirate, config
):
    """
    Perform the first iteration of aspirating and dispensing.
    
    This exactly matches the work.py First_iteration function behavior.
    """
    protocol.comment("Starting First_iteration")
    
    # Calculate volumes
    sds_vol_aspirate = config["SDS_VOL"] * config["NUM_OF_GENERATORS"]
    all_sds = 4 * sds_vol_aspirate
    
    # First aspirate both liquids
    protocol.comment(f"Aspirating {thorium_vol_aspirate}µL thorium with p1 and {all_sds}µL SDS with p2")
    first_aspirate(p1, p2, sds, thorium, thorium_vol_aspirate, all_sds)
    
    # Safe move to prepare for dispensing
    safe_move(p2, home_point, temp_point)
    
    # Dispense to each generator location
    index = 0
    for val in config["generators_locations"]:
        if index == config["NUM_OF_GENERATORS"]:
            break
            
        # Create destination points
        dest1 = Location(Point(float(val[0]), float(val[1]), float(val[2])), None)
        dest2 = Location(Point(float(val[0]) + 1, float(val[1]), float(val[2])), None)
        
        # Dispense to positions
        protocol.comment(f"Dispensing to generator {index+1}: {dispense_amount[0]}µL SDS and {dispense_amount[1]}µL thorium")
        p2.dispense(dispense_amount[0], dest2)
        p1.dispense(dispense_amount[1], dest1)
        index += 1
        
    # Safe move back and blow out any remaining liquid
    safe_move(p2, temp_point, home_point)
    protocol.comment("Blowing out remaining SDS")
    p2.blow_out(sds)


def first_aspirate(p1, p2, sds, thorium, thorium_vol_aspirate, all_sds):
    """Aspirate liquids for the first iteration."""
    p1.aspirate(thorium_vol_aspirate, thorium)
    p2.aspirate(all_sds, sds)


def calculate_vol(protocol, dispense_amount, config):
    """
    Calculate dispensing volumes based on radioactive volume.
    
    This exactly matches the work.py calculate_vol function behavior.
    """
    all_th = config["radioactive_VOL"] * config["NUM_OF_GENERATORS"]
    
    protocol.comment(f"Calculating volumes for radioactive_VOL={config['radioactive_VOL']} with total={all_th}")
    
    if all_th <= 20:
        dispense_amount.append(config["radioactive_VOL"])
        protocol.comment(f"Single dispense amount: {config['radioactive_VOL']}µL")
            
    elif all_th <= 40 and all_th > 20:
        divide = config["radioactive_VOL"] / 2
        res = str(divide).split(".")
        
        # Check if it has a simple decimal (one digit)
        if len(res) == 1 or len(res[1]) == 1:
            val = round(divide, 1)
            dispense_amount.append(val)
            dispense_amount.append(val)
            protocol.comment(f"Two equal dispense amounts: {val}µL each")
        else:
            temp = float(res[0])
            tostr = str(res[1])
            sec = ((float(tostr[0])) + 1) / 10
            first_amount = temp + sec
            sec_amount = temp + (sec - 0.1)
            dispense_amount.append(round(first_amount, 1))
            dispense_amount.append(round(sec_amount, 1))
            protocol.comment(f"Two unequal dispense amounts: {round(first_amount, 1)}µL and {round(sec_amount, 1)}µL")
                
    else:
        divide = config["radioactive_VOL"] / 3
        res = str(divide).split(".")
        
        # Check if it has a simple decimal (one digit)
        if len(res) == 1 or len(res[1]) == 1:
            val = round(divide, 1)
            dispense_amount.append(val)
            dispense_amount.append(val)
            dispense_amount.append(val)
            protocol.comment(f"Three equal dispense amounts: {val}µL each")
        else:
            # First handle the first portion
            temp = float(res[0])
            tostr = str(res[1])
            sec = ((float(tostr[0])) + 1) / 10
            first_amount = temp + sec
            dispense_amount.append(first_amount)
            
            # Then split the remaining amount into two parts
            gap = round(config["radioactive_VOL"] - first_amount, 1)
            divide = gap / 2
            res = str(divide).split(".")
            
            # Check if the second division has a simple decimal
            if len(res) == 1 or len(res[1]) == 1:
                val = round(divide, 1)
                dispense_amount.append(val)
                dispense_amount.append(val)
                protocol.comment(f"Three dispense amounts: {first_amount}µL, {val}µL, and {val}µL")
            else:
                # Create slightly different values for the last two portions
                temp = float(res[0])
                tostr = str(res[1])
                sec = ((float(tostr[0])) + 1) / 10
                second_amount = temp + sec
                third_amount = temp + (sec - 0.1)
                dispense_amount.append(round(second_amount, 1))
                dispense_amount.append(round(third_amount, 1))
                protocol.comment(f"Three unequal dispense amounts: {first_amount}µL, {round(second_amount, 1)}µL, and {round(third_amount, 1)}µL")
    
    protocol.comment(f"Final dispense_amount array: {dispense_amount}")


def create_lct_point(config):
    """
    Create location points from coordinate lists.
    
    This exactly matches the work.py createLctPoint function behavior.
    """
    # Create each location point from config coordinates
    firs_home = Location(
        Point(
            float(config["hight_home_lct"][0]), 
            float(config["hight_home_lct"][1]), 
            float(config["hight_home_lct"][2])
        ), 
        None
    )
    
    first_temp = Location(
        Point(
            float(config["hight_temp_lct"][0]), 
            float(config["hight_temp_lct"][1]), 
            float(config["hight_temp_lct"][2])
        ), 
        None
    )
    
    # Use radioactive_lct or thorium_lct, whichever is available
    thorium_key = "thorium_lct" if "thorium_lct" in config else "radioactive_lct"
    thorium = Location(
        Point(
            float(config[thorium_key][0]), 
            float(config[thorium_key][1]), 
            float(config[thorium_key][2])
        ), 
        None
    )
    
    sds = Location(
        Point(
            float(config["sds_lct"][0]), 
            float(config["sds_lct"][1]), 
            float(config["sds_lct"][2])
        ), 
        None
    )
    
    home_point = Location(
        Point(
            float(config["home_lct"][0]), 
            float(config["home_lct"][1]), 
            float(config["home_lct"][2])
        ), 
        None
    )
    
    temp_point = Location(
        Point(
            float(config["temp_lct"][0]), 
            float(config["temp_lct"][1]), 
            float(config["temp_lct"][2])
        ), 
        None
    )
    
    return firs_home, first_temp, home_point, sds, temp_point, thorium


def safe_move(p, home_point, temp_point):
    """Safely move the pipette between two points."""
    p.move_to(home_point)
    p.move_to(temp_point)