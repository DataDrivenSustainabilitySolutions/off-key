"""The restore test's own state reads back unchanged, and a loss names its kind."""

import json
import re
from copy import deepcopy
from itertools import count
from types import SimpleNamespace

import httpx
import pytest
from off_key_core.schemas.alarms import AlarmCreate
from off_key_core.schemas.favorites import FavoriteRef
from off_key_core.schemas.members import (
    AcceptInvitation,
    MemberInvitation,
    MemberUpdate,
    RoleCreate,
)
from off_key_core.schemas.system import SystemChange
from off_key_core.schemas.user import UserLogin

from tests.support import restorable_state
from tests.support.restorable_state import SESSION_COOKIE, create_restorable_state

OPERATOR = "admin@example.com"


def answer(value=None, status=200, **headers):
    return httpx.Response(status, json=value, headers=headers)


class Stack:
    """A gateway, mail sink and source broker held in memory.

    Bodies are read with the gateway's own schemas, so a request the API would
    refuse fails here too.
    """

    def __init__(self):
        self.ids = count(1)
        self.revision = self.collection_revision = 1
        self.document = {"brokers": [], "devices": [], "readings": [], "groups": []}
        self.policies, self.history, self.alarms = {}, {}, {}
        self.roles = {"admin": ["manage_members"], "user": []}
        self.members = {OPERATOR: self.member(OPERATOR, "admin", True)}
        self.invitations, self.passwords, self.sessions = {}, {}, {}
        self.bearers = {"operator": OPERATOR}
        self.favourites, self.mail, self.seen = {}, [], []
        self.routes = [
            ("GET", r"/v1/catalogue", self.catalogue),
            ("PUT", r"/v1/catalogue", self.save_catalogue),
            ("PUT", r"/v1/recording", self.record),
            ("POST", r"/v1/recording/status", self.catalogue),
            ("GET", r"/v1/readings/([^/]+)/measurements", self.measurements),
            ("POST", r"/v1/alarms", self.raise_alarm),
            ("GET", r"/v1/alarms", self.list_alarms),
            ("DELETE", r"/v1/alarms/([^/]+)", self.delete_alarm),
            ("POST", r"/v1/roles", self.create_role),
            ("GET", r"/v1/roles", self.list_roles),
            ("DELETE", r"/v1/roles/([^/]+)", self.delete_role),
            ("POST", r"/v1/invitations", self.invite),
            ("GET", r"/v1/members", self.list_members),
            ("PATCH", r"/v1/members/(\d+)", self.update_member),
            ("DELETE", r"/v1/members/(\d+)", self.remove_member),
            ("POST", r"/v1/auth/accept-invitation", self.accept),
            ("POST", r"/v1/auth/login", self.login),
            ("POST", r"/v1/auth/refresh", self.refresh),
            ("GET", r"/v1/me", self.me),
            ("POST", r"/v1/favorites", self.add_favourite),
            ("GET", r"/v1/favorites", self.list_favourites),
            ("DELETE", r"/v1/favorites", self.remove_favourite),
            ("GET", r"/api/v1/messages", self.messages),
            ("GET", r"/api/v1/message/(\d+)", self.message),
        ]

    def __call__(self, request):
        self.seen.append(request)
        body = json.loads(request.content) if request.content else None
        for method, path, handle in self.routes:
            found = re.fullmatch(path, request.url.path)
            if found and request.method == method:
                return handle(request, body, *found.groups())
        return answer(status=404)

    def member(self, email, role, verified=False):
        return {
            "id": next(self.ids),
            "email": email,
            "role": role,
            "is_active": True,
            "is_verified": verified,
        }

    def caller(self, request):
        bearer = request.headers["Authorization"].removeprefix("Bearer ")
        return self.members[self.bearers[bearer]]

    def kept(self):
        """Everything a removal must clear; history outlives its reading."""
        starred = {email: items for email, items in self.favourites.items() if items}
        return deepcopy((self.document, self.alarms, self.roles, self.members, starred))

    def catalogue(self, *_):
        document = self.document
        runtime = {
            "collection_revision": self.collection_revision,
            "collection": {"revision": self.collection_revision, "status": "applied"},
            "ingress": {
                "sources": {
                    broker["id"]: {"state": "connected"}
                    for broker in document["brokers"]
                }
            },
            "bindings": {
                reading["id"]: {
                    "policy": self.policies.get(reading["id"], {"mode": "off"})
                }
                for reading in document["readings"]
            },
        }
        return answer(
            {"revision": self.revision, "document": document, "runtime": runtime}
        )

    def save_catalogue(self, request, body):
        change = SystemChange.model_validate(body)
        if change.expected_revision != self.revision:
            return answer(status=409)
        self.revision += 1
        saved = change.document.model_dump(mode="json", by_alias=True)
        self.document = {kind: saved[kind] for kind in self.document}
        return self.catalogue()

    def record(self, request, body):
        self.policies |= dict.fromkeys(body["reading_ids"], body["policy"])
        self.collection_revision += 1
        return self.catalogue()

    def measurements(self, request, body, reading_id):
        return answer(self.history.get(reading_id, []))

    def raise_alarm(self, request, body):
        alarm = AlarmCreate.model_validate(body).model_dump(mode="json")
        (device,) = {
            reading["device_id"]
            for reading in self.document["readings"]
            if reading["id"] in alarm["reading_ids"]
        }
        alarm |= {"alarm_id": str(next(self.ids)), "device_id": device}
        self.alarms[alarm["alarm_id"]] = alarm
        return answer(alarm, 201)

    def list_alarms(self, request, body):
        device = request.url.params["device_id"]
        return answer(
            [alarm for alarm in self.alarms.values() if alarm["device_id"] == device]
        )

    def delete_alarm(self, request, body, alarm_id):
        del self.alarms[alarm_id]
        return answer(status=204)

    def role(self, role_id):
        holders = sum(member["role"] == role_id for member in self.members.values())
        return {"id": role_id, "permissions": self.roles[role_id], "members": holders}

    def create_role(self, request, body):
        role = RoleCreate.model_validate(body)
        role_id = re.sub(r"[^a-z0-9]+", "-", role.name.lower())
        self.roles[role_id] = [str(permission) for permission in role.permissions]
        return answer(self.role(role_id), 201)

    def list_roles(self, request, body):
        return answer([self.role(role_id) for role_id in self.roles])

    def delete_role(self, request, body, role_id):
        if self.role(role_id)["members"]:
            return answer(status=409)
        del self.roles[role_id]
        return answer(status=204)

    def invite(self, request, body):
        invitation = MemberInvitation.model_validate(body)
        assert invitation.role in self.roles
        token = f"invitation-{next(self.ids):032d}"
        self.invitations[token] = invitation.email
        self.members[invitation.email] = self.member(invitation.email, invitation.role)
        self.mail.append(
            {
                "ID": str(next(self.ids)),
                "To": [{"Address": invitation.email}],
                "Text": f"Choose your password: http://app/register#token={token}\n",
            }
        )
        return answer({"message": "Invitation sent."})

    def list_members(self, request, body):
        return answer(sorted(self.members.values(), key=lambda member: member["email"]))

    def member_by_id(self, member_id):
        return next(
            member for member in self.members.values() if member["id"] == int(member_id)
        )

    def update_member(self, request, body, member_id):
        member = self.member_by_id(member_id)
        member["is_active"] = MemberUpdate.model_validate(body).is_active
        return answer(member)

    def remove_member(self, request, body, member_id):
        member = self.member_by_id(member_id)
        if member["is_active"]:
            return answer(status=409)
        del self.members[member["email"]]
        self.favourites.pop(member["email"], None)
        return answer(status=204)

    def accept(self, request, body):
        accepted = AcceptInvitation.model_validate(body)
        email = self.invitations.pop(accepted.token)
        self.members[email]["is_verified"] = True
        self.passwords[email] = accepted.password
        return answer({})

    def signed_in(self, email, **headers):
        bearer = f"bearer-{next(self.ids)}"
        self.bearers[bearer] = email
        return answer({"access_token": bearer}, **headers)

    def login(self, request, body):
        login = UserLogin.model_validate(body)
        if self.passwords.get(login.email) != login.password:
            return answer(status=401)
        if not login.remember_me:
            return self.signed_in(login.email)
        session = f"session-{next(self.ids)}"
        self.sessions[session] = login.email
        # Secure, as a public deployment sets it: a cookie jar would not return
        # it over plain HTTP.
        cookie = f"{SESSION_COOKIE}={session}; HttpOnly; Path=/; SameSite=lax; Secure"
        return self.signed_in(login.email, **{"set-cookie": cookie})

    def refresh(self, request, body):
        if request.headers.get("X-Off-Key-Session") != "1":
            return answer(status=403)
        session = request.headers.get("Cookie", "").removeprefix(f"{SESSION_COOKIE}=")
        if session not in self.sessions:
            return answer(status=401)
        return self.signed_in(self.sessions[session])

    def me(self, request, body):
        member = self.caller(request)
        return answer(member | {"permissions": self.roles[member["role"]]})

    def add_favourite(self, request, body):
        favourite = FavoriteRef.model_validate(body).model_dump()
        self.favourites.setdefault(self.caller(request)["email"], []).append(favourite)
        return answer(favourite)

    def list_favourites(self, request, body):
        return answer(self.favourites.get(self.caller(request)["email"], []))

    def remove_favourite(self, request, body):
        favourite = FavoriteRef.model_validate(dict(request.url.params)).model_dump()
        self.favourites[self.caller(request)["email"]].remove(favourite)
        return answer(status=204)

    def messages(self, request, body):
        return answer({"messages": self.mail})

    def message(self, request, body, message_id):
        return answer(next(item for item in self.mail if item["ID"] == message_id))

    def publish(self, topic, payload, qos):
        """What the source broker receives is stored only for recorded readings."""
        (reading,) = (
            item["id"] for item in self.document["readings"] if item["topic"] == topic
        )
        if self.policies.get(reading, {}).get("mode") == "original":
            point = {"timestamp": f"t{next(self.ids)}", "value": float(payload)}
            self.history.setdefault(reading, []).insert(0, point)
        return SimpleNamespace(
            wait_for_publish=lambda timeout: None, is_published=lambda: True
        )


