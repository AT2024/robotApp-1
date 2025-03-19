# Inert tray location
FIRST_WAFER = [173.562, -175.178, 27.9714, 109.5547, 0.2877, -90.059]  # Initial position of the first wafer

# Distance between wafers in holder
GAP_WAFERS = 2.7  

# Spreading Machine locations
GEN_DROP = [
    [130.2207, 159.230, 123.400, 179.7538, -0.4298, -89.9617],  # Location 1
    [85.5707, 159.4300, 123.400, 179.7538, -0.4298, -89.6617],  # Location 2
    [41.0207, 159.4300, 123.400, 179.7538, -0.4298, -89.6617],  # Location 3
    [-3.5793, 159.3300, 123.400, 179.7538, -0.4298, -89.6617],  # Location 4
    [-47.9793, 159.2300, 123.400, 179.7538, -0.4298, -89.6617],  # Location 5
]

# Initial position of the first baking tray
FIRST_BAKING_TRAY = [-141.6702, -170.5871, 27.9420, -178.2908, -69.0556, 1.7626]

# Carousel position
CAROUSEL = [143.013, -246.775, 101.480, 89.704, -0.296, -89.650]

# Safe points
SAFE_POINT = [135, -17.6177, 160, 123.2804, 40.9554, -101.3308]  # Safe point for the robot
CAROUSEL_SAFEPOINT = [25.567, -202.630, 179.700, 90.546, 0.866, -90.882]  # Safe point for carousel

# Photogate positions
T_PHOTOGATE = [53.167, -222.7301, 96.7439, 90.5463, 0.8661, -90.882]  # Top photogate position
C_PHOTOGATE = [95.167, -222.7301, 96.7439, 90.5463, 0.8661, -90.882]  # Center photogate position

# Motion parameters
ACC = 50  # Acceleration
EMPTY_SPEED = 50  # Speed when empty
SPREAD_WAIT = 2  # Wait time during spreading
WAFER_SPEED = 35  # Speed for wafers
SPEED = 35  # General speed
ALIGN_SPEED = 20  # Speed for alignment
ENTRY_SPEED = 15  # Speed for entry
FORCE = 100  # Force applied
CLOSE_WIDTH = 1.0  # Width when closing
total_wafers = 55
wafers_per_cycle = 5
wafers_per_carousel = 11
# IP and Port
IP = "192.168.0.100"
PORT = 10000

meca_config = {
    "first_wafer": FIRST_WAFER,
    "gap_wafers": GAP_WAFERS,
    "gen_drop": GEN_DROP,
    "first_baking_tray": FIRST_BAKING_TRAY,
    "carousel": CAROUSEL,
    "safe_point": SAFE_POINT,
    "carousel_safe_point": CAROUSEL_SAFEPOINT,
    "t_photogate": T_PHOTOGATE,
    "c_photogate": C_PHOTOGATE,
    "acc": ACC,
    "empty_speed": EMPTY_SPEED,
    "spread_wait": SPREAD_WAIT,
    "wafer_speed": WAFER_SPEED,
    "speed": SPEED,
    "align_speed": ALIGN_SPEED,
    "entry_speed": ENTRY_SPEED,
    "force": FORCE,
    "close_width": CLOSE_WIDTH,
    "total_wafers": total_wafers,
    "wafers_per_cycle": wafers_per_cycle,
    "wafers_per_carousel": wafers_per_carousel,
    "ip": IP,
    "port": PORT,
}
