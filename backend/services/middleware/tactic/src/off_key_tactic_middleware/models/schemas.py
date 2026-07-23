"""
Pydantic schemas for ML model hyperparameters.

Each model in the registry has a corresponding schema that defines
its configurable hyperparameters with defaults and validation.

These schemas serve multiple purposes:
1. API validation - ensure valid params are passed
2. Documentation - auto-generate param docs
3. Type safety - IDE support and runtime validation
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelHyperparameters(BaseModel):
    """Base class for model hyperparameters"""

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Static PyOD Models
# =============================================================================


class PyODIsolationForestParams(ModelHyperparameters):
    """Hyperparameters for PyOD Isolation Forest used by static baselines."""

    n_estimators: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of isolation trees in the ensemble",
    )
    contamination: float = Field(
        default=0.1,
        gt=0.0,
        lt=0.5,
        description="Expected outlier fraction used by PyOD internals",
    )
    random_state: int | None = Field(
        default=42,
        description="Random seed for reproducible static training",
    )


class PyODKNNParams(ModelHyperparameters):
    """Hyperparameters for PyOD KNN used by static baselines."""

    n_neighbors: int = Field(
        default=5,
        ge=1,
        le=200,
        description="Number of neighbors used for outlier scoring",
    )
    method: Literal["largest", "mean", "median"] = Field(
        default="largest",
        description="Neighbor-distance aggregation method",
    )
    contamination: float = Field(
        default=0.1,
        gt=0.0,
        lt=0.5,
        description="Expected outlier fraction used by PyOD internals",
    )


class PyODLOFParams(ModelHyperparameters):
    """Hyperparameters for PyOD Local Outlier Factor static baselines."""

    n_neighbors: int = Field(
        default=20,
        ge=2,
        le=500,
        description="Neighborhood size for local-density comparison",
    )
    contamination: float = Field(
        default=0.1,
        gt=0.0,
        lt=0.5,
        description="Expected outlier fraction used by PyOD internals",
    )


class PyODOCSVMParams(ModelHyperparameters):
    """Hyperparameters for PyOD One-Class SVM static baselines."""

    kernel: Literal["rbf", "linear", "poly", "sigmoid"] = Field(
        default="rbf",
        description="SVM kernel",
    )
    nu: float = Field(
        default=0.1,
        gt=0.0,
        lt=1.0,
        description="Upper bound on training outlier fraction",
    )
    gamma: Literal["scale", "auto"] = Field(
        default="scale",
        description="Kernel coefficient strategy",
    )
    contamination: float = Field(
        default=0.1,
        gt=0.0,
        lt=0.5,
        description="Expected outlier fraction used by PyOD internals",
    )


class PyODHBOSParams(ModelHyperparameters):
    """Hyperparameters for PyOD HBOS static baselines."""

    n_bins: int = Field(
        default=10,
        ge=2,
        le=200,
        description="Histogram bin count",
    )
    alpha: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Regularization parameter for empty bins",
    )
    tol: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Tolerance for histogram boundary extension",
    )
    contamination: float = Field(
        default=0.1,
        gt=0.0,
        lt=0.5,
        description="Expected outlier fraction used by PyOD internals",
    )


class PyODPCAParams(ModelHyperparameters):
    """Hyperparameters for PyOD PCA static baselines."""

    n_components: int | None = Field(
        default=None,
        ge=1,
        description="Number of principal components; None lets PyOD choose",
    )
    contamination: float = Field(
        default=0.1,
        gt=0.0,
        lt=0.5,
        description="Expected outlier fraction used by PyOD internals",
    )
    weighted: bool = Field(
        default=True,
        description="Use weighted reconstruction error",
    )
    standardization: bool = Field(
        default=True,
        description="Standardize features before PCA",
    )
