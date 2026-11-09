"""Bound external compiler metadata without changing canonical compilation."""

from ..schemas.pipelines import (
    PipelineIssue,
    PipelineValidation,
    PipelineValidationReport,
)
from ..utils.json_budget import bounded_utf8_text, fits_json_budget, json_size_up_to
from .pipeline_prepare import stage_split

MAX_PIPELINE_REPORT_BYTES = 512 * 1024
_ISSUE_BUDGET = 64 * 1024
_DEFINITION_BUDGET = 256 * 1024


def _fits(value, budget=MAX_PIPELINE_REPORT_BYTES):
    return fits_json_budget(value, budget)


def _bounded_fix(fix):
    """A fix whose text would be cut is no longer a fix."""
    if fix is None or bounded_utf8_text(fix.text, 512) != fix.text:
        return None
    return fix


def _bounded_issues(issues):
    bounded = []
    truncated = False
    for issue in issues:
        item = issue.model_copy(
            update={
                "message": bounded_utf8_text(issue.message, 1024),
                "code": bounded_utf8_text(issue.code, 64),
                "fix": _bounded_fix(issue.fix),
                "parameter_path": [
                    bounded_utf8_text(part, 128) if isinstance(part, str) else part
                    for part in issue.parameter_path[:32]
                ]
                if issue.parameter_path is not None
                else None,
                "node_id": bounded_utf8_text(issue.node_id, 100)
                if issue.node_id
                else None,
            }
        )
        if len(bounded) >= 64 or not _fits([*bounded, item], _ISSUE_BUDGET):
            truncated = True
            break
        truncated |= item != issue
        bounded.append(item)
    return bounded, truncated


def _hidden(result: PipelineValidation) -> set[str]:
    """Steps the editor does not show yet: a schema 1 design's calibration step,
    which it draws as part of the policy."""
    if result.definition.strategy is None:
        return set()
    return {node.id for node in result.definition.nodes if node.kind == "calibration"}


def _shown_features(result: PipelineValidation, hidden: set[str]):
    """Feature tables without hidden steps, whose lineage skips over them."""
    through = {
        f"{identifier}.{column.name}": column.previous
        for identifier in hidden
        for column in result.features.get(identifier, [])
    }

    def previous(name):
        while name in through:
            name = through[name]
        return name

    return {
        identifier: [
            column
            if column.previous not in through
            else column.model_copy(update={"previous": previous(column.previous)})
            for column in columns
        ]
        for identifier, columns in result.features.items()
        if identifier not in hidden
    }


def _parents(result, identifier, hidden):
    parents = []
    for edge in sorted(result.definition.edges, key=lambda item: item.order):
        if edge.target != identifier:
            continue
        if edge.source in hidden:
            parents.extend(_parents(result, edge.source, hidden))
        else:
            parents.append(edge.source)
    return parents


def _priority_nodes(result, selected):
    if selected is None:
        return []
    parents = _parents(result, selected, _hidden(result))
    return list(dict.fromkeys([selected, *parents]))


def _budget_notice(report):
    report.issues.append(
        PipelineIssue(
            code="metadata_budget",
            message=(
                "Report metadata was bounded to 512KiB. Select a node for complete "
                "ordered feature names; omitted provenance is not an empty lineage."
            ),
        )
    )


def _warm_up(result: PipelineValidation) -> tuple[int, dict[str, int]]:
    """Observations the Prepare stage takes before the learned stage sees one,
    and the observation that gives each of its steps a first output."""
    split = stage_split(result) if result.valid else None
    if split is None:
        return 0, {}
    return split.required - 1, {key: split.first_output[key] for key in split.steps}


def bounded_validation_report(
    result: PipelineValidation,
    selected_node_id: str | None = None,
    *,
    include_definition: bool = True,
) -> PipelineValidationReport:
    issues, truncated = _bounded_issues(result.issues)
    preparation, ready_after = _warm_up(result)
    hidden = _hidden(result)
    report = PipelineValidationReport(
        valid=result.valid,
        issues=issues,
        definition=result.definition if include_definition else None,
        definition_omitted=not include_definition,
        order=[identifier for identifier in result.order if identifier not in hidden],
        features=_shown_features(result, hidden),
        fingerprint=result.fingerprint,
        selected_node_id=selected_node_id,
        issues_truncated=truncated,
        preparation_observations=preparation,
        ready_after=ready_after,
    )
    if selected_node_id is not None and selected_node_id not in {
        node.id for node in result.definition.nodes
    }:
        report.features = {}
        report.features_complete = False
        report.issues.append(
            PipelineIssue(code="selected_node", message="Selected node does not exist")
        )
    if not _fits(report.definition, _DEFINITION_BUDGET):
        report.definition = None
        report.definition_omitted = True
    if _fits(report) and not (
        truncated or (include_definition and report.definition_omitted)
    ):
        return report
    _budget_notice(report)
    if _fits(report):
        return report
    # Lineage goes first: which readings, steps and features each one comes from.
    report.features = {
        identifier: [
            column.model_copy(update={"slots": [], "steps": [], "previous": None})
            for column in columns
        ]
        for identifier, columns in report.features.items()
    }
    report.provenance_complete = False
    if _fits(report):
        return report
    return _selected_tables(report, result, selected_node_id)


def focused_validation_report(result: PipelineValidation, selected_node_id: str):
    """Inspect one immutable node and its parents without repeating its graph."""
    priority = _priority_nodes(result, selected_node_id)
    focused = result.model_copy(
        update={
            "features": {
                key: result.features[key] for key in priority if key in result.features
            }
        }
    )
    report = bounded_validation_report(
        focused, selected_node_id, include_definition=False
    )
    report.features_complete &= len(focused.features) == len(result.features)
    return report


def _selected_tables(report, result, selected):
    compact = report.features
    priority = _priority_nodes(result, selected)
    report.features = {key: compact[key] for key in priority if key in compact}
    report.features_complete = False
    if not _fits(report):
        # Only an invalid schema can have more than 100 aggregate parent features.
        report.features = {}
        report.issues.append(
            PipelineIssue(
                code="selected_schema_unavailable",
                message="Selected inputs exceed the supported feature schema budget",
                node_id=selected,
            )
        )
        return report
    remaining = MAX_PIPELINE_REPORT_BYTES - json_size_up_to(
        report, MAX_PIPELINE_REPORT_BYTES
    )
    for identifier, columns in compact.items():
        if identifier not in report.features:
            size = json_size_up_to({identifier: columns}, remaining)
            if size <= remaining:
                report.features[identifier] = columns
                remaining -= size
    return report
