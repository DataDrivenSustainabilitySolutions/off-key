# EMQX version and license

off-key stays on an open-source EMQX broker. Every EMQX pin is held below 5.9,
because 5.9 is where EMQX changed licence:

| EMQX release | `emqx/emqx` image licence |
| --- | --- |
| 5.8.x and earlier | Apache License 2.0 for the open-source edition |
| 5.9.0 and later, including every 6.x | Business Source License 1.1 |

The BSL is source-available, not open source. Its additional use grant allows
production use of a single node that is not offered to third parties as a hosted
or embedded product, plus non-commercial production use by educational and
non-profit organisations. Clusters and anything beyond that need a commercial
licence, and each version becomes Apache 2.0 only four years after its release.
The licence text is the `LICENSE` file at each EMQX release tag on GitHub.

## Where the version is pinned

| File | Role |
| --- | --- |
| `infra/ansible/inventories/prod/group_vars/all/release.yml` | Production and the public demo, by digest |
| `infra/stack/docker-compose.swarm.yml` | Default when `EMQX_IMAGE` is unset |
| `docker-compose.yml`, `docker-compose.cluster.yml` | Local stacks, also used by `dev/local` |
| `backend/tests/collection_integration/compose.yml` | Default broker of the collection suite |
| `.github/workflows/ci.yml` | `collection` job matrix |

All of them carry the production version. `infra/tests/test_platform_pins.py`
fails when any of them drifts from production or reaches 5.9, and when the
Dependabot ignore rule below is removed.

## Updates

Dependabot ignores `emqx/emqx` from 5.9.0 on, so it only proposes 5.8.x
patches. 5.8.9 (December 2025) is the last open-source `emqx/emqx` image.
A newer EMQX needs a licence decision first, or a move to another open-source
broker.

## Support horizon

EMQ ended maintenance of the open-source 5.8 edition on 28 February 2026, so
5.8.9 gets no further official images, bug fixes or Debian base-image updates.
EMQ still maintains the `release-58` branch for its Enterprise 5.8 builds
(`e5.8.10`, `e5.8.11`, ...) until August 2027. On that branch the broker core
stays Apache 2.0 and only the Enterprise app folders are BSL, so an
open-source image could be built from it with the `emqx` profile. Fixes made
after 5.8.9 reach off-key only through such a build or through a move to
another broker.

EMQX does not support downgrades, so a data directory written by 6.x is not
reused by 5.8. The local stack keeps EMQX data in the `local_emqx58_data` volume
and starts a fresh broker there; the older `local_emqx_data` volume from the 6.x
period is left alone and can be removed with `docker volume rm
<project>_local_emqx_data`, where `<project>` is `COMPOSE_PROJECT_NAME` from the
local `.env`, once nothing in it is needed.
