"""Convert Compose's resolved JSON model to Swarm's supported input schema."""

import json
import sys


def compile_stack(model):
    model.pop("name", None)
    for service in model["services"].values():
        for field in ("command", "entrypoint"):
            if service.get(field) is None:
                service.pop(field, None)
        for port in service.get("ports", []):
            if "published" in port:
                port["published"] = int(port["published"])
    return model


if __name__ == "__main__":
    json.dump(compile_stack(json.load(sys.stdin)), sys.stdout)
