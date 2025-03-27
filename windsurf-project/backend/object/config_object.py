class Config:
    def __init__(self, id=None, param=None, value=None):
        """
        Initialize Config object according to the database schema
        
        Args:
            id (int): Primary key id for the config (same as robot id)
            param (str): Parameter name 
            value (str): Parameter value
        """
        self.id = id
        self.param = param
        self.value = value
        
    def __repr__(self):
        return f"Config(id={self.id}, param={self.param}, value={self.value})"
        
    @staticmethod
    def get_by_robot_id(robot_id):
        """
        Static method to retrieve config by robot ID
        This would query the database in a real implementation
        
        Args:
            robot_id (int): ID of robot to retrieve config for
            
        Returns:
            Config object or None if not found
        """
        # Placeholder implementation
        return None
        