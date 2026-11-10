"""Phase 2b analysis as pre-registered in PLAN.md: stage 1 alone, then stages 1 and 2 pooled.

Usage, from projects/done-claims:
  uv run python -m doneclaims.phase2b STAGE1_TRIALS [STAGE2_TRIALS] [--out results/phase2b/analysis.json]
Each TRIALS file is a trials.csv written by doneclaims.harbor. Only completed trials count.

Primary (H1): over the issues with at least one completed unverified stage-1 attempt, the Mantel-Haenszel
odds ratio of resolution for unverified against ran_passing, strata = issue, stage-1 and stage-2 trials
pooled. H1 is supported only if the upper end of the 95% interval is below 1.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

from .data import RESULTS
from .study import STRATA, by, comparisons, rate

INT_FIELDS = ("n_steps", "n_product_files", "runs_after_edit", "tests_after_edit", "remote_fetches")
WITHIN_ISSUE = {"within_instance": STRATA["within_instance"]}
UNVERIFIED_SHARE_GATE = 0.08


def load(path: Path, stage: int) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [r for r in csv.DictReader(handle) if r["status"] == "completed"]
    for r in rows:
        r["stage"] = stage
        r["target"] = r["target"] == "True"
        r["claims_success"] = r["claims_success"] == "True"
        for field in INT_FIELDS:
            r[field] = int(r[field] or 0)
    return rows


def unverified_share(rows: list[dict]) -> float:
    changed = [r for r in rows if r["category"] != "no_product_change"]
    return sum(r["category"] == "unverified" for r in changed) / len(changed) if changed else 0.0


def stage2_issues(stage1: list[dict]) -> list[str]:
    return sorted({r["instance_id"] for r in stage1 if r["category"] == "unverified"})


def describe(rows: list[dict]) -> dict:
    changed = [r for r in rows if r["category"] != "no_product_change"]
    passing = [r for r in rows if r["category"] == "ran_passing"]
    return {
        "trials": len(rows),
        "issues": len({r["instance_id"] for r in rows}),
        "all": rate(rows),
        "by_category": {k: rate(v) for k, v in by(rows, "category").items()},
        "ran_passing_by_evidence": {
            "with_test_run": rate([r for r in passing if r["tests_after_edit"]]),
            "script_only": rate([r for r in passing if not r["tests_after_edit"]]),
            "last_outcome_pass": rate([r for r in passing if r["last_outcome"] == "pass"]),
            "no_failure_signal": rate([r for r in passing if r["last_outcome"] == "unknown"]),
        },
        "unverified_share_of_changed": unverified_share(rows),
        "odds_ratios": comparisons(changed, WITHIN_ISSUE)["within_instance"],
        "odds_ratios_without_remote_fetch": comparisons(
            [r for r in changed if not r["remote_fetches"]], WITHIN_ISSUE
        )["within_instance"],
    }


def analyse(stage1: list[dict], stage2: list[dict] | None) -> dict:
    share = unverified_share(stage1)
    issues = stage2_issues(stage1)
    report = {
        "stage1": describe(stage1),
        "gate": {
            "unverified_share": share,
            "threshold": UNVERIFIED_SHARE_GATE,
            "stage2_runs": share >= UNVERIFIED_SHARE_GATE,
            "stage2_issues": len(issues),
        },
    }
    if stage2 is not None:
        chosen = set(issues)
        pooled = [r for r in stage1 + stage2 if r["instance_id"] in chosen]
        stray = sorted({r["instance_id"] for r in stage2} - chosen)
        primary = describe(pooled)
        h1 = primary["odds_ratios"][0]
        report["pooled"] = primary
        report["stage2_trials"] = dict(Counter(r["category"] for r in stage2))
        report["stage2_issues_outside_set"] = stray
        report["h1"] = {
            "odds_ratio": h1["odds_ratio"],
            "ci95": h1["ci95"],
            "informative_issues": h1["informative_strata"],
            "supported": h1["odds_ratio"] is not None and h1["ci95"][1] < 1,
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2b analysis")
    parser.add_argument("stage1", type=Path)
    parser.add_argument("stage2", type=Path, nargs="?")
    parser.add_argument("--out", type=Path, default=RESULTS / "phase2b" / "analysis.json")
    args = parser.parse_args()

    stage1 = load(args.stage1, 1)
    stage2 = load(args.stage2, 2) if args.stage2 else None
    report = analyse(stage1, stage2)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    gate = report["gate"]
    verdict = "runs" if gate["stage2_runs"] else "does not run"
    print(f"stage 1: {report['stage1']['trials']} completed trials")
    share, chosen = gate["unverified_share"], gate["stage2_issues"]
    print(f"unverified share {share:.3f}; stage 2 {verdict} on {chosen} issues")
    for item in report["stage1"]["odds_ratios"]:
        ci, strata = item["ci95"], item["informative_strata"]
        print(f"stage 1, {item['comparison']}: {item['odds_ratio']} {ci} ({strata} issues)")
    if "h1" in report:
        h1 = report["h1"]
        print(f"H1, stages pooled: OR {h1['odds_ratio']} {h1['ci95']} ({h1['informative_issues']} issues)")
        print(f"H1 supported: {h1['supported']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
