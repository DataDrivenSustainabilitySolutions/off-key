"""System live-session harness."""

from off_key_core.schemas.system import SystemDocument, SystemSnapshot
from off_key_tactic_middleware.config.system_live import (
    SystemLiveSettings,
)
from off_key_tactic_middleware.services.catalogue.system_live import (
    SystemLiveService,
)


class FakeWorker:
    def __init__(self, connection, topics, credential, message, state, *, proxy=None):
        self.connection = connection
        self.topics = topics
        self.credential = credential
        self.proxy = proxy
        self.message = message
        self.state = state
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        self.state("connected", None)

    def stop(self):
        self.stopped = True

    def update_topics(self, topics):
        self.topics = topics
        return True


def snapshot(revision=1, *, host="broker", credential_ref=None):
    return SystemSnapshot(
        revision=revision,
        storage_origin="saved",
        document=SystemDocument(
            connections=[
                {
                    "id": "broker",
                    "label": "MQTT",
                    "host": host,
                    "credential_ref": credential_ref,
                }
            ],
            streams=[
                {
                    "id": "temperature",
                    "label": "Temperature",
                    "connection_id": "broker",
                    "topic": "room/values",
                    "payload_pointer": "/temperature",
                }
            ],
        ),
    )


def manager(**overrides):
    settings = SystemLiveSettings(
        SYSTEM_LIVE_ENABLED=True,
        SYSTEM_LIVE_ALLOWED_HOSTS=["broker"],
        **overrides,
    )
    now = [100.0]
    service = SystemLiveService(
        settings, worker_factory=FakeWorker, clock=lambda: now[0]
    )
    return service, now
