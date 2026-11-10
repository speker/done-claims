"""Numbers for the phase 2b smoke gates (PLAN.md), from a classified Harbor job.

Usage, from projects/done-claims:
  uv run python phase2/smoke_gates.py JOB_DIR TRIALS_CSV
Each ran_failing trial's last failing run is tagged as an environment error or a test failure from its
output; the tags are a starting point for reading the trials by hand, which decides the gate.
"""

import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from doneclaims import rules  # noqa: E402
from doneclaims.atif import assess_atif, repository_roots, to_event, tool_calls  # noqa: E402

ENVIRONMENT = re.compile(
    r"No module named|command not found|can't open file|Django module not found|No such file or directory"
    r"|cannot import name .* from partially initialized module"
)


def last_run_after_edit(document: dict) -> tuple[rules.Outcome | None, str]:
    result = assess_atif(document)
    roots = repository_roots(document)
    last = (None, "")
    for call in tool_calls(document):
        event = to_event(call, roots)
        if (
            event.outcome is not None
            and result.last_product_edit is not None
            and call.index >= result.last_product_edit
        ):
            last = (event.outcome, call.output)
    return last


def main() -> int:
    job, trials = Path(sys.argv[1]), Path(sys.argv[2])
    rows = list(csv.DictReader(trials.open(encoding="utf-8", newline="")))
    statuses = [r["status"] for r in rows]
    print(f"trials: {len(rows)}; setup timeouts: {statuses.count('exception:AgentSetupTimeoutError')}")
    print("statuses:", {s: statuses.count(s) for s in sorted(set(statuses))})

    base = testbed = 0
    for r in rows:
        path = job / r["trial"] / "agent" / "trajectory.json"
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            base += text.count("/opt/miniconda3/lib/python3.11")
            testbed += text.count("/opt/miniconda3/envs/testbed")
    print(f"mentions in transcripts: base python 3.11 {base}, task environment {testbed}")

    done = [r for r in rows if r["status"] == "completed"]
    print(
        "categories:",
        {c: sum(r["category"] == c for r in done) for c in sorted({r["category"] for r in done})},
    )
    failing = [r for r in done if r["category"] == "ran_failing"]
    environment = 0
    for r in failing:
        document = json.loads((job / r["trial"] / "agent" / "trajectory.json").read_text(encoding="utf-8"))
        _, output = last_run_after_edit(document)
        tag = "environment" if ENVIRONMENT.search(output) else "test"
        environment += tag == "environment"
        tail = " | ".join(line.strip() for line in output.strip().splitlines()[-2:])[:160]
        print(f"  ran_failing {r['trial']}: {tag} :: {tail}")
    if failing:
        share = (len(failing) - environment) / len(failing)
        print(f"ran_failing: {len(failing)}; tagged test failure {len(failing) - environment} ({share:.0%})")
    tested = [r for r in done if r["category"] == "ran_passing" and int(r["tests_after_edit"] or 0) > 0]
    explicit = sum(r["last_outcome"] == "pass" for r in tested)
    print(f"ran_passing with a test run: {len(tested)}; explicit pass: {explicit}")
    changed = [r for r in done if r["category"] != "no_product_change"]
    if changed:
        share = sum(r["category"] == "unverified" for r in changed) / len(changed)
        print(f"unverified share of changed trials: {share:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
