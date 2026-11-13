"""Plan the CI jobs a change needs; anything uncertain runs every job.

Only explicitly classified changes run less than everything:

- docs: root-level Markdown that no image, service or deployment reads.
- landing, published-docs, static: landing content, published documentation,
  or both. Focused checks run; main releases reuse verified application images.
- frontend: frontend sources other than its Dockerfile and dependency
  manifests. The frontend image, both deployment rehearsals and the tests that
  read frontend sources still run; backend, broker, RADAR and infrastructure
  suites, whose inputs did not change, do not.

Every other path, an unreadable diff, an empty diff, an unknown event or any
error selects the full plan.

Pull requests run only the fast suites of their plan. The heavy suites (image
builds, Swarm rehearsals, RADAR, collection, infrastructure, observability)
run on the main push after merging, which deployment requires to pass. A pull request labelled `full-ci` runs its whole plan; the
label is read when the run starts, so re-running CI after adding it is enough.
If the labels cannot be read, the pull request runs its whole plan. Manual runs are always full. A main push compares
against the newest ancestor whose main CI run kept full release evidence, so a
superseded or cancelled run can never hide an untested change.
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path, PurePosixPath

WORKFLOW = "ci.yml"
EVIDENCE = "production-release"
# Every job in ci.yml except changes and ci-gate.
JOBS = (
    "lint",
    "backend",
    "frontend",
    "frontend-browser",
    "contracts",
    "infrastructure",
    "collection",
    "radar",
    "images",
    "publish",
    "deployment-smoke",
    "observability",
    "static",
    "static-release",
)
# The backend and infrastructure suites already include the contract tests;
# "images" stands for this event's image job (see plan_for).
FULL = set(JOBS) - {"contracts", "publish", "static", "static-release"}
SELECTED = {
    "full": FULL,
    "frontend": {
        "lint",
        "frontend",
        "frontend-browser",
        "contracts",
        "images",
        "deployment-smoke",
    },
    "docs": {"static"},
    "landing": {"static", "static-release"},
    "published-docs": {"static", "static-release"},
    "static": {"static", "static-release"},
}
# Suites a pull request leaves to the main push unless it carries FULL_CI_LABEL.
HEAVY = {
    "infrastructure",
    "collection",
    "radar",
    "images",
    "deployment-smoke",
    "observability",
}
FULL_CI_LABEL = "full-ci"
STATIC_RELEASE_MODES = {"landing", "published-docs", "static"}
LANDING_PATHS = {
    "assets/landing/export.py",
    "infra/stack/landing.html.j2",
    "infra/stack/landing.md.j2",
    "infra/stack/landing-llms.txt.j2",
    "infra/stack/landing-assets.json",
}
# Frontend files that change the image or its dependencies select everything.
FRONTEND_BROAD = {
    "frontend/Dockerfile",
    "frontend/.dockerignore",
    "frontend/.npmrc",
    "frontend/package.json",
    "frontend/package-lock.json",
}


def classify(path):
    """Classify a changed path, including both sides of renames."""
    if not path or path.startswith("/") or ".." in PurePosixPath(path).parts:
        return "full"
    if path in LANDING_PATHS or (
        path.startswith("assets/landing/")
        and PurePosixPath(path).suffix in {".jpg", ".jpeg", ".png", ".webp", ".txt"}
    ):
        return "landing"
    if path.startswith("docs/") or path == "zensical.toml":
        return "published-docs"
    # Other build programs, dependencies and shared assets remain full changes.
    if "/" not in path and path.endswith(".md"):
        return "docs"
    if path.startswith("frontend/") and path not in FRONTEND_BROAD:
        return "frontend"
    return "full"


def mode_for(paths):
    if not paths:
        return "full"
    kinds = {classify(path) for path in paths}
    if "full" in kinds:
        return "full"
    kinds.discard("docs")
    if not kinds:
        return "docs"
    if "frontend" in kinds:
        return "frontend" if kinds == {"frontend"} else "full"
    return next(iter(kinds)) if len(kinds) == 1 else "static"


def plan_for(mode, event):
    selected = set(SELECTED[mode]) - {"publish"}
    if event != "push":
        selected.discard("static-release")
    if "images" in selected:
        # A main push publishes the images it rehearses; other events only build them.
        selected.discard("images")
        selected.add("publish" if event == "push" else "images")
    return {job: job in selected for job in JOBS}


def git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True, timeout=120
    ).stdout


def is_ancestor(ancestor, descendant):
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        check=False,
        timeout=120,
    )
    return result.returncode == 0


def changed_paths(base, head):
    # Without rename detection a rename lists both its old and new path.
    output = git("diff", "--name-only", "--no-renames", "-z", base, head, "--")
    return [path for path in output.split("\0") if path]


def github(path):
    request = urllib.request.Request(
        f"{os.environ['GITHUB_API_URL']}/repos/{os.environ['GITHUB_REPOSITORY']}/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def evidenced_base(head, repository, api=None, ancestor=None):
    """The newest main ancestor whose successful CI run kept release evidence."""
    api, ancestor = api or github, ancestor or is_ancestor
    runs = api(
        f"actions/workflows/{WORKFLOW}/runs?branch=main&event=push&status=success&per_page=50"
    )["workflow_runs"]
    for run in sorted(runs, key=lambda run: run["id"], reverse=True):
        sha = run["head_sha"]
        if (
            sha == head
            or run.get("event") != "push"
            or run.get("head_branch") != "main"
            or run.get("conclusion") != "success"
            or (run.get("head_repository") or {}).get("full_name") != repository
            or not ancestor(sha, head)
        ):
            continue
        artifacts = api(f"actions/runs/{run['id']}/artifacts?name={EVIDENCE}")
        if any(
            item["name"] == EVIDENCE and not item["expired"]
            for item in artifacts["artifacts"]
        ):
            return sha
    return None


def comparison(event_name, event, head, repository, api=None, ancestor=None):
    """The base whose diff to head covers every untested change, or None."""
    ancestor = ancestor or is_ancestor
    if event_name == "pull_request":
        # The merge ref's first parent is the base branch it was merged onto.
        parents = git("rev-list", "--parents", "-n", "1", head).split()
        if len(parents) != 3 or parents[2] != event["pull_request"]["head"]["sha"]:
            return None
        return parents[1]
    if event_name == "merge_group":
        group = event["merge_group"]
        if group["head_sha"] != head or not ancestor(group["base_sha"], head):
            return None
        return group["base_sha"]
    if event_name == "push" and event.get("ref") == "refs/heads/main":
        return evidenced_base(head, repository, api, ancestor)
    return None


def wants_full_ci(event, api=None):
    """Whether a pull request carries the full-ci label right now."""
    api = api or github
    try:
        number = event["pull_request"]["number"]
        labels = api(f"issues/{number}/labels?per_page=100")
        return any(label.get("name") == FULL_CI_LABEL for label in labels)
    except Exception:  # noqa: BLE001 - unreadable labels run the whole plan
        return True


def defer_heavy(event_name, event, mode, jobs, reason, api=None):
    """Leave a pull request's heavy suites to the main push."""
    if event_name != "pull_request" or not any(jobs[job] for job in HEAVY):
        return mode, jobs, reason
    if wants_full_ci(event, api):
        return mode, jobs, f"{reason}; {FULL_CI_LABEL} label runs the whole plan"
    jobs = {job: run and job not in HEAVY for job, run in jobs.items()}
    return mode, jobs, f"{reason}; heavy suites run on the main push"


