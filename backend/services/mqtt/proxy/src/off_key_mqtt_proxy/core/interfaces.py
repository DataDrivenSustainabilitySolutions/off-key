"""
MQTT Service Component Interfaces
Defines protocols and interfaces that all MQTT service components must implement
for consistent lifecycle management and type safety.
"""

from typing import Protocol


class Stoppable(Protocol):
    """
    Protocol for components that can be gracefully stopped.
    All MQTT service components should implement this interface to ensure
    consistent shutdown behavior and eliminate runtime method discovery.
    """

    async def stop(self) -> None:
        """
        Gracefully stop the component.
        This method should:
        1. Stop processing new work
        2. Complete any in-flight operations where possible
        3. Release any resources (connections, files, etc.)
        4. Be idempotent (safe to call multiple times)
        Raises:
            Exception: If shutdown fails and component cannot be stopped safely
        """
        ...


class HealthCheckable(Protocol):
    """
    Protocol for components that can report their health status.
    Optional interface for components that want to provide health information
    for monitoring and debugging purposes.
    """

    def get_health_status(self) -> dict:
        """
        Get the current health status of the component.
        Returns:
            dict: Health status information including component state,
                  any error conditions, and relevant metrics
        """
        ...


class ShutdownFailedError(Exception):
    """
    Exception raised when one or more components fail to shutdown properly.
    Aggregates multiple shutdown errors to provide comprehensive failure context
    while allowing the shutdown process to continue for other components.
    """

    def __init__(self, message: str, errors: list[Exception]):
        """
        Initialize shutdown failure exception.
        Args:
            message: High-level description of the shutdown failure
            errors: List of individual component shutdown exceptions
        """
        super().__init__(message)
        self.errors = errors

    def __str__(self):
        error_summary = f"{len(self.errors)} component(s) failed to shutdown"
        error_details = "\n".join(f"  - {error}" for error in self.errors)
        return f"{super().__str__()}: {error_summary}\n{error_details}"
