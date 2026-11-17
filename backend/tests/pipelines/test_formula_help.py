"""The formula help names every function, so it reads the same outside the editor."""

from off_key_core.models.pipeline_formula import FUNCTIONS
from off_key_core.schemas.pipelines import FormulaParameters


def test_the_formula_help_names_every_function():
    help_text = FormulaParameters.model_fields["expression"].description
    assert all(name in help_text for name in FUNCTIONS)
    assert "typing" not in help_text
