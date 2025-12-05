"""
Pydantic schemas for model hyperparameters.

Each model in the registry has a corresponding schema that defines
its configurable hyperparameters with defaults and validation.

These schemas serve multiple purposes:
1. API validation - ensure valid params are passed
2. Documentation - auto-generate param docs
3. Type safety - IDE support and runtime validation
"""

from typing import Any, Dict, Literal, Optional
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
    Hyperparameters for K-Nearest Neighbors anomaly detector.

    Note: KNN in onad requires a FaissSimilaritySearchEngine object which is
    created internally by the registry based on window_size and warm_up params.
    """

    k: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Number of nearest neighbors to consider for anomaly scoring",
    )
    window_size: int = Field(
        default=1000,
        ge=10,
        le=100000,
        description="Maximum data points in the similarity engine's sliding window",
    )
    warm_up: int = Field(
        default=50,
        ge=1,
        description="Minimum data points required before similarity search",
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

    num_trees: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Number of isolation trees in the ensemble",
    )
    max_leaf_samples: int = Field(
        default=32,
        ge=1,
        description="Maximum samples allowed in leaf nodes",
    )
    window_size: int = Field(
        default=2048,
        ge=10,
        le=100000,
        description="Size of the sliding window for tree updates",
    )


class MondrianIsolationForestParams(ModelHyperparameters):
    """
    Hyperparameters for Mondrian Forest anomaly detector.

    A streaming anomaly detection algorithm based on Mondrian processes.
    Efficient for high-dimensional streaming data.
    """

    n_estimators: int = Field(
        default=100,
        ge=1,
        le=500,
        description="Number of trees in the ensemble",
    )
    subspace_size: int = Field(
        default=256,
        ge=1,
        description="Number of features allocated to each tree",
    )
    lambda_: float = Field(
        default=1.0,
        gt=0,
        description="Intensity parameter for the Mondrian process",
    )
    seed: Optional[int] = Field(
        default=None,
        description="Random seed for reproducibility",
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

    nu: float = Field(
        default=0.1,
        gt=0,
        lt=1,
        description="Upper bound on outlier fraction, lower bound on support vectors",
    )
    initial_gamma: float = Field(
        default=1.0,
        gt=0,
        description="Initial RBF kernel width",
    )
    buffer_size: int = Field(
        default=200,
        ge=10,
        description="Size of the sample buffer",
    )
    sv_budget: int = Field(
        default=100,
        ge=10,
        description="Maximum number of support vectors",
    )


# =============================================================================
# Preprocessing Components (for reference)
# =============================================================================


class StandardScalerParams(ModelHyperparameters):
    """Hyperparameters for incremental standard scaler from ONAD."""

    with_std: bool = Field(
        default=True,
        description="Scale data by dividing by standard deviation",
    )


class IncrementalPCAParams(ModelHyperparameters):
    """Hyperparameters for incremental PCA from ONAD."""

    n_components: int = Field(
        default=10,
        ge=1,
        description="Number of principal components to retain",
    )
    n0: int = Field(
        default=50,
        ge=1,
        description="Initial sample count for warm-up phase",
    )
    forgetting_factor: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Weight for newer values (0-1). None for no adaptive weighting.",
    )


# =============================================================================
# Preprocessing step schema
# =============================================================================


class PreprocessingStep(BaseModel):
    """Generic preprocessing step definition."""

    type: Literal["standard_scaler", "pca"] = Field(
        description="Preprocessing transformer type"
    )
    params: Dict[str, Any] = Field(default_factory=dict)
