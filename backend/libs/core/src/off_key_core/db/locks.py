"""PostgreSQL advisory-lock keys used across services.

Keys are global to the database, so every service takes them from here.
73128002 is retired and must not be reused. RADAR sensor assignments lock
on hashtext('off-key-radar-sensor-assignments') instead of a number.
"""

from typing import Final

COLLECTION_CONFIGURATION_LOCK: Final = 73128001
COLLECTION_PROXY_LOCK: Final = 73128003
MIGRATION_LOCK: Final = 73128004
SYSTEM_INGRESS_LOCK: Final = 73128005
DOJO_QUEUE_LOCK: Final = 73128006
DOJO_METRICS_LOCK: Final = 73128008
# Held while a writer appends telemetry, so log positions commit in order and a
# reader that has seen a position has seen every smaller one.
TELEMETRY_LOG_LOCK: Final = 73128009
# Membership changes deliberately serialize with schema migrations.
MEMBERSHIP_LOCK: Final = MIGRATION_LOCK
