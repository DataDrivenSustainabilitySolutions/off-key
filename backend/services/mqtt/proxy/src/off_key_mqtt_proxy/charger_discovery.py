"""
Charger Discovery Service for MQTT Telemetry Subscriptions

Discovers chargers from the database and their telemetry hierarchies
from the Pionix API,
then manages MQTT topic subscriptions for real-time telemetry data.
"""

from datetime import datetime
from typing import Dict, List, Set, Optional, Iterable, Tuple, AsyncGenerator, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.clients.base_client import ChargerAPIClient
from off_key_core.config.config import settings
from off_key_core.config.logs import logger
from off_key_core.db.models import Charger
from off_key_core.utils.enum import HealthStatus
from .config import MQTTConfig


@dataclass
class DiscoveryMetrics:
    """Charger discovery performance metrics"""

    total_chargers_discovered: int
    total_hierarchies_discovered: int
    total_subscriptions_attempted: int
    total_subscriptions_successful: int
    subscription_success_rate: float
    failed_chargers_count: int
    last_discovery_time: Optional[str]
    chargers_with_partial_subscriptions: int


@dataclass
class DiscoveryHealthStatus:
    """Charger discovery health status"""

    status: HealthStatus
    health_score: float
    total_chargers: int
    healthy_chargers: int
    failed_chargers: int
    total_topics: int
    last_discovery_time: Optional[str]


@dataclass
class ChargerTelemetryInfo:
    """Information about a charger's telemetry hierarchies"""

    charger_id: str
    hierarchies: List[str]
    mqtt_topics: List[str]
    last_discovered: datetime
    subscription_status: Dict[str, bool]

    def get_failed_subscriptions(self) -> List[str]:
        """Get list of failed subscription topics"""
        return [
            topic for topic, status in self.subscription_status.items() if not status
        ]


class ChargerDiscoveryError(Exception):
    """Charger discovery error"""

    pass


