"""Convert Compose's resolved JSON model to Swarm's supported input schema."""

import json
import sys

COMPONENT_LABEL = "off-key.component"


def is_observability(service):
    return (
        service.get("deploy", {}).get("labels", {}).get(COMPONENT_LABEL)
        == "observability"
    )


def select_component(model, component):
    """Keep only the requested lifecycle and the definitions its services use."""
    selected = {
        name: service
        for name, service in model["services"].items()
        if is_observability(service) == (component == "observability")
    }
    result = model | {"services": selected}
    for key in ("configs", "secrets", "networks", "volumes"):
        used = set()
        for service in selected.values():
            if key == "networks":
                used.update(service.get(key, {}))
            else:
                used.update(
                    item["source"]
                    for item in service.get(key, [])
                    if isinstance(item, dict)
                    and item.get("source")
                    and (key != "volumes" or item.get("type") == "volume")
                )
        if key in model:
            result[key] = {
                name: value for name, value in model[key].items() if name in used
            }
    return result


def compile_stack(model):
    model.pop("name", None)
    for service in model["services"].values():
        for budget in service.get("deploy", {}).get("resources", {}).values():
            if "cpus" in budget:
                budget["cpus"] = str(budget["cpus"])
        for field in ("command", "entrypoint"):
            if service.get(field) is None:
                service.pop(field, None)
        for port in service.get("ports", []):
            if "published" in port:
                port["published"] = int(port["published"])
    return model


if __name__ == "__main__":
    model = compile_stack(json.load(sys.stdin))
    if len(sys.argv) > 1:
        if sys.argv[1] not in ("application", "observability"):
            raise SystemExit("Expected application or observability component")
        model = select_component(model, sys.argv[1])
    json.dump(model, sys.stdout)
