from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.schema import (
    MetaData,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.types import TIMESTAMP


def anomalies_table(metadata: MetaData) -> Table:
    """Alarm rows; RADAR writes them, core and the gateway read them."""
    return Table(
        "anomalies",
        metadata,
        Column("charger_id", Text, nullable=False, index=True),
        Column("timestamp", TIMESTAMP(timezone=True), nullable=False, index=True),
        Column("telemetry_type", Text, nullable=False, index=True),
        # Empty scope belongs to historical and manually created records. Monitor
        # IDs stay in history after the monitor is deleted, so this is not a
        # foreign key.
        Column(
            "service_id", Text, nullable=False, default="", server_default=text("''")
        ),
        Column("anomaly_type", Text, nullable=False, index=True),
        Column("anomaly_value", Float, nullable=False, index=True),
        # 'conformal_pvalue' for static conformal monitoring; NULL predates it.
        Column("value_type", Text, nullable=True),
        # Exact telemetry streams involved, so multivariate rows highlight only
        # the charts whose sensors contributed to the aligned vector.
        Column("sensor_set", JSON, nullable=True),
        PrimaryKeyConstraint(
            "charger_id", "timestamp", "telemetry_type", "service_id", name="pk_anomaly"
        ),
        Index("idx_anomaly_lookup", "charger_id", "timestamp", "telemetry_type"),
        Index("idx_anomaly_charger_timestamp", "charger_id", "timestamp"),
        Index(
            "idx_anomaly_timestamp_desc",
            "timestamp",
            postgresql_using="btree",
            postgresql_ops={"timestamp": "DESC"},
        ),
    )


def anomaly_identity_table(metadata: MetaData) -> Table:
    """Stable public IDs for anomaly rows, which have a composite natural key."""
    return Table(
        "anomaly_identity",
        metadata,
        Column(
            "anomaly_id",
            Text,
            primary_key=True,
            nullable=False,
            server_default=text("gen_random_uuid()::text"),
        ),
        Column("charger_id", Text, nullable=False, index=True),
        Column("timestamp", TIMESTAMP(timezone=True), nullable=False, index=True),
        Column("telemetry_type", Text, nullable=False, index=True),
        Column(
            "service_id", Text, nullable=False, default="", server_default=text("''")
        ),
        Column(
            "created", DateTime(timezone=True), server_default=func.now(), index=True
        ),
        UniqueConstraint(
            "charger_id",
            "timestamp",
            "telemetry_type",
            "service_id",
            name="uq_anomaly_identity_target",
        ),
        ForeignKeyConstraint(
            ["charger_id", "timestamp", "telemetry_type", "service_id"],
            [
                "anomalies.charger_id",
                "anomalies.timestamp",
                "anomalies.telemetry_type",
                "anomalies.service_id",
            ],
            ondelete="CASCADE",
            name="fk_anomaly_identity_anomaly",
        ),
        Index("idx_anomaly_identity_charger_timestamp", "charger_id", "timestamp"),
    )


def radar_runtime_checkpoints_table(metadata: MetaData) -> Table:
    """One authenticated, bounded recovery snapshot per managed monitor."""
    return Table(
        "radar_runtime_checkpoints",
        metadata,
        Column(
            "service_id",
            Text,
            ForeignKey(
                "services.id", ondelete="CASCADE", name="fk_radar_checkpoint_service"
            ),
            primary_key=True,
        ),
        Column("format_version", Integer, nullable=False),
        Column("configuration_fingerprint", Text, nullable=False),
        Column("runtime_fingerprint", Text, nullable=False),
        Column("processed_count", BigInteger, nullable=False),
        Column("saved_at", TIMESTAMP(timezone=True), nullable=False),
        Column("payload", LargeBinary, nullable=False),
        Column("signature", Text, nullable=False),
        CheckConstraint("processed_count >= 0", name="ck_radar_checkpoint_count"),
    )


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
