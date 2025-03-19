from datetime import date


class Carousel:
    def __init__(self, serial_baking_trey, Carousel_time: date, in_use):
        self.serial_baking_trey = serial_baking_trey
        self.caruele_time = Carousel_time
        self.in_use = in_use

    def __repr__(self):
        return f"Carousel(num_trey={self.serial_baking_trey}, wafer_serial={self.wafer_serial}, date={self.caruele_time}, in_use={self.in_use})"

    @staticmethod
    def is_in_use(carousel_number):
        # Placeholder implementation - will be replaced with DB query later
        return False  # Simulate carousel is never in use for now
