"""Check selected live feeds, or discover one active entity per provider.

Print a reusable FeedSelection JSON document to stdout and counts to stderr.
Discovery lasts at most 30 seconds and never publishes to a public broker.
"""

import argparse
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from off_key_core.demo.catalogue import FeedSelection

from .normalize import Normalizer
from .relay import feeds, load_selection, subscriber


def candidate(source: str, mqtt_topic: str) -> dict:
    if source in ("weather", "traffic"):
        return {f"{source}_station": int(mqtt_topic.split("/")[1])}
    return {}


def _receiver(feed, selection, discover, chosen, counts):
    normalizer = Normalizer(selection)

    def receive(client, _userdata, message):
        nonlocal normalizer
        if discover and feed.id not in chosen:
            try:
                change = candidate(feed.id, message.topic)
                selected = FeedSelection.model_validate(selection.model_dump() | change)
                candidate_normalizer = Normalizer(selected)
            except (ValueError, TypeError, KeyError, IndexError, OverflowError):
                return
            messages = candidate_normalizer.messages(
                feed.id,
                message.topic,
                message.payload,
                received_at=time.time(),
                retained=message.retain,
            )
            if not messages:
                return
            chosen[feed.id] = change
            normalizer = candidate_normalizer
            narrowed = next(item for item in feeds(selected) if item.id == feed.id)
            if narrowed.topics != feed.topics:
                client.unsubscribe(list(feed.topics))
                client.subscribe([(topic, 0) for topic in narrowed.topics])
        else:
            messages = normalizer.messages(
                feed.id,
                message.topic,
                message.payload,
                received_at=time.time(),
                retained=message.retain,
            )
        counts[feed.id] = counts.get(feed.id, 0) + bool(messages)

    return receive


def probe(selection: FeedSelection, seconds: int, discover: bool) -> FeedSelection:
    chosen: dict[str, dict] = {}
    counts: dict[str, int] = {}
    clients = []
    discovery = {
        # Use Digitraffic's documented network subscription. The '+' filters
        # do not deliver measurements on this service. Narrow after the first
        # valid observation, retaining only a bounded selected catalogue.
        "weather": ("weather-v2/#",),
        "traffic": ("tms-v2/#",),
    }

    try:
        for feed in feeds(selection):
            if discover and feed.id in discovery:
                feed = replace(feed, topics=discovery[feed.id])
            clients.append(
                subscriber(
                    feed,
                    _receiver(
                        feed,
                        selection,
                        discover and feed.id in discovery,
                        chosen,
                        counts,
                    ),
                )
            )
        threading.Event().wait(seconds)
    finally:
        for client in clients:
            client.disconnect()
            client.loop_stop()
    for feed in feeds(selection):
        print(
            f"{feed.id}: {counts.get(feed.id, 0)} fresh selected observations",
            file=sys.stderr,
        )
    values = selection.model_dump()
    for change in chosen.values():
        values.update(change)
    return FeedSelection.model_validate(values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discover", action="store_true")
    parser.add_argument("--seconds", type=int, choices=range(1, 31), default=20)
    parser.add_argument("--selection", type=Path, help="JSON selections to verify")
    args = parser.parse_args()
    selected = load_selection(args.selection)
    print(probe(selected, args.seconds, args.discover).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
