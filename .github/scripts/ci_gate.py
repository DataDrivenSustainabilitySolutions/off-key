"""Pass only if every planned job succeeded and every other job was skipped.

Reads the `needs` context and the plan the changes job wrote. A job missing
from either side, an unreadable plan, a failed or cancelled planner, or any
result other than the planned one fails the gate. A skip is accepted only for a
job the plan did not select.
"""

import json
import os
import sys

PLANNER = "changes"


def problems(needs, plan_json):
    planner = needs.get(PLANNER, {}).get("result")
    if planner != "success":
        return [f"{PLANNER} {planner}, expected success"]
    try:
        plan = json.loads(plan_json)
    except (TypeError, ValueError):
        return ["the CI plan is unreadable"]
    if not isinstance(plan, dict) or not all(
        isinstance(job, str) and isinstance(run, bool) for job, run in plan.items()
    ):
        return ["the CI plan is malformed"]
    jobs = set(needs) - {PLANNER}
    errors = [f"{job} is not in the CI plan" for job in sorted(jobs - set(plan))]
    errors += [f"{job} is planned but not gated" for job in sorted(set(plan) - jobs)]
    for job in sorted(jobs & set(plan)):
        expected = "success" if plan[job] else "skipped"
        result = needs[job].get("result")
        if result != expected:
            errors.append(f"{job} {result}, expected {expected}")
    return errors


def main():
    errors = problems(json.loads(os.environ["NEEDS"]), os.environ.get("PLAN"))
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print("Every planned job succeeded; every other job was planned out")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
