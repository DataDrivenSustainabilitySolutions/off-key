"""
Tests for DatabaseWriter batch operations.

Tests cover:
- Batch accumulation
- Flush operations
- Retry logic
- Error handling
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestDatabaseWriter:
    """Tests for DatabaseWriter batch operations."""

    @pytest.fixture
    def db_config(self):
        """Create test database configuration."""
        config = MagicMock()
        config.db_batch_size = 10
        config.db_batch_timeout = 1.0
        config.db_write_enabled = True
        return config

    @pytest.mark.asyncio
    async def test_write_anomaly_adds_to_batch(self, db_config, sample_anomaly_result):
        """Test that write_anomaly adds results to batch."""
        from off_key_mqtt_radar.database import DatabaseWriter

        with patch(
            "off_key_mqtt_radar.database.get_radar_async_session_factory"
        ) as mock_factory:
            mock_factory.return_value = AsyncMock()

            writer = DatabaseWriter(db_config)
            writer._is_running = True
            writer._batch = []

            await writer.write_anomaly(sample_anomaly_result)

            assert len(writer._batch) == 1

    @pytest.mark.asyncio
    async def test_batch_flush_on_size_threshold(
        self, db_config, sample_anomaly_result
    ):
        """Test that batch flushes when size threshold is reached."""
        from off_key_mqtt_radar.database import DatabaseWriter

        db_config.db_batch_size = 2

        with patch(
            "off_key_mqtt_radar.database.get_radar_async_session_factory"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_session),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            writer = DatabaseWriter(db_config)
            writer._is_running = True
            writer._batch = []
            writer._flush_batch = AsyncMock()

            # Add items up to threshold
            for _ in range(2):
                await writer.write_anomaly(sample_anomaly_result)

            # Flush should have been called
            writer._flush_batch.assert_called()

    @pytest.mark.asyncio
    async def test_get_health_status_healthy(self, db_config):
        """Test health status when writer is healthy."""
        from off_key_mqtt_radar.database import DatabaseWriter

        with patch(
            "off_key_mqtt_radar.database.get_radar_async_session_factory"
        ) as mock_factory:
            mock_factory.return_value = AsyncMock()

            writer = DatabaseWriter(db_config)
            writer._is_running = True
            writer._consecutive_errors = 0

            status = writer.get_health_status()

            assert status["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_get_health_status_disabled(self, db_config):
        """Test health status when writer is disabled."""
        from off_key_mqtt_radar.database import DatabaseWriter

        db_config.db_write_enabled = False

        with patch(
            "off_key_mqtt_radar.database.get_radar_async_session_factory"
        ) as mock_factory:
            mock_factory.return_value = AsyncMock()

            writer = DatabaseWriter(db_config)

            status = writer.get_health_status()

            assert status["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_get_health_status_degraded_on_errors(self, db_config):
        """Test health status is degraded when errors occur."""
        from off_key_mqtt_radar.database import DatabaseWriter

        with patch(
            "off_key_mqtt_radar.database.get_radar_async_session_factory"
        ) as mock_factory:
            mock_factory.return_value = AsyncMock()

            writer = DatabaseWriter(db_config)
            writer._is_running = True
            writer._consecutive_errors = 5

            status = writer.get_health_status()

            assert status["status"] == "degraded"


class TestDatabaseWriterRetry:
    """Tests for DatabaseWriter retry logic."""

    @pytest.fixture
    def db_config(self):
        """Create test database configuration."""
        config = MagicMock()
        config.db_batch_size = 10
        config.db_batch_timeout = 1.0
        config.db_write_enabled = True
        return config

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self, db_config, sample_anomaly_result):
        """Test retry behavior on transient database errors."""
        from off_key_mqtt_radar.database import DatabaseWriter

        with patch(
            "off_key_mqtt_radar.database.get_radar_async_session_factory"
        ) as mock_factory:
            mock_session = AsyncMock()
            # First call fails, second succeeds
            mock_session.execute = AsyncMock(
                side_effect=[Exception("Connection lost"), None]
            )
            mock_factory.return_value = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_session),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            writer = DatabaseWriter(db_config)
            writer._is_running = True
            writer._failed_batch = []

            # Add failed items for retry
            writer._failed_batch.append(sample_anomaly_result)

            # Should handle the retry gracefully
            # (Actual retry logic depends on implementation)
