"""The calibration methods RADAR runs, described for the control plane.

The methods come from ``aberrant.calibration``. The control plane reads the
generated ``calibration_catalog.json`` and never imports the numerical runtime.
``python -m off_key_mqtt_radar.catalog --write`` regenerates it.
"""

import math

from aberrant import __version__
from aberrant.calibration import CALIBRATORS


def _bound(value: float) -> float | None:
    return value if math.isfinite(value) else None


def generate_calibration_catalog() -> dict:
    return {
        "aberrant_version": __version__,
        # The order the methods are offered in: conformal, then Bayesian.
        "order": list(CALIBRATORS),
        "calibrators": {
            spec.id: {
                "name": spec.name,
                "reference": spec.reference,
                "summary": spec.summary,
                "family": spec.family,
                "coverage": spec.coverage,
                "parameters": [
                    {
                        "key": parameter.key,
                        "label": parameter.label,
                        "default": parameter.default,
                        "low": parameter.low,
                        "high": parameter.high,
                        "step": parameter.step,
                        "minimum": parameter.minimum,
                        "maximum": _bound(parameter.maximum),
                        "exclusive_minimum": parameter.exclusive_minimum,
                        "exclusive_maximum": parameter.exclusive_maximum,
                        "integer": parameter.integer,
                        "help": parameter.help,
                    }
                    for parameter in spec.parameters
                ],
            }
            for spec in CALIBRATORS.values()
        },
    }
