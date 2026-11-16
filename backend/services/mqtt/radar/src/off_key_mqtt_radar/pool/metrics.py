"""Pool state for Prometheus, read from the replica's own bookkeeping on scrape."""

import time
from collections import Counter
from collections.abc import Iterator

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

from .worker import RadarPool, resident_bytes


class PoolCollector(Collector):
    """Expose children, capacity, lease health and crashes of one replica."""

    def __init__(self, pool: RadarPool):
        self.pool = pool

    def collect(self) -> Iterator[CounterMetricFamily | GaugeMetricFamily]:
        children = list(self.pool.children.values())
        running = GaugeMetricFamily(
            "offkey_radar_pool_children",
            "Workloads this replica is running, by kind.",
            labels=["kind"],
        )
        by_kind = Counter(child.kind for child in children)
        for kind in self.pool.options.kinds:
            running.add_metric([kind], by_kind.get(kind, 0))
        yield running
        yield GaugeMetricFamily(
            "offkey_radar_pool_capacity",
            "Workloads this replica may run at once.",
            value=self.pool.options.capacity,
        )
        yield GaugeMetricFamily(
            "offkey_radar_pool_healthy",
            "1 while the replica holds its leases.",
            value=int(self.pool.healthy),
        )
        yield GaugeMetricFamily(
            "offkey_radar_pool_lease_age_seconds",
            "Seconds since the replica last renewed its leases.",
            value=time.monotonic() - self.pool.last_renewed,
        )
        resident = 0
        for child in children:
            if child.process.returncode is None:
                resident += resident_bytes(child.process.pid) or 0
        yield GaugeMetricFamily(
            "offkey_radar_pool_children_resident_bytes",
            "Resident memory of all running children.",
            value=resident,
        )
        yield CounterMetricFamily(
            "offkey_radar_pool_crashes",
            "Children that ended with a crash.",
            value=self.pool.crashes,
        )
        yield CounterMetricFamily(
            "offkey_radar_pool_memory_kills",
            "Children killed for exceeding their memory limit.",
            value=self.pool.memory_kills,
        )
