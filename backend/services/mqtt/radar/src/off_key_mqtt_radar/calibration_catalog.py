"""The calibration methods RADAR runs, described for the control plane.

The methods come from ``aberrant.calibration``. The control plane reads the
generated ``calibration_catalog.json`` and never imports the numerical runtime.
``python -m off_key_mqtt_radar.catalog --write`` regenerates it.
"""

from aberrant import __version__
from aberrant.calibration import CALIBRATORS


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
                "parameters": spec.schema(),
            }
            for spec in CALIBRATORS.values()
        },
    }
