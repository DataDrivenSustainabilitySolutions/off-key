"""
Pydantic schemas for model hyperparameters.

Each model in the registry has a corresponding schema that defines
its configurable hyperparameters with defaults and validation.

These schemas serve multiple purposes:
1. API validation - ensure valid params are passed
2. Documentation - auto-generate param docs
3. Type safety - IDE support and runtime validation
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


class ModelHyperparameters(BaseModel):
    """Base class for model hyperparameters"""

    class Config:
        extra = "forbid"  # Reject unknown parameters


# =============================================================================
# Distance-based Models
# =============================================================================


class IncrementalKNNParams(ModelHyperparameters):
    """
    Hyperparameters for Incremental K-Nearest Neighbors anomaly detector.

    Uses a sliding window approach with distance-based anomaly scoring.
    """

    n_neighbors: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of nearest neighbors to consider for anomaly scoring",
    )
    window_size: int = Field(
        default=1000,
        ge=10,
        le=100000,
        description="Size of the sliding window for storing reference points",
    )


# =============================================================================
# Forest-based Models
# =============================================================================


class OnlineIsolationForestParams(ModelHyperparameters):
    """
    Hyperparameters for Online Isolation Forest anomaly detector.

    Streaming variant of Isolation Forest that incrementally updates
    trees as new data arrives.
    """

    n_trees: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of isolation trees in the ensemble",
    )
    height_limit: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum depth of each tree. None for auto (log2 of window_size)",
    )
    window_size: int = Field(
        default=1000,
        ge=10,
        le=100000,
        description="Size of the sliding window for tree updates",
    )


class HalfSpaceTrees(ModelHyperparameters):
    """
    Hyperparameters for Half-Space Trees anomaly detector.

    A fast streaming anomaly detection algorithm based on
    random space partitioning. Good for high-dimensional data.
    """

    n_trees: int = Field(
        default=25,
        ge=1,
        le=500,
        description="Number of half-space trees in the ensemble",
    )
    height: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Maximum depth of each tree",
    )
    window_size: int = Field(
        default=250,
        ge=10,
        le=10000,
        description="Size of the reference window",
    )


# =============================================================================
# SVM-based Models
# =============================================================================


class AdaptiveSVMParams(ModelHyperparameters):
    """
    Hyperparameters for Incremental One-Class SVM with Adaptive Kernel.

    Online variant of One-Class SVM that adapts its kernel parameters
    based on incoming data distribution.
    """

    kernel: Literal["rbf", "linear", "poly"] = Field(
        default="rbf",
        description="Kernel function type",
    )
    nu: float = Field(
        default=0.1,
        gt=0,
        lt=1,
        description="Upper bound on fraction of outliers"
        " and lower bound on support vectors",
    )
    gamma: Optional[float] = Field(
        default=None,
        gt=0,
        description="Kernel coefficient. None for auto (1/n_features)",
    )


# =============================================================================
# Preprocessing Components (for reference)
# =============================================================================


class StandardScalerParams(ModelHyperparameters):
    """Hyperparameters for incremental standard scaler"""

    with_mean: bool = Field(
        default=True,
        description="Center data by subtracting mean",
    )
    with_std: bool = Field(
        default=True,
        description="Scale data by dividing by standard deviation",
    )


class IncrementalPCAParams(ModelHyperparameters):
    """Hyperparameters for incremental PCA"""

    n_components: int = Field(
        default=10,
        ge=1,
        description="Number of principal components to retain",
    )