@pytest.fixture
def stack(monkeypatch):
    stack = Stack()
    publisher = SimpleNamespace(
        connect=lambda host, port: None,
        loop_start=lambda: None,
        loop_stop=lambda: None,
        disconnect=lambda: None,
        publish=stack.publish,
    )
    monkeypatch.setattr(restorable_state, "MQTTClient", lambda *_, **__: publisher)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    return stack


@pytest.fixture
def state(stack):
    transport = httpx.MockTransport(stack)
    with (
        httpx.Client(
            base_url="http://gateway",
            transport=transport,
            headers={"Authorization": "Bearer operator"},
        ) as operator,
        httpx.Client(base_url="http://gateway", transport=transport) as guest,
        httpx.Client(base_url="http://mail", transport=transport) as mail,
    ):
        yield create_restorable_state(operator, guest, mail)


def test_created_state_reads_back_unchanged_and_is_removed_without_a_trace(
    stack, state
):
    pristine = Stack().kept()
    assert stack.kept() != pristine
    expected = state.expected
    assert [member["is_verified"] for member in expected["members"]] == [
        True,
        True,
        False,
    ]
    assert expected["colleague"]["permissions"] == ["manage_monitors", "manage_alarms"]
    assert len(expected["operator favourites"]) == 2
    assert len(expected["colleague favourites"]) == 1
    assert [len(alarm["reading_ids"]) for alarm in expected["alarms"]] == [1, 2]
    assert [len(points) for points in expected["history"].values()] == [4, 4, 4]
    assert stack.document["groups"][0]["member_ids"] == [state.entity.device_id]

    state.assert_restored()
    state.accept_invitation()
    assert stack.members[state.invited]["is_verified"]
    state.remove()
    assert stack.kept() == pristine
    # The colleague's session travels on its refresh alone, never beside the
    # operator's credential.
    carried = [request for request in stack.seen if "Cookie" in request.headers]
    assert len(carried) == 2
    for request in carried:
        assert request.url.path == "/v1/auth/refresh"
        assert "Authorization" not in request.headers


LOSSES = {
    "members": lambda stack, state: stack.members[state.invited].update(
        is_active=False
    ),
    "roles": lambda stack, state: stack.roles[state.role_id].clear(),
    "operator favourites": lambda stack, state: stack.favourites[OPERATOR].pop(),
    "colleague favourites": lambda stack, state: stack.favourites[
        state.colleague
    ].clear(),
    "alarms": lambda stack, state: stack.alarms.pop(state.alarm_ids[0]),
    "history": lambda stack, state: stack.history[state.entity.reading_ids[0]].pop(),
}


@pytest.mark.parametrize("kind", list(LOSSES))
def test_a_loss_names_the_kind_that_changed(stack, state, kind):
    LOSSES[kind](stack, state)
    with pytest.raises(AssertionError, match=f"The {kind} changed"):
        state.assert_restored()


def test_a_lost_session_no_longer_signs_the_colleague_in(stack, state):
    stack.sessions.clear()
    with pytest.raises(httpx.HTTPStatusError) as error:
        state.assert_restored()
    assert error.value.response.status_code == 401
