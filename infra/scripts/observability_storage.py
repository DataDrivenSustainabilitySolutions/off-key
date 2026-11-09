"""Prepare only Aberration's bounded log filesystem; no Docker/host restarts.

The controller validates settings with ObservabilitySettings before sending them.
This stdlib-only helper runs on a worker with the existing system Python.
"""

import json
import os
import pathlib
import stat
import subprocess
import sys

GIB = 1024**3
HEADER = "# Managed by Aberration observability storage.\n"


def run(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=90)


def atomic_json(path, value):
    temporary = path.with_suffix(".pending")
    with open(
        temporary, "w", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW, 0o600)
    ) as output:
        json.dump(value, output)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def prepare(settings):
    root = pathlib.Path(settings["storage_root"])
    mount = pathlib.Path(settings["data_root"])
    if (
        str(root) != "/var/lib/aberration-observability"
        or str(mount) != "/srv/aberration-observability"
    ):
        raise ValueError("Refusing storage outside the dedicated observability paths")
    if not 4 <= settings["storage_size_gib"] <= 100:
        raise ValueError("Invalid observability storage size")
    for path in (root, mount):
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Refusing symlinked storage")
    root.mkdir(mode=0o700, exist_ok=True)
    root_metadata = root.stat()
    if root_metadata.st_uid != 0 or root_metadata.st_mode & 0o077:
        raise ValueError("Observability storage root is not private and root-owned")
    owner = root / "ownership.json"
    image = root / "storage.ext4"
    if owner.is_symlink() or image.is_symlink():
        raise ValueError("Refusing symlinked storage ownership or image")
    identity = {
        "stack": settings["stack_name"],
        "size_bytes": settings["storage_size_gib"] * GIB,
    }
    previous = json.loads(owner.read_text()) if owner.exists() else None
    if previous and any(previous.get(k) != v for k, v in identity.items()):
        raise ValueError(
            "Existing storage belongs to a different policy; no automatic resize"
        )
    if image.exists() and not previous:
        raise ValueError("Unowned filesystem image; refusing to overwrite it")
    changed = False
    if not image.exists():
        if previous:
            raise ValueError(
                "Owned filesystem image is missing; restore it before deploying"
            )
        available = os.statvfs(root).f_bavail * os.statvfs(root).f_frsize
        if available < identity["size_bytes"] + 10 * GIB:
            raise ValueError(
                "Insufficient host disk headroom for bounded observability storage"
            )
        atomic_json(owner, identity | {"phase": "preparing"})
        descriptor = os.open(
            image, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
        try:
            os.ftruncate(descriptor, identity["size_bytes"])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        run("mkfs.ext4", "-F", "-m", "0", "-L", "aberration-observability", str(image))
        changed = True
    metadata = image.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != 0
        or metadata.st_size != identity["size_bytes"]
    ):
        raise ValueError("Unexpected filesystem image ownership, type or size")
    host_space = os.statvfs(root)
    future_growth = max(0, metadata.st_size - metadata.st_blocks * 512)
    if host_space.f_bavail * host_space.f_frsize < future_growth + 10 * GIB:
        raise ValueError("Insufficient host disk headroom for remaining storage growth")
    uuid = run("blkid", "-s", "UUID", "-o", "value", str(image)).stdout.strip()
    if not uuid or (previous and previous.get("uuid") not in (None, uuid)):
        raise ValueError("Filesystem identity mismatch")
    if run("blkid", "-s", "TYPE", "-o", "value", str(image)).stdout.strip() != "ext4":
        raise ValueError("Unexpected filesystem type")
    mounted = run("mountpoint", "-q", str(mount), check=False).returncode == 0
    if not mounted:
        if mount.exists() and any(mount.iterdir()):
            raise ValueError("Refusing to cover existing files with a mount")
        mount.mkdir(mode=0o000, exist_ok=True)
        mount.chmod(0o000)  # Service UIDs fail closed if the filesystem is unavailable.
    unit = pathlib.Path("/etc/systemd/system/aberration-observability-storage.service")
    if unit.is_symlink():
        raise ValueError("Refusing a symlinked systemd unit")
    content = (
        HEADER
        + f"""[Unit]
Description=Aberration bounded observability storage
After=local-fs.target
Before=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -ec 'mountpoint -q {mount} || mount -o loop,nodev,nosuid,noexec {image} {mount}'
ExecStop=/usr/bin/umount {mount}
TimeoutStartSec=90
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
"""
    )
    if unit.exists() and not unit.read_text().startswith(HEADER):
        raise ValueError("Refusing to replace a unit managed by another application")
    if not unit.exists() or unit.read_text() != content:
        unit.write_text(content)
        unit.chmod(0o644)
        run("systemctl", "daemon-reload")
        changed = True
    run("systemctl", "enable", "--now", unit.name)
    actual_uuid = run(
        "findmnt", "-n", "-o", "UUID", "--mountpoint", str(mount)
    ).stdout.strip()
    if actual_uuid != uuid:
        raise ValueError("Mounted filesystem does not match the owned image")
    for name, uid, gid in (("loki", 10001, 10001), ("grafana", 472, 0)):
        directory = mount / name
        if directory.is_symlink():
            raise ValueError("Refusing a symlinked data directory")
        if not directory.exists():
            directory.mkdir(mode=0o700)
            changed = True
        details = directory.stat()
        if (details.st_uid, details.st_gid, stat.S_IMODE(details.st_mode)) != (
            uid,
            gid,
            0o700,
        ):
            os.chown(directory, uid, gid)
            directory.chmod(0o700)
            changed = True
    ready = identity | {"phase": "ready", "uuid": uuid}
    if previous != ready:
        atomic_json(owner, ready)
    return {
        "changed": changed,
        "capacity_bytes": identity["size_bytes"],
        "filesystem_uuid": uuid,
    }


if __name__ == "__main__":
    print(json.dumps(prepare(json.loads(sys.argv[1]))))
