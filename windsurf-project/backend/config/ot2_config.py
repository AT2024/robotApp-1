# ot2_config.py

ot2_config = {
    "NUM_OF_GENERATORS": 5,
    "radioactive_VOL": 6.6,
    "SDS_VOL": 1.0,
    "CUR": 2,
    "sds_lct": [287, 226, 40],
    "radioactive_lct": [354, 225, 40],
    "generators_locations": [
        [4, 93, 133],
        [4, 138, 133],
        [4, 183, 133],
        [4, 228, 133],
        [4, 273, 133],
    ],
    "home_lct": [350, 350, 147],
    "temp_lct": [8, 350, 147],
    "hight_home_lct": [302, 302, 147],
    "hight_temp_lct": [8, 228, 147],
    "tip_location": "1",
    "check_lct": [130, 160, 73],
    "st_lct": [100, 20, 53],
    "sec_lct": [100, 30, 53],
    "ip": "169.254.49.202",
    # "url": lambda ip, port: f"http://{ip}:{port}",
    "port": 31950,
}
