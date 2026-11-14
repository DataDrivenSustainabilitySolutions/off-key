"""Alarms by catalogue device and reading, as Reporting shows them."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from off_key_core.auth.agents import OPEN_TO_AGENTS
from off_key_core.config.logs import logger
from off_key_core.schemas.alarms import (
    MAX_ALARM_READINGS,
    Alarm,
    AlarmCount,
    AlarmCreate,
    AlarmDeletionCommit,
    AlarmDeletionPreview,
    AlarmDetail,
    AlarmPage,
    AlarmQuery,
    AlarmSelection,
)
from off_key_core.utils.mail import send_alarm_email
from off_key_tactic_middleware.services.catalogue.system import SystemService
from off_key_tactic_middleware.services.data import AlarmService
from off_key_tactic_middleware.services.data.alarm_actions import AlarmActions

from ...providers import get_alarm_actions, get_alarm_service, get_system_service
from ..errors import DomainErrorRoute
from .devices import utc

router = APIRouter(route_class=DomainErrorRoute)
# Reading alarms is open to every member, even though the query is a POST.
query_router = APIRouter(route_class=DomainErrorRoute)


@query_router.post("/query", response_model=AlarmPage, openapi_extra=OPEN_TO_AGENTS)
async def query_alarms(
    query: AlarmQuery,
    service: AlarmService = Depends(get_alarm_service),
    system: SystemService = Depends(get_system_service),
):
    """Alarms of catalogue readings, newest first, with catalogue names.

    Scope by `reading_ids` (reading ids from `GET /v1/catalogue`) and narrow by
    one `reading_id`, `monitor_id`, `since`/`until` and `max_p_value`.
    `summary` and `readings` describe every match, not just this page; pass
    `next` as `before` for older alarms. Reporting in the web app uses this
    query.
    """
    return await service.query(query, await system.read())


@router.get("/count", response_model=AlarmCount, openapi_extra=OPEN_TO_AGENTS)
async def count_alarms(
    since: datetime | None = None,
    service: AlarmService = Depends(get_alarm_service),
):
    """Number of alarms, all of them or those since a time."""
    return AlarmCount(count=await service.count_alarms(since=utc(since)))


@router.get("", response_model=list[Alarm], openapi_extra=OPEN_TO_AGENTS)
async def list_alarms(
    device_id: str | None = Query(
        default=None, description="Alarms of every reading of this device."
    ),
    reading_id: list[str] | None = Query(
        default=None,
        description="Alarms about any of these readings; repeat the field.",
    ),
    monitor_id: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(default=500, ge=1, le=1000),
    service: AlarmService = Depends(get_alarm_service),
    system: SystemService = Depends(get_system_service),
):
    """The newest alarms, of one device, of readings, or of every reading.

    Name `device_id` or one or more `reading_id`, not both, or neither for
    every alarm. A multivariate alarm that did not record its readings belongs
    to every reading of its device. 404 when the catalogue lacks the device.
    """
    if device_id is not None and reading_id:
        raise HTTPException(
            status_code=422, detail="Name either device_id or reading_id"
        )
    if reading_id and len(reading_id) > MAX_ALARM_READINGS:
        raise HTTPException(
            status_code=422, detail=f"Name at most {MAX_ALARM_READINGS} readings"
        )
    return await service.list_alarms(
        await system.read(),
        device_id=device_id,
        stream_ids=reading_id,
        service_id=monitor_id,
        limit=limit,
    )


@router.post("", response_model=Alarm, status_code=201)
async def create_alarm(
    alarm: AlarmCreate,
    service: AlarmService = Depends(get_alarm_service),
    system: SystemService = Depends(get_system_service),
):
    """Record an alarm by hand and email the configured alert recipients.

    Monitors record their own alarms; this is for external detectors. Name
    the readings it is about, all of one device. 404 for an unknown reading.
    Needs `manage_alarms`.
    """
    created = Alarm.model_validate(
        await service.create_alarm(alarm, await system.read())
    )
    logger.warning(
        "event=gateway.alarm_created alarm_id=%s device_id=%s alarm_type=%s",
        created.alarm_id,
        created.device_id,
        created.alarm_type,
    )
    try:
        await send_alarm_email(created)
    except Exception as e:
        # The alarm is recorded either way.
        logger.error(
            "event=gateway.alarm_email_failed alarm_id=%s error=%s",
            created.alarm_id,
            e,
        )
    return created


@router.delete("/{alarm_id}", status_code=204, response_class=Response)
async def delete_alarm(
    alarm_id: str, service: AlarmService = Depends(get_alarm_service)
):
    """Remove one alarm by its `alarm_id`. 404 when there is none. Needs
    `manage_alarms`."""
    await service.delete_alarm(alarm_id=alarm_id)
    logger.info("event=gateway.alarm_deleted alarm_id=%s", alarm_id)
    return Response(status_code=204)


@router.get("/{alarm_id}", response_model=AlarmDetail)
async def alarm_detail(
    alarm_id: str,
    actions: AlarmActions = Depends(get_alarm_actions),
    system: SystemService = Depends(get_system_service),
):
    """One anomaly and its exact recorded detector evidence, when retained."""
    return await actions.detail(alarm_id, await system.read())


@router.post("/deletion-preview", response_model=AlarmDeletionPreview)
async def preview_deletion(
    selection: AlarmSelection,
    actions: AlarmActions = Depends(get_alarm_actions),
    system: SystemService = Depends(get_system_service),
):
    """Freeze selected IDs or all filter matches. Requires manage_alarms."""
    return await actions.preview(selection, await system.read())


@router.post("/delete", response_model=AlarmCount)
async def delete_selection(
    selection: AlarmDeletionCommit,
    actions: AlarmActions = Depends(get_alarm_actions),
):
    """Atomically delete a frozen selection, with an idempotent retry token."""
    return AlarmCount(count=await actions.delete(selection.token))
