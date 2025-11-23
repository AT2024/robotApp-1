"""
Configuration Manager for runtime.json file operations.
Handles atomic file writes and configuration management.
"""

import json
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger("config_manager")


class ConfigManager:
    """Manages runtime configuration file operations with atomic writes."""

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize ConfigManager.

        Args:
            config_path: Path to runtime.json file. Defaults to backend/config/runtime.json
        """
        if config_path is None:
            # Default to backend/config/runtime.json
            backend_dir = Path(__file__).parent.parent
            config_path = backend_dir / "config" / "runtime.json"

        self.config_path = Path(config_path)

        # Ensure config directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"ConfigManager initialized with config path: {self.config_path}")

    async def load_runtime_config(self) -> Dict[str, Any]:
        """
        Load configuration from runtime.json file.

        Returns:
            Dict containing all configuration data
        """
        try:
            if not self.config_path.exists():
                logger.warning(f"Config file not found at {self.config_path}, returning empty config")
                return {}

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            logger.info(f"Loaded runtime config from {self.config_path}")
            return config
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from {self.config_path}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error loading runtime config: {e}", exc_info=True)
            return {}

    async def save_runtime_config(self, config_type: str, data: Dict[str, Any]) -> bool:
        """
        Save configuration to runtime.json file using atomic write.

        Args:
            config_type: Type of config (meca, ot2, arduino, wiper)
            data: Configuration data to save

        Returns:
            True if save was successful, False otherwise
        """
        try:
            # Load existing config
            existing_config = await self.load_runtime_config()

            # Update with new data
            existing_config[config_type] = data

            # Atomic write: write to temp file, then rename
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                dir=self.config_path.parent,
                text=True
            )

            try:
                with open(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(existing_config, f, indent=2, ensure_ascii=False)

                # Atomic rename
                Path(temp_path).replace(self.config_path)

                logger.info(f"Successfully saved {config_type} configuration to {self.config_path}")
                return True

            except Exception as e:
                # Clean up temp file on error
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass
                raise e

        except Exception as e:
            logger.error(f"Error saving runtime config for {config_type}: {e}", exc_info=True)
            return False

    async def merge_configs(self, updates: Dict[str, Dict[str, Any]]) -> bool:
        """
        Merge multiple configuration updates at once.

        Args:
            updates: Dict mapping config_type to configuration data

        Returns:
            True if merge was successful, False otherwise
        """
        try:
            # Load existing config
            existing_config = await self.load_runtime_config()

            # Merge all updates
            for config_type, data in updates.items():
                existing_config[config_type] = data

            # Atomic write
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                dir=self.config_path.parent,
                text=True
            )

            try:
                with open(temp_fd, 'w', encoding='utf-8') as f:
                    json.dump(existing_config, f, indent=2, ensure_ascii=False)

                # Atomic rename
                Path(temp_path).replace(self.config_path)

                logger.info(f"Successfully merged {len(updates)} configuration updates")
                return True

            except Exception as e:
                # Clean up temp file on error
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except Exception:
                    pass
                raise e

        except Exception as e:
            logger.error(f"Error merging runtime configs: {e}", exc_info=True)
            return False


# Global singleton instance
_config_manager_instance: Optional[ConfigManager] = None


def get_config_manager(config_path: Optional[Path] = None) -> ConfigManager:
    """
    Get or create the global ConfigManager instance.

    Args:
        config_path: Optional custom path for config file

    Returns:
        ConfigManager instance
    """
    global _config_manager_instance

    if _config_manager_instance is None:
        _config_manager_instance = ConfigManager(config_path)

    return _config_manager_instance
