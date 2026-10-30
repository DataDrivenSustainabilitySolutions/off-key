"""Bound external compiler metadata without changing canonical compilation."""

from ..schemas.pipelines import (
    PipelineIssue,
    PipelineValidation,
    PipelineValidationReport,
)
from ..utils.json_budget import bounded_utf8_text, fits_json_budget, json_size_up_to

MAX_PIPELINE_REPORT_BYTES = 512 * 1024
_ISSUE_BUDGET = 64 * 1024
_DEFINITION_BUDGET = 256 * 1024


def _fits(value, budget=MAX_PIPELINE_REPORT_BYTES):
    return fits_json_budget(value, budget)


def _bounded_issues(issues):
    bounded = []
    truncated = False
    for issue in issues:
        item = issue.model_copy(
            update={
                "message": bounded_utf8_text(issue.message, 1024),
                "code": bounded_utf8_text(issue.code, 64),
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


def _priority_nodes(result, selected):
    if selected is None:
        return []
    parents = [
        edge.source
        for edge in sorted(result.definition.edges, key=lambda item: item.order)
        if edge.target == selected
    ]
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


def bounded_validation_report(
    result: PipelineValidation,
    selected_node_id: str | None = None,
    *,
    include_definition: bool = True,
) -> PipelineValidationReport:
    issues, truncated = _bounded_issues(result.issues)
    report = PipelineValidationReport(
        valid=result.valid,
        issues=issues,
        definition=result.definition if include_definition else None,
        definition_omitted=not include_definition,
        order=result.order,
        features=result.features,
        fingerprint=result.fingerprint,
        selected_node_id=selected_node_id,
        issues_truncated=truncated,
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
    report.features = {
        identifier: [column.model_copy(update={"slots": []}) for column in columns]
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
