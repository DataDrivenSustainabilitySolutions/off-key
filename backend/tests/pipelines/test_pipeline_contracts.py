"""Real lightweight graph compilation, bounded catalog controls and fingerprints."""

import subprocess
import sys

import pytest
from off_key_core.models.pipeline_fields import component_fields
from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    pipeline_catalog,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import BoundInput, PipelineDefinition

pytestmark = pytest.mark.radar_integration


def template(strategy="adaptive_stream"):
    return next(
        item.definition.model_copy(deep=True)
        for item in pipeline_catalog().templates
        if item.definition.strategy == strategy
    )


def branched(strategy="adaptive_stream"):
    definition = template(strategy)
    family = "adaptive" if strategy == "adaptive_stream" else "static"
    projection = "uncentered_pca" if family == "adaptive" else "pca"
    data = definition.model_dump(mode="json")
    data["input_slots"] = [
        {"id": "voltage", "label": "Voltage"},
        {"id": "current", "label": "Current"},
        {"id": "temperature", "label": "Temperature"},
    ]
    data["nodes"].extend(
        [
            {
                "id": "scaled_inputs",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": ["voltage", "current"]},
            },
            {
                "id": "scaler",
                "kind": "transform",
                "component": f"{family}.standard_scaler",
            },
            {
                "id": "projection",
                "kind": "transform",
                "component": f"{family}.{projection}",
                "params": {"n_components": 1},
            },
            {
                "id": "raw",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": ["temperature"]},
            },
            {"id": "merge", "kind": "merge", "component": "features.merge"},
        ]
    )
    data["edges"] = [edge for edge in data["edges"] if edge["target"] != "detector"] + [
        {"source": "input", "target": "scaled_inputs"},
        {"source": "scaled_inputs", "target": "scaler"},
        {"source": "scaler", "target": "projection"},
        {"source": "input", "target": "raw"},
        {"source": "projection", "target": "merge", "order": 0},
        {"source": "raw", "target": "merge", "order": 1},
        {"source": "merge", "target": "detector"},
    ]
    return PipelineDefinition.model_validate(data)


def test_complete_catalog_and_templates_have_bounded_controls():
    catalog = pipeline_catalog(True)
    assert catalog.authoring_enabled
    assert len(catalog.components) >= 48
    assert len({item.id for item in catalog.components}) == len(catalog.components)
    assert {item.definition.strategy for item in catalog.templates} == {
        "static_baseline",
        "adaptive_stream",
    }
    for item in catalog.templates:
        assert compile_pipeline(item.definition).valid
    for component in catalog.components:
        assert {field.name for field in component.fields} == set(
            component.parameter_schema.get("properties", {})
        )
    gadget = next(
        item for item in catalog.components if item.id == "detector:aberrant_gadget_svm"
    )
    graph = next(field for field in gadget.fields if field.name == "graph")
    assert graph.type == "integer_adjacency" and graph.nullable
    martingale = next(
        item for item in catalog.components if item.id == "policy.martingale"
    )
    trackers = next(field for field in martingale.fields if field.name == "trackers")
    assert trackers.discriminator == "betting_function"
    assert trackers.variants and set(trackers.variants) == {
        "power",
        "simple_mixture",
        "simple_jumper",
    }


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_branch_projection_raw_bypass_and_lineage(strategy):
    result = compile_pipeline(branched(strategy))
    outputs = result.features["detector"]
    assert [item.name for item in outputs] == ["projection.component_1", "temperature"]
    assert [item.slots for item in outputs] == [["current", "voltage"], ["temperature"]]
    assert [item.raw for item in outputs] == [False, True]
    assert (
        result.order.index("projection")
        < result.order.index("merge")
        < result.order.index("detector")
    )
    assert result.feature_output_id == "merge"


def test_normalization_is_detached_and_fingerprint_ignores_presentation_order():
    original = branched()
    before = original.model_dump(mode="json")
    first = compile_pipeline(original)
    assert original.model_dump(mode="json") == before
    edited = original.model_copy(deep=True)
    edited.nodes.reverse()
    edited.edges.reverse()
    edited.input_slots[0].label = "Different display label"
    edited.nodes[0].label = "A cosmetic title"
    assert compile_pipeline(edited).fingerprint == first.fingerprint
    edited.edges = [
        edge.model_copy(update={"order": 1 - edge.order})
        if edge.target == "merge"
        else edge
        for edge in edited.edges
    ]
    assert compile_pipeline(edited).fingerprint != first.fingerprint


def test_future_component_contract_is_preserved_as_a_draft_but_cannot_execute():
    definition = template()
    definition.nodes[0].contract_version = 2
    result = validate_pipeline(definition)
    assert not result.valid and result.fingerprint is None
    assert result.definition.nodes[0].contract_version == 2
    assert "component_version" in {issue.code for issue in result.issues}


