"""Phases 1 and 2a again with `test` and `testing` subpackages of the main package counted as product code.

    uv run python pkgtest_sensitivity.py [--rule changed|frozen] [--workers N] [--out FILE]
    (from projects/done-claims)

The rule is patched in this process and its workers only; the committed results are not touched. Phase 1
needs the twelve source shards (python -m doneclaims.fetch). Phase 2a needs the finished Harbor job, whose
transcripts are not published, and is skipped when it is not in the local cache. For each phase it reports
how many rows change category against the committed results and the within-issue odds ratio of unverified
against ran_passing. `--rule frozen` keeps the committed rule and should reproduce the committed results.
"""

import argparse
import csv
import gzip
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from doneclaims import harbor, rules, study
from doneclaims.data import CACHE, RESULTS, SHARD_COUNT

PKG_TEST = re.compile(r"^(?:(?:lib|src)/)?[A-Za-z_]\w*/(?:test|testing)/")
FROZEN = rules.file_role
PHASE2A_JOB = CACHE / "phase2" / "full-gptoss-instr"
PHASE2A_RESULTS = RESULTS / "phase2" / "full-gptoss-instr" / "trials.csv"
COMPARISON = "unverified vs ran_passing"
RULE_ENV = "DONECLAIMS_PKGTEST_RULE"


def changed_role(path: str) -> str:
    return "product" if PKG_TEST.match(path.replace("\\", "/")) else FROZEN(path)


def apply_rule(rule: str) -> None:
    rules.file_role = changed_role if rule == "changed" else FROZEN


apply_rule(os.environ.get(RULE_ENV, "changed"))


def classify_shard(index: int) -> list[dict]:
    return study.process_shard(index)


def within_issue(section: dict) -> dict:
    items = section["stratified_odds_ratios"]["within_instance"]
    return next(item for item in items if item["comparison"] == COMPARISON)


def moved(frozen: dict, rows: list[dict], key: Callable[[dict], object]) -> dict[str, int]:
    counts = Counter((frozen[key(r)], r["category"]) for r in rows if frozen[key(r)] != r["category"])
    return {f"{before} -> {after}": n for (before, after), n in sorted(counts.items())}


def phase1(workers: int) -> dict:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        rows = [row for shard in pool.map(classify_shard, range(SHARD_COUNT)) for row in shard]
    with gzip.open(RESULTS / "features.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        frozen = {(int(r["shard"]), int(r["row"])): r["category"] for r in csv.DictReader(handle)}
    submitted = [r for r in rows if r["exit_status"] == study.SUBMITTED]
    return {
        "submitted": len(submitted),
        "moved": moved(frozen, submitted, lambda r: (r["shard"], r["row"])),
        "within_issue": within_issue(study.summarise(rows, {})["submitted"]),
    }


def phase2a() -> dict:
    rows = harbor.read_job(PHASE2A_JOB)
    with PHASE2A_RESULTS.open(encoding="utf-8", newline="") as handle:
        frozen = {r["trial"]: r["category"] for r in csv.DictReader(handle)}
    completed = [r for r in rows if r["status"] == harbor.COMPLETED]
    return {
        "completed": len(completed),
        "moved": moved(frozen, completed, lambda r: r["trial"]),
        "within_issue": within_issue(harbor.summarise(rows, {})["completed"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rule", choices=("changed", "frozen"), default="changed")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    os.environ[RULE_ENV] = args.rule
    apply_rule(args.rule)
    result = {
        "rule": args.rule,
        "pattern": PKG_TEST.pattern,
        "code_sha256": study.code_digest(),
        "phase1": phase1(args.workers),
    }
    if PHASE2A_JOB.is_dir():
        result["phase2a"] = phase2a()
    else:
        print(f"phase2a: skipped, no Harbor job at {PHASE2A_JOB}")
    for phase in ("phase1", "phase2a"):
        if phase not in result:
            continue
        r = result[phase]
        low, high = r["within_issue"]["ci95"]
        print(
            f"{phase}: {sum(r['moved'].values())} rows change category {r['moved']}; "
            f"{COMPARISON} within issue {r['within_issue']['odds_ratio']:.3f} [{low:.3f}, {high:.3f}], "
            f"strata {r['within_issue']['informative_strata']}"
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
