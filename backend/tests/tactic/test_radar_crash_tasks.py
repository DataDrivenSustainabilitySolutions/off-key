"""Swarm task history names the crashes that a restarted worker hides."""

from off_key_tactic_middleware.facades.docker import crashed_tasks


def task(task_id, state, timestamp, **status):
    return {"ID": task_id, "Status": {"State": state, "Timestamp": timestamp, **status}}


def test_keeps_only_crashes_newest_first_with_their_reason():
    crashes = crashed_tasks(
        [
            task("clean", "shutdown", "2026-11-03T09:00:00Z"),
            task("done", "complete", "2026-11-03T09:01:00Z"),
            task("running", "running", "2026-11-03T09:02:00Z"),
            task(
                "oom",
                "failed",
                "2026-11-03T10:00:00Z",
                Err="task: non-zero exit (137)",
                ContainerStatus={"ExitCode": 137},
            ),
            task("lost", "Orphaned", "2026-11-03T11:00:00Z", Message="node down"),
            "not a task",
        ]
    )

    assert [crash["task_id"] for crash in crashes] == ["lost", "oom"]
    assert crashes[0] == {
        "task_id": "lost",
        "state": "orphaned",
        "error": "node down",
        "exit_code": None,
        "ended_at": "2026-11-03T11:00:00Z",
        "node_id": None,
    }
    assert crashes[1]["exit_code"] == 137
    assert "memory limit" in crashes[1]["hint"]


def test_a_task_without_status_is_not_a_crash():
    assert crashed_tasks([{"ID": "bare"}, {"ID": "odd", "Status": "failed"}]) == []
