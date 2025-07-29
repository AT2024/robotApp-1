from datetime import datetime

class ThoriumVial:
    def __init__(self, id=None, vial_serial_number=None, initial_volume=None,
                 current_volume=None, opening_time=None):
        """
        Initialize ThoriumVial object according to the database schema
        
        Args:
            id (int): Primary key id for the thorium vial
            vial_serial_number (str): Unique serial number for the vial
            initial_volume (float): Initial volume of thorium in the vial
            current_volume (float): Current volume of thorium in the vial
            opening_time (datetime): Time when vial was opened
        """
        self.id = id
        self.vial_serial_number = vial_serial_number
        self.initial_volume = initial_volume
        self.current_volume = current_volume or initial_volume
        self.opening_time = opening_time or datetime.now()
        
        # Relationships
        self._wafers = []  # One-to-many with Wafer
        
    def __repr__(self):
        return (f"ThoriumVial(id={self.id}, "
                f"vial_serial_number={self.vial_serial_number}, "
                f"initial_volume={self.initial_volume}, "
                f"current_volume={self.current_volume}, "
                f"opening_time={self.opening_time})")
    
    @property
    def wafers(self):
        """Returns list of wafers that used material from this vial"""
        return self._wafers
        
    def add_wafer(self, wafer):
        """
        Associates a wafer with this thorium vial
        
        Args:
            wafer: Wafer object to be associated
        """
        wafer.thorium_id = self.id
        self._wafers.append(wafer)
        
    def use_volume(self, amount):
        """
        Reduce the current volume of the vial
        
        Args:
            amount (float): Amount of thorium to use
            
        Returns:
            bool: True if successful, False if not enough volume
        """
        if self.current_volume < amount:
            return False
            
        self.current_volume -= amount
        return True
        
    @staticmethod
    def get_by_id(thorium_id):
        """
        Static method to retrieve thorium vial by ID
        This would query the database in a real implementation
        
        Args:
            thorium_id (int): ID of thorium vial to retrieve
            
        Returns:
            ThoriumVial object or None if not found
        """
        # Placeholder implementation
        return None