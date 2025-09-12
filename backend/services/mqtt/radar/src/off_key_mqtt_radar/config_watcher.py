"""
Configuration File Watcher

Monitors configuration file changes and triggers reloads automatically.
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Callable, Optional, Awaitable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from off_key_core.config.logs import logger


class ConfigFileHandler(FileSystemEventHandler):
    """File system event handler for configuration file changes"""

    def __init__(self, config_file_path: Path, callback: Callable[[], Awaitable[None]]):
        super().__init__()
        self.config_file_path = config_file_path.resolve()
        self.callback = callback
        self.last_modified = 0
        self.debounce_time = 1.0  # seconds

        # Get event loop for async callback
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None

        logger.info(f"Watching config file: {self.config_file_path}")

    def on_modified(self, event):
        """Handle file modification events"""
        if event.is_directory:
            return

        # Check if it's our config file
        if Path(event.src_path).resolve() == self.config_file_path:
            current_time = time.time()

            # Debounce rapid file changes (common with editors)
            if current_time - self.last_modified < self.debounce_time:
                return

            self.last_modified = current_time
            logger.info(f"Configuration file changed: {event.src_path}")

            # Trigger callback asynchronously
            if self.loop and self.callback:
                self.loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self.callback())
                )


class ConfigWatcher:
    """
    Configuration file watcher that monitors changes and triggers callbacks

    Features:
    - Monitors specific file for changes
    - Debounces rapid changes
    - Async callback support
    - Graceful error handling
    """

    def __init__(
        self, config_file_path: str, reload_callback: Callable[[], Awaitable[None]]
    ):
        self.config_file_path = Path(config_file_path)
        self.reload_callback = reload_callback
        self.observer: Optional[Observer] = None
        self.handler: Optional[ConfigFileHandler] = None
        self.is_watching = False

        # Validate config file exists
        if not self.config_file_path.exists():
            logger.warning(
                f"Configuration file does not exist: {self.config_file_path}"
            )
            logger.info("File watching will start once the file is created")

        logger.info(f"Initialized config watcher for: {self.config_file_path}")

    async def start(self):
        """Start watching the configuration file"""
        if self.is_watching:
            logger.warning("Config watcher is already running")
            return

        try:
            # Create handler
            self.handler = ConfigFileHandler(
                self.config_file_path, self._handle_config_change
            )

            # Create observer
            self.observer = Observer()

            # Watch the directory containing the config file
            watch_dir = self.config_file_path.parent
            if not watch_dir.exists():
                logger.error(f"Configuration directory does not exist: {watch_dir}")
                return

            self.observer.schedule(self.handler, str(watch_dir), recursive=False)
            self.observer.start()

            self.is_watching = True
            logger.info(f"Started watching configuration directory: {watch_dir}")

        except Exception as e:
            logger.error(f"Failed to start config watcher: {e}")
            await self.stop()

    async def stop(self):
        """Stop watching the configuration file"""
        if not self.is_watching:
            return

        logger.info("Stopping configuration file watcher")

        try:
            if self.observer:
                self.observer.stop()
                self.observer.join(timeout=5.0)

            self.observer = None
            self.handler = None
            self.is_watching = False

            logger.info("Configuration file watcher stopped")

        except Exception as e:
            logger.error(f"Error stopping config watcher: {e}")

    async def _handle_config_change(self):
        """Handle configuration file change"""
        try:
            logger.info("Processing configuration file change")

            # Validate file exists and is readable
            if not self.config_file_path.exists():
                logger.error("Configuration file was deleted")
                return

            # Check if file is readable
            try:
                with open(self.config_file_path, "r") as f:
                    f.read(1)  # Try to read first byte
            except Exception as e:
                logger.error(f"Configuration file is not readable: {e}")
                return

            # Call the reload callback
            await self.reload_callback()

        except Exception as e:
            logger.error(f"Error handling configuration change: {e}")

    def get_status(self) -> dict:
        """Get watcher status information"""
        return {
            "watching": self.is_watching,
            "config_file": str(self.config_file_path),
            "file_exists": self.config_file_path.exists(),
            "file_readable": self._is_file_readable(),
            "last_modified": self._get_file_mtime(),
        }

    def _is_file_readable(self) -> bool:
        """Check if configuration file is readable"""
        try:
            return self.config_file_path.exists() and os.access(
                self.config_file_path, os.R_OK
            )
        except Exception:
            return False

    def _get_file_mtime(self) -> Optional[float]:
        """Get file modification time"""
        try:
            if self.config_file_path.exists():
                return self.config_file_path.stat().st_mtime
        except Exception:
            pass
        return None


class ConfigReloader:
    """
    Handles the actual reloading of configuration with validation and error handling
    """

    def __init__(self, service_instance):
        self.service = service_instance
        self.reload_count = 0
        self.last_reload_time = None
        self.reload_errors = []

    async def reload_config(self):
        """Reload configuration from file"""
        start_time = time.time()

        try:
            logger.info("Starting configuration reload")

            # Import here to avoid circular imports
            from .config import radar_settings

            # Store old config for comparison
            old_config = (
                self.service.config.dict() if hasattr(self.service, "config") else {}
            )

            # Force reload of environment variables
            from dotenv import load_dotenv

            # Reload default .env
            load_dotenv(override=True)

            # Reload custom config file if it exists
            custom_config_file = getattr(radar_settings, "custom_config_file", None)
            if custom_config_file and Path(custom_config_file).exists():
                load_dotenv(custom_config_file, override=True)

            # Recreate settings to pick up new values
            new_settings = radar_settings.__class__()
            new_config = new_settings.config

            # Validate new configuration
            await self._validate_config(new_config)

            # Apply new configuration
            old_service_config = self.service.config
            self.service.config = new_config

            # Handle configuration changes that require component restarts
            await self._handle_config_changes(old_service_config, new_config)

            # Update statistics
            self.reload_count += 1
            self.last_reload_time = time.time()

            reload_time = time.time() - start_time
            logger.info(f"Configuration reloaded successfully in {reload_time:.3f}s")

            # Log significant changes
            self._log_config_changes(old_config, new_config.dict())

        except Exception as e:
            error_msg = f"Configuration reload failed: {e}"
            logger.error(error_msg, exc_info=True)
            self.reload_errors.append({"timestamp": time.time(), "error": str(e)})

            # Keep only last 10 errors
            if len(self.reload_errors) > 10:
                self.reload_errors = self.reload_errors[-10:]

    async def _validate_config(self, config):
        """Validate new configuration before applying it"""
        # Basic validation
        if not config.broker_host:
            raise ValueError("MQTT broker host cannot be empty")

        if not (1 <= config.broker_port <= 65535):
            raise ValueError("MQTT broker port must be between 1 and 65535")

        if not config.subscription_topics:
            raise ValueError("At least one subscription topic is required")

        if config.memory_limit_mb <= 0:
            raise ValueError("Memory limit must be positive")

        # Add more validation as needed
        logger.debug("Configuration validation passed")

    async def _handle_config_changes(self, old_config, new_config):
        """Handle configuration changes that require component updates"""

        # Check for MQTT connection changes
        mqtt_changed = (
            old_config.broker_host != new_config.broker_host
            or old_config.broker_port != new_config.broker_port
            or old_config.use_tls != new_config.use_tls
            or old_config.use_auth != new_config.use_auth
            or old_config.username != new_config.username
            or old_config.api_key != new_config.api_key
        )

        if mqtt_changed:
            logger.info("MQTT connection settings changed - will require reconnection")
            # Note: Full MQTT reconnection would be complex and might require restart
            # For now, just log the change

        # Check for topic subscription changes
        if old_config.subscription_topics != new_config.subscription_topics:
            logger.info("Subscription topics changed - will require resubscription")
            # Note: Topic resubscription could be implemented here

        # Check for memory limit changes
        if old_config.memory_limit_mb != new_config.memory_limit_mb:
            logger.info(
                f"Memory limit changed: "
                f"{old_config.memory_limit_mb} -> {new_config.memory_limit_mb} MB"
            )
            if hasattr(self.service, "memory_manager"):
                self.service.memory_manager.max_memory_mb = new_config.memory_limit_mb

        # Check for anomaly detection threshold changes
        if old_config.thresholds != new_config.thresholds:
            logger.info("Anomaly detection thresholds changed")
            # Note: Threshold changes would take effect immediately for new messages

    def _log_config_changes(self, old_config: dict, new_config: dict):
        """Log significant configuration changes"""
        changes = []

        for key in set(old_config.keys()) | set(new_config.keys()):
            old_value = old_config.get(key)
            new_value = new_config.get(key)

            if old_value != new_value:
                # Don't log sensitive values
                if "key" in key.lower() or "password" in key.lower():
                    changes.append(f"{key}: [REDACTED] -> [REDACTED]")
                else:
                    changes.append(f"{key}: {old_value} -> {new_value}")

        if changes:
            logger.info("Configuration changes:")
            for change in changes[:10]:  # Limit to first 10 changes
                logger.info(f"  - {change}")

            if len(changes) > 10:
                logger.info(f"  ... and {len(changes) - 10} more changes")

    def get_reload_stats(self) -> dict:
        """Get configuration reload statistics"""
        return {
            "reload_count": self.reload_count,
            "last_reload_time": self.last_reload_time,
            "recent_errors": self.reload_errors[-5:] if self.reload_errors else [],
            "error_count": len(self.reload_errors),
        }
