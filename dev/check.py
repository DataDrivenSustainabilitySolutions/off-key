"""Run the fast CI checks a branch needs before it is pushed.

Pull-request CI runs only the fast suites, and every push of every pull request
spends CI minutes, so a push should already pass them. This picks the suites
from the paths changed since the branch left origin/main (committed, staged and
unstaged) and runs them in CI's order. `--all` runs every fast suite.

    make check                # what this branch touched
    make check ARGS=--all     # every fast suite
    make check ARGS=--browser # also the route-mocked browser journeys (Docker)

The route-mocked browser journeys run only with --browser, because they need
Docker and the Playwright image; CI runs them on every pull request.
"""

import argparse
import subprocess
import sys

SYNC = [
    "uv",
    "sync",
    "--project",
    "backend",
    "--all-packages",
    "--all-groups",
    "--frozen",
]
BACKEND = [
    ["uv", "run", "--project", "backend", "ty", "check", "--project", "backend"],
    [
        "uv",
        "run",
        "--project",
        "backend",
        "python",
        "backend/scripts/generate_pipeline_types.py",
        "--check",
    ],
    [
        "uv",
        "run",
        "--project",
        "backend",
        "python",
        "-m",
        "off_key_mqtt_radar.catalog",
        "--check",
    ],
    ["uv", "run", "--project", "backend", "python", "-m", "pytest", "-q", "-x"],
]
FRONTEND = [
    ["npm", "--prefix", "frontend", "ci"],
    ["npm", "--prefix", "frontend", "run", "lint"],
    ["npm", "--prefix", "frontend", "run", "knip"],
    ["npm", "--prefix", "frontend", "test"],
    ["npm", "--prefix", "frontend", "run", "build"],
]
CI = [
    [
        "uv",
        "run",
        "--frozen",
        "--project",
        "..",
        "python",
        "-m",
        "unittest",
        "-q",
        "test_ci_plan",
        "test_ci_workflow",
        "test_docs",
    ],
]


# CI's frontend-browser job: the checked build behind `vite preview`, journeys
# in the Playwright image the chart pixel comparisons were recorded with.
BROWSER = r"""
set -euo pipefail
if ! docker info > /dev/null 2>&1; then
  echo "--browser needs a running Docker daemon for the Playwright image." >&2
  exit 1
fi
cd frontend
if curl --silent --output /dev/null http://localhost:5173; then
  echo "Port 5173 is already serving; stop that server first." >&2
  exit 1
fi
# Start Vite itself, not an npx wrapper, so the trap stops the server.
./node_modules/.bin/vite preview --port 5173 --strictPort > /tmp/off-key-vite-preview.log 2>&1 &
preview=$!
trap 'kill $preview 2>/dev/null; wait $preview 2>/dev/null || true' EXIT
curl --fail --silent --retry 30 --retry-all-errors --retry-delay 1 \
  http://localhost:5173 > /dev/null
version="$(node -p "require('./node_modules/@playwright/test/package.json').version")"
docker run --rm --network host --ipc host --volume "${PWD}:/work" --workdir /work \
  --env CI=true "mcr.microsoft.com/playwright:v${version}-noble" npm run test:e2e:mocked
"""


def git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def changed():
    base = git("merge-base", "origin/main", "HEAD").strip()
    paths = set(git("diff", "--name-only", base).split())
    paths |= set(git("diff", "--name-only", "--cached").split())
    paths |= set(git("ls-files", "--others", "--exclude-standard").split())
    return paths


def suites(paths, everything, browser=False):
    frontend = everything or any(p.startswith("frontend/") for p in paths)
    ci = everything or any(p.startswith((".github/", "infra/", "docs/")) for p in paths)
    backend = everything or any(
        not p.startswith(("frontend/", "docs/")) and not p.endswith(".md")
        for p in paths
    )
    steps = [
        SYNC,
        ["uv", "run", "--project", "backend", "pre-commit", "run", "--all-files"],
    ]
    steps += BACKEND if backend else []
    steps += FRONTEND if frontend or browser else []
    steps += [["bash", "-c", BROWSER]] if browser else []
    steps += CI if ci else []
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="run every fast suite")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="also run the route-mocked browser journeys (needs Docker)",
    )
    args = parser.parse_args()
    paths = changed()
    if not paths and not (args.all or args.browser):
        print("Nothing changed since origin/main.")
        return 0
    for step in suites(paths, args.all, args.browser):
        print("+", " ".join(step), flush=True)
        env_dir = {"cwd": "infra/tests"} if "unittest" in step else {}
        if subprocess.run(step, check=False, **env_dir).returncode:
            print("Fix this before pushing; CI would fail on it too.")
            return 1
    print("Fast checks passed. The heavy suites run on main after merging.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
