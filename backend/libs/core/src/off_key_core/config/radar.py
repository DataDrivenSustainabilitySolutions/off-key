"""Shared defaults for authenticated RADAR recovery."""

# Local environments need a stable key across replacement workers. Production
# always requires its own mounted secret and never uses this public default.
DEVELOPMENT_CHECKPOINT_SECRET = (
    "off-key-development-checkpoints-change-before-production"
)
