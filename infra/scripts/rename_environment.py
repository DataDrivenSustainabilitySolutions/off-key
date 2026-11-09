#!/usr/bin/env python3
"""Plan or write a private dotenv migration without changing credential values."""

import argparse
import os
import re
from pathlib import Path

ASSIGNMENT = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z_0-9]*)(\s*=)(.*)$")
IDENTITY = re.compile(r"off[-_]?key", re.IGNORECASE)
IDENTITY_VALUES = frozenset(
    {
        "APP_NAME",
        "COMPOSE_PROJECT_NAME",
        "FRONTEND_IMAGE",
        "API_GATEWAY_IMAGE",
        "TACTIC_MIDDLEWARE_IMAGE",
        "DB_SYNC_IMAGE",
        "MQTT_RADAR_IMAGE",
        "MQTT_PROXY_IMAGE",
        "TACTIC_RADAR_IMAGE",
        "TACTIC_DOCKER_DEFAULT_NETWORK",
        "TACTIC_DOCKER_ADDITIONAL_NETWORKS",
        "POSTGRES_DB",
        "JWT_ISSUER",
        "JWT_AUDIENCE",
        "MQTT_CLIENT_ID_PREFIX",
        "MQTT_USERNAME",
        "MQTT_LOCAL_PROXY_USERNAME",
        "RADAR_MQTT_USERNAME",
        "SYSTEM_COLLECTION_MQTT_USERNAME",
    }
)


def require_single_line(value: str) -> None:
    """Refuse multiline secrets rather than parsing their contents as assignments."""
    value = value.lstrip()
    if not value or value[0] not in {"'", '"'}:
        return
    quote, escaped = value[0], False
    for character in value[1:]:
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return
    raise ValueError("Multiline dotenv values require manual migration")


def migrate(contents: str) -> tuple[str, list[str]]:
    lines, changes, names = [], [], set()
    for line in contents.splitlines(keepends=True):
        match = ASSIGNMENT.match(line.rstrip("\r\n"))
        if not match:
            lines.append(line)
            continue
        prefix, key, equals, value = match.groups()
        require_single_line(value)
        renamed = (
            key.replace("OFFKEY_", "ABERRATION_", 1)
            if key.startswith("OFFKEY_")
            else key
        )
        if renamed in names:
            raise ValueError(f"Duplicate destination variable: {renamed}")
        names.add(renamed)
        updated = IDENTITY.sub("aberration", value) if key in IDENTITY_VALUES else value
        # Only the shipped local Mailpit placeholders are branding, not accounts.
        if key in {"EMAIL_USERNAME", "EMAIL_FROM"}:
            updated = value.replace("off-key@example.com", "aberration@example.com")
            if value.strip("\"'") == "off-key":
                updated = value.replace("off-key", "aberration")
        if renamed != key or updated != value:
            changes.append(f"{key} -> {renamed}" if renamed != key else key)
        ending = line[len(line.rstrip("\r\n")) :]
        lines.append(prefix + renamed + equals + updated + ending)
    return "".join(lines), changes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, help="New private file; never overwrite")
    args = parser.parse_args()
    migrated, changes = migrate(args.source.read_text())
    if args.output:
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(migrated)
    print("Changed variable names/identities (values withheld):")
    for name in changes:
        print(f"  {name}")
    print(
        "Migrate the corresponding database, Docker resources and MQTT users before use."
    )
    print(
        "Credential values were preserved. YAML inventories/vaults need separate review."
    )


if __name__ == "__main__":
    main()
