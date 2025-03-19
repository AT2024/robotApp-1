from opentrons import protocol_api
from opentrons.types import Point, Location

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

    Parameters:
    - protocol: The Opentrons protocol context.
    """
    try:
        # Simple debugging to check parameter access
        protocol.comment("Starting protocol execution")

        # Look for parameters in common locations
        params = None

        # Try different methods to access parameters
        if hasattr(protocol, "parameters"):
            params = protocol.parameters
            protocol.comment("Found parameters in protocol.parameters")
        elif hasattr(protocol, "_protocol_json") and isinstance(
            protocol._protocol_json, dict
        ):
            json_data = protocol._protocol_json
            if "parameters" in json_data:
                params = json_data["parameters"]
                protocol.comment("Found parameters in _protocol_json.parameters")
            elif "metadata" in json_data and "parameters" in json_data["metadata"]:
                params = json_data["metadata"]["parameters"]
                protocol.comment(
                    "Found parameters in _protocol_json.metadata.parameters"
                )
        elif hasattr(protocol, "bundled_data"):
            params = protocol.bundled_data
            protocol.comment("Found parameters in bundled_data")

        # If we still don't have parameters, use hardcoded defaults
        if not params:
            protocol.comment("WARNING: No parameters found, using default values")
            params = {
                "NUM_OF_GENERATORS": 5,
                "radioactive_VOL": 6.6,
                "SDS_VOL": 1.0,
                "CUR": 2,
                "sds_lct": [287.0, 226.0, 40.0],
                "thorium_lct": [354.0, 225.0, 40.0],
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
                "tip_location": "1",
                "check_lct": [130.0, 160.0, 73.0],
                "st_lct": [100.0, 20.0, 53.0],
                "sec_lct": [100.0, 30.0, 53.0],
            }

        # Extract parameters with defaults as fallback
        NUM_OF_GENERATORS = params.get("NUM_OF_GENERATORS", 5)
        radioactive_VOL = params.get("radioactive_VOL", 6.6)
        SDS_VOL = params.get("SDS_VOL", 1.0)
        CUR = params.get("CUR", 2)
        sds_lct = params.get("sds_lct", [287.0, 226.0, 40.0])
        thorium_lct = params.get("thorium_lct", [354.0, 225.0, 40.0])
        generators_locations = params.get(
            "generators_locations",
            [
                [4.0, 93.0, 133.0],
                [4.0, 138.0, 133.0],
                [4.0, 183.0, 133.0],
                [4.0, 228.0, 133.0],
                [4.0, 273.0, 133.0],
            ],
        )
        home_lct = params.get("home_lct", [350.0, 350.0, 147.0])
        temp_lct = params.get("temp_lct", [8.0, 350.0, 147.0])
        hight_home_lct = params.get("hight_home_lct", [302.0, 302.0, 147.0])
        hight_temp_lct = params.get("hight_temp_lct", [8.0, 228.0, 147.0])
        tip_location = params.get("tip_location", "1")
        check_lct = params.get("check_lct", [130.0, 160.0, 73.0])
        st_lct = params.get("st_lct", [100.0, 20.0, 53.0])
        sec_lct = params.get("sec_lct", [100.0, 30.0, 53.0])
        trayNumber = params.get("trayNumber", "Unknown")
        vialNumber = params.get("vialNumber", "Unknown")

        # Verify we received the parameters from config
        protocol.comment(f"Working with tray {trayNumber} and vial {vialNumber}")
        protocol.comment(f"Using NUM_OF_GENERATORS={NUM_OF_GENERATORS}")
        protocol.comment(f"Using radioactive_VOL={radioactive_VOL}")
        protocol.comment(f"Using SDS_VOL={SDS_VOL}")

        # Helper Functions
        def Second_iteration(dispense_amount, home_point, p1, p2, temp_point, thorium):
            """Perform the second iteration of dispensing."""
            if len(dispense_amount) > 2:
                index = 0
                thorium_vol_aspirate = dispense_amount[2] * NUM_OF_GENERATORS
                p1.aspirate(thorium_vol_aspirate, thorium)
                p2_aspirated = False
                if len(dispense_amount) > 3:
                    thorium_vol_aspirate = dispense_amount[3] * NUM_OF_GENERATORS
                    p2.aspirate(thorium_vol_aspirate, thorium)
                    p2_aspirated = True
                safeMove(p1, home_point, temp_point)
                for val in generators_locations:
                    if index == NUM_OF_GENERATORS:
                        break
                    dest1 = Location(
                        Point(float(val[0]), float(val[1]), float(val[2])), None
                    )
                    dest2 = Location(
                        Point(float(val[0]) + 1, float(val[1]), float(val[2])), None
                    )
                    p1.dispense(dispense_amount[2], dest1)
                    if p2_aspirated and len(dispense_amount) > 3:
                        p2.dispense(dispense_amount[3], dest2)
                    else:
                        dest = Location(Point(float(val[0]), float(val[1]), 145), None)
                        p1.move_to(dest)
                    p1.move_to(
                        Location(Point(float(val[0]) + 1, float(val[1]), 145), None)
                    )
                    index += 1
                safeMove(p1, temp_point, home_point)
                p1.blow_out(thorium)
                if p2_aspirated:
                    p2.blow_out(thorium)

        def First_iteration(
            dispense_amount,
            home_point,
            p1,
            p2,
            sds,
            temp_point,
            thorium,
            thorium_vol_aspirate,
        ):
            """Perform the first iteration of aspirating and dispensing."""
            sds_vol_aspirate = SDS_VOL * NUM_OF_GENERATORS
            all_sds = 4 * sds_vol_aspirate
            First_aspirate(all_sds, p1, p2, sds, thorium, thorium_vol_aspirate)
            safeMove(p2, home_point, temp_point)
            index = 0
            for val in generators_locations:
                if index == NUM_OF_GENERATORS:
                    break
                dest1 = Location(
                    Point(float(val[0]), float(val[1]), float(val[2])), None
                )
                dest2 = Location(
                    Point(float(val[0]) + 1, float(val[1]), float(val[2])), None
                )
                p2.dispense(dispense_amount[0], dest2)
                p1.dispense(dispense_amount[1], dest1)
                index += 1
            safeMove(p2, temp_point, home_point)
            p2.blow_out(sds)

        def First_aspirate(all_sds, p1, p2, sds, thorium, thorium_vol_aspirate):
            """Aspirate liquids for the first iteration."""
            p1.aspirate(thorium_vol_aspirate, thorium)
            p2.aspirate(all_sds, sds)

        def calculate_vol(dispense_amount):
            """Calculate dispensing volumes based on radioactive volume."""
            protocol.comment(
                f"Calculating volumes with radioactive_VOL={radioactive_VOL}"
            )
            all_th = radioactive_VOL * NUM_OF_GENERATORS
            if all_th <= 20:
                dispense_amount.append(radioactive_VOL)
            elif 20 < all_th <= 40:
                divide = radioactive_VOL / 2
                res = str(divide).split(".")
                if len(res) < 2 or len(res[1]) == 1:
                    val = round(divide, 1)
                    dispense_amount.append(val)
                    dispense_amount.append(val)
                else:
                    temp = float(res[0])
                    tostr = str(res[1])
                    sec = ((float(tostr[0])) + 1) / 10
                    first_amount = temp + sec
                    sec_amount = temp + (sec - 0.1)
                    dispense_amount.append(round(first_amount, 1))
                    dispense_amount.append(round(sec_amount, 1))
            else:
                divide = radioactive_VOL / 3
                res = str(divide).split(".")
                if len(res) < 2 or len(res[1]) == 1:
                    val = round(divide, 1)
                    dispense_amount.append(val)
                    dispense_amount.append(val)
                    dispense_amount.append(val)
                else:
                    temp = float(res[0])
                    tostr = str(res[1])
                    sec = ((float(tostr[0])) + 1) / 10
                    first_amount = temp + sec
                    dispense_amount.append(first_amount)
                    gap = round(radioactive_VOL - first_amount, 1)
                    divide = gap / 2
                    res = str(divide).split(".")
                    if len(res) < 2 or len(res[1]) == 1:
                        val = round(divide, 1)
                        dispense_amount.append(val)
                        dispense_amount.append(val)
                    else:
                        temp = float(res[0])
                        tostr = str(res[1])
                        sec = ((float(tostr[0])) + 1) / 10
                        first_amount = temp + sec
                        sec_amount = temp + (sec - 0.1)
                        dispense_amount.append(round(first_amount, 1))
                        dispense_amount.append(round(sec_amount, 1))

        def createLctPoint():
            """Create location points from coordinate lists."""
            protocol.comment("Creating location points from coordinates")
            # Create location objects from coordinates
            try:
                firs_home = Location(
                    Point(
                        float(hight_home_lct[0]),
                        float(hight_home_lct[1]),
                        float(hight_home_lct[2]),
                    ),
                    None,
                )
                first_temp = Location(
                    Point(
                        float(hight_temp_lct[0]),
                        float(hight_temp_lct[1]),
                        float(hight_temp_lct[2]),
                    ),
                    None,
                )
                thorium = Location(
                    Point(
                        float(thorium_lct[0]),
                        float(thorium_lct[1]),
                        float(thorium_lct[2]),
                    ),
                    None,
                )
                sds = Location(
                    Point(float(sds_lct[0]), float(sds_lct[1]), float(sds_lct[2])), None
                )
                home_point = Location(
                    Point(float(home_lct[0]), float(home_lct[1]), float(home_lct[2])),
                    None,
                )
                temp_point = Location(
                    Point(float(temp_lct[0]), float(temp_lct[1]), float(temp_lct[2])),
                    None,
                )
                return firs_home, first_temp, home_point, sds, temp_point, thorium
            except Exception as e:
                protocol.comment(f"Error creating location points: {str(e)}")
                raise

        def safeMove(p, home_point, temp_point):
            """Safely move the pipette between two points."""
            p.move_to(home_point)
            p.move_to(temp_point)

        # Main Protocol Execution
        try:
            protocol.comment("Loading labware and instruments")
            # Load labware and instruments
            tiprack = protocol.load_labware("opentrons_96_tiprack_20ul", "1")
            copyTiprack = protocol.load_labware("opentrons_96_tiprack_20ul", "11")
            p1 = protocol.load_instrument(
                "p20_single_gen2", "left", tip_racks=[tiprack]
            )
            p2 = protocol.load_instrument(
                "p20_single_gen2", "right", tip_racks=[tiprack]
            )

            protocol.comment("Picking up tips")
            # Pick up tips
            p1.pick_up_tip()
            p2.pick_up_tip()

            protocol.comment("Initializing location points")
            # Initialize locations using coordinates
            firs_home, first_temp, home_point, sds, temp_point, thorium = (
                createLctPoint()
            )

            # Execute protocol steps
            protocol.comment("Beginning protocol execution")
            p1.move_to(home_point)

            dispense_amount = [SDS_VOL]
            calculate_vol(dispense_amount)
            thorium_vol_aspirate = dispense_amount[1] * NUM_OF_GENERATORS

            protocol.comment("Starting First_iteration")
            First_iteration(
                dispense_amount,
                home_point,
                p1,
                p2,
                sds,
                temp_point,
                thorium,
                thorium_vol_aspirate,
            )

            protocol.comment("Starting Second_iteration")
            Second_iteration(dispense_amount, home_point, p1, p2, temp_point, thorium)

            protocol.comment("Dropping tips")
            # Drop tips
            p1.drop_tip()
            p2.drop_tip()

            protocol.comment("Protocol completed successfully")
        except Exception as e:
            protocol.comment(f"Error during protocol execution: {str(e)}")
            raise
    except Exception as e:
        protocol.comment(f"Parameter access error: {str(e)}")
        raise
