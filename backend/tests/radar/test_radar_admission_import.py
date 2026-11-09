"""The RADAR image has no TACTIC/account configuration or full ORM runtime."""

import os
import subprocess
import sys
from pathlib import Path


def test_admission_import_needs_only_radar_runtime_environment():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from aberration_mqtt_radar.admission import RadarAdmissionSettings; "
            "import sys; assert 'aberration_core.db.models' not in sys.modules; "
            "assert RadarAdmissionSettings().RADAR_LIFECYCLE_VERSION is None",
        ],
        env={
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "SYSTEMROOT", "WINDIR"}
        },
        cwd=Path(sys.executable).parent,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_package_import_loads_no_runtime_modules():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, aberration_mqtt_radar; "
            "loaded = [m for m in sys.modules "
            "if m.startswith('aberration_mqtt_radar.')]; "
            "assert not loaded, loaded",
        ],
        cwd=Path(sys.executable).parent,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
