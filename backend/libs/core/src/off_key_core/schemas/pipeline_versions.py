"""Schema 1 and schema 2 monitoring designs, translated one to one.

Schema 2 has no lane. Each learned step says how it learns, and a calibration
step sits between the detectors and the alarm policy. Schema 1 designs carried
a ``strategy`` and wired the detectors straight into the policy; they are
translated when they are read. A schema 2 design that schema 1 can express is
still written in its schema 1 form, so stored designs and fingerprints stay as
they were. The editor reads and writes schema 2 (``editor_form``).
"""

from typing import Any, Literal

from pydantic import BaseModel

Learning = Literal["none", "batch", "online", "pretrained"]
Strategy = Literal["static_baseline", "adaptive_stream"]
CALIBRATION_PREFIX = "calibrate."
FIXED_SPLIT = f"{CALIBRATION_PREFIX}fixed_split"
CALIBRATION_ID = "calibrate"
# A pretrained step scores and then takes in every observation, as an online
# one does, so both run in the adaptive lane.
_STRATEGY_BY_LEARNING: dict[str, Strategy] = {
    "batch": "static_baseline",
    "online": "adaptive_stream",
    "pretrained": "adaptive_stream",
}


def component_learning(component: str) -> Learning:
    """How a component learns, from its identity alone."""
    if component.startswith("detector:"):
        from ..models.static import STATIC_MODELS

        return (
            "batch"
            if component.removeprefix("detector:") in STATIC_MODELS
            else "online"
        )
    if component.startswith("static."):
        return "batch"
    if component.startswith("adaptive."):
        return "online"
    if component.startswith("forecast."):
        return "pretrained"
    return "none"


def learning_modes(nodes: list[dict[str, Any]]) -> set[Learning]:
    """The ways the learned steps of a design learn."""
    modes = {component_learning(str(node.get("component", ""))) for node in nodes}
    modes.discard("none")
    return modes


def derived_strategy(nodes: list[dict[str, Any]]) -> Strategy | None:
    """Today's lane of a design whose learned steps all learn the same way."""
    lanes = {_STRATEGY_BY_LEARNING[mode] for mode in learning_modes(nodes)}
    return next(iter(lanes)) if len(lanes) == 1 else None


def _plain(items) -> list[dict[str, Any]]:
    return [
        item.model_dump() if isinstance(item, BaseModel) else dict(item)
        for item in items or []
    ]


def _calibration_id(nodes: list[dict[str, Any]]) -> str:
    taken = {node.get("id") for node in nodes}
    candidate, index = CALIBRATION_ID, 1
    while candidate in taken:
        index += 1
        candidate = f"{CALIBRATION_ID}_{index}"
    return candidate


def upgrade(data: Any) -> Any:
    """A schema 1 design as schema 2: the policy's inputs move to a fixed split."""
    if not isinstance(data, dict) or data.get("schema_version", 1) != 1:
        return data
    data = {**data, "schema_version": 2}
    nodes, edges = _plain(data.get("nodes")), _plain(data.get("edges"))
    policies = [node for node in nodes if node.get("kind") == "policy"]
    if len(policies) != 1 or any(node.get("kind") == "calibration" for node in nodes):
        return {**data, "nodes": nodes, "edges": edges}
    policy = policies[0]
    identifier = _calibration_id(nodes)
    params = dict(policy.get("params") or {})
    fusion = params.pop("fusion", None)
    policy["params"] = params
    nodes.insert(
        nodes.index(policy),
        {
            "id": identifier,
            "kind": "calibration",
            "component": FIXED_SPLIT,
            "params": {} if fusion is None else {"fusion": fusion},
        },
    )
    for edge in edges:
        if edge.get("target") == policy["id"]:
            edge["target"] = identifier
    edges.append({"source": identifier, "target": policy["id"], "order": 0})
    return {**data, "nodes": nodes, "edges": edges}


def downgrade(data: dict[str, Any]) -> dict[str, Any]:
    """The schema 1 form of a design, or the design itself when it has none."""
    nodes, edges = _plain(data.get("nodes")), _plain(data.get("edges"))
    strategy = derived_strategy(nodes)
    calibrations = [node for node in nodes if node.get("kind") == "calibration"]
    if strategy is None or len(calibrations) > 1:
        return data
    if calibrations:
        calibration = calibrations[0]
        if calibration.get("component") != FIXED_SPLIT:
            return data
        identifier = calibration["id"]
        others = [node for node in nodes if node is not calibration]
        if identifier != _calibration_id(others) or (
            calibration.get("contract_version", 1) != 1
        ):
            # Reading the schema 1 form back would rename the step.
            return data
        leaving = [edge for edge in edges if edge.get("source") == identifier]
        by_id = {node.get("id"): node for node in nodes}
        if (
            len(leaving) != 1
            or by_id.get(leaving[0].get("target"), {}).get("kind") != "policy"
        ):
            return data
        policy = by_id[leaving[0]["target"]]
        fusion = (calibration.get("params") or {}).get("fusion")
        if fusion is not None:
            policy["params"] = {**(policy.get("params") or {}), "fusion": fusion}
        nodes = [node for node in nodes if node is not calibration]
        edges = [edge for edge in edges if edge is not leaving[0]]
        for edge in edges:
            if edge.get("target") == identifier:
                edge["target"] = policy["id"]
    return {
        **data,
        "schema_version": 1,
        "strategy": strategy,
        "nodes": nodes,
        "edges": edges,
    }


def editor_form(data: dict[str, Any]) -> dict[str, Any]:
    """A written design as the editor reads it: schema 2, without a lane."""
    data = dict(upgrade(data))
    data.pop("strategy", None)
    return data
