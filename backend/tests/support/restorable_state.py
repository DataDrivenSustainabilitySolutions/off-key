"""State of several kinds that a redeployment must hand back unchanged.

The rehearsal starts on a fresh stack, so its restore test creates what it
restores through the public API: recorded history over several readings, a
catalogue group, manual alarms, favourites, a custom role, a second member who
stays signed in on a remembered device and an invitation nobody has accepted.
"""

import os
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from paho.mqtt.client import CallbackAPIVersion
from paho.mqtt.client import Client as MQTTClient

from tests.support.integration_catalogue import (
    RecordedEntity,
    add_recorded_entity,
    remove_recorded_entity,
)

# The rehearsal publishes its SMTP fixture's API here, as smoke.env says.
MAIL_SINK = os.getenv("MAILPIT_BASE_URL", "http://127.0.0.1:8025")
PASSWORD = "RehearsalPass123!"
SESSION_COOKIE = "off_key_remembered_session"
# Every value is distinct within its reading, so history is matched by value.
HISTORY = {
    "temperature": (21.0, 21.5, 22.0, 22.5),
    "humidity": (40.0, 41.0, 42.0, 43.0),
    "pressure": (1001.0, 1002.0, 1003.0, 1004.0),
}


def _json(response: httpx.Response):
    response.raise_for_status()
    return response.json()


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@dataclass
class RestorableState:
    """What was created, and how the API showed it before any redeployment.

    `operator` is signed in as the administrator. `guest` carries no credential
    of its own: account links and the colleague's session go through it, so the
    colleague's cookie never reaches a request of the operator.
    """

    operator: httpx.Client
    guest: httpx.Client
    entity: RecordedEntity
    group_id: str
    alarm_ids: list[str]
    role_id: str
    colleague: str
    session: str
    invited: str
    invitation: str
    favourites: list[dict[str, str]]
    expected: dict = field(default_factory=dict)

    def read(self) -> dict:
        """Every created kind as the API shows it now."""
        # A remembered device trades its cookie for a new access token, so a
        # redeployment that lost the session fails here.
        refreshed = _json(
            self.guest.post(
                "/v1/auth/refresh",
                headers={
                    "X-Off-Key-Session": "1",
                    "Cookie": f"{SESSION_COOKIE}={self.session}",
                },
            )
        )
        colleague = _bearer(refreshed["access_token"])
        return {
            "members": _json(self.operator.get("/v1/members")),
            "roles": _json(self.operator.get("/v1/roles")),
            "operator favourites": _json(self.operator.get("/v1/favorites")),
            "colleague": _json(self.guest.get("/v1/me", headers=colleague)),
            "colleague favourites": _json(
                self.guest.get("/v1/favorites", headers=colleague)
            ),
            "alarms": _json(
                self.operator.get(
                    "/v1/alarms", params={"device_id": self.entity.device_id}
                )
            ),
            "history": {
                reading_id: _json(
                    self.operator.get(f"/v1/readings/{reading_id}/measurements")
                )
                for reading_id in self.entity.reading_ids
            },
        }

    def assert_restored(self) -> None:
        current = self.read()
        for kind, expected in self.expected.items():
            assert current[kind] == expected, (
                f"The {kind} changed across the redeployment: "
                f"{current[kind]!r} != {expected!r}"
            )

    def accept_invitation(self) -> None:
        """An invitation sent before the restore still admits its member."""
        self.guest.post(
            "/v1/auth/accept-invitation",
            json={"token": self.invitation, "password": PASSWORD},
        ).raise_for_status()
        accepted = [
            member
            for member in _json(self.operator.get("/v1/members"))
            if member["email"] == self.invited
        ]
        assert [member["is_verified"] for member in accepted] == [True]

    def remove(self) -> None:
        for alarm_id in self.alarm_ids:
            self.operator.delete(f"/v1/alarms/{alarm_id}").raise_for_status()
        for favourite in self.favourites:
            self.operator.delete("/v1/favorites", params=favourite).raise_for_status()
        # A member is disabled before removal, which also drops their favourites.
        for member in _json(self.operator.get("/v1/members")):
            if member["email"] in {self.colleague, self.invited}:
                path = f"/v1/members/{member['id']}"
                self.operator.patch(path, json={"is_active": False}).raise_for_status()
                self.operator.delete(path).raise_for_status()
        self.operator.delete(f"/v1/roles/{self.role_id}").raise_for_status()
        # A group must not name a device the catalogue no longer has.
        current = _json(self.operator.get("/v1/catalogue"))
        current["document"]["groups"] = [
            group
            for group in current["document"]["groups"]
            if group["id"] != self.group_id
        ]
        self.operator.put(
            "/v1/catalogue",
            json={
                "expected_revision": current["revision"],
                "document": current["document"],
            },
        ).raise_for_status()
        remove_recorded_entity(self.operator, self.entity)


def stored_values(operator: httpx.Client, reading_id: str) -> set[float]:
    points = _json(operator.get(f"/v1/readings/{reading_id}/measurements"))
    return {point["value"] for point in points}


