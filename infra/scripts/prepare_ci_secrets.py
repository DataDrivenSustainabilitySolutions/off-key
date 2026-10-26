"""Materialize deployment configuration in a private, temporary runner directory.

OFFKEY_ENVIRONMENT names the inventory (prod by default, or demo); each
environment's workflow maps its own GitHub secrets onto the names below.
"""

import json
import os
import sys
from pathlib import Path

FILES = {
    "OFFKEY_VAULT": "vault.yml",
    "OFFKEY_VAULT_PASSWORD": "vault-password",
    "OFFKEY_INVENTORY": "hosts.yml",
    "OFFKEY_DEPLOY_SSH_KEY": "deploy-key",
    "OFFKEY_DEPLOY_KNOWN_HOSTS": "known-hosts",
}


def main():
    directory = Path(os.environ["OFFKEY_DEPLOY_DIRECTORY"])
    environment = os.environ.get("OFFKEY_ENVIRONMENT", "prod")
    if environment not in {"prod", "demo"}:
        sys.exit(f"Unknown deployment environment {environment!r}.")
    values = {name: os.environ.get(name, "") for name in FILES}
    if any(not value.strip() for value in values.values()):
        sys.exit(
            f"The {environment} environment setup is incomplete; "
            "see the GitHub setup guide."
        )
    if not values["OFFKEY_VAULT"].startswith("$ANSIBLE_VAULT;"):
        sys.exit("The vault secret must contain the encrypted Ansible vault.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    for name, filename in FILES.items():
        destination = directory / filename
        destination.touch(mode=0o600, exist_ok=False)
        destination.write_text(values[name].rstrip("\n") + "\n")
    credentials = directory / "registry.json"
    credentials.touch(mode=0o600, exist_ok=False)
    credentials.write_text(
        json.dumps(
            {
                "ghcr_username": os.environ["GITHUB_ACTOR"],
                "ghcr_token": os.environ["GH_TOKEN"],
            }
        )
    )
    # Ansible inventory lives beside the environment's group_vars; secrets remain temporary.
    inventories = Path("infra/ansible/inventories") / environment
    (inventories / "group_vars/all/vault.yml").symlink_to(directory / "vault.yml")
    (inventories / "hosts.yml").symlink_to(directory / "hosts.yml")


if __name__ == "__main__":
    main()