def test_bound_fingerprint_has_one_canonical_shape():
    definition = template()
    raw = {
        "slot_id": "value",
        "reading_id": "reading",
        "entity_id": "entity",
        "accepted_topic": "telemetry/entity/value",
        "input_key": "value",
    }
    model = BoundInput.model_validate(raw)
    assert execution_fingerprint(definition, [raw]) == execution_fingerprint(
        definition, [model]
    )
    assert execution_fingerprint(
        definition, [raw | {"unit": "V"}]
    ) != execution_fingerprint(definition, [model])


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda data: data["nodes"].append(data["nodes"][0]), "duplicate_node"),
        (
            lambda data: data["edges"].append(
                {"source": "missing", "target": "detector"}
            ),
            "connection",
        ),
        (
            lambda data: data["edges"].append(
                {"source": "detector", "target": "input"}
            ),
            "cycle",
        ),
        (
            lambda data: data["nodes"].append(
                {
                    "id": "unused",
                    "kind": "transform",
                    "component": "features.passthrough",
                }
            ),
            "disconnected",
        ),
        (
            lambda data: data["nodes"][0].update(
                component="arbitrary.module.Component"
            ),
            "component",
        ),
        (
            lambda data: data["nodes"][1].update(component="detector:pyod_iforest"),
            "strategy",
        ),
        (
            lambda data: data["edges"].append({"source": "input", "target": "policy"}),
            "port_type",
        ),
    ],
)
def test_invalid_drafts_return_issues_without_execution(mutation, code):
    data = template().model_dump(mode="json")
    mutation(data)
    result = validate_pipeline(PipelineDefinition.model_validate(data))
    assert not result.valid and result.fingerprint is None
    assert code in {issue.code for issue in result.issues}


def test_merge_collisions_projection_width_and_intermediate_budget():
    graph = branched()
    projection = next(node for node in graph.nodes if node.id == "projection")
    projection.params["n_components"] = 3
    assert "incoming feature count" in compile_error(graph)
    collision = branched()
    raw = next(node for node in collision.nodes if node.id == "raw")
    raw.component = "features.rename"
    raw.params = {"mapping": {"temperature": "projection.component_1"}}
    assert "collide" in compile_error(collision)


def compile_error(definition):
    with pytest.raises(ValueError) as caught:
        compile_pipeline(definition)
    return str(caught.value)


def test_transformed_unit_interval_model_requires_explicit_clipping():
    graph = template()
    detector = next(node for node in graph.nodes if node.kind == "detector")
    detector.component = "detector:aberrant_half_space_trees"
    detector.params = {}
    assert compile_pipeline(graph).valid  # Raw input remains runtime-checked.
    data = graph.model_dump(mode="json")
    data["nodes"].append(
        {"id": "scale", "kind": "transform", "component": "adaptive.min_max_scaler"}
    )
    data["edges"][0] = {"source": "input", "target": "scale"}
    data["edges"].append({"source": "scale", "target": "detector"})
    scaled = PipelineDefinition.model_validate(data)
    assert "explicitly clipped" in compile_error(scaled)
    next(node for node in scaled.nodes if node.id == "scale").params["clip"] = True
    assert compile_pipeline(scaled).valid


@pytest.mark.parametrize(
    ("params", "minimum"),
    [({"window_size": 1}, 2), ({"window_size": 2, "absoluteValues": True}, 3)],
)
def test_impossible_retained_readiness_is_rejected(params, minimum):
    graph = template()
    detector = next(node for node in graph.nodes if node.kind == "detector")
    detector.component = "detector:aberrant_moving_geometric_average"
    detector.params = params
    assert f"minimum of {minimum}" in compile_error(graph)


def test_partial_inference_preserves_valid_upstream_and_independent_branches():
    graph = branched()
    next(node for node in graph.nodes if node.id == "scaled_inputs").params = {
        "features": []
    }
    result = validate_pipeline(graph)
    assert not result.valid and result.fingerprint is None
    assert [feature.name for feature in result.features["input"]] == [
        "voltage",
        "current",
        "temperature",
    ]
    assert [feature.name for feature in result.features["raw"]] == ["temperature"]
    assert {"scaled_inputs", "scaler", "projection", "merge", "detector"}.isdisjoint(
        result.features
    )
    # An unrelated disconnected node must not erase a complete path's metadata.
    data = branched().model_dump(mode="json")
    data["nodes"].append(
        {
            "id": "unused",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": []},
        }
    )
    result = validate_pipeline(PipelineDefinition.model_validate(data))
    assert not result.valid
    assert [feature.name for feature in result.features["detector"]] == [
        "projection.component_1",
        "temperature",
    ]


def test_incomplete_selection_after_projection_exposes_its_canonical_inputs():
    graph = branched()
    raw = next(node for node in graph.nodes if node.id == "raw")
    raw.params = {"features": []}
    graph.edges = [edge for edge in graph.edges if edge.target != "raw"]
    graph.edges.append(type(graph.edges[0])(source="projection", target="raw"))
    result = validate_pipeline(graph)
    assert not result.valid
    assert [feature.name for feature in result.features["projection"]] == [
        "projection.component_1"
    ]
    assert "raw" not in result.features


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "additionalProperties": {"type": "string"}},
        {"type": "array", "items": {"type": "string"}},
        {"anyOf": [{"type": "integer"}, {"type": "string"}]},
        {"$ref": "https://example.invalid/schema"},
        {"$ref": "#/$defs/Missing"},
    ],
)
def test_unsupported_parameter_forms_fail_catalog_generation(schema):
    with pytest.raises(ValueError):
        component_fields({"properties": {"unsupported": schema}})


def test_control_plane_import_has_no_scientific_runtime():
    """Launch schemas and the pipeline catalogue load without numerical runtimes."""
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from off_key_core.schemas.radar import AdaptiveStreamConfig; "
            "from off_key_core.models.pipelines import pipeline_catalog; "
            "AdaptiveStreamConfig(); pipeline_catalog(); "
            "modules = {'aberrant','numpy','scipy','faiss','pyod'}; "
            "assert not modules & sys.modules.keys()",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
