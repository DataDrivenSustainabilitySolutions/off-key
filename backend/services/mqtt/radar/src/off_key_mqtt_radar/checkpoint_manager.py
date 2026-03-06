"""
Checkpoint Manager for RADAR Service

Handles model checkpoint persistence with:
- Atomic file operations for safe concurrent access
- Stale lock cleanup
- Service ID namespacing
"""

import glob
import os
import time
from typing import Optional

from off_key_core.config.logs import logger
from .config.runtime import get_radar_checkpoint_settings


class CheckpointManager:
    """
    Manages checkpoint file operations for model persistence.

    Supports multiple RADAR instances running concurrently by:
    - Namespacing checkpoints by SERVICE_ID
    - Using atomic file locking to prevent races
    - Cleaning up stale locks from crashed processes
    """

    def __init__(
        self,
        checkpoint_dir: Optional[str] = None,
        service_id: Optional[str] = None,
        stale_lock_age_seconds: int = 3600,
    ):
        """
        Initialize checkpoint manager.

        Args:
            checkpoint_dir: Directory for checkpoint files (default: from env)
            service_id: Unique identifier for this service instance (default: from env)
            stale_lock_age_seconds: Max age before a lock is considered stale
        """
        runtime = get_radar_checkpoint_settings()
        self.checkpoint_dir = checkpoint_dir or runtime.RADAR_CHECKPOINT_DIR
        self.service_id = service_id or runtime.SERVICE_ID
        self.stale_lock_age_seconds = stale_lock_age_seconds
        self._claimed_lock_path: Optional[str] = None
        self._log_context = {"component": "checkpoint_manager"}

    def find_latest_checkpoint(self) -> Optional[str]:
        """
        Find the most recent checkpoint file for this service.

        Checkpoints are namespaced by SERVICE_ID to support multiple RADAR
        containers running independently.

        Returns:
            Path to the latest checkpoint file, or None if not found.
        """
        pattern = os.path.join(self.checkpoint_dir, f"{self.service_id}_*.pkl")
        checkpoints = glob.glob(pattern)

        if not checkpoints:
            return None

        # Sort by mtime descending and try to claim the most recent
        checkpoints_sorted = sorted(checkpoints, key=self._safe_getmtime, reverse=True)

        for checkpoint_path in checkpoints_sorted:
            if self._try_claim_checkpoint(checkpoint_path):
                return checkpoint_path

        return None

    def _safe_getmtime(self, path: str) -> float:
        """
        Safely get file modification time.

        Handles race condition where file is deleted between glob
        and sorting - deleted files sort to end and are skipped.

        Args:
            path: File path to check

        Returns:
            Modification time, or 0.0 if file doesn't exist
        """
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    def _is_lock_stale(self, lock_path: str) -> bool:
        """
        Check if a lock file is stale based on file age.

        Uses file modification time for cross-platform compatibility.

        Args:
            lock_path: Path to the lock file

        Returns:
            True if lock is stale or doesn't exist, False otherwise
        """
        try:
            lock_mtime = os.path.getmtime(lock_path)
            age_seconds = time.time() - lock_mtime
            return age_seconds > self.stale_lock_age_seconds
        except OSError:
            return True

    def _try_claim_checkpoint(self, checkpoint_path: str) -> bool:
        """
        Attempt to atomically claim a checkpoint file.

        Uses atomic file creation to prevent race conditions when multiple
        service instances start simultaneously. Handles stale locks from
        crashed processes.

        Args:
            checkpoint_path: Path to the checkpoint file

        Returns:
            True if checkpoint was successfully claimed, False otherwise
        """
        lock_path = checkpoint_path + ".lock"

        # Check for stale lock and remove it
        if os.path.exists(lock_path) and self._is_lock_stale(lock_path):
            try:
                os.remove(lock_path)
                logger.info(
                    f"Removed stale checkpoint lock: {lock_path}",
                    extra=self._log_context,
                )
            except OSError as e:
                logger.warning(
                    f"Failed to remove stale lock {lock_path}: {e}",
                    extra=self._log_context,
                )

        try:
            # Try to create lock file atomically
            # os.open with O_CREAT | O_EXCL fails if file exists
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode())
            finally:
                os.close(fd)

            self._claimed_lock_path = lock_path
            logger.debug(
                f"Claimed checkpoint: {checkpoint_path}", extra=self._log_context
            )
            return True

        except FileExistsError:
            logger.debug(
                f"Checkpoint already claimed by another process: {checkpoint_path}",
                extra=self._log_context,
            )
            return False
        except OSError as e:
            logger.warning(
                f"Failed to claim checkpoint {checkpoint_path}: {e}",
                extra=self._log_context,
            )
            return False

    def cleanup_lock(self) -> None:
        """
        Remove the checkpoint lock file if we claimed one.

        Should be called during service shutdown.
        """
        if self._claimed_lock_path:
            try:
                os.remove(self._claimed_lock_path)
                logger.debug(
                    f"Removed checkpoint lock: {self._claimed_lock_path}",
                    extra=self._log_context,
                )
            except OSError as e:
                logger.warning(
                    f"Failed to remove checkpoint lock: {e}", extra=self._log_context
                )
            finally:
                self._claimed_lock_path = None

    @property
    def claimed_lock_path(self) -> Optional[str]:
        """Get the path of the currently claimed lock, if any."""
        return self._claimed_lock_path
