from fastapi import APIRouter, HTTPException, Query, Request, Response
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, field_validator
from off_key_core.utils.mqtt_topics import normalize_mqtt_topic_filters

from off_key_core.schemas.radar import (
    AdaptiveStreamConfig,
    MonitoringStrategy,
    PerformanceConfig,
    StaticBaselineConfig,
)
from ...facades.tactic import tactic, TacticError
from ..rate_limiter import limiter

router = APIRouter()

shared_limit_fetch = limiter.shared_limit("60/minute", scope="services")
shared_limit_execute = limiter.shared_limit("20/minute", scope="services")


def _get_tactic_error_detail(error: TacticError) -> str:
    """Extract API detail from TACTIC error body when available."""
    if isinstance(error.body, dict):
        detail = error.body.get("detail")
        if detail:
            return str(detail)
    return str(error)


def _normalize_models_for_gateway(
    models_from_tactic: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Normalize TACTIC model list into gateway's existing dictionary response shape.

    Data source stays TACTIC; only the transport shape is adapted for consumers.
    """
    normalized: Dict[str, Dict[str, Any]] = {}
    for model in models_from_tactic:
        model_type = model.get("model_type")
        if not model_type:
            continue

        normalized[model_type] = {
            "name": model.get("name"),
            "description": model.get("description", ""),
            "family": model["family"],
            "strategy": model.get("strategy", "adaptive_stream"),
            "complexity": model.get("complexity", "unknown"),
            "memory_usage": model.get("memory_usage", "unknown"),
            "parameters": model.get("parameter_schema", model.get("parameters", {})),
            "default_parameters": model.get("default_parameters", {}),
            "version": model.get("version"),
            "requires_special_handling": model.get("requires_special_handling", False),
        }

    return normalized


def _normalize_preprocessors_for_gateway(
    preprocessors_from_tactic: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Normalize TACTIC preprocessor list into gateway's existing
    dictionary response shape.

    Data source stays TACTIC; only the transport shape is adapted for consumers.
    """
    normalized: Dict[str, Dict[str, Any]] = {}
    for preprocessor in preprocessors_from_tactic:
        model_type = preprocessor.get("model_type")
        if not model_type:
            continue

        normalized[model_type] = {
            "name": preprocessor.get("name"),
            "description": preprocessor.get("description", ""),
            "family": preprocessor["family"],
            "parameters": preprocessor.get(
                "parameter_schema",
                preprocessor.get("parameters", {}),
            ),
            "default_parameters": preprocessor.get("default_parameters", {}),
            "version": preprocessor.get("version"),
            "requires_special_handling": preprocessor.get(
                "requires_special_handling", False
            ),
        }

    return normalized


class MonitoringServiceConfig(BaseModel):
    container_name: str = Field(
        ..., description="Name for the monitoring service container"
    )
    service_type: str = Field(
        default="radar", description="Type of monitoring service (radar, custom, etc.)"
    )
    mqtt_topics: List[str] = Field(..., description="List of MQTT topics to monitor")
    strategy: MonitoringStrategy = Field(
        default="adaptive_stream",
        description="Monitoring strategy: static_baseline or adaptive_stream",
    )
    model_type: str = Field(
        default="knn",
        description="Legacy/effective ML model type for the selected strategy",
    )
    model_params: Optional[Dict[str, Any]] = Field(
        default=None, description="Model-specific parameters"
    )
    preprocessing_steps: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Ordered preprocessing steps applied before the model"
    )
    performance_config: Optional["PerformanceConfig"] = Field(
        default=None,
        description=(
            "Performance and heuristic settings "
            "(reference window/min-samples/tail-alpha, sensor strategy)"
        ),
    )
    static_baseline_config: Optional["StaticBaselineConfig"] = Field(
        default=None,
        description="Static baseline conformal detector settings",
    )
    adaptive_stream_config: Optional["AdaptiveStreamConfig"] = Field(
        default=None,
        description="Adaptive/non-static stream detector settings",
    )
    requirements: Optional[List[str]] = Field(
        None, description="List of pip packages to install"
    )
    environment_variables: Optional[Dict[str, str]] = Field(
        None, description="Additional environment variables"
    )

    @field_validator("mqtt_topics")
    @classmethod
    def validate_mqtt_topics(cls, value: List[str]) -> List[str]:
        return normalize_mqtt_topic_filters(
            value,
            require_charger_prefix=True,
            require_telemetry_topic=True,
        )


