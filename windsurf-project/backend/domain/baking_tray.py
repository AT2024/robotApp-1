class BakingTray:
    def __init__(self, id=None, tray_serial_number=None, in_use=False, 
                 capacity=55, next_pos=1):
        """
        Initialize BakingTray object according to the database schema
        
        Args:
            id (int): Primary key id for the tray
            tray_serial_number (str): Unique serial number for the tray
            in_use (bool): Whether the tray is currently in use
            capacity (int): Maximum capacity of wafers (default 55)
            next_pos (int): Next available position (1-55)
        """
        self.id = id
        self.tray_serial_number = tray_serial_number
        self.in_use = in_use
        self.capacity = capacity
        self.next_pos = next_pos
        
        # Relationships
        self._wafers = []  # One-to-many with Wafer
        self._carousels = []  # One-to-many with Carousel
        
    def __repr__(self):
        return (f"BakingTray(id={self.id}, tray_serial_number={self.tray_serial_number}, "
                f"in_use={self.in_use}, capacity={self.capacity}, next_pos={self.next_pos})")
    
    @property
    def wafers(self):
        """Returns list of wafers in this tray"""
        return self._wafers
        
    @property
    def carousels(self):
        """Returns list of carousels that used this tray"""
        return self._carousels
        
    def add_wafer(self, wafer):
        """
        Adds a wafer to this tray at the next available position
        
        Args:
            wafer: Wafer object to be added
            
        Returns:
            bool: True if successful, False if tray is full
        """
        if self.is_full():
            return False
            
        wafer.tray_id = self.id
        wafer.wafer_pos = self.next_pos
        self._wafers.append(wafer)
        self.next_pos += 1
        return True
        
    def is_full(self):
        """Returns True if tray is at capacity"""
        return self.next_pos > self.capacity
    
    @staticmethod
    def get_by_id(tray_id):
        """
        Static method to retrieve tray by ID
        This would query the database in a real implementation
        
        Args:
            tray_id (int): ID of tray to retrieve
            
        Returns:
            BakingTray object or None if not found
        """
        # Placeholder implementation
        return None