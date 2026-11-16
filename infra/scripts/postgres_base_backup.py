"""Take a PostgreSQL base backup into the WAL archive and prune what it supersedes.

Runs on the node that holds the postgres task, from the systemd timer that the
postgres_wal role installs. Everything happens inside the running container,
in the archive volume it mounts at /var/lib/postgresql/wal-archive:

1. ``pg_basebackup`` writes ``base/<UTC timestamp>.partial`` (server-side
   zstd, no WAL: the archive already holds it) and renames it when complete.
2. Only the newest ``keep`` complete base backups stay; older ones go.
3. ``pg_archivecleanup`` removes archived WAL older than the oldest backup
   kept, so every kept backup can still be rolled forward to now.

Usage: python3 postgres_base_backup.py <stack> [--keep N]
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime

ARCHIVE = "/var/lib/postgresql/wal-archive"
BACKUP_NAME = re.compile(r"^\d{8}T\d{6}Z$")
LSN = re.compile(r"^([0-9A-Fa-f]{1,8})/([0-9A-Fa-f]{1,8})$")
SEGMENT_BYTES = 16 * 1024 * 1024


def wal_segment(timeline: int, lsn: str, segment_bytes: int = SEGMENT_BYTES) -> str:
    """The WAL file that holds ``lsn``, as PostgreSQL names it."""
    match = LSN.match(lsn)
    if match is None:
        raise ValueError(f"Not an LSN: {lsn}")
    position = (int(match[1], 16) << 32) | int(match[2], 16)
    segment = position // segment_bytes
    per_id = 0x100000000 // segment_bytes
    return f"{timeline:08X}{segment // per_id:08X}{segment % per_id:08X}"


def oldest_needed_segment(manifest: dict) -> str:
    """First WAL file the backup described by ``manifest`` needs to recover."""
    ranges = manifest.get("WAL-Ranges") or []
    if not ranges:
        raise ValueError("The backup manifest names no WAL range")
    first = min(ranges, key=lambda item: int(item["Timeline"]))
    return wal_segment(int(first["Timeline"]), first["Start-LSN"])


def split_backups(names: list[str], keep: int) -> tuple[list[str], list[str]]:
    """(kept, removable) complete backups, newest first; partial ones are left."""
    complete = sorted((n for n in names if BACKUP_NAME.match(n)), reverse=True)
    return complete[:keep], complete[keep:]


def container(stack: str) -> str:
    found = subprocess.run(
        [
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.swarm.service.name={stack}_postgres",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if len(found) != 1:
        raise SystemExit(
            f"Expected one running {stack}_postgres container, found {len(found)}"
        )
    return found[0]


def in_container(name: str, *argv: str) -> str:
    return subprocess.run(
        ["docker", "exec", "-u", "postgres", name, *argv],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def run(stack: str, keep: int) -> dict:
    if keep < 1:
        raise SystemExit("Keep at least one base backup")
    name = container(stack)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    partial = f"{ARCHIVE}/base/{stamp}.partial"
    in_container(
        name,
        "pg_basebackup",
        "-U",
        "postgres",
        "-D",
        partial,
        "-Ft",
        "-X",
        "none",
        "--checkpoint=fast",
        "--compress=server-zstd",
    )
    in_container(name, "mv", partial, f"{ARCHIVE}/base/{stamp}")
    kept, removable = split_backups(
        in_container(name, "ls", f"{ARCHIVE}/base").split(), keep
    )
    for old in removable:
        in_container(name, "rm", "-r", "--", f"{ARCHIVE}/base/{old}")
    manifest = json.loads(
        in_container(name, "cat", f"{ARCHIVE}/base/{kept[-1]}/backup_manifest")
    )
    oldest = oldest_needed_segment(manifest)
    in_container(name, "pg_archivecleanup", "-x", ".zst", f"{ARCHIVE}/wal", oldest)
    return {"backup": stamp, "kept": kept, "removed": removable, "wal_from": oldest}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("stack")
    parser.add_argument("--keep", type=int, default=2)
    arguments = parser.parse_args()
    json.dump(run(arguments.stack, arguments.keep), sys.stdout)
    print()
