"""The public demo uses a dedicated server-side account, never a human account."""

from .permissions import Permission

DEMO_VIEWER_ROLE = "demo-viewer"
# Dojo currently requires this permission for reads too. The gateway's explicit
# guest allowlist forbids every mutation; it never sends the credential to a browser.
DEMO_VIEWER_PERMISSIONS = frozenset({Permission.use_dojo})
