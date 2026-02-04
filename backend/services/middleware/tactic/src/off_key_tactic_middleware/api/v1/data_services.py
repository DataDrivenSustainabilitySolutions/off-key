"""
Data services router for TACTIC middleware.

This module provides HTTP endpoints that act as a service layer between
the API Gateway and the database, implementing proper separation of concerns.
"""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from off_key_core.db.base import get_db_async
from off_key_core.db.models import Charger, Telemetry, User, Favorite, Anomaly
from off_key_core.config.logs import logger
from ...schemas import (
    ChargerResponse,
    TelemetryResponse,
    TelemetryTypeResponse,
    UserResponse,
    FavoriteResponse,
    AnomalyResponse,
    UserCreateRequest,
    UserLoginRequest,
    FavoriteCreateRequest,
    AnomalyCreateRequest,
)

router = APIRouter()

# =============================================================================
# Charger Services
# =============================================================================

@router.get("/chargers", response_model=List[ChargerResponse])
async def get_chargers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db_async),
):
    """Get chargers with optional filtering."""
    query = select(Charger)

    if active_only:
        query = query.filter(Charger.online == True)

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    chargers = result.scalars().all()

    logger.info(f"Retrieved {len(chargers)} chargers (active_only={active_only})")
    return chargers


@router.get("/chargers/active/ids", response_model=dict)
async def get_active_charger_ids(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db_async),
):
    """Get IDs of active chargers only."""
    query = (
        select(Charger.charger_id)
        .filter(Charger.online == True)
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    active_ids = result.scalars().all()

    return {"active": list(active_ids)}


# =============================================================================
# Telemetry Services
# =============================================================================

@router.get("/telemetry/{charger_id}/types", response_model=List[str])
async def get_telemetry_types(
    charger_id: str,
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db_async),
):
    """Get available telemetry types for a charger."""
    query = (
        select(Telemetry.type)
        .where(Telemetry.charger_id == charger_id)
        .distinct()
        .order_by(Telemetry.type.asc())
        .limit(limit)
    )
    result = await db.execute(query)
    types = result.scalars().all()

    logger.info(f"Retrieved {len(types)} telemetry types for charger {charger_id}")
    return types


@router.get("/telemetry/{charger_id}/{telemetry_type}")
async def get_telemetry_data(
    charger_id: str,
    telemetry_type: str,
    limit: int = Query(1000, ge=1, le=10000),
    after_timestamp: Optional[datetime] = Query(None),
    paginated: bool = Query(False),
    db: AsyncSession = Depends(get_db_async),
):
    """Get telemetry data with cursor-based pagination."""
    query = select(Telemetry).filter(
        Telemetry.charger_id == charger_id,
        Telemetry.type == telemetry_type
    )

    # Cursor-based pagination for time-series data
    if after_timestamp is not None:
        query = query.filter(Telemetry.timestamp < after_timestamp)

    # Always order by timestamp DESC for time-series data
    query = query.order_by(Telemetry.timestamp.desc()).limit(limit)

    result = await db.execute(query)
    telemetry_records = result.scalars().all()

    logger.info(
        f"Retrieved {len(telemetry_records)} telemetry records for "
        f"{charger_id}/{telemetry_type}"
    )

    # Format results to match frontend expectations
    formatted_results = [
        {"timestamp": str(record.timestamp), "value": record.value}
        for record in telemetry_records
    ]

    # Return paginated response only if explicitly requested
    if paginated:
        return {
            "data": formatted_results,
            "pagination": {
                "limit": limit,
                "has_more": len(formatted_results) == limit,
                "next_cursor": (
                    formatted_results[-1]["timestamp"] if formatted_results else None
                ),
            },
        }

    # Default: return simple array for backward compatibility
    return formatted_results


# =============================================================================
# User Services
# =============================================================================

@router.get("/users/{email}", response_model=Optional[UserResponse])
async def get_user_by_email(
    email: str,
    db: AsyncSession = Depends(get_db_async),
):
    """Get user by email address."""
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()

    if not user:
        return None

    return user


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreateRequest,
    db: AsyncSession = Depends(get_db_async),
):
    """Create a new user."""
    # Check if user already exists
    existing = await db.execute(select(User).filter(User.email == user_data.email))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    # Create new user
    new_user = User(
        email=user_data.email,
        hashed_password=user_data.hashed_password,
        verification_token=user_data.verification_token,
        role=user_data.role,
    )

    db.add(new_user)
    await db.flush()
    await db.commit()
    await db.refresh(new_user)

    logger.info(f"Created new user: {user_data.email}")
    return new_user


@router.patch("/users/{email}/verify")
async def verify_user_email(
    email: str,
    db: AsyncSession = Depends(get_db_async),
):
    """Mark user as email verified."""
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_verified = True
    user.verification_token = None
    await db.commit()

    logger.info(f"Verified email for user: {email}")
    return {"message": "Email verified successfully"}


