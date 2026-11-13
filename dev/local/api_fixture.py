"""A small HTTP API with synthetic readings, for trying HTTP sources locally."""

import argparse
import json
import math
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080
# The station measures this often; a poll in between repeats the observation.
OBSERVATION_SECONDS = 15


def station(now: float) -> dict:
    """The latest observation as many public APIs report one: a timestamp that
    moves only with a new measurement, nested fields and one number as text."""
    observed = now - now % OBSERVATION_SECONDS
    phase = observed / 240
    return {
        "station": "roof",
        "observed_at": datetime.fromtimestamp(observed, UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "temperature": round(18 + 6 * math.sin(phase), 2),
        "humidity": f"{55 + 20 * math.cos(phase):.1f}",
        "wind": {
            "speed": round(4.5 + 3 * math.sin(phase * 3), 2),
            "gusting": math.sin(phase * 3) > 0.6,
        },
        "sky": "Clear" if math.sin(phase / 2) > 0 else "Overcast",
    }


def meter(now: float) -> dict:
    """A meter that names no time of its own: every poll is a new value."""
    return {
        "power_kw": round(18 + 7 * math.sin(now / 30), 3),
        "energy_kwh": round(now % 86400 / 3600 * 18, 3),
    }


ROUTES = {
    "/health": lambda now: {"status": "ok"},
    "/v1/stations/roof/latest": station,
    "/v1/meters/main": meter,
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # Keep the socket open between polls.

    def log_message(self, *arguments):
        pass

    def do_GET(self):
        route = ROUTES.get(self.path.partition("?")[0])
        reply = {"detail": "Not found"} if route is None else route(time.time())
        body = json.dumps(reply, allow_nan=False).encode()
        self.send_response(404 if route is None else 200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(port: int = PORT) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("", port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", required=True)
    parser.parse_args()
    with serve() as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