def plan(event_name, event, head, repository, api=None, ancestor=None):
    return defer_heavy(
        event_name,
        event,
        *plan_without_deferral(event_name, event, head, repository, api, ancestor),
        api=api,
    )


def plan_without_deferral(event_name, event, head, repository, api=None, ancestor=None):
    try:
        base = comparison(event_name, event, head, repository, api, ancestor)
        if base is None:
            return "full", plan_for("full", event_name), "no trusted comparison base"
        paths = changed_paths(base, head)
        mode = mode_for(paths)
        return mode, plan_for(mode, event_name), f"{len(paths)} paths since {base}"
    except Exception as error:  # noqa: BLE001 - any failure must select everything
        return "full", plan_for("full", event_name), f"classification failed: {error}"


def main():
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    head = git("rev-parse", "HEAD").strip()
    if head != os.environ["GITHUB_SHA"]:
        mode, jobs, reason = defer_heavy(
            event_name,
            event,
            "full",
            plan_for("full", event_name),
            "unexpected checkout",
        )
    else:
        mode, jobs, reason = plan(
            event_name, event, head, os.environ["GITHUB_REPOSITORY"]
        )
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
        output.write(f"mode={mode}\nplan={json.dumps(jobs, sort_keys=True)}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    lines = [f"CI plan: **{mode}** ({reason})", ""]
    lines += [f"- {job}: {'run' if run else 'not needed'}" for job, run in jobs.items()]
    if summary:
        with Path(summary).open("a") as output:
            output.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
