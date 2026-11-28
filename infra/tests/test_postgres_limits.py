"""Production Postgres leaves room for every pool and for release jobs."""

import unittest

import yaml
from support import ROOT

SWARM = ROOT / "stack/docker-compose.swarm.yml"
SERVICE_VARS = ROOT / "ansible/roles/stack_prepare/vars/main.yml"
# Slots for services on library pool defaults, release jobs, preflight replicas and an admin.
HEADROOM = 40


def postgres_settings():
    command = yaml.safe_load(SWARM.read_text())["services"]["postgres"]["command"]
    assert command[0] == "postgres", command
    pairs = zip(command[1::2], command[2::2], strict=True)
    return dict(value.split("=", 1) for flag, value in pairs if flag == "-c")


def explicit_pool_slots():
    environments = yaml.safe_load(SERVICE_VARS.read_text())["service_environment"]
    return sum(
        int(environment["POSTGRES_ASYNC_POOL_SIZE"])
        + int(environment.get("POSTGRES_ASYNC_MAX_OVERFLOW", 0))
        for environment in environments.values()
        if "POSTGRES_ASYNC_POOL_SIZE" in environment
    )


class PostgresLimitsTest(unittest.TestCase):
    def test_max_connections_covers_pools_and_release_jobs(self):
        self.assertGreaterEqual(
            int(postgres_settings()["max_connections"]),
            explicit_pool_slots() + HEADROOM,
        )

    def test_dead_client_connections_are_dropped(self):
        settings = postgres_settings()
        idle = int(settings["tcp_keepalives_idle"])
        interval = int(settings["tcp_keepalives_interval"])
        count = int(settings["tcp_keepalives_count"])
        self.assertLessEqual(idle + interval * count, 300)


if __name__ == "__main__":
    unittest.main()
