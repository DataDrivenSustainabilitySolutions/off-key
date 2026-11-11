"""Applies to and Result: which features a step uses and where its output goes.

The compiler, the validation API and both RADAR runtimes read a step's scope
through this module, so a feature order is decided in exactly one place:
untouched features keep their order and new features are appended in the
order of Applies to.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..schemas.pipelines import (
    MinMaxScalerParameters,
    RobustScalerParameters,
    RollingRobustScalerParameters,
    StandardScalerParameters,
)
from .pipeline_prepare import (
    LANE_COMPONENTS,
    PREPARE_COMPONENTS,
    PREPARE_MODELS,
    default_suffix,
)

# Steps that map each feature to one value, by the parameters that name their
# added features; each parameter model holds the step's default suffix.
_ELEMENTWISE_MODELS = {
    "static.standard_scaler": StandardScalerParameters,
    "adaptive.standard_scaler": StandardScalerParameters,
    "static.min_max_scaler": MinMaxScalerParameters,
    "adaptive.min_max_scaler": MinMaxScalerParameters,
    "static.robust_scaler": RobustScalerParameters,
    "adaptive.robust_scaler": RollingRobustScalerParameters,
}
ELEMENTWISE_SUFFIXES: dict[str, str] = {
    component: model.model_fields["suffix"].default
    for component, model in _ELEMENTWISE_MODELS.items()
}
# Steps that turn the features they use into new components.
PROJECTIONS = frozenset(
    {
        "static.pca",
        "adaptive.uncentered_pca",
        "static.random_projection",
        "adaptive.random_projection",
    }
)
# Steps that learn from data; nothing in the Prepare stage may follow one.
LEARNED_COMPONENTS = frozenset(ELEMENTWISE_SUFFIXES) | PROJECTIONS
SCOPED_COMPONENTS = LEARNED_COMPONENTS | PREPARE_COMPONENTS
SCOPE_DEFAULTS: dict[str, Any] = {"apply_to": None, "result": "replace", "suffix": None}
# Steps whose output is usually wanted next to their input add it by default.
RESULT_DEFAULTS: dict[str, str] = {
    component: model.model_fields["result"].default
    for component, model in PREPARE_MODELS.items()
    if "result" in model.model_fields
    and model.model_fields["result"].default != "replace"
}
MAX_FEATURE_NAME_LENGTH = 120


class ScopeError(ValueError):
    """A scope that cannot apply at this point of the graph."""

    def __init__(self, message: str, parameter: str):
        super().__init__(message)
        self.parameter_path: list[str | int] = [parameter]


def scope_defaults(component: str) -> dict[str, Any]:
    return {**SCOPE_DEFAULTS, "result": RESULT_DEFAULTS.get(component, "replace")}


def canonical_scope(component: str, params: dict[str, Any]) -> dict[str, Any]:
    """Leave scope settings out at their defaults, and a suffix that adds nothing."""
    defaults = scope_defaults(component)
    if params.get("result", defaults["result"]) == "replace":
        params.pop("suffix", None)
    for name, default in defaults.items():
        if name in params and params[name] == default:
            del params[name]
    return params


def adds(component: str, params: dict[str, Any]) -> bool:
    """Whether a step keeps the features it uses and adds its output."""
    return params.get("result", RESULT_DEFAULTS.get(component, "replace")) == "add"


def split_scope(params: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate scope settings from the parameters a runtime component takes."""
    scope = {name: params[name] for name in SCOPE_DEFAULTS if name in params}
    return scope, {
        name: value for name, value in params.items() if name not in SCOPE_DEFAULTS
    }


def is_scoped(component: str, params: dict[str, Any]) -> bool:
    """Whether a step changes only some features or adds its output."""
    return component in SCOPED_COMPONENTS and (
        params.get("apply_to") is not None or adds(component, params)
    )


@dataclass(frozen=True)
class StepScope:
    """Where a scoped step reads its features and writes its output."""

    inputs: tuple[str, ...]
    """Incoming feature names, in their order."""
    selected: tuple[str, ...]
    """The features the step uses, in the order of Applies to."""
    add: bool
    elementwise: bool
    added: tuple[str, ...] = ()
    """Names of the features an elementwise step adds, one per selected feature."""

    @property
    def indices(self) -> list[int]:
        position = {name: index for index, name in enumerate(self.inputs)}
        return [position[name] for name in self.selected]

    @property
    def kept(self) -> list[int]:
        """Incoming features a projection leaves in place."""
        if self.add:
            return list(range(len(self.inputs)))
        chosen = set(self.selected)
        return [index for index, name in enumerate(self.inputs) if name not in chosen]

    def output_names(self, components: Sequence[str] = ()) -> list[str]:
        """The step's features: elementwise steps keep positions, outputs append."""
        if self.elementwise:
            return list(self.inputs) + list(self.added if self.add else ())
        return [self.inputs[index] for index in self.kept] + list(components)


def _selected(
    component: str, params: dict[str, Any], names: tuple[str, ...]
) -> tuple[str, ...]:
    """The features a step uses: Applies to, or every feature that arrives.

    A Rolling relation compares the others with one feature, which is never
    among them.
    """
    available = set(names)
    apply_to = params.get("apply_to")
    against = params.get("against") if component == "prepare.relation" else None
    if against is not None and against not in available:
        raise ScopeError(f"{against} is not available at this step.", "against")
    if apply_to is None:
        selected = tuple(name for name in names if name != against)
        if against is not None and not selected:
            raise ScopeError(
                f"Only {against} arrives here. A Rolling relation needs another "
                "feature to compare with it.",
                "apply_to",
            )
        return selected
    missing = [name for name in apply_to if name not in available]
    if missing:
        raise ScopeError(f"{missing[0]} is not available at this step.", "apply_to")
    if against in apply_to:
        raise ScopeError(
            f"{against} is the feature the others are compared with. Leave it "
            "out of Applies to.",
            "apply_to",
        )
    return tuple(apply_to)


def step_scope(
    component: str, params: dict[str, Any], inputs: Sequence[str]
) -> StepScope:
    """Resolve a step's scope against the features that reach it."""
    names = tuple(inputs)
    available = set(names)
    selected = _selected(component, params, names)
    add = adds(component, params)
    elementwise = component in ELEMENTWISE_SUFFIXES or component in LANE_COMPONENTS
    added: tuple[str, ...] = ()
    if elementwise and add:
        suffix = params.get("suffix") or (
            ELEMENTWISE_SUFFIXES[component]
            if component in ELEMENTWISE_SUFFIXES
            else default_suffix(component, params)
        )
        added = tuple(f"{name}_{suffix}" for name in selected)
        taken = next((name for name in added if name in available), None)
        if taken is not None:
            raise ScopeError(
                f"{taken} already exists. Choose another suffix.", "suffix"
            )
        long = next(
            (name for name in added if len(name) > MAX_FEATURE_NAME_LENGTH), None
        )
        if long is not None:
            raise ScopeError(
                f"{long[:40]}… is longer than {MAX_FEATURE_NAME_LENGTH} characters. "
                "Choose a shorter suffix.",
                "suffix",
            )
    return StepScope(names, selected, add, elementwise, added)
