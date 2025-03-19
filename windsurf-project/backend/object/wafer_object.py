from datetime import date

class Wafer:
  def __init__(self, wafer_serial, tray_serial, radioactive_number,spreading_time: date,qaresele_time: date ,generator
   , location_tray, location_qarusele, robot_ot2, robot_meca):
    self.wafer_serial = wafer_serial 
    self.tray_serial = tray_serial
    self.radioactive_number = radioactive_number
    self.spreading_time = spreading_time
    self.qaresele_time = qaresele_time
    self.generator  = generator
    self.location_tray = location_tray
    self.location_qarusele = location_qarusele
    self.robot_ot2 = robot_ot2
    self.robot_meca = robot_meca

  def __repr__(self):
    return (f"Wafer(wafer_serial={self.wafer_serial}, tray_serial={self.tray_serial}, "
        f"radioactive_number={self.radioactive_number}, spreading_time={self.spreading_time}, qaresele_time={self.qaresele_time}, "
        f"generator={self.generator}, location_tray={self.location_tray}, location_qarusele={self.location_qarusele}, "
        f"robot_ot2={self.robot_ot2}, robot_meca={self.robot_meca})")