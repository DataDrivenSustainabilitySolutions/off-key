"""A design as a file, and what its layout keeps: switched-off steps and notes."""

import pytest
from off_key_core.models.pipelines import compile_pipeline
from off_key_core.schemas.pipeline_versions import editor_form
from off_key_core.schemas.pipelines import (
    DESIGN_FILE_FORMAT,
    DESIGN_FILE_SCHEMA,
    MAX_PIPELINE_EXECUTION_BYTES,
    PipelineDefinition,
    PipelineDesignFile,
    PipelineLayout,
)
from pydantic import ValidationError

from tests.support.pipelines import template


def test_design_file_needs_its_marker_and_takes_the_address_of_its_schema():
    stored = template("adaptive_stream").model_dump(mode="json")
    definition = editor_form(stored)
    file = PipelineDesignFile.model_validate(
        {
            "$schema": DESIGN_FILE_SCHEMA,
            "format": DESIGN_FILE_FORMAT,
            "name": "Charger health",
            "definition": definition,
        }
    )
    assert (file.schema_version, file.description) == (1, "")
    assert file.layout == PipelineLayout()
    assert compile_pipeline(file.definition).valid
    # Written again, the address keeps the key editors look for.
    assert file.model_dump(mode="json", by_alias=True)["$schema"] == DESIGN_FILE_SCHEMA
    for broken in (
        {"definition": definition},
        {"format": "aberration-system", "definition": definition},
        {"format": DESIGN_FILE_FORMAT},
        {"format": DESIGN_FILE_FORMAT, "definition": definition, "schema_version": 2},
        {"format": DESIGN_FILE_FORMAT, "definition": definition, "bindings": {}},
        # A file holds the design as the composer shows it, which is schema 2.
        {"format": DESIGN_FILE_FORMAT, "definition": stored},
        {"format": DESIGN_FILE_FORMAT, "definition": {"nodes": [], "edges": []}},
    ):
        with pytest.raises(ValidationError):
            PipelineDesignFile.model_validate(broken)


def test_layout_keeps_what_a_switched_off_step_was():
    layout = PipelineLayout.model_validate(
        {
            "nodes": {"smooth": {"x": 288, "y": 96}},
            "switched_off": {
                "smooth": {"component": "prepare.smooth", "params": {"window_size": 5}}
            },
        }
    )
    was = layout.switched_off["smooth"]
    assert (was.component, was.contract_version, was.params) == (
        "prepare.smooth",
        1,
        {"window_size": 5},
    )
    assert PipelineLayout.model_validate(layout.model_dump(mode="json")) == layout
    assert PipelineLayout.model_validate({"nodes": {}}).switched_off == {}
    for broken in (
        {"smooth": {"params": {}}},
        {"smooth": {"component": "prepare.smooth", "kind": "transform"}},
        {
            "smooth": {
                "component": "prepare.smooth",
                "params": {"text": "x" * MAX_PIPELINE_EXECUTION_BYTES},
            }
        },
        {f"step_{index}": {"component": "prepare.smooth"} for index in range(65)},
    ):
        with pytest.raises(ValidationError):
            PipelineLayout.model_validate({"switched_off": broken})


def test_layout_keeps_the_notes_of_a_design():
    note = {
        "id": "note_1",
        "x": 288,
        "y": 0,
        "text": "Smooth first.\nThe sensor is noisy.",
    }
    layout = PipelineLayout.model_validate({"notes": [note]})
    assert layout.model_dump(mode="json")["notes"] == [note]
    assert PipelineLayout.model_validate(layout.model_dump(mode="json")) == layout
    assert PipelineLayout.model_validate({"nodes": {}}).notes == []
    with pytest.raises(ValidationError, match="Two notes have the id 'note_1'"):
        PipelineLayout.model_validate({"notes": [note, {**note, "x": 0}]})
    for broken in (
        [{**note, "text": ""}],
        [{**note, "text": "x" * 2001}],
        [{**note, "id": ""}],
        [{"id": "note_1", "text": "No place"}],
        [{**note, "color": "yellow"}],
        [{**note, "id": f"note_{index}"} for index in range(51)],
    ):
        with pytest.raises(ValidationError):
            PipelineLayout.model_validate({"notes": broken})


def test_a_switched_off_step_runs_as_the_pass_through_step_it_is():
    """The definition holds the step that stands in, so what runs is what it reads."""
    design = template("adaptive_stream").model_dump(mode="json")
    detector = next(node for node in design["nodes"] if node["kind"] == "detector")
    design["nodes"].append(
        {"id": "smooth", "kind": "transform", "component": "features.passthrough"}
    )
    for edge in design["edges"]:
        if edge["target"] == detector["id"]:
            edge["target"] = "smooth"
    design["edges"].append({"source": "smooth", "target": detector["id"]})
    compiled = compile_pipeline(PipelineDefinition.model_validate(design))
    assert compiled.valid
    before = next(
        edge["source"] for edge in design["edges"] if edge["target"] == "smooth"
    )
    names = [feature.name for feature in compiled.features["smooth"]]
    assert names == [feature.name for feature in compiled.features[before]]
