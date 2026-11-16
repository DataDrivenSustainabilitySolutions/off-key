# TimescaleDB license

off-key's database is TimescaleDB, and it already relies on features under the
Timescale License (TSL), which is source-available, not OSI open source. This page
records what that means and why it is acceptable, the way
[EMQX version and license](emqx-license.md) does for the broker.

## The two editions

| Edition | License | What off-key uses from it |
| --- | --- | --- |
| Apache 2 Edition | Apache License 2.0 | Hypertables, chunks, `create_hypertable`, `set_chunk_time_interval` |
| Community Edition | Timescale License (TSL) | Retention policies (`add_retention_policy`), user-defined jobs (`add_job`, used for anomaly retention and the storage cap), and, when `TELEMETRY_COMPRESS_AFTER_HOURS` is set, native compression |

The `timescale/timescaledb` image ships the Community Edition and enables it by
default. Check a running server with `SHOW timescaledb.license;`: `timescale` means
Community features are on, `apache` means only the Apache 2 Edition is active.
`reconcile_compression` refuses to enable compression on an `apache` server
rather than failing inside TimescaleDB.

## How this differs from EMQX

Both licenses are source-available, but they restrict different things:

| | EMQX 5.9 and later (BSL 1.1) | TimescaleDB Community (TSL) |
| --- | --- | --- |
| Self-hosted production use | Single node only, and not offered to third parties as a hosted or embedded product | Any number of nodes, no fee |
| Clustering | Needs a commercial license | Allowed |
| Main restriction | Running it beyond the use grant | Offering TimescaleDB itself to third parties as a hosted database service (DBaaS) |
| Becomes open source | Each version after four years | Never; TSL code stays TSL |

off-key installs TimescaleDB as an internal part of its own application and never
offers it to anyone as a database service, so the TSL's restriction does not apply.
That is why EMQX was frozen at its last Apache-2.0 release and TimescaleDB was not.

## If OSI open source becomes a hard requirement

Two routes keep the current behaviour without TSL code:

- Run TimescaleDB in Apache-only mode (`timescaledb.license = apache`) and replace
  the policies and jobs with an external scheduler that calls `drop_chunks`, which
  is in the Apache 2 Edition. Compression has no Apache-licensed equivalent there.
- Move to plain PostgreSQL declarative partitioning with
  [pg_partman](https://github.com/pgpartman/pg_partman) (PostgreSQL License) for
  daily partitions and retention, and drop the TimescaleDB extension.

Both are migrations, not settings, and neither is planned.

## Sources

- [TimescaleDB editions](https://docs.tigerdata.com/about/latest/timescaledb-editions/)
- [Timescale License](https://www.tigerdata.com/legal/licenses)
