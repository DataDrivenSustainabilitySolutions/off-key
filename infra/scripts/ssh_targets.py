"""Show where a release connects over SSH and whether the runner trusts each host.

A release that cannot reach a host prints only the failed task's name and cause.
This names each inventory host's SSH target, whether the known-hosts file has an
entry for exactly that address and port, whether the key the host presents now
matches it, and, given another stack's inventory, whether the target is the same
there. Addresses are management-tailnet addresses; no key material or other
configuration is printed.
"""

import argparse
import json
import subprocess
from pathlib import Path

DEFAULT_USER = "ansible"  # ansible.cfg remote_user


def targets(inventory: dict) -> dict[str, dict]:
    """Each host's SSH target and groups from `ansible-inventory --list` output."""
    hostvars = inventory.get("_meta", {}).get("hostvars", {})
    groups: dict[str, list[str]] = {}
    for group, members in inventory.items():
        if group in {"_meta", "all", "ungrouped"} or not isinstance(members, dict):
            continue
        for host in members.get("hosts", []):
            groups.setdefault(host, []).append(group)
    result = {}
    for host in sorted(set(hostvars) | set(groups)):
        values = hostvars.get(host, {})
        result[host] = {
            "address": str(values.get("ansible_host") or host),
            "port": int(values.get("ansible_port") or 22),
            "user": str(values.get("ansible_user") or DEFAULT_USER),
            "groups": sorted(groups.get(host, [])),
            "own_key": bool(values.get("ansible_ssh_private_key_file")),
        }
    return result


def identity(address: str, port: int) -> str:
    return address if port == 22 else f"[{address}]:{port}"


def known_keys(
    known_hosts: Path, address: str, port: int
) -> set[tuple[str, str]] | None:
    """The trusted (type, key) pairs for this address and port; None if unreadable."""
    found = subprocess.run(
        ["ssh-keygen", "-F", identity(address, port), "-f", str(known_hosts)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if found.returncode not in (0, 1):
        return None
    return {
        tuple(line.split()[1:3])
        for line in found.stdout.splitlines()
        if line and not line.startswith("#") and len(line.split()) >= 3
    }


def presented_keys(address: str, port: int) -> set[tuple[str, str]] | None:
    """The host keys the target presents now; None if it does not answer."""
    try:
        scan = subprocess.run(
            ["ssh-keyscan", "-T", "5", "-p", str(port), address],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        ).stdout
    except subprocess.TimeoutExpired:
        return None
    keys = {
        tuple(line.split()[1:3])
        for line in scan.splitlines()
        if line and not line.startswith("#") and len(line.split()) >= 3
    }
    return keys or None


def describe(
    host: str,
    target: dict,
    trusted: set | None,
    presented: set | None,
    other: dict | None,
    other_name: str,
) -> str:
    groups = ", ".join(target["groups"]) or "no group"
    line = (
        f"SSH target {host} ({groups}): {target['user']}@{target['address']} "
        f"port {target['port']}; known-hosts entry: "
    )
    line += "unreadable" if trusted is None else ("yes" if trusted else "no")
    if presented is None:
        line += "; host key: no answer"
    elif trusted:
        line += "; host key: " + ("matches" if presented & trusted else "differs")
    if other is not None:
        match = other.get(host)
        if match is None:
            line += f"; not in the {other_name} inventory"
        else:
            same = all(match[key] == target[key] for key in ("address", "port", "user"))
            line += f"; same as {other_name}: " + (
                "yes"
                if same
                else f"no, {other_name} uses {match['user']}@{match['address']} "
                f"port {match['port']}"
            )
    if target.get("own_key"):
        line += "; sets its own ansible_ssh_private_key_file, which the runner lacks"
    return line


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path, help="ansible-inventory --list JSON")
    parser.add_argument("--known-hosts", type=Path, required=True)
    parser.add_argument("--compare", type=Path, help="another stack's inventory JSON")
    parser.add_argument("--compare-name", default="production")
    parser.add_argument("--no-scan", action="store_true")
    args = parser.parse_args()
    hosts = targets(json.loads(args.inventory.read_text()))
    other = None
    if args.compare and args.compare.is_file():
        other = targets(json.loads(args.compare.read_text()))
    for host, target in hosts.items():
        trusted = known_keys(args.known_hosts, target["address"], target["port"])
        presented = (
            None if args.no_scan else presented_keys(target["address"], target["port"])
        )
        print(describe(host, target, trusted, presented, other, args.compare_name))


if __name__ == "__main__":
    main()
