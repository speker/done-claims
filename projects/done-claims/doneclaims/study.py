"""Classify every trajectory and compare resolution rates across evidence categories.

Usage, from projects/done-claims: uv run python -m doneclaims.study [--workers N]
Writes results/features.csv.gz (one row per trajectory, no trajectory text) and results/summary.json.
"""

import argparse
import csv
import gzip
import hashlib
import json
import platform
import subprocess
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime

import pyarrow
import pyarrow.parquet as pq

from . import __version__
from .data import COLUMNS, PROJECT, REPO, RESULTS, REVISION, SHARD_COUNT, shard_path
from .evidence import Category, assess
from .stats import Table, mantel_haenszel, wilson

FIELDS = [
    "shard",
    "row",
    "instance_id",
    "model_name",
    "target",
    "exit_status",
    "category",
    "n_steps",
    "n_product_files",
    "touched_tests",
    "last_product_edit",
    "runs_after_edit",
    "tests_after_edit",
    "last_outcome",
    "claims_success",
]
SUBMITTED = "submitted"
REFERENCE = Category.RAN_PASSING


def process_shard(index: int) -> list[dict]:
    rows = []
    position = 0
    for batch in pq.ParquetFile(shard_path(index)).iter_batches(batch_size=128, columns=COLUMNS):
        for record in batch.to_pylist():
            result = assess(record["trajectory"], record["generated_patch"])
            rows.append(
                {
                    "shard": index,
                    "row": position,
                    "instance_id": record["instance_id"],
                    "model_name": record["model_name"],
                    "target": bool(record["target"]),
                    "exit_status": record["exit_status"],
                    "category": result.category.value,
                    "n_steps": result.n_steps,
                    "n_product_files": len(result.product_files),
                    "touched_tests": result.touched_tests,
                    "last_product_edit": "" if result.last_product_edit is None else result.last_product_edit,
                    "runs_after_edit": result.runs_after_edit,
                    "tests_after_edit": result.tests_after_edit,
                    "last_outcome": result.last_outcome.value if result.last_outcome else "",
                    "claims_success": result.claims_success,
                }
            )
            position += 1
    return rows


def rate(rows: list[dict]) -> dict:
    n = len(rows)
    resolved = sum(r["target"] for r in rows)
    if n == 0:
        return {"n": 0, "resolved": 0}
    low, high = wilson(resolved, n)
    return {"n": n, "resolved": resolved, "rate": resolved / n, "ci95": [low, high]}


Predicate = Callable[[dict], bool]