@router.patch("/users/{email}/password")
async def update_user_password(
    email: str,
    new_password_hash: str,
    db: AsyncSession = Depends(get_db_async),
):
    """Update user password."""
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = new_password_hash
    await db.commit()

    logger.info(f"Updated password for user: {email}")
    return {"message": "Password updated successfully"}


# =============================================================================
# Favorites Services
# =============================================================================

@router.get("/users/{user_id}/favorites", response_model=List[str])
async def get_user_favorites(
    user_id: int,
    db: AsyncSession = Depends(get_db_async),
):
    """Get user's favorite charger IDs."""
    result = await db.execute(select(Favorite).filter(Favorite.user_id == user_id))
    favorites = result.scalars().all()

    charger_ids = [f.charger_id for f in favorites]
    logger.info(f"Retrieved {len(charger_ids)} favorites for user {user_id}")
    return charger_ids


@router.post("/users/{user_id}/favorites")
async def add_user_favorite(
    user_id: int,
    charger_id: str,
    db: AsyncSession = Depends(get_db_async),
):
    """Add charger to user's favorites."""
    # Check if already exists
    existing = await db.execute(
        select(Favorite).filter(
            Favorite.user_id == user_id,
            Favorite.charger_id == charger_id
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Charger already favorited")

    # Add new favorite
    new_favorite = Favorite(user_id=user_id, charger_id=charger_id)
    db.add(new_favorite)
    await db.commit()

    logger.info(f"Added favorite {charger_id} for user {user_id}")
    return {"message": "Favorite added"}


@router.delete("/users/{user_id}/favorites/{charger_id}")
async def remove_user_favorite(
    user_id: int,
    charger_id: str,
    db: AsyncSession = Depends(get_db_async),
):
    """Remove charger from user's favorites."""
    result = await db.execute(
        select(Favorite).filter(
            Favorite.user_id == user_id,
            Favorite.charger_id == charger_id
        )
    )
    favorite = result.scalars().first()

    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")

    await db.delete(favorite)
    await db.commit()

    logger.info(f"Removed favorite {charger_id} for user {user_id}")
    return {"message": "Favorite removed"}


# =============================================================================
# Anomaly Services
# =============================================================================

@router.get("/anomalies/{charger_id}", response_model=List[AnomalyResponse])
async def get_charger_anomalies(
    charger_id: str,
    limit: int = Query(500, ge=1, le=1000),
    db: AsyncSession = Depends(get_db_async),
):
    """Get anomalies for a specific charger."""
    result = await db.execute(
        select(Anomaly)
        .filter(Anomaly.charger_id == charger_id)
        .order_by(Anomaly.timestamp.desc())
        .limit(limit)
    )
    anomalies = result.scalars().all()

    logger.info(f"Retrieved {len(anomalies)} anomalies for charger {charger_id}")
    return [
        {
            "charger_id": a.charger_id,
            "timestamp": a.timestamp,
            "telemetry_type": a.telemetry_type,
            "anomaly_type": a.anomaly_type,
            "anomaly_value": a.anomaly_value,
        }
        for a in anomalies
    ]


@router.post("/anomalies")
async def create_anomaly(
    anomaly_data: AnomalyCreateRequest,
    db: AsyncSession = Depends(get_db_async),
):
    """Create a new anomaly record."""
    new_anomaly = Anomaly(
        charger_id=anomaly_data.charger_id,
        timestamp=anomaly_data.timestamp,
        telemetry_type=anomaly_data.telemetry_type,
        anomaly_type=anomaly_data.anomaly_type,
        anomaly_value=anomaly_data.anomaly_value,
    )

    db.add(new_anomaly)
    await db.commit()
    await db.refresh(new_anomaly)

    logger.warning(
        f"Anomaly created | Charger: {anomaly_data.charger_id} | "
        f"Type: {anomaly_data.anomaly_type} | Value: {anomaly_data.anomaly_value}"
    )

    return {"message": "Anomaly created", "anomaly_id": new_anomaly.charger_id}


@router.delete("/anomalies/{charger_id}")
async def delete_anomaly(
    charger_id: str,
    timestamp: datetime,
    telemetry_type: str,
    db: AsyncSession = Depends(get_db_async),
):
    """Delete a specific anomaly."""
    result = await db.execute(
        select(Anomaly).filter(
            Anomaly.charger_id == charger_id,
            Anomaly.timestamp == timestamp,
            Anomaly.telemetry_type == telemetry_type,
        )
    )
    anomaly = result.scalars().first()

    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    await db.delete(anomaly)
    await db.commit()

    logger.info(f"Deleted anomaly for charger {charger_id} at {timestamp}")
    return {"message": "Anomaly deleted"}