"""Run the fast CI checks a branch needs before it is pushed.

Pull-request CI runs only the fast suites, and every push of every pull request
spends CI minutes, so a push should already pass them. This picks the suites
from the paths changed since the branch left origin/main (committed, staged and
unstaged) and runs them in CI's order. `--all` runs every fast suite.

    make check            # what this branch touched
    make check ARGS=--all # every fast suite
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


def suites(paths, everything):
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
    steps += FRONTEND if frontend else []
    steps += CI if ci else []
    return steps


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="run every fast suite")
    args = parser.parse_args()
    paths = changed()
    if not paths and not args.all:
        print("Nothing changed since origin/main.")
        return 0
    for step in suites(paths, args.all):
        print("+", " ".join(step), flush=True)
        env_dir = {"cwd": "infra/tests"} if "unittest" in step else {}
        if subprocess.run(step, check=False, **env_dir).returncode:
            print("Fix this before pushing; CI would fail on it too.")
            return 1
    print("Fast checks passed. The merge queue runs the heavy suites.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
