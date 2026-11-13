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
        "weather",
        "Finnish road weather",
        "https://www.digitraffic.fi/en/road-traffic/",
        "Fintraffic / Digitraffic",
        "CC BY 4.0",
        CC_BY,
        "One roadside weather station. Updates can be several minutes apart.",
    ),
    Source(
        "traffic",
        "Finnish road traffic counts",
        "https://www.digitraffic.fi/en/road-traffic/",
        "Fintraffic / Digitraffic",
        "CC BY 4.0",
        CC_BY,
        "One automatic traffic measurement station: five-minute sliding "
        "averages, updated about once a minute.",
    ),
    Source(
        "mosquitto",
        "Mosquitto public broker metrics",
        "https://test.mosquitto.org/",
        "Eclipse Mosquitto public test broker",
        "Public test service terms",
        "https://test.mosquitto.org/",
        "Real client counts and message traffic from a public test broker. "
        "Fresh updates are timestamped on arrival; service interruptions are possible.",
    ),
)


def public_sources() -> list[dict]:
    return [asdict(source) for source in SOURCES]
