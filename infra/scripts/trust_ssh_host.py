#!/usr/bin/env python3
"""Enroll an SSH host only after matching a fingerprint obtained out of band."""

import argparse
import fcntl
import os
import re
import subprocess
import tempfile
from pathlib import Path


def enroll(host, port, fingerprint, known_hosts):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.:-]*", host):
        raise ValueError(
            "Use an IP address or DNS hostname, not an SSH command or alias"
        )
    if not 1 <= port <= 65535 or not re.fullmatch(
        r"SHA256:[A-Za-z0-9+/]{43}", fingerprint
    ):
        raise ValueError(
            "Supply a valid port and the SHA256 fingerprint from the server console"
        )
    scan = subprocess.run(
        ["ssh-keyscan", "-T", "5", "-p", str(port), "-t", "ed25519", host],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout
    with tempfile.NamedTemporaryFile(mode="w+") as candidate:
        candidate.write(scan)
        candidate.flush()
        result = subprocess.run(
            ["ssh-keygen", "-lf", candidate.name, "-E", "sha256"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    fingerprints = {line.split()[1] for line in result.stdout.splitlines()}
    if fingerprints != {fingerprint}:
        raise ValueError("Host fingerprint mismatch; known_hosts has not been changed")
    lines = [line for line in scan.splitlines() if line and not line.startswith("#")]
    if not lines or any(line.split()[1] != "ssh-ed25519" for line in lines):
        raise ValueError("No valid Ed25519 host key was returned")
    identity = host if port == 22 else f"[{host}]:{port}"
    known_hosts.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(known_hosts, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a+") as output:
        # Serialize enrollment checks; append so OpenSSH's concurrent additions
        # are preserved even though it does not participate in this lock.
        fcntl.flock(output, fcntl.LOCK_EX)
        existing = subprocess.run(
            ["ssh-keygen", "-F", identity, "-f", str(known_hosts)],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if existing.returncode not in (0, 1):
            raise ValueError("Cannot read the existing known_hosts file")
        keys = {
            tuple(line.split()[1:3])
            for line in existing.stdout.splitlines()
            if line and not line.startswith("#")
        }
        scanned = {tuple(line.split()[1:3]) for line in lines}
        if keys:
            if scanned.issubset(keys):
                return
            raise ValueError(
                "This host already has different trusted keys; verify the rotation and remove the old entry explicitly"
            )
        # One O_APPEND write preserves complete records alongside other writers.
        records = "\n" + "".join(
            f"{identity} {kind} {key}\n" for kind, key in sorted(scanned)
        )
        os.write(output.fileno(), records.encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument(
        "fingerprint", help="Trusted SHA256 fingerprint from the VM/provider console"
    )
    parser.add_argument("--port", type=int, default=22)
    parser.add_argument(
        "--known-hosts", type=Path, default=Path.home() / ".ssh/known_hosts"
    )
    args = parser.parse_args()
    try:
        enroll(args.host, args.port, args.fingerprint, args.known_hosts)
    except (ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"Host enrollment failed: {exc}\n")
    print(f"Verified {args.host}:{args.port} ({args.fingerprint})")


if __name__ == "__main__":
    main()
