from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import MetaData, PrimaryKeyConstraint, Table
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP


def monitoring_evidence_table(metadata: MetaData) -> Table:
    return Table(
        "monitoring_evidence",
        metadata,
        Column("service_id", Text, nullable=False),
        Column("timestamp", TIMESTAMP(timezone=True), nullable=False),
        Column("sequence_number", Integer, nullable=False),
        Column("charger_id", Text, nullable=False, index=True),
        Column(
            "sensor_set",
            JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        Column(
            "input_timestamps",
            JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        Column(
            "strategy",
            Text,
            nullable=False,
            default="static_baseline",
            server_default=text("'static_baseline'"),
        ),
        Column("model_type", Text, nullable=True),
        Column("p_value", Float, nullable=True),
        Column("anomaly_score", Float, nullable=True),
        Column("e_value", Float, nullable=True),
        Column("e_value_is_infinite", Boolean, nullable=False, default=False),
        Column("log_e_value", Float, nullable=True),
        Column("restarted_martingale", Float, nullable=True),
        Column(
            "restarted_martingale_is_infinite",
            Boolean,
            nullable=False,
            default=False,
        ),
        Column("log_restarted_martingale", Float, nullable=True),
        Column(
            "tracker_results",
            JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            default=list,
            server_default=text("'[]'"),
        ),
        Column("threshold", Float, nullable=False),
        Column("alarm", Boolean, nullable=False, default=False),
        Column(
            "created",
            DateTime(timezone=True),
            server_default=func.now(),
            index=True,
        ),
        PrimaryKeyConstraint(
            "service_id",
            "timestamp",
            "sequence_number",
            name="pk_monitoring_evidence",
        ),
        CheckConstraint(
            "(strategy = 'static_baseline' AND p_value IS NOT NULL) OR "
            "(strategy = 'adaptive_stream' AND anomaly_score IS NOT NULL "
            "AND anomaly_score <> 'NaN'::double precision "
            "AND anomaly_score NOT IN "
            "('Infinity'::double precision, '-Infinity'::double precision))",
            name="ck_monitoring_evidence_strategy_payload",
        ),
        Index(
            "idx_monitoring_evidence_charger_timestamp",
            "charger_id",
            "timestamp",
        ),
        Index(
            "idx_monitoring_evidence_charger_created_cursor",
            "charger_id",
            "created",
            "timestamp",
            "service_id",
            "sequence_number",
        ),
        Index(
            "idx_monitoring_evidence_service_sequence",
            "service_id",
            "sequence_number",
        ),
        Index(
            "idx_monitoring_evidence_sensor_set_gin",
            "sensor_set",
            postgresql_using="gin",
        ),
    )
