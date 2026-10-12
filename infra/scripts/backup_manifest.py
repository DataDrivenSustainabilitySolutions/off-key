"""Publish and verify a complete service backup without inspecting its contents."""

import argparse
import hashlib
import json
import os
import re
from pathlib import Path


def validate_names(service, names):
    if not names or len(names) != len(set(names)):
        raise ValueError("The backup artifact list must be nonempty and unique")
    if any(Path(name).name != name or name in (".", "..") for name in names):
        raise ValueError("Backup artifacts must be plain filenames")
    if service == "postgres":
        valid = (
            "roles.sql" in names
            and len(names) > 1
            and all(
                name == "roles.sql" or re.fullmatch(r".+\.dump", name) for name in names
            )
        )
    else:
        valid = len(names) == 1 and re.fullmatch(r"emqx-export-.+\.tar\.gz", names[0])
    if not valid:
        raise ValueError(f"Invalid {service} backup artifact list")


def checksum(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing regular backup artifact: {path.name}")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "verify"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("service", choices=("postgres", "emqx"))
    parser.add_argument("timestamp")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    manifest_path = args.directory / "manifest.json"
    if args.operation == "create":
        validate_names(args.service, args.files)
        if manifest_path.exists():
            raise ValueError("A completed backup must never be overwritten")
        manifest = {
            "version": 1,
            "service": args.service,
            "timestamp": args.timestamp,
            "files": {
                name: checksum(args.directory / name) for name in sorted(args.files)
            },
        }
        temporary = args.directory / ".manifest.pending"
        with temporary.open("x", encoding="utf-8") as stream:
            os.chmod(temporary, 0o600)
            json.dump(manifest, stream, sort_keys=True)
            stream.write("\n")
        temporary.replace(manifest_path)
    else:
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError(
                "Backup is missing or incomplete: no completion manifest. "
                "Take a new backup; legacy artifacts require a separately reviewed recovery procedure."
            )
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest.get("version") != 1
            or manifest.get("service") != args.service
            or manifest.get("timestamp") != args.timestamp
            or not isinstance(manifest.get("files"), dict)
        ):
            raise ValueError(
                "Backup manifest does not match the requested service and timestamp"
            )
        validate_names(args.service, list(manifest["files"]))
        for name, expected in manifest["files"].items():
            if checksum(args.directory / name) != expected:
                raise ValueError(f"Backup checksum mismatch: {name}")
    print(json.dumps(sorted(manifest["files"])))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, TypeError, AttributeError) as error:
        raise SystemExit(str(error)) from error
