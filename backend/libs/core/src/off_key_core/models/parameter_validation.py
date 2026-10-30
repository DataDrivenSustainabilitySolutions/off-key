"""Structured parameter diagnostics shared by schema, form and graph validation."""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from itertools import islice
from typing import LiteralString, cast

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError


class ParameterIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    loc: tuple[str | int, ...]
    message: str


def parameter_error(title: str, issues: Sequence[ParameterIssue]) -> ValidationError:
    details: list[InitErrorDetails] = [
        {
            "type": PydanticCustomError(
                cast(LiteralString, issue.code), "{message}", {"message": issue.message}
            ),
            "loc": issue.loc,
            "input": None,
        }
        for issue in issues[:64]
    ]
    return ValidationError.from_exception_data(title, details)


@contextmanager
def parameter_location(*prefix: str | int) -> Generator[None]:
    try:
        yield
    except ValidationError as error:
        raise parameter_error(
            error.title,
            [
                ParameterIssue(
                    code=item["type"], loc=(*prefix, *item["loc"]), message=item["msg"]
                )
                for item in error.errors(include_url=False, include_context=False)
            ],
        ) from error


def validate_parameter_schema(title: str, schema: dict, values: dict) -> None:
    issues = []
    seen = set()
    for error in islice(Draft202012Validator(schema).iter_errors(values), 64):
        paths = [tuple(error.absolute_path)]
        code = "invalid_type" if error.validator == "type" else "invalid_value"
        if error.validator == "required":
            code = "missing_parameter"
            paths = [
                (*error.absolute_path, name)
                for name in error.validator_value
                if name not in error.instance
            ]
        elif (
            error.validator == "additionalProperties"
            and error.validator_value is False
            and isinstance(error.schema, dict)
        ):
            code = "unexpected_parameter"
            paths = [
                (*error.absolute_path, name)
                for name in error.instance
                if name not in error.schema.get("properties", {})
            ]
        for path in paths:
            if (code, path) in seen:
                continue
            seen.add((code, path))
            message = (
                f"{path[-1]!r} is a required property"
                if code == "missing_parameter"
                else error.message
            )
            issues.append(ParameterIssue(code=code, loc=path, message=message))
    if issues:
        raise parameter_error(title, issues)
