"""System document and SQLite session helpers."""

from off_key_core.schemas.system import SystemDocument
from sqlalchemy import JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB


class AsyncSessionAdapter:
    """Use a real disposable SQLite database without an optional async driver."""

    def __init__(self, session):
        self.session = session

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def execute(self, statement, params=None):
        return self.session.execute(statement, params)

    def add(self, row):
        self.session.add(row)

    async def flush(self):
        self.session.flush()


def document():
    return SystemDocument.model_validate(
        {
            "label": "Workshop",
            "connections": [{"id": "broker-1", "label": "MQTT", "host": "localhost"}],
            "devices": [{"id": "room-1", "label": "Office", "kind": "room"}],
            "streams": [
                {
                    "id": "temperature-1",
                    "label": "Temperature",
                    "connection_id": "broker-1",
                    "device_id": "room-1",
                    "topic": "home/office/environment",
                    "payload_pointer": "/readings/temperature",
                    "unit": "°C",
                }
            ],
            "groups": [
                {
                    "id": "group-1",
                    "label": "Office",
                    "member_ids": ["room-1", "temperature-1"],
                }
            ],
        }
    )


def create_sqlite_tables(engine, tables) -> None:
    """Create PostgreSQL tables in SQLite, storing JSONB columns as JSON."""
    metadata = MetaData()
    for original in tables:
        for column in original.to_metadata(metadata).columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
