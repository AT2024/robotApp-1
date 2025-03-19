from .wafer_object import Wafer

class BakingTrey:
    def __init__(self, wafer):
        self.serial_baking_trey = None
        self.spreading_time = wafer.spreading_time
        self.Carousel_time = wafer.spreading_time
        self.status = False

    @property
    def Carousel_time(self):
        return self._Carousel_time

    @Carousel_time.setter
    def Carousel_time(self, value):
        self._Carousel_time = value

    @staticmethod
    def exists(trey_number):
        # Placeholder implementation - will be replaced with DB query later
        return True  # Simulate tray always exists for now

    @staticmethod
    def is_full(trey_number):
        # Placeholder implementation - will be replaced with DB query later
        return False # Simulate tray is never full for now
