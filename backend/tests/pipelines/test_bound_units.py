import pytest
from off_key_core.models.pipelines import execution_fingerprint, pipeline_catalog
from off_key_core.schemas.pipelines import BoundInput, PipelineExecutionConfig


def execution(declared: str | None, bound: str | None) -> PipelineExecutionConfig:
    template = pipeline_catalog().templates[0].definition
    definition = template.model_copy(
        update={
            "input_slots": [
                slot.model_copy(update={"unit": declared})
                for slot in template.input_slots
            ]
        }
    )
    bindings = [
        BoundInput(
            slot_id=slot.id,
            reading_id=f"reading-{slot.id}",
            entity_id="device",
            accepted_topic=f"telemetry/device/{slot.id}",
            input_key=f"device_{slot.id}",
            unit=bound,
        )
        for slot in definition.input_slots
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        revision_id="revision",
        run_id="run",
        fingerprint=execution_fingerprint(definition, bindings),
    )


@pytest.mark.parametrize(
    ("declared", "bound"), [(None, None), (None, "V"), ("V", "V"), ("V", None)]
)
def test_a_reading_of_unknown_unit_fits_a_declared_unit(declared, bound):
    assert execution(declared, bound).bindings[0].unit == bound


def test_two_known_units_that_differ_are_refused():
    with pytest.raises(ValueError, match="units must match"):
        execution("V", "A")