class ServiceResponse(BaseModel):
    service_id: str
    container_id: str
    container_name: str
    status: str
    mqtt_topics: List[str]


MonitoringServiceConfig.model_rebuild()


def _resolve_effective_start_config(
    config: MonitoringServiceConfig,
) -> Dict[str, Any]:
    """Resolve new strategy-specific config while preserving legacy payloads."""
    performance_config = config.performance_config
    model_type = config.model_type
    model_params = config.model_params or {}
    preprocessing_steps = config.preprocessing_steps or []
    resolved_static_baseline_config = None
    resolved_adaptive_stream_config = None

    if config.strategy == "static_baseline":
        static_config = config.static_baseline_config or StaticBaselineConfig(
            model_type=model_type,
            model_params=model_params,
        )
        model_type = static_config.model_type
        model_params = static_config.model_params
        preprocessing_steps = []
        resolved_static_baseline_config = static_config
    elif config.adaptive_stream_config:
        adaptive_config = config.adaptive_stream_config
        effective_performance_config = (
            performance_config or adaptive_config.performance_config
        )
        model_type = adaptive_config.model_type
        model_params = adaptive_config.model_params
        preprocessing_steps = adaptive_config.preprocessing_steps
        performance_config = effective_performance_config
        resolved_adaptive_stream_config = adaptive_config.model_copy(
            update={"performance_config": effective_performance_config}
        )

    return {
        "strategy": config.strategy,
        "model_type": model_type,
        "model_params": model_params,
        "preprocessing_steps": preprocessing_steps,
        "performance_config": (
            performance_config.model_dump(exclude_none=True)
            if performance_config
            else None
        ),
        "static_baseline_config": (
            resolved_static_baseline_config.model_dump(exclude_none=True)
            if resolved_static_baseline_config
            else None
        ),
        "adaptive_stream_config": (
            resolved_adaptive_stream_config.model_dump(exclude_none=True)
            if resolved_adaptive_stream_config
            else None
        ),
    }


@router.get("/all", response_model=List[Dict[str, Any]])
@shared_limit_fetch
async def list_services(
    request: Request,
    active_only: bool = False,
    include_docker_status: bool = False,
):
    """
    Lists all monitoring services.

    Parameters:
    - active_only: If true, only return active services
    - include_docker_status: If true, check actual Docker container status
      for each service. This is slower but provides accurate real-time status.
      When enabled, each service will include a 'docker_status' field with
      values like: 'running', 'complete', 'failed', 'not_found', 'error'.
    """
    try:
        return await tactic.list_radar_services(
            active_only=active_only,
            include_docker_status=include_docker_status,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list monitoring services: {str(e)}"
        )


