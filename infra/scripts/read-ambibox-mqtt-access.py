#!/usr/bin/env python3
"""Save existing EMQX MQTT credentials privately and report only the file path."""

import json
import os
import subprocess
import sys
import tempfile

containers = subprocess.run(
    [
        "docker",
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.swarm.service.name={sys.argv[1]}_emqx-main",
    ],
    check=True,
    capture_output=True,
    text=True,
).stdout.split()
if not containers:
    sys.exit(0)

expression = (
    'io:format("~ts~n", [emqx_utils_json:encode('
    "emqx_config:get_raw([connectors, mqtt], #{}))])."
)
result = subprocess.run(
    ["docker", "exec", containers[0], "/opt/emqx/bin/emqx", "eval", expression],
    check=True,
    capture_output=True,
    text=True,
)
connectors = json.JSONDecoder().raw_decode(result.stdout[result.stdout.index("{") :])[0]
matches = [
    value
    for name, value in connectors.items()
    if name == "ambibox" or name.startswith("offkey_ambibox_")
]
if not matches:
    sys.exit(0)
credentials = {
    (value.get("username", ""), value.get("password", "")) for value in matches
}
if len(credentials) != 1:
    raise SystemExit(
        "AmbiBox connectors have different credentials; provide an explicit pair"
    )
username, password = credentials.pop()
if not username or not password or password == "******":
    raise SystemExit("Existing AmbiBox credentials are unavailable")
destination = tempfile.NamedTemporaryFile(
    mode="w", prefix="offkey-ambibox-", delete=False
)
try:
    with destination:
        json.dump({"mqtt_username": username, "mqtt_password": password}, destination)
except BaseException:
    os.unlink(destination.name)
    raise
print(destination.name)
