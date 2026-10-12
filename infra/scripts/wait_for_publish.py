"""Wait for this main commit's publisher before looking for production images."""

import argparse
import re
import time

from pin_release import main_runs


def wait_for_publish(revision: str, timeout: int = 1200) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A full lowercase main commit SHA is required")
    deadline = time.monotonic() + timeout
    while True:
        run = main_runs("docker-publish.yml", revision).get(revision)
        if run and run["status"] == "completed":
            if run["conclusion"] == "success":
                return run
            raise RuntimeError(
                f"Docker Publish run {run['id']} (attempt {run['run_attempt']}) "
                f"ended with {run['conclusion']}; production images cannot be tested. "
                f"See {run['html_url']}"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            state = run["status"] if run else "not started"
            raise TimeoutError(f"Docker Publish for {revision} is still {state}")
        time.sleep(min(10, remaining))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("revision")
    args = parser.parse_args()
    print(f"Waiting for Docker Publish for {args.revision}", flush=True)
    run = wait_for_publish(args.revision)
    print(f"Docker Publish run {run['id']} succeeded")