def record_history(operator: httpx.Client, entity: RecordedEntity) -> None:
    """Send real source data and wait until every value is stored."""
    publisher = MQTTClient(
        CallbackAPIVersion.VERSION2, client_id=f"rehearsal-history-{entity.device_id}"
    )
    publisher.connect(
        os.getenv("E2E_SOURCE_MQTT_HOST", "localhost"),
        int(os.getenv("E2E_SOURCE_MQTT_PORT", "1884")),
    )
    publisher.loop_start()
    try:
        for values in zip(*HISTORY.values(), strict=True):
            for key, value in zip(HISTORY, values, strict=True):
                message = publisher.publish(entity.topics[key], str(value), qos=1)
                message.wait_for_publish(timeout=5)
                assert message.is_published()
            time.sleep(0.1)
    finally:
        publisher.disconnect()
        publisher.loop_stop()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if all(
            set(values) <= stored_values(operator, entity.readings[key])
            for key, values in HISTORY.items()
        ):
            return
        time.sleep(1)
    pytest.fail("The recorded history did not reach persistent storage")


def invite(operator: httpx.Client, mail: httpx.Client, email: str, role: str) -> str:
    """Invite an address and return the single-use token its email carries."""
    operator.post(
        "/v1/invitations", json={"email": email, "role": role}
    ).raise_for_status()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        for message in _json(mail.get("/api/v1/messages"))["messages"]:
            if not any(recipient["Address"] == email for recipient in message["To"]):
                continue
            text = _json(mail.get(f"/api/v1/message/{message['ID']}"))["Text"]
            if link := re.search(r"/register#token=([A-Za-z0-9_-]+)", text):
                return link.group(1)
        time.sleep(1)
    pytest.fail(f"No invitation for {email} arrived in the mail sink")


def add_group(operator: httpx.Client, entity: RecordedEntity, group_id: str) -> None:
    """A group changes the saved document only, never what is recorded."""
    current = _json(operator.get("/v1/catalogue"))
    current["document"]["groups"].append(
        {
            "id": group_id,
            "label": "Rehearsal collection",
            "color": "#8a4f7d",
            "member_ids": [entity.device_id],
        }
    )
    operator.put(
        "/v1/catalogue",
        json={
            "expected_revision": current["revision"],
            "document": current["document"],
        },
    ).raise_for_status()


def raise_alarms(operator: httpx.Client, entity: RecordedEntity) -> list[str]:
    """One alarm about a single reading and one about two readings together."""
    readings = entity.readings
    alarms = (
        {
            "reading_ids": [readings["temperature"]],
            "alarm_type": "Rehearsal manual alarm",
            "value": 0.01,
            "value_type": "tail_pvalue",
        },
        {
            "reading_ids": [readings["humidity"], readings["pressure"]],
            "alarm_type": "Rehearsal combined alarm",
            "value": 7.5,
        },
    )
    return [
        _json(
            operator.post(
                "/v1/alarms", json=alarm | {"timestamp": datetime.now(UTC).isoformat()}
            )
        )["alarm_id"]
        for alarm in alarms
    ]


def create_restorable_state(
    operator: httpx.Client, guest: httpx.Client, mail: httpx.Client
) -> RestorableState:
    identity = uuid4().hex[:12]
    entity = add_recorded_entity(
        operator, label="Rehearsal history entity", keys=tuple(HISTORY)
    )
    group_id = f"test-group-{identity}"
    add_group(operator, entity, group_id)
    record_history(operator, entity)
    alarm_ids = raise_alarms(operator, entity)
    role = _json(
        operator.post(
            "/v1/roles",
            json={
                "name": f"Rehearsal operators {identity[:8]}",
                "permissions": ["manage_monitors", "manage_alarms"],
            },
        )
    )
    # The colleague accepts their invitation and signs in on a remembered device.
    colleague = f"rehearsal-colleague-{identity}@example.com"
    guest.post(
        "/v1/auth/accept-invitation",
        json={
            "token": invite(operator, mail, colleague, role["id"]),
            "password": PASSWORD,
        },
    ).raise_for_status()
    login = guest.post(
        "/v1/auth/login",
        json={"email": colleague, "password": PASSWORD, "remember_me": True},
    )
    access_token = _json(login)["access_token"]
    session = login.cookies.get(SESSION_COOKIE)
    assert session, "Signing in on a remembered device set no session cookie"
    # A second invitation stays pending until every redeployment is over.
    invited = f"rehearsal-invited-{identity}@example.com"
    invitation = invite(operator, mail, invited, "user")
    favourites = [
        {"kind": "device", "id": entity.device_id},
        {"kind": "reading", "id": entity.readings["temperature"]},
    ]
    for favourite in favourites:
        operator.post("/v1/favorites", json=favourite).raise_for_status()
    guest.post(
        "/v1/favorites",
        json={"kind": "reading", "id": entity.readings["pressure"]},
        headers=_bearer(access_token),
    ).raise_for_status()
    state = RestorableState(
        operator=operator,
        guest=guest,
        entity=entity,
        group_id=group_id,
        alarm_ids=alarm_ids,
        role_id=role["id"],
        colleague=colleague,
        session=session,
        invited=invited,
        invitation=invitation,
        favourites=favourites,
    )
    state.expected = state.read()
    return state