@router.post("/start", response_model=ServiceResponse)
@shared_limit_execute
async def start_monitoring_service(
    request: Request,
    config: MonitoringServiceConfig,
):
    """
    Starts a new monitoring service container via TACTIC orchestration.
    """
    try:
        if config.service_type == "radar":
            effective_config = _resolve_effective_start_config(config)
            response = await tactic.start_radar_service(
                container_name=config.container_name,
                mqtt_topics=config.mqtt_topics,
                strategy=effective_config["strategy"],
                model_type=effective_config["model_type"],
                model_params=effective_config["model_params"],
                preprocessing_steps=effective_config["preprocessing_steps"],
                mqtt_config=None,
                anomaly_thresholds=None,
                performance_config=effective_config["performance_config"],
                static_baseline_config=effective_config["static_baseline_config"],
                adaptive_stream_config=effective_config["adaptive_stream_config"],
            )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported service type: {config.service_type}",
            )

        return response
    except TacticError as e:
        raise HTTPException(
            status_code=e.status or 502,
            detail=_get_tactic_error_detail(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to start monitoring service: {str(e)}"
        )


@router.get("", response_model=Dict[str, Any])
@shared_limit_fetch
async def get_service_details(
    request: Request,
    container_name: Optional[str] = Query(default=None),
    container_id: Optional[str] = Query(default=None),
):
    """
    Gets details for a specific monitoring service by container name or ID.
    """
    if not container_name and not container_id:
        raise HTTPException(
            status_code=400,
            detail="You must provide either container_name or container_id.",
        )

    if container_name and container_id:
        raise HTTPException(
            status_code=400,
            detail="Provide only one of container_name or container_id.",
        )

    try:
        service_detail = await tactic.get_radar_service_details(
            container_name=container_name,
            container_id=container_id,
        )

        if not service_detail:
            raise HTTPException(status_code=404, detail="Service not found")

        return service_detail
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get service details: {str(e)}"
        )


@router.delete("/stop")
@shared_limit_execute
async def stop_monitoring_service(
    request: Request,
    container_name: Optional[str] = Query(default=None),
    container_id: Optional[str] = Query(default=None),
):
    """
    Stops and removes a running monitoring service container via TACTIC.
    """
    if not container_name and not container_id:
        raise HTTPException(
            status_code=400,
            detail="You must provide either container_name or container_id.",
        )

    if container_name and container_id:
        raise HTTPException(
            status_code=400,
            detail="Provide only one of container_name or container_id.",
        )

    try:
        response = await tactic.stop_radar_service(
            container_name=container_name,
            container_id=container_id,
        )

        success = response.get("status") == "stopped"

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Container '{container_name or container_id}'"
                f" not found or could not be stopped",
            )

        return {
            "status": "stopped",
            "message": f"Container '{container_name or container_id}'"
            f" stopped successfully",
        }
    except TacticError as e:
        raise HTTPException(
            status_code=e.status or 502,
            detail=_get_tactic_error_detail(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to stop monitoring service: {str(e)}"
        )


@router.get("/models", response_model=Dict[str, Any])
@shared_limit_fetch
async def list_available_models_endpoint(
    request: Request,
    response: Response,
    strategy: Optional[MonitoringStrategy] = Query(default=None),
):
    """
    Lists all available anomaly detection models and their hyperparameters.

    Returns information about each model including:
    - description: What the model does
    - family: Model family (forest, distance, svm, etc.)
    - complexity: Computational complexity
    - memory_usage: Expected memory footprint
    - parameters: JSON schema for hyperparameters with defaults and constraints

    Use this endpoint to discover available models and their configuration options
    before starting a monitoring service.

    Response is cacheable for 5 minutes since model definitions rarely change.
    """
    # Enable client-side caching - models rarely change
    response.headers["Cache-Control"] = "public, max-age=300"
    try:
        models = await tactic.list_available_models()
        normalized = _normalize_models_for_gateway(models)
        if strategy:
            return {
                key: model
                for key, model in normalized.items()
                if model.get("strategy") == strategy
            }
        return normalized
    except TacticError as e:
        raise HTTPException(
            status_code=e.status or 502,
            detail=_get_tactic_error_detail(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get available models: {str(e)}"
        )


@router.get("/preprocessors", response_model=Dict[str, Any])
@shared_limit_fetch
async def list_available_preprocessors_endpoint(request: Request, response: Response):
    """List available preprocessing steps and their parameters.

    Examples: standard scaler, PCA.

    Response is cacheable for 5 minutes since preprocessor definitions rarely change.
    """
    # Enable client-side caching - preprocessors rarely change
    response.headers["Cache-Control"] = "public, max-age=300"
    try:
        preprocessors = await tactic.list_available_preprocessors()
        return _normalize_preprocessors_for_gateway(preprocessors)
    except TacticError as e:
        raise HTTPException(
            status_code=e.status or 502,
            detail=_get_tactic_error_detail(e),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get available preprocessors: {str(e)}",
        )
