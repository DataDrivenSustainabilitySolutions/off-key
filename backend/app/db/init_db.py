import logging

from .base import engine


def initialize_timescaledb():
    """Convert 'sensors' table into a TimescaleDB hypertable if not already converted."""
    with engine.connect() as conn:
        try:
            conn.execute(
                "SELECT create_hypertable('telemetry', 'timestamp', if_not_exists => TRUE);"
            )
            conn.execute(
                "SELECT add_retention_policy('telemetry', INTERVAL '14 days', if_not_exists => TRUE);"
            )
            logging.info("TimescaleDB hypertable setup complete.")
        except Exception as e:
            logging.error(f"Error setting up TimescaleDB hypertable: {e}")
