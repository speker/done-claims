"""Draw a seeded audit sample and render compact trajectory views for checking by hand.

Usage, from projects/done-claims:
  uv run python -m doneclaims.audit [--per-category 10] [--seed 20261105] [--out results/audit.csv]
  uv run python -m doneclaims.audit --recheck results/audit_pass1.csv --out results/audit_recheck.csv
Views contain dataset text, so they go to data/cache/done-claims/audit/ and stay out of git.
The output CSV lists the sample; its verdict and note columns are filled in by the reviewer.
--recheck re-renders an earlier sample with the current rules and keeps its previous category.
"""

import argparse
import csv
import gzip
import random
import sys
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from . import rules
from .data import CACHE, COLUMNS, PROJECT, RESULTS, shard_path
from .evidence import assess, closing_text
from .trajectory import parse

CATEGORIES = ("unverified", "ran_failing", "ran_passing", "undetermined")
AUDIT_FIELDS = [
    "sample_id",
    "category",
    "previous_category",
    "shard",
    "row",
    "instance_id",
    "model_name",
    "target",
    "verdict",
    "note",
]


def tail(observation: str, lines: int = 3) -> str:
    body = observation.split("\n(Open file:")[0]
    kept = [line.strip() for line in body.splitlines() if line.strip()]
    return " | ".join(kept[-lines:])[:300]


def render(sample_id: str, row: dict, record: dict) -> str:
    steps = parse(record["trajectory"])
    result = assess(record["trajectory"], record["generated_patch"])
    previous = f" (was {row['previous_category']})" if row.get("previous_category") else ""
    lines = [
        f"## {sample_id} {result.category.value}{previous} target={row['target']} "
        f"{row['instance_id']} ({row['model_name']})",
        f"patch files: {rules.patch_files(record['generated_patch'])}",
        f"product files: {list(result.product_files)}",
        f"last product edit: {result.last_product_edit}; runs after it: {result.runs_after_edit}; "
        f"last outcome: {result.last_outcome}",
        "",
    ]
    for step in steps:
        action = rules.classify(step.command, step.open_file)
        first = (step.command or "<no command>").splitlines()[0][:100]
        detail = ""
        if action.writes:
            detail += f" writes={list(action.writes)} applied={rules.write_applied(action, step.observation)}"
        if action.kind in rules.RUN_KINDS:
            detail += (
                f" outcome={rules.outcome(action.kind, step.observation).value} :: {tail(step.observation)}"
            )
        mark = "  <== last product edit" if step.index == result.last_product_edit else ""
        lines.append(f"- [{step.index}] {action.kind.value}: `{first}`{detail}{mark}")
    lines.append(f"\nclosing: {closing_text(steps)[:400]}\n")
    return "\n".join(lines)


def draw(per_category: int, seed: int) -> list[dict]:
    with gzip.open(RESULTS / "features.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if r["exit_status"] == "submitted"]
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["category"] in CATEGORIES:
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


def load(sample: list[dict]) -> dict[tuple[int, int], dict]:
    wanted: dict[int, set[int]] = defaultdict(set)
    for r in sample:
        wanted[int(r["shard"])].add(int(r["row"]))
    records: dict[tuple[int, int], dict] = {}
    for shard, positions in wanted.items():
        position = 0
        for batch in pq.ParquetFile(shard_path(shard)).iter_batches(batch_size=128, columns=COLUMNS):
            for record in batch.to_pylist():
                if position in positions:
                    records[(shard, position)] = record
                position += 1
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Draw and render the audit sample")
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument("--recheck", type=Path, help="re-render the sample listed in an earlier audit CSV")
    parser.add_argument("--out", type=Path, default=Path("results/audit.csv"))
    parser.add_argument("--force", action="store_true", help="overwrite an existing output CSV")
    args = parser.parse_args()

    target = args.out if args.out.is_absolute() else PROJECT / args.out
    if target.exists() and not args.force:
        print(f"{target} exists and may hold verdicts; pass --force to overwrite", file=sys.stderr)
        return 2
    recheck = args.recheck if args.recheck is None or args.recheck.is_absolute() else PROJECT / args.recheck
    sample = earlier_sample(recheck) if recheck else draw(args.per_category, args.seed)
    records = load(sample)
    for r in sample:
        record = records[(int(r["shard"]), int(r["row"]))]
        r["category"] = assess(record["trajectory"], record["generated_patch"]).category.value

    views = CACHE / "audit" / f"{target.stem}_views.md"
    views.parent.mkdir(parents=True, exist_ok=True)
    views.write_text(
        "\n".join(render(r["sample_id"], r, records[(int(r["shard"]), int(r["row"]))]) for r in sample),
        encoding="utf-8",
    )
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({**r, "verdict": "", "note": ""} for r in sample)
    print(f"{len(sample)} samples -> {target}; views in {views}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
