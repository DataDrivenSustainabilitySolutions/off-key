"""Materialize a stack's deploy configuration in a private, temporary runner directory.

Production and the public demo keep their encrypted vault and inventory only as
GitHub environment secrets; no machine holds a lasting copy.
"""

import json
import os
import sys
from pathlib import Path

SHARED = {
    "OFFKEY_DEPLOY_SSH_KEY": "deploy-key",
    "OFFKEY_DEPLOY_KNOWN_HOSTS": "known-hosts",
}
STACKS = {
    "prod": {
        "OFFKEY_PROD_VAULT": "vault.yml",
        "OFFKEY_VAULT_PASSWORD": "vault-password",
        "OFFKEY_PROD_INVENTORY": "hosts.yml",
    },
    "demo": {
        "OFFKEY_DEMO_VAULT": "vault.yml",
        "OFFKEY_VAULT_PASSWORD": "vault-password",
        "OFFKEY_DEMO_INVENTORY": "hosts.yml",
    },
}


def files(stack: str) -> dict[str, str]:
    return STACKS[stack] | SHARED


def main(stack: str = "prod"):
    if stack not in STACKS:
        sys.exit(f"Unknown stack {stack!r}; expected one of {sorted(STACKS)}.")
    directory = Path(os.environ["OFFKEY_DEPLOY_DIRECTORY"])
    wanted = files(stack)
    values = {name: os.environ.get(name, "") for name in wanted}
    missing = sorted(name for name, value in values.items() if not value.strip())
    if missing:
        sys.exit(
            f"The {stack} deploy setup is incomplete ({', '.join(missing)} is empty); "
            "see the GitHub setup guide."
        )
    vault = next(name for name, filename in wanted.items() if filename == "vault.yml")
    if not values[vault].startswith("$ANSIBLE_VAULT;"):
        sys.exit(f"{vault} must contain the encrypted Ansible vault.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    for name, filename in wanted.items():
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
    # The inventory lives beside the stack's group_vars; secrets remain temporary.
    inventory = Path(f"infra/ansible/inventories/{stack}")
    (inventory / "group_vars/all/vault.yml").symlink_to(directory / "vault.yml")
    (inventory / "hosts.yml").symlink_to(directory / "hosts.yml")


if __name__ == "__main__":
    main(*sys.argv[1:2])