class ChargerDiscoveryService:
    """
    Charger discovery service for MQTT telemetry subscriptions

    Handles:
    - Discovering chargers from database
    - Fetching telemetry hierarchies from Pionix API
    - Managing MQTT topic subscriptions
    - Tracking subscription status
    - Handling discovery errors and retries
    """

    def __init__(
        self,
        config: MQTTConfig,
        session_factory: Callable[[], AsyncSession],
        api_client: ChargerAPIClient,
    ):
        self.config = config
        self._session_factory = session_factory
        self.api_client = api_client

        # Discovery state
        self.chargers: Dict[str, ChargerTelemetryInfo] = {}
        self.failed_chargers: Set[str] = set()
        self.last_discovery_time: Optional[datetime] = None

        # Performance metrics
        # TODO: Define data scope (stateful?)
        self.total_chargers_discovered = 0
        self.total_hierarchies_discovered = 0
        self.total_subscriptions_attempted = 0
        self.total_subscriptions_successful = 0

    async def discover_chargers(self) -> List[ChargerTelemetryInfo]:
        """
        Discover all chargers and their telemetry hierarchies

        Returns:
            List of charger telemetry information

        Raises:
            ChargerDiscoveryError: If discovery fails
        """
        logger.info("Starting charger discovery process")
        discovery_start_time = datetime.now()

        try:
            # Get chargers based on configured source
            if self.config.discovery_source == "api":
                charger_ids = await self._get_chargers_from_api()
            elif self.config.discovery_source == "database":
                charger_ids = await self._get_chargers_from_database()
            else:  # api_with_db_fallback
                charger_ids = await self._get_chargers_from_api()
                if not charger_ids:
                    logger.info("No chargers from API, falling back to database")
                    charger_ids = await self._get_chargers_from_database()

            logger.info(f"Found {len(charger_ids)} chargers to discover")

            # Discover telemetry hierarchies for each charger
            charger_info_list = []

            for charger_id in charger_ids:
                try:
                    charger_info = await self._discover_charger_hierarchies(charger_id)
                    if charger_info:
                        charger_info_list.append(charger_info)
                        self.chargers[charger_id] = charger_info
                        self.total_chargers_discovered += 1
                    else:
                        self.failed_chargers.add(charger_id)

                except Exception as e:
                    logger.error(
                        f"Failed to discover hierarchies for charger {charger_id}: {e}"
                    )
                    self.failed_chargers.add(charger_id)

            self.last_discovery_time = datetime.now()
            discovery_duration = (
                self.last_discovery_time - discovery_start_time
            ).total_seconds()

            logger.info(
                f"Charger discovery completed in {discovery_duration:.2f}s | "
                f"Successful: {len(charger_info_list)} | "
                f"Failed: {len(self.failed_chargers)} | "
                f"Total hierarchies: {self.total_hierarchies_discovered}"
            )

            return charger_info_list

        except Exception as e:
            logger.error(f"Charger discovery failed: {e}")
            raise ChargerDiscoveryError(f"Discovery failed: {e}")

    async def _get_chargers_from_database(self) -> List[str]:
        """Get all charger IDs from the database (online and offline)"""
        try:
            # Get all chargers to allow rediscovery of offline chargers
            stmt = select(Charger.charger_id)
            async with self._session_factory() as session:
                result = await session.execute(stmt)
            charger_ids = result.scalars().all()
            charger_list = list(charger_ids)

            if not charger_list:
                logger.warning("No chargers found in database")
            else:
                logger.info(f"Retrieved {len(charger_list)} chargers from database")

            return charger_list

        except Exception as e:
            logger.error(f"Failed to query chargers from database: {e}")
            raise ChargerDiscoveryError(f"Database query failed: {e}")

    async def _get_chargers_from_api(self) -> List[str]:
        """Get all charger IDs directly from the API"""
        try:
            chargers_data = await self.api_client.get_chargers()
            if not chargers_data:
                logger.warning("No chargers received from API")
                return []

            charger_ids = [
                charger["id"]
                for charger in chargers_data
                if isinstance(charger, dict) and "id" in charger
            ]
            logger.info(f"Retrieved {len(charger_ids)} chargers from API")
            return charger_ids

        except Exception as e:
            logger.error(f"Failed to query chargers from API: {e}")
            return []

    async def _discover_charger_hierarchies(
        self, charger_id: str
    ) -> Optional[ChargerTelemetryInfo]:
        """
        Discover telemetry hierarchies for a specific charger

        Args:
            charger_id: The charger ID to discover hierarchies for

        Returns:
            ChargerTelemetryInfo if successful, None otherwise
        """
        logger.debug(f"Discovering hierarchies for charger: {charger_id}")

        try:
            # Fetch device model from API
            device_model = await self.api_client.get_device_info(charger_id)

            # Extract telemetry hierarchies
            hierarchies = [
                hierarchy
                for part in device_model.get("parts", [])
                if isinstance(part, dict)
                for telemetry in part.get("telemetries", [])
                if (hierarchy := telemetry.get("hierarchy"))
            ]

            if not hierarchies:
                logger.warning(
                    f"No telemetry hierarchies found for charger {charger_id}"
                )
                return None

            # Generate MQTT topics
            mqtt_topics = [
                settings.build_mqtt_topic(charger_id=charger_id, hierarchy=hierarchy)
                for hierarchy in hierarchies
            ]

            self.total_hierarchies_discovered += len(hierarchies)

            logger.debug(
                f"Found {len(hierarchies)} hierarchies for charger {charger_id}"
            )

            return ChargerTelemetryInfo(
                charger_id=charger_id,
                hierarchies=hierarchies,
                mqtt_topics=mqtt_topics,
                last_discovered=datetime.now(),
                subscription_status={},
            )

        except Exception as e:
            logger.error(
                f"Failed to discover hierarchies for charger {charger_id}: {e}"
            )
            return None

    async def _subscription_generator(
        self, mqtt_client, topics_to_try: Iterable[str]
    ) -> AsyncGenerator[Tuple[str, bool], None]:
        """
        Generator that yields subscription attempts for topics

        Args:
            mqtt_client: The MQTT client instance
            topics_to_try: Iterable of topic strings to attempt subscription

        Yields:
            Tuple of (topic, success_bool) for each subscription attempt
        """
        for topic in topics_to_try:
            try:
                success = await mqtt_client.subscribe(
                    topic, qos=self.config.subscription_qos
                )
                yield topic, success
            except Exception as e:
                logger.error(f"Error subscribing to {topic}: {e}")
                yield topic, False

    async def subscribe_to_charger_topics(
        self, mqtt_client, charger_info: ChargerTelemetryInfo
    ) -> bool:
        """
        Subscribe to all MQTT topics for a charger

        Args:
            mqtt_client: The MQTT client instance
            charger_info: Charger telemetry information

        Returns:
            True if all subscriptions successful, False otherwise
        """
        logger.info(
            f"Subscribing to {len(charger_info.mqtt_topics)} "
            f"topics for charger {charger_info.charger_id}"
        )

        success_count = 0

        async for topic, success in self._subscription_generator(
            mqtt_client, charger_info.mqtt_topics
        ):
            # Update global metrics
            self.total_subscriptions_attempted += 1

            # Update subscription status
            charger_info.subscription_status[topic] = success

            # Handle success/failure with context-specific logging
            if success:
                success_count += 1
                self.total_subscriptions_successful += 1
                logger.debug(f"Successfully subscribed to {topic}")
            else:
                logger.warning(f"Failed to subscribe to {topic}")

        all_successful = success_count == len(charger_info.mqtt_topics)

        if all_successful:
            logger.info(
                f"All subscriptions successful for charger {charger_info.charger_id}"
            )
        else:
            failed_topics = charger_info.get_failed_subscriptions()
            logger.warning(
                f"Partial subscription success for charger {charger_info.charger_id}: "
                f"{success_count}/{len(charger_info.mqtt_topics)} successful. "
                f"Failed topics: {failed_topics}"
            )

        return all_successful

    async def retry_failed_subscriptions(self, mqtt_client, charger_id: str) -> bool:
        """
        Retry failed subscriptions for a specific charger

        Args:
            mqtt_client: The MQTT client instance
            charger_id: The charger ID to retry subscriptions for

        Returns:
            True if all retries successful, False otherwise
        """
        if charger_id not in self.chargers:
            logger.warning(f"Charger {charger_id} not found in discovered chargers")
            return False

        charger_info = self.chargers[charger_id]
        failed_topics = charger_info.get_failed_subscriptions()

        if not failed_topics:
            logger.debug(f"No failed subscriptions to retry for charger {charger_id}")
            return True

        logger.info(
            f"Retrying {len(failed_topics)} failed subscriptions "
            f"for charger {charger_id}"
        )

        success_count = 0

        async for topic, success in self._subscription_generator(
            mqtt_client, failed_topics
        ):
            # Update subscription status (no global metrics for retries)
            charger_info.subscription_status[topic] = success

            # Handle success/failure with retry-specific logging
            if success:
                success_count += 1
                logger.debug(f"Successfully retried subscription to {topic}")
            else:
                logger.warning(f"Failed to retry subscription to {topic}")

        all_successful = success_count == len(failed_topics)

        if all_successful:
            logger.info(f"All retry subscriptions successful for charger {charger_id}")
        else:
            logger.warning(
                f"Partial retry success for charger {charger_id}: "
                f"{success_count}/{len(failed_topics)} successful"
            )

        return all_successful

    async def refresh_charger_discovery(
        self, charger_id: str
    ) -> Optional[ChargerTelemetryInfo]:
        """
        Refresh discovery for a specific charger

        Args:
            charger_id: The charger ID to refresh

        Returns:
            Updated ChargerTelemetryInfo if successful, None otherwise
        """
        logger.info(f"Refreshing discovery for charger: {charger_id}")

        try:
            charger_info = await self._discover_charger_hierarchies(charger_id)

            if charger_info:
                self.chargers[charger_id] = charger_info
                self.failed_chargers.discard(charger_id)
                logger.info(
                    f"Successfully refreshed discovery for charger {charger_id}"
                )
                return charger_info
            else:
                self.failed_chargers.add(charger_id)
                logger.warning(f"Failed to refresh discovery for charger {charger_id}")
                return None

        except Exception as e:
            logger.error(f"Error refreshing discovery for charger {charger_id}: {e}")
            self.failed_chargers.add(charger_id)
            return None

    def get_charger_info(self, charger_id: str) -> Optional[ChargerTelemetryInfo]:
        """Get charger telemetry information"""
        return self.chargers.get(charger_id)

    def get_all_chargers(self) -> List[ChargerTelemetryInfo]:
        """Get all discovered chargers"""
        return list(self.chargers.values())

    def get_failed_chargers(self) -> Set[str]:
        """Get list of chargers that failed discovery"""
        return self.failed_chargers.copy()

    def get_all_topics(self) -> List[str]:
        """Get all MQTT topics for all chargers"""
        topics = []
        for charger_info in self.chargers.values():
            topics.extend(charger_info.mqtt_topics)
        return topics

    def get_subscription_status(self) -> Dict[str, Dict[str, bool]]:
        """Get subscription status for all chargers"""
        status = {}
        for charger_id, charger_info in self.chargers.items():
            status[charger_id] = charger_info.subscription_status.copy()
        return status

    def get_discovery_metrics(self) -> DiscoveryMetrics:
        """Get discovery performance metrics"""
        success_rate = 0
        if self.total_subscriptions_attempted > 0:
            success_rate = (
                self.total_subscriptions_successful / self.total_subscriptions_attempted
            ) * 100

        return DiscoveryMetrics(
            total_chargers_discovered=self.total_chargers_discovered,
            total_hierarchies_discovered=self.total_hierarchies_discovered,
            total_subscriptions_attempted=self.total_subscriptions_attempted,
            total_subscriptions_successful=self.total_subscriptions_successful,
            subscription_success_rate=round(success_rate, 2),
            failed_chargers_count=len(self.failed_chargers),
            last_discovery_time=(
                self.last_discovery_time.isoformat()
                if self.last_discovery_time
                else None
            ),
            chargers_with_partial_subscriptions=len(
                [
                    c
                    for c in self.chargers.values()
                    if len(c.get_failed_subscriptions()) > 0
                ]
            ),
        )

    def get_health_status(self) -> DiscoveryHealthStatus:
        """Get health status for monitoring"""
        total_chargers = len(self.chargers)
        healthy_chargers = len(
            [
                c
                for c in self.chargers.values()
                if len(c.get_failed_subscriptions()) == 0
            ]
        )

        health_score = 100
        if total_chargers > 0:
            health_score = (healthy_chargers / total_chargers) * 100

        return DiscoveryHealthStatus(
            status=(
                HealthStatus.HEALTHY
                if health_score >= 95
                else (
                    HealthStatus.DEGRADED
                    if health_score >= 80
                    else HealthStatus.UNHEALTHY
                )
            ),
            health_score=round(health_score, 2),
            total_chargers=total_chargers,
            healthy_chargers=healthy_chargers,
            failed_chargers=len(self.failed_chargers),
            total_topics=len(self.get_all_topics()),
            last_discovery_time=(
                self.last_discovery_time.isoformat()
                if self.last_discovery_time
                else None
            ),
        )

    async def stop(self):
        """
        Stop charger discovery service (implements Stoppable protocol)
        The ChargerDiscoveryService is stateless and doesn't maintain background
        tasks or persistent connections, so stopping just clears the discovery state.
        """
        logger.debug("Stopping charger discovery service")

        # Clear discovery state
        self.chargers.clear()
        self.failed_chargers.clear()
        self.last_discovery_time = None

        # Reset metrics
        self.total_chargers_discovered = 0
        self.total_hierarchies_discovered = 0
        self.total_subscriptions_attempted = 0
        self.total_subscriptions_successful = 0

        logger.debug("Charger discovery service stopped")
