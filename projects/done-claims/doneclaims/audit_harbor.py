"""Draw a seeded audit sample from a classified Harbor job and render its transcripts for checking by hand.

Usage, from projects/done-claims:
  uv run python -m doneclaims.audit_harbor JOB_DIR TRIALS_CSV --out CSV [--per-category 10] [--seed 20261107]
TRIALS_CSV is the trials.csv that doneclaims.harbor wrote for JOB_DIR. Views quote agent transcripts, so
they go to data/cache/done-claims/audit/phase2/ and stay out of git. The reviewer fills in verdict and note.
"""

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from .atif import assess_atif, closing_message, repository_roots, to_event, tool_calls
from .data import CACHE, PROJECT

CATEGORIES = ("unverified", "ran_failing", "ran_passing", "no_product_change")
AUDIT_FIELDS = [
    "sample_id",
    "category",
    "previous_category",
    "trial",
    "instance_id",
    "reward",
    "verdict",
    "note",
]


def tail(output: str, lines: int = 3) -> str:
    kept = [
        line.strip() for line in output.splitlines() if line.strip() and not line.startswith("[metadata]")
    ]
    return " | ".join(kept[-lines:])[:300]


def describe(name: str, arguments: dict) -> str:
    if name == "Bash":
        text = str(arguments.get("command") or "<no command>")
    else:
        text = str(arguments.get("file_path") or arguments.get("notebook_path") or json.dumps(arguments))
    return text.splitlines()[0][:120] if text else ""


def render(sample_id: str, row: dict, document: dict) -> str:
    result = assess_atif(document)
    roots = repository_roots(document)
    previous = f" (was {row['previous_category']})" if row.get("previous_category") else ""
    lines = [
        f"## {sample_id} {result.category.value}{previous} reward={row['reward']} "
        f"{row['instance_id']} ({row['trial']})",
        f"product files: {list(result.product_files)}",
        f"last product edit: {result.last_product_edit}; runs after it: {result.runs_after_edit}; "
        f"tests after it: {result.tests_after_edit}; last outcome: {result.last_outcome}; "
        f"success claim: {result.claims_success}",
        "",
    ]
    for call in tool_calls(document):
        event = to_event(call, roots)
        detail = f" writes={list(event.action.writes)} applied={event.applied}" if event.action.writes else ""
        if event.outcome is not None:
            detail += f" outcome={event.outcome.value} :: {tail(call.output)}"
        elif call.failed:
            detail += f" error :: {tail(call.output, 1)}"
        mark = "  <== last product edit" if call.index == result.last_product_edit else ""
        lines.append(
            f"- [{call.index}] {event.action.kind.value} {call.name}: `{describe(call.name, call.arguments)}`"
            f"{detail}{mark}"
        )
    lines.append(f"\nclosing: {closing_message(document)[:500]}\n")
    return "\n".join(lines)


def draw(trials: Path, per_category: int, seed: int) -> list[dict]:
    with trials.open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if r["status"] == "completed"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["trial"]):
        groups[r["category"]].append(r)
    rng = random.Random(seed)
    sample = []
    for category in CATEGORIES:
        for i, r in enumerate(rng.sample(groups[category], min(per_category, len(groups[category])))):
            sample.append({**r, "sample_id": f"{category}-{i + 1:02d}", "previous_category": ""})
    return sample


def earlier_sample(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [{**r, "previous_category": r["category"]} for r in csv.DictReader(handle)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Draw and render an audit sample from a Harbor job")
    parser.add_argument("job", type=Path)
    parser.add_argument("trials", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261107)
    parser.add_argument("--recheck", type=Path, help="re-render the sample listed in an earlier audit CSV")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output CSV")
    args = parser.parse_args()

    target = args.out if args.out.is_absolute() else PROJECT / args.out
    if target.exists() and not args.force:
        print(f"{target} exists and may hold verdicts; pass --force to overwrite", file=sys.stderr)
        return 2
    recheck = args.recheck if args.recheck is None or args.recheck.is_absolute() else PROJECT / args.recheck
    sample = earlier_sample(recheck) if recheck else draw(args.trials, args.per_category, args.seed)
    views = CACHE / "audit" / "phase2" / f"{target.parent.name}_{target.stem}_views.md"
    views.parent.mkdir(parents=True, exist_ok=True)
    rendered = []
    for r in sample:
        document = json.loads(
            (args.job / r["trial"] / "agent" / "trajectory.json").read_text(encoding="utf-8")
        )
        r["category"] = assess_atif(document).category.value
        rendered.append(render(r["sample_id"], r, document))
    views.write_text("\n".join(rendered), encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({**r, "verdict": "", "note": ""} for r in sample)
    print(f"{len(sample)} samples -> {target}; views in {views}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
