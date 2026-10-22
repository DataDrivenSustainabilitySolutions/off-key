"""The largest pipeline definition the limits admit."""

from off_key_core.models.pipelines import (
    pipeline_catalog,
)
from off_key_core.schemas.pipelines import PipelineDefinition


def maximum_definition():
    definition = pipeline_catalog().templates[1].definition.model_dump(mode="json")
    definition["input_slots"] = [
        {"id": f"slot_{index:03}" + "x" * 92, "label": f"Reading {index}"}
        for index in range(100)
    ]
    previous = "input"
    edges = []
    for index in range(60):
        identifier = f"p{index:02}_" + "x" * 96
        definition["nodes"].append(
            {
                "id": identifier,
                "kind": "transform",
                "component": "adaptive.random_projection",
                "params": {"n_components": 100},
            }
        )
        edges.append({"source": previous, "target": identifier})
        previous = identifier
    definition["edges"] = [
        *edges,
        {"source": previous, "target": "detector"},
        {"source": "detector", "target": "policy"},
        {"source": "policy", "target": "output"},
    ]
    return PipelineDefinition.model_validate(definition)
