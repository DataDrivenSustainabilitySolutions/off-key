"""Bound pipelines equivalent to monitors configured with the setup forms."""

from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    form_inputs,
    lower_form_monitor,
)
from off_key_core.schemas.pipelines import BoundInput, PipelineExecutionConfig
from off_key_core.schemas.radar import FormMonitorConfig, RadarStartConfig


def form_pipeline(
    monitoring=None,
    topics=("telemetry/entity/a",),
    *,
    performance_config=None,
    revision_id="revision",
    run_id="run",
) -> PipelineExecutionConfig:
    """The bound execution TACTIC would start for this form configuration."""
    form = {"container_name": "form-monitor", "mqtt_topics": list(topics)}
    if monitoring is not None:
        form["monitoring"] = (
            monitoring.model_dump(mode="json")
            if hasattr(monitoring, "model_dump")
            else monitoring
        )
    if performance_config is not None:
        form["performance_config"] = (
            performance_config.model_dump(mode="json")
            if hasattr(performance_config, "model_dump")
            else performance_config
        )
    parsed = FormMonitorConfig.model_validate(form)
    definition = compile_pipeline(lower_form_monitor(parsed)).definition
    bindings = [
        BoundInput(
            slot_id=f"input_{index + 1}",
            reading_id=f"reading-{index + 1}",
            entity_id=topic.split("/")[1] if "/" in topic else "entity",
            accepted_topic=topic,
            input_key=key,
        )
        for index, (key, topic) in enumerate(form_inputs(parsed))
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        fingerprint=execution_fingerprint(definition, bindings),
        revision_id=revision_id,
        run_id=run_id,
    )


def form_radar_config(
    monitoring=None, topics=("telemetry/entity/a",), config_class=None, **fields
):
    """A RADAR configuration running the form-equivalent pipeline."""
    if config_class is None:
        from off_key_mqtt_radar.config.config import AnomalyDetectionConfig

        config_class = AnomalyDetectionConfig
    performance = {
        name: fields[name] for name in ("sensor_key_strategy",) if name in fields
    }
    return config_class(
        pipeline=form_pipeline(
            monitoring, topics, performance_config=performance or None
        ),
        **fields,
    )


def form_launch(*, runtime_image=None, **fields) -> RadarStartConfig:
    """The pipeline launch that replaces a setup-form launch with these fields."""
    form = FormMonitorConfig.model_validate(fields)
    return RadarStartConfig(
        **form.model_dump(exclude={"launch_version", "monitoring"}),
        runtime_image=runtime_image,
        pipeline=form_pipeline(
            form.monitoring,
            form.mqtt_topics,
            performance_config=form.performance_config,
        ),
    )


def stored_revision(launch: RadarStartConfig) -> list:
    """Design rows that own the revision a test launch runs."""
    from off_key_core.db.pipelines import MonitoringPipeline, PipelineRevision

    definition = launch.pipeline.definition.model_dump(mode="json")
    return [
        MonitoringPipeline(
            id="form-design", name="Form monitor", draft=definition, is_template=False
        ),
        PipelineRevision(
            id=launch.pipeline.revision_id,
            pipeline_id="form-design",
            number=1,
            definition=definition,
            fingerprint=launch.pipeline.fingerprint,
            catalog_id="fixture",
        ),
    ]


def set_pipeline_environment(monkeypatch, monitoring=None, topics=None):
    """Give RadarSettings the pipeline TACTIC would launch."""
    pipeline = form_pipeline(monitoring, topics or ["telemetry/charger-sim-1/sine"])
    monkeypatch.setenv("RADAR_PIPELINE_CONFIG", pipeline.model_dump_json())
