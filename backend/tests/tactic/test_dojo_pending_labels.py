"""Pending labels: proposed by a condition or as intervals, by a member or an
agent, and added or dismissed by a member."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.auth.agents import agent_key_digest, new_agent_key
from off_key_core.db.models import (
    Agent,
    User,
)
from off_key_core.models.pipeline_formula import evaluator, parse
from off_key_core.schemas.dojo import (
    CsvImportQuery,
    LabelCreate,
    LabelRule,
    PendingLabelAccept,
    PendingLabelChoice,
    PendingLabelDismiss,
    PendingLabelProposal,
)
from off_key_tactic_middleware.domain import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from off_key_tactic_middleware.services.dojo.pending_labels import (
    DojoPendingLabels,
    Holds,
    shaped,
)

from tests.support.dojo import create_dojo_tables
from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app
from tests.support.http import asgi_client
from tests.support.membership import bootstrap
from tests.support.tokens import access_token

T0 = datetime(2026, 3, 1, tzinfo=UTC)
SECOND = timedelta(seconds=1)


def at(minute: float) -> datetime:
    return T0 + timedelta(minutes=minute)


def found(condition: str, rows, names: int) -> list:
    holds = Holds(evaluator(parse(condition, condition=True)), names)
    for row in rows:
        holds.feed(*row)
    return holds.finish()


def test_a_condition_holds_from_its_first_instant_to_its_last():
    rows = [
        (at(minute), "u", float(value))
        for minute, value in enumerate([0, 5, 6, 0, 7, 0, 0, 8, 9])
    ]
    assert found("u > 1", rows, 1) == [
        (at(1), at(2)),
        # A lone instant gets a second.
        (at(4), at(4) + SECOND),
        # Still holding at the last value.
        (at(7), at(8)),
    ]


def test_each_series_keeps_its_last_value_until_its_next():
    rows = [
        # The condition waits until both series have a value.
        (at(0), "u", 5.0),
        (at(1), "i", 1.0),
        (at(2), "u", 6.0),
        (at(3), "i", 0.0),
        (at(4), "i", 2.0),
        (at(5), "u", 0.0),
    ]
    assert found("u > 1 and i > 0", rows, 2) == [
        (at(1), at(2)),
        (at(4), at(4) + SECOND),
    ]


def test_a_value_the_condition_cannot_compute_is_skipped():
    rows = [(at(0), "u", 1.0), (at(1), "u", 0.0), (at(2), "u", 2.0)]
    # 1 / 0 neither ends the interval nor starts one.
    assert found("1 / u > 0", rows, 1) == [(at(0), at(2))]


def test_close_intervals_join_before_short_ones_are_left_out():
    intervals = [(at(0), at(1)), (at(2), at(3)), (at(10), at(10.5))]
    assert shaped(intervals, timedelta(minutes=2), timedelta(0)) == [
        (at(0), at(3)),
        (at(10), at(10.5)),
    ]
    assert shaped(intervals, timedelta(0), timedelta(minutes=1)) == [
        (at(0), at(1)),
        (at(2), at(3)),
    ]


@pytest_asyncio.fixture
async def sessions(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, factory = member_database
    async with engine.begin() as connection:
        await connection.run_sync(create_dojo_tables)
    member = await bootstrap(factory)
    async with factory() as session:
        agent = Agent(
            name="Labeller", key_hash=agent_key_digest(new_agent_key()), key_hint="abcd"
        )
        session.add(agent)
        await session.commit()
        user = await session.get(User, member)
        await session.refresh(agent)
        rows = "\n".join(
            # Speed is high from minute 10 to 19 and 40 to 41, the motor hot
            # from minute 15 to 49.
            f"{at(minute).isoformat()},"
            f"{3500 if 10 <= minute < 20 or 40 <= minute < 42 else 1000},"
            f"{90 if 15 <= minute < 50 else 40}"
            for minute in range(60)
        )
        dataset = await DojoDatasets(session).import_csv(
            f"time,speed,motor temperature\n{rows}\n".encode(),
            CsvImportQuery(name="Drives"),
            created_by=member,
        )
    return factory, dataset, user, agent


@pytest.mark.asyncio
async def test_a_rule_proposes_where_its_condition_holds(sessions):
    factory, dataset, user, agent = sessions
    rule = LabelRule(
        condition="speed > 3000 and `motor temperature` > 80", note="Hot at speed"
    )
    async with factory() as session:
        made = await DojoPendingLabels(session).propose_by_rule(dataset.id, rule, user)
    assert [(item.start_at, item.end_at) for item in made.items] == [
        (at(15), at(19)),
        (at(40), at(41)),
    ]
    assert {(item.rule, item.note, item.created_by) for item in made.items} == {
        ("speed > 3000 and `motor temperature` > 80", "Hot at speed", user.id)
    }
    assert (made.skipped, made.truncated, made.replaced) == (0, False, 0)
    async with factory() as session:
        longer = await DojoPendingLabels(session).propose_by_rule(
            dataset.id,
            LabelRule(condition="speed > 3000", min_duration_seconds=120),
            agent,
        )
        # Pending labels score nothing: the dataset still has no labels.
        assert (await DojoLabels(session).list(dataset.id)).items == []
    assert [(item.start_at, item.created_by_agent) for item in longer.items] == [
        (at(10), "Labeller")
    ]


@pytest.mark.asyncio
async def test_a_rule_names_the_series_it_cannot_find(sessions):
    factory, dataset, user, _ = sessions
    async with factory() as session:
        with pytest.raises(ValidationError, match="Unknown feature sped"):
            await DojoPendingLabels(session).propose_by_rule(
                dataset.id, LabelRule(condition="sped > 3000"), user
            )
        with pytest.raises(ValidationError, match="Write a condition"):
            await DojoPendingLabels(session).propose_by_rule(
                dataset.id, LabelRule(condition="speed + 1"), user
            )


@pytest.mark.asyncio
async def test_intervals_on_a_label_are_skipped_and_replace_takes_back_your_own(
    sessions,
):
    factory, dataset, user, agent = sessions
    async with factory() as session:
        await DojoLabels(session).create(
            dataset.id,
            LabelCreate(start_at=at(0), end_at=at(5)),
            created_by=user.id,
        )
        service = DojoPendingLabels(session)
        await service.propose_by_rule(
            dataset.id, LabelRule(condition="speed > 3000"), user
        )
        first = await service.propose(
            dataset.id,
            PendingLabelProposal(
                labels=[
                    LabelCreate(start_at=at(4), end_at=at(6)),
                    LabelCreate(start_at=at(20), end_at=at(25), note="Vibration"),
                ],
                rule="where the vibration doubled",
            ),
            agent,
        )
        assert (len(first.items), first.skipped) == (1, 1)
        again = await service.propose(
            dataset.id,
            PendingLabelProposal(
                labels=[LabelCreate(start_at=at(30), end_at=at(31))], replace=True
            ),
            agent,
        )
        listed = await service.list(dataset.id)
        with pytest.raises(ValidationError, match="outside the dataset"):
            await service.propose(
                dataset.id,
                PendingLabelProposal(
                    labels=[LabelCreate(start_at=at(100), end_at=at(101))]
                ),
                agent,
            )
    assert again.replaced == 1
    # The member's rule kept its pending label; the agent's first was replaced.
    assert [(item.start_at, item.created_by_agent) for item in listed.items] == [
        (at(10), None),
        (at(30), "Labeller"),
        (at(40), None),
    ]


@pytest.mark.asyncio
async def test_a_member_adds_pending_labels_changed_or_not_and_dismisses_others(
    sessions, monkeypatch
):
    factory, dataset, user, agent = sessions
    async with factory() as session:
        service = DojoPendingLabels(session)
        made = await service.propose(
            dataset.id,
            PendingLabelProposal(
                labels=[
                    LabelCreate(start_at=at(minute), end_at=at(minute + 2), note="Trip")
                    for minute in (10, 20, 30, 31)
                ],
                rule="where the breaker tripped",
            ),
            agent,
        )
    first, second, third, overlapping = (item.id for item in made.items)
    async with factory() as session:
        service = DojoPendingLabels(session)
        added = await service.accept(
            dataset.id,
            PendingLabelAccept(
                items=[
                    PendingLabelChoice(id=first),
                    PendingLabelChoice(id=second, end_at=at(25), note="Long trip"),
                ]
            ),
            created_by=user.id,
        )
        # Two overlapping pending labels cannot both become labels.
        with pytest.raises(ConflictError, match="may not overlap"):
            await service.accept(
                dataset.id,
                PendingLabelAccept(
                    items=[
                        PendingLabelChoice(id=third),
                        PendingLabelChoice(id=overlapping),
                    ]
                ),
                created_by=user.id,
            )
        await session.rollback()
        await service.dismiss(dataset.id, PendingLabelDismiss(ids=[overlapping]))
        with pytest.raises(NotFoundError):
            await service.dismiss(dataset.id, PendingLabelDismiss(ids=[first]))
        left = await service.list(dataset.id)
        labels = await DojoLabels(session).list(dataset.id)
    assert [(item.start_at, item.end_at, item.note) for item in added] == [
        (at(10), at(12), "Trip"),
        (at(20), at(25), "Long trip"),
    ]
    assert {(item.rule, item.suggested_by_agent) for item in labels.items} == {
        ("where the breaker tripped", "Labeller")
    }
    assert [item.id for item in left.items] == [third]


@pytest.mark.asyncio
async def test_routes_let_keys_propose_and_only_members_decide(sessions):
    factory, dataset, user, agent = sessions
    key = new_agent_key()
    async with factory() as session:
        stored = await session.get(Agent, agent.id)
        stored.key_hash = agent_key_digest(key)
        await session.commit()
    application = gateway_app(sessions=factory)
    path = f"/v1/dojo/datasets/{dataset.id}/pending-labels"
    as_agent = {"Authorization": f"Bearer {key}"}
    as_member = {"Authorization": f"Bearer {access_token(user)}"}
    async with asgi_client(application) as client:
        proposed = await client.post(
            f"{path}/by-rule",
            json={"condition": "speed > 3000", "merge_gap_seconds": 3600},
            headers=as_agent,
        )
        listed = await client.get(path, headers=as_agent)
        refused = await client.post(
            f"{path}/accept",
            json={"items": [{"id": proposed.json()["items"][0]["id"]}]},
            headers=as_agent,
        )
        accepted = await client.post(
            f"{path}/accept",
            json={"items": [{"id": proposed.json()["items"][0]["id"]}]},
            headers=as_member,
        )
    assert proposed.status_code == 201, proposed.text
    assert [item["start_at"] for item in proposed.json()["items"]] == [
        "2026-03-01T00:10:00Z"
    ]
    assert listed.json()["items"][0]["created_by_agent"] == "Labeller"
    assert refused.status_code == 403
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["items"][0]["suggested_by_agent"] == "Labeller"
