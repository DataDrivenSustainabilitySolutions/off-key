"""Holding the last value of an input sent only when it changes."""

from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    validate_pipeline,
)
from off_key_core.models.pipeline_edits import edit_design
from off_key_core.schemas.pipeline_tools import DesignEditRequest
from off_key_core.schemas.pipelines import PipelineExecutionConfig

from tests.support.pipelines import quick, template


def edited(edits, definition, layout=None):
    return edit_design(
        DesignEditRequest.model_validate(
            {
                "edits": edits,
                "definition": definition,
                **({} if layout is None else {"layout": layout}),
            }
        )
    )


def _hold(definition, hold):
    source = next(n for n in definition.nodes if n.component == "source.aligned")
    source.params = {"hold": hold}
    return definition


def test_a_design_holds_an_input_it_takes_in():
    definition = quick()
    slot = definition.input_slots[0].id
    result = compile_pipeline(_hold(definition, [{"input": slot, "seconds": 3600}]))
    assert result.valid
    source = next(n for n in result.definition.nodes if n.kind == "source")
    assert source.params == {"hold": [{"input": slot, "seconds": 3600.0}]}


def test_holding_an_input_the_design_lacks_is_an_error():
    result = validate_pipeline(_hold(quick(), [{"input": "gone", "seconds": 60}]))
    assert not result.valid
    assert any(
        issue.code == "parameters" and "gone" in issue.message
        for issue in result.issues
    )


def test_an_empty_hold_keeps_the_fingerprint():
    plain = compile_pipeline(quick())
    held = compile_pipeline(_hold(quick(), []))
    assert held.fingerprint == plain.fingerprint
    source = next(n for n in held.definition.nodes if n.kind == "source")
    assert source.params == {}


def test_a_run_holds_by_the_bound_reading_key():
    definition = compile_pipeline(
        _hold(quick(), [{"input": "temperature", "seconds": 900}])
    ).definition
    bindings = [
        dict(
            slot_id=slot.id,
            reading_id=f"r-{slot.id}",
            entity_id="entity",
            accepted_topic=f"telemetry/entity/{slot.id}",
            input_key=f"key-{slot.id}",
        )
        for slot in definition.input_slots
    ]
    execution = PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        fingerprint=execution_fingerprint(definition, bindings),
        revision_id="revision",
        run_id="run",
    )
    assert execution.held_seconds == {"key-temperature": 900.0}


def test_removing_an_input_stops_holding_it():
    data = template().model_dump(mode="json")
    slot = data["input_slots"][0]["id"]
    held = edited(
        [
            {
                "op": "set_params",
                "id": "input",
                "params": {"hold": [{"input": slot, "seconds": 60}]},
            }
        ],
        data,
    )
    assert held.report.valid
    removed = edited(
        [{"op": "remove_input", "id": slot}],
        held.definition.model_dump(mode="json"),
        held.layout.model_dump(mode="json"),
    )
    source = next(n for n in removed.definition.nodes if n.id == "input")
    assert source.params.get("hold", []) == []
