"""First-run setup must preserve operator state and refuse unsafe viewer roles."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import bcrypt
import pytest
from off_key_core.auth.demo import DEMO_VIEWER_ROLE
from off_key_core.demo.catalogue import FeedSelection
from off_key_tactic_middleware import bootstrap_demo as setup
from off_key_tactic_middleware.domain import ConflictError

PASSWORD = "demo-only-test-password-01234567890123456789"


@pytest.fixture
def membership(monkeypatch):
    session = Mock(
        get=AsyncMock(return_value=SimpleNamespace(permissions=["use_dojo"])),
        scalar=AsyncMock(return_value=None),
        commit=AsyncMock(),
    )
    members = Mock(
        _lock_membership=AsyncMock(), _manager_count=AsyncMock(return_value=1)
    )
    monkeypatch.setattr(setup, "MemberService", lambda _: members)
    return session, members


@pytest.mark.parametrize(
    "role,active,verified",
    [
        ("admin", True, True),
        (DEMO_VIEWER_ROLE, False, True),
        (DEMO_VIEWER_ROLE, True, False),
    ],
)
async def test_existing_accounts_are_not_repurposed_or_reenabled(
    membership, role, active, verified
):
    session, _ = membership
    user = SimpleNamespace(role=role, is_active=active, is_verified=verified)
    session.scalar.return_value = user
    with pytest.raises(ConflictError):
        await setup.ensure_viewer(session, "viewer@example.com", PASSWORD)
    assert vars(user) == dict(role=role, is_active=active, is_verified=verified)
    session.commit.assert_not_awaited()
    session.add.assert_not_called()


async def test_admin_setup_and_exact_viewer_permissions_are_required(membership):
    session, members = membership
    members._manager_count.return_value = 0
    with pytest.raises(ConflictError, match="administrator invitation"):
        await setup.ensure_viewer(session, "viewer@example.com", PASSWORD)
    members._manager_count.return_value = 1
    session.get.return_value.permissions.append("manage_sources")
    with pytest.raises(ConflictError, match="role was changed"):
        await setup.ensure_viewer(session, "viewer@example.com", PASSWORD)
    session.commit.assert_not_awaited()


async def test_rotation_revokes_old_tokens_without_changing_the_member(membership):
    session, _ = membership
    user = SimpleNamespace(
        role=DEMO_VIEWER_ROLE,
        is_active=True,
        is_verified=True,
        hashed_password=bcrypt.hashpw(
            b"old-password", bcrypt.gensalt(rounds=4)
        ).decode(),
        session_version=3,
    )
    session.scalar.return_value = user
    await setup.ensure_viewer(session, "viewer@example.com", PASSWORD)
    assert user.session_version == 4
    assert bcrypt.checkpw(PASSWORD.encode(), user.hashed_password.encode())
    assert user.role == DEMO_VIEWER_ROLE
    await setup.ensure_viewer(session, "viewer@example.com", PASSWORD)
    assert user.session_version == 4


async def test_saved_catalogue_and_recording_policy_survive_reinitialization(
    monkeypatch,
):
    service = Mock(
        read=AsyncMock(return_value=SimpleNamespace(storage_origin="saved")),
        save=AsyncMock(),
        apply_collection=AsyncMock(),
    )
    monkeypatch.setattr(setup, "SystemService", lambda _: service)
    assert await setup.seed_catalogue(Mock(), FeedSelection()) == {"status": "kept"}
    service.save.assert_not_awaited()
    service.apply_collection.assert_not_awaited()


async def test_initial_catalogue_records_exactly_the_selected_readings(monkeypatch):
    service = Mock(
        read=AsyncMock(return_value=SimpleNamespace(storage_origin="empty")),
        save=AsyncMock(
            return_value=SimpleNamespace(
                revision=1, runtime=SimpleNamespace(collection_revision=0)
            )
        ),
        apply_collection=AsyncMock(),
    )
    monkeypatch.setattr(setup, "SystemService", lambda _: service)
    assert await setup.seed_catalogue(Mock(), FeedSelection()) == {
        "status": "loaded",
        "readings": 12,
    }
    document = service.save.call_args.args[0].document
    request = service.apply_collection.call_args.args[0]
    assert set(request.stream_ids) == {reading.id for reading in document.streams}
    assert request.policy.mode == "sample" and request.policy.interval_seconds == 5


def dojo(monkeypatch, *, suite_id, studied):
    session = Mock(
        scalar=AsyncMock(side_effect=[suite_id, 1]),
        scalars=AsyncMock(return_value=Mock(all=Mock(return_value=studied))),
    )
    benchmarks = Mock(
        import_series=AsyncMock(
            return_value=SimpleNamespace(
                items=[SimpleNamespace(id=f"d{index}") for index in range(6)]
            )
        )
    )
    suites = Mock(
        create_suite=AsyncMock(return_value=SimpleNamespace(id="s1")),
        create_study=AsyncMock(),
    )
    monkeypatch.setattr(setup, "DojoBenchmarks", lambda _: benchmarks)
    monkeypatch.setattr(setup, "DojoSuites", lambda _: suites)
    return session, benchmarks, suites


async def test_the_dojo_gets_a_ucr_suite_and_a_study_of_each_starter(monkeypatch):
    session, benchmarks, suites = dojo(monkeypatch, suite_id=None, studied=[])
    assert await setup.seed_dojo(session) == "2 studies started"
    request = benchmarks.import_series.await_args.args[0]
    assert request.series_ids == list(setup.DEMO_SERIES)
    suite = suites.create_suite.await_args.args[0]
    assert suite.name == setup.DEMO_SUITE and len(suite.dataset_ids) == 6
    assert suites.create_suite.await_args.kwargs == {"created_by": 1}
    studies = [call.args[0] for call in suites.create_study.await_args_list]
    assert [study.name for study in studies] == ["Static baseline", "Adaptive stream"]
    assert {study.suite_id for study in studies} == {"s1"}


async def test_a_seeded_dojo_is_kept_and_only_a_missing_study_is_started(
    monkeypatch,
):
    session, benchmarks, suites = dojo(
        monkeypatch, suite_id="s0", studied=["Static baseline"]
    )
    assert await setup.seed_dojo(session) == "1 study started"
    benchmarks.import_series.assert_not_awaited()
    suites.create_suite.assert_not_awaited()
    [call] = suites.create_study.await_args_list
    assert (call.args[0].suite_id, call.args[0].name) == ("s0", "Adaptive stream")
    session, _, suites = dojo(
        monkeypatch, suite_id="s0", studied=["Static baseline", "Adaptive stream"]
    )
    assert await setup.seed_dojo(session) == "kept"
    suites.create_study.assert_not_awaited()
