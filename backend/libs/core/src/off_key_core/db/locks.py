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
# Membership changes deliberately serialize with schema migrations.
MEMBERSHIP_LOCK: Final = MIGRATION_LOCK
