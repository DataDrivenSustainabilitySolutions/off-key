"""Small executable pipelines for tests that need a real bound execution."""

from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import PipelineDefinition, PipelineExecutionConfig
from off_key_core.utils.mqtt_topics import derive_monitoring_sensor_keys


def minimal_static_execution(topic="telemetry/entity/a"):
    """Bind one reading to source, Isolation Forest, martingale and evidence."""
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            dict(
                strategy="static_baseline",
                input_slots=[dict(id="a", label="Power")],
                nodes=[
                    dict(id="input", kind="source", component="source.aligned"),
                    dict(
                        id="model",
                        kind="detector",
                        component="detector:pyod_iforest",
                        params={"n_estimators": 10},
                    ),
                    dict(id="policy", kind="policy", component="policy.martingale"),
                    dict(id="output", kind="output", component="output.evidence"),
                ],
                edges=[
                    dict(source="input", target="model"),
                    dict(source="model", target="policy"),
                    dict(source="policy", target="output"),
                ],
                settings=dict(training_window_size=20, calibration_window_size=5),
            )
        )
    ).definition
    bindings = [
        dict(
            slot_id="a",
            reading_id="r-a",
            entity_id="entity",
            accepted_topic=topic,
            input_key=derive_monitoring_sensor_keys(
                [topic], sensor_key_strategy="full_hierarchy"
            )[0],
        )
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        fingerprint=execution_fingerprint(definition, bindings),
        revision_id="revision",
        run_id="run",
    )
