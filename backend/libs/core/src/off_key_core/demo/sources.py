"""Public provenance. This module contains no credentials or runtime claims."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    attribution: str
    license: str
    license_url: str
    note: str = ""
    simulated: bool = False


CC_BY = "https://creativecommons.org/licenses/by/4.0/"
SOURCES = (
    Source(
        "hsl",
        "Helsinki trams",
        "https://digitransit.fi/en/developers/apis/5-realtime-api/vehicle-positions/high-frequency-positioning/",
        "HSL / Digitransit",
        "CC BY 4.0",
        CC_BY,
    ),
    Source(
        "hamburg",
        "Hamburg road detectors",
        "https://suche.transparenz.hamburg.de/dataset/traffic-lights-data-hamburg",
        "Freie und Hansestadt Hamburg",
        "DL-DE BY 2.0",
        "https://www.govdata.de/dl-de/by-2-0",
        "Event-driven observations; quiet periods are expected.",
    ),
    Source(
        "marine",
        "Finnish marine traffic",
        "https://www.digitraffic.fi/en/marine-traffic/",
        "Fintraffic / Digitraffic",
        "CC BY 4.0",
        CC_BY,
    ),
    Source(
        "rail",
        "Finnish trains",
        "https://www.digitraffic.fi/en/railway-traffic/",
        "Fintraffic / Digitraffic",
        "CC BY 4.0",
        CC_BY,
    ),
    Source(
        "solar",
        "TDengine solar simulation",
        "https://tdengine.com/free-public-mqtt-data-feed-real-time-solar-fleet-simulation-now-available/",
        "TDengine",
        "Provider's public feed terms",
        "https://tdengine.com/free-public-mqtt-data-feed-real-time-solar-fleet-simulation-now-available/",
        "Simulated industrial telemetry. "
        "Availability and cadence depend on the provider.",
        True,
    ),
)


def public_sources() -> list[dict]:
    return [asdict(source) for source in SOURCES]
