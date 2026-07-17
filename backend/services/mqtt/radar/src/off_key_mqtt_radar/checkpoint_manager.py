"""
Checkpoint Manager for RADAR Service

Handles model checkpoint persistence with:
- Atomic file operations for safe concurrent access
- Stale lock cleanup
- Service ID namespacing
"""

import glob
import hashlib
import hmac
import os
import pickle
import time
import uuid
from typing import Any
from typing import Optional

from off_key_core.config.logs import logger
from .config.runtime import get_radar_checkpoint_settings


_CHECKPOINT_MAGIC = b"OFFKEY-CHECKPOINT-V1\n"
_checkpoint_secret_warning_logged = False


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

    @staticmethod
    def _checkpoint_secret() -> bytes:
        return get_radar_checkpoint_settings().checkpoint_secret_bytes

    @classmethod
    def _sign(cls, payload: bytes) -> str:
        secret = cls._checkpoint_secret()
        if not secret:
            return ""
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()

    @classmethod
    def _verify(cls, payload: bytes, signature: str) -> bool:
        global _checkpoint_secret_warning_logged
        secret = cls._checkpoint_secret()
        if not secret:
            if not _checkpoint_secret_warning_logged:
                logger.warning(
                    "RADAR_CHECKPOINT_SECRET is not configured; checkpoint "
                    "signature verification is disabled outside production"
                )
                _checkpoint_secret_warning_logged = True
            return True
        if not signature:
            return False
        expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def candidate_paths(self) -> list[str]:
        pattern = os.path.join(self.checkpoint_dir, f"{self.service_id}_*.pkl")
        return sorted(glob.glob(pattern), key=self._safe_getmtime, reverse=True)

    def claim(self, checkpoint_path: str) -> bool:
        return self._try_claim_checkpoint(checkpoint_path)

    def save(self, checkpoint: dict[str, Any], processed_count: int) -> str:
        os.makedirs(self.checkpoint_dir, exist_ok=True)
        timestamp = int(time.time())
        filename = f"{self.service_id}_{processed_count}_{timestamp}.pkl"
        checkpoint_path = os.path.join(self.checkpoint_dir, filename)
        temporary_path = f"{checkpoint_path}.tmp-{uuid.uuid4().hex}"
        payload = pickle.dumps(checkpoint)
        signature = self._sign(payload).encode("ascii")
        envelope = _CHECKPOINT_MAGIC + signature + b"\n" + payload

        try:
            with open(temporary_path, "xb") as checkpoint_file:
                checkpoint_file.write(envelope)
                checkpoint_file.flush()
                os.fsync(checkpoint_file.fileno())
            os.replace(temporary_path, checkpoint_path)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

        return checkpoint_path

    def load(self, checkpoint_path: str) -> dict[str, Any]:
        with open(checkpoint_path, "rb") as checkpoint_file:
            stored = checkpoint_file.read()

        if stored.startswith(_CHECKPOINT_MAGIC):
            encoded_signature, separator, payload = stored[
                len(_CHECKPOINT_MAGIC) :
            ].partition(b"\n")
            if not separator:
                raise ValueError("Checkpoint envelope is incomplete")
            signature = encoded_signature.decode("ascii")
        else:
            payload = stored
            signature_path = checkpoint_path + ".sig"
            signature = ""
            if os.path.exists(signature_path):
                with open(signature_path, encoding="utf-8") as signature_file:
                    signature = signature_file.read().strip()

        if not self._verify(payload, signature):
            raise ValueError(
                f"Checkpoint signature verification failed: {checkpoint_path}"
            )
        checkpoint = pickle.loads(payload)
        if not isinstance(checkpoint, dict):
            raise ValueError("Checkpoint payload must be a dictionary")
        return checkpoint

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
