"""
Base Client Protocol

Defines the interface that all charger API clients must implement.
Uses Python's Protocol for structural typing (no inheritance required).
"""

from typing import Protocol, List, Dict, Any, Optional, runtime_checkable


@runtime_checkable
class ChargerAPIClient(Protocol):
    """
    Protocol defining the interface for charger API clients.

    Any client that implements these methods with matching signatures
    will be considered a valid ChargerAPIClient, regardless of inheritance.
    """

    async def get_chargers(self) -> List[Dict[str, Any]]:
        """
        Get all active chargers from the API.

        Returns:
            List of charger data dictionaries
        """
        ...

    async def get_device_info(self, charger_id: str) -> Dict[str, Any]:
        """
        Get device information/model for a specific charger.

        Args:
            charger_id: The unique identifier of the charger

        Returns:
            Dictionary containing device information
        """
        ...

    async def get_telemetry_data(
        self, charger_id: str, hierarchy: str, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get telemetry data for a specific charger and hierarchy.

        Args:
            charger_id: The unique identifier of the charger
            hierarchy: The telemetry hierarchy/metric path
            limit: Optional limit on number of records to retrieve

        Returns:
            Dictionary containing telemetry data
        """
        ...