def stratified(
    rows: list[dict], label: str, exposed: Predicate, reference: Predicate, key: Callable[[dict], object]
) -> dict:
    cells: dict[object, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        if exposed(r):
            cells[key(r)][0 if r["target"] else 1] += 1
        elif reference(r):
            cells[key(r)][2 if r["target"] else 3] += 1
    try:
        result = mantel_haenszel(Table(*c) for c in cells.values())
    except ValueError as error:
        return {
            "comparison": label,
            "odds_ratio": None,
            "ci95": None,
            "informative_strata": 0,
            "note": str(error),
        }
    return {
        "comparison": label,
        "odds_ratio": result.estimate,
        "ci95": [result.low, result.high],
        "informative_strata": result.informative_strata,
    }


def in_category(category: Category) -> Predicate:
    return lambda r: r["category"] == category


def instance(r: dict) -> object:
    return r["instance_id"]


def instance_and_model(r: dict) -> object:
    return r["instance_id"], r["model_name"]


STRATA = {"within_instance": instance, "within_instance_and_model": instance_and_model}


def comparisons(changed: list[dict], strata: dict[str, Callable[[dict], object]] = STRATA) -> dict:
    passing = in_category(REFERENCE)
    unverified = in_category(Category.UNVERIFIED)
    specs = [
        ("unverified vs ran_passing", unverified, passing),
        ("ran_failing vs ran_passing", in_category(Category.RAN_FAILING), passing),
        (
            "unverified with success claim vs unverified without",
            lambda r: unverified(r) and r["claims_success"],
            lambda r: unverified(r) and not r["claims_success"],
        ),
        (
            "ran_passing with test run vs ran_passing script only",
            lambda r: passing(r) and bool(r["tests_after_edit"]),
            lambda r: passing(r) and not r["tests_after_edit"],
        ),
    ]
    return {
        name: [stratified(changed, label, exposed, reference, key) for label, exposed, reference in specs]
        for name, key in strata.items()
    }


def by(rows: Iterable[dict], field: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[str(r[field])].append(r)
    return dict(sorted(groups.items()))


def code_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted((PROJECT / "doneclaims").glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def git_state() -> dict:
    def run(*args: str) -> str:
        done = subprocess.run(["git", *args], cwd=PROJECT, capture_output=True, text=True, timeout=30)
        return done.stdout.strip()

    return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain", "--", "."))}


def summarise(rows: list[dict], meta: dict) -> dict:
    submitted = [r for r in rows if r["exit_status"] == SUBMITTED]
    changed = [r for r in submitted if r["category"] != Category.NO_PRODUCT_CHANGE]
    return {
        "meta": meta,
        "exit_status_counts": dict(Counter(r["exit_status"] for r in rows).most_common()),
        "submitted": {
            "all": rate(submitted),
            "by_category": {k: rate(v) for k, v in by(submitted, "category").items()},
            "by_model_and_category": {
                m: {k: rate(v) for k, v in by(group, "category").items()}
                for m, group in by(submitted, "model_name").items()
            },
            "ran_passing_by_evidence": {
                "with_test_run": rate(
                    [r for r in submitted if r["category"] == REFERENCE and r["tests_after_edit"]]
                ),
                "script_only": rate(
                    [r for r in submitted if r["category"] == REFERENCE and not r["tests_after_edit"]]
                ),
                "last_outcome_pass": rate(
                    [r for r in submitted if r["category"] == REFERENCE and r["last_outcome"] == "pass"]
                ),
                "last_outcome_unknown": rate(
                    [r for r in submitted if r["category"] == REFERENCE and r["last_outcome"] == "unknown"]
                ),
            },
            "claims_success_by_category": {
                k: {
                    "claims": rate([r for r in v if r["claims_success"]]),
                    "no_claim": rate([r for r in v if not r["claims_success"]]),
                }
                for k, v in by(changed, "category").items()
            },
            "stratified_odds_ratios": comparisons(changed),
        },
    }


def write_features(rows: list[dict]) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    with gzip.open(RESULTS / "features.csv.gz", "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def report(summary: dict) -> None:
    sub = summary["submitted"]
    print(f"submitted trajectories: {sub['all']['n']}, resolved {sub['all']['resolved']}")
    print(f"{'category':<20}{'n':>8}{'resolved':>10}{'rate':>8}  95% CI")
    for name, r in sub["by_category"].items():
        low, high = r["ci95"]
        print(f"{name:<20}{r['n']:>8}{r['resolved']:>10}{r['rate']:>8.3f}  [{low:.3f}, {high:.3f}]")
    for stratum, items in sub["stratified_odds_ratios"].items():
        for item in items:
            low, high = item["ci95"]
            print(
                f"OR {item['comparison']} ({stratum}): {item['odds_ratio']:.3f} "
                f"[{low:.3f}, {high:.3f}], strata {item['informative_strata']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the completion-evidence study")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--shards", type=int, default=SHARD_COUNT)
    args = parser.parse_args()
    missing = [str(shard_path(i)) for i in range(args.shards) if not shard_path(i).exists()]
    if missing:
        print("missing shards; run python -m doneclaims.fetch first:\n" + "\n".join(missing), file=sys.stderr)
        return 2

    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = [row for shard in pool.map(process_shard, range(args.shards)) for row in shard]
    meta = {
        "dataset": REPO,
        "revision": REVISION,
        "shards": args.shards,
        "trajectories": len(rows),
        "doneclaims": __version__,
        "code_sha256": code_digest(),
        "python": platform.python_version(),
        "pyarrow": pyarrow.__version__,
        "git": git_state(),
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - started, 1),
    }
    summary = summarise(rows, meta)
    write_features(rows)
    (RESULTS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    report(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
