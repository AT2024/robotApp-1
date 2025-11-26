from opentrons import protocol_api
from opentrons.types import Point, Location

# metadata
metadata = {
    "protocolName": "Cherrypicking from Coordinates",
    "author": "Nick <protocols@opentrons.com>",
    "source": "Custom Protocol Request",
    "apiLevel": "2.9",
}

# Constants - these will be replaced by runtime.json values at upload time
NUM_OF_GENERATORS = 5
THORIUM_VOL = 6.6
SDS_VOL = 1.0
CUR = 2
sds_lct = [287, 226, 40]
thorium_lct = [354, 225, 40]
generators_locations = [[4, 93, 133], [4, 138, 133], [4, 183, 133], [4, 228, 133], [4, 273, 133]]
home_lct = [350, 350, 147]
temp_lct = [8, 350, 147]
hight_home_lct = [302, 302, 147]
hight_temp_lct = [8, 228, 147]
tip_location = "1"
check_lct = [130, 160, 73]
st_lct = [100, 20, 53]
sec_lct = [100, 30, 53]


def run(ctx: protocol_api.ProtocolContext):
    tiprack, copyTiprack, p1, p2 = Init_objects(ctx)

    firs_home, first_temp, home_point, sds, temp_point, thorium = createLctPoint()

    Fake_pick_up(copyTiprack, p1, p2)
    p1.move_to(home_point)

    dispense_amount = [SDS_VOL]
    calculate_vol(dispense_amount)

    thorium_vol_aspirate = dispense_amount[1] * NUM_OF_GENERATORS

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

    Second_iteration(dispense_amount, home_point, p1, p2, temp_point, thorium)


def Real_pick_up(tiprack, p1, p2):
    p1.pick_up_tip(tiprack.wells()[CUR])
    p2.pick_up_tip(tiprack.wells()[CUR + 1])


def Drop_tips(p1, p2):
    p1.drop_tip()
    p2.drop_tip()


def Second_iteration(dispense_amount, home_point, p1, p2, temp_point, thorium):
    if len(dispense_amount) > 2:
        index = 0
        thorium_vol_aspirate = dispense_amount[2]
        p1.aspirate(thorium_vol_aspirate, thorium)
        if len(dispense_amount) > 3:
            thorium_vol_aspirate = dispense_amount[3]
            p2.aspirate(thorium_vol_aspirate, thorium)

        safeMove(p1, home_point, temp_point)

        for val in generators_locations:
            if index == NUM_OF_GENERATORS:
                break
            dest1 = Location(Point(float(val[0]), float(val[1]), float(val[2])), None)
            dest2 = Location(
                Point(float(val[0]) + 1, float(val[1]), float(val[2])), None
            )
            p1.dispense(dispense_amount[2], dest1)
            if len(dispense_amount) > 3:
                p2.dispense(dispense_amount[3], dest2)
            else:
                dest = Location(Point(float(val[0]), float(val[1]), 145), None)
                p1.move_to(dest)
            p1.move_to(Location(Point(float(val[0]) + 1, float(val[1]), 145), None))
            index += 1
        safeMove(p1, temp_point, home_point)
        p1.blow_out(thorium)
        p2.blow_out(thorium)


def First_iteration(
    dispense_amount, home_point, p1, p2, sds, temp_point, thorium, thorium_vol_aspirate
):
    sds_vol_aspirate = SDS_VOL * NUM_OF_GENERATORS
    all_sds = 4 * sds_vol_aspirate
    First_aspirate(all_sds, p1, p2, sds, thorium, thorium_vol_aspirate)
    safeMove(p2, home_point, temp_point)
    index = 0
    for val in generators_locations:
        if index == NUM_OF_GENERATORS:
            break
        dest1 = Location(Point(float(val[0]), float(val[1]), float(val[2])), None)
        dest2 = Location(Point(float(val[0]) + 1, float(val[1]), float(val[2])), None)
        p2.dispense(dispense_amount[0], dest2)
        p1.dispense(dispense_amount[1], dest1)
        index += 1
    safeMove(p2, temp_point, home_point)
    p2.blow_out(sds)


def First_aspirate(all_sds, p1, p2, sds, thorium, thorium_vol_aspirate):
    p1.aspirate(thorium_vol_aspirate, thorium)
    p2.aspirate(all_sds, sds)


def Fake_pick_up(copyTiprack, p1, p2):
    p1.pick_up_tip(copyTiprack.wells()[89])
    p2.pick_up_tip(copyTiprack.wells()[90])


def Init_objects(ctx):
    tiprack = ctx.load_labware("opentrons_96_tiprack_20ul", tip_location)
    copyTiprack = ctx.load_labware("opentrons_96_tiprack_20ul", "11")
    p1 = ctx.load_instrument("p20_single_gen2", "left", tip_racks=[tiprack])
    p2 = ctx.load_instrument("p20_single_gen2", "right", tip_racks=[tiprack])
    return tiprack, copyTiprack, p1, p2


def calculate_vol(dispense_amount):
    all_th = THORIUM_VOL * NUM_OF_GENERATORS
    if all_th <= 20:
        dispense_amount.append(THORIUM_VOL)
    elif all_th <= 40 and all_th > 20:
        divide = THORIUM_VOL / 2
        res = str(divide).split(".")
        if len(res[1]) == 1:
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
        divide = THORIUM_VOL / 3
        res = str(divide).split(".")
        if len(res[1]) == 1:
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
            gap = round(THORIUM_VOL - first_amount, 1)
            divide = gap / 2
            res = str(divide).split(".")
            if len(res[1]) == 1:
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
    firs_home = Location(
        Point(hight_home_lct[0], hight_home_lct[1], hight_home_lct[2]), None
    )
    first_temp = Location(
        Point(hight_temp_lct[0], hight_temp_lct[1], hight_temp_lct[2]), None
    )
    thorium = Location(Point(thorium_lct[0], thorium_lct[1], thorium_lct[2]), None)
    sds = Location(Point(sds_lct[0], sds_lct[1], sds_lct[2]), None)
    home_point = Location(Point(home_lct[0], home_lct[1], home_lct[2]), None)
    temp_point = Location(Point(temp_lct[0], temp_lct[1], temp_lct[2]), None)
    return firs_home, first_temp, home_point, sds, temp_point, thorium


def safeMove(p, home_point, temp_point):
    p.move_to(home_point)
    p.move_to(temp_point)
