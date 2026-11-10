"""Phase 2: classify every trial of a finished Harbor job with the phase 1 rules.

Usage, from projects/done-claims:
  uv run python -m doneclaims.harbor JOB_DIR [--out DIR]
JOB_DIR holds Harbor's config.json and one directory per trial (result.json, agent/trajectory.json).
Writes trials.csv (one row per trial, no transcript text) and summary.json to DIR,
by default results/phase2/<job name>.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .atif import assess_atif, remote_fetches
from .data import RESULTS
from .evidence import Category
from .study import REFERENCE, by, code_digest, comparisons, git_state, instance, rate

ASSESSED = [
    "category",
    "n_steps",
    "n_product_files",
    "touched_tests",
    "last_product_edit",
    "runs_after_edit",
    "tests_after_edit",
    "last_outcome",
    "claims_success",
    "remote_fetches",
]
FIELDS = [
    "trial",
    "instance_id",
    "model_name",
    "status",
    "reward",
    "target",
    *ASSESSED,
    "input_tokens",
    "output_tokens",
    "agent_seconds",
]
COMPLETED = "completed"
WITHIN_TASK = {"within_instance": instance}


def _seconds(timing: dict | None) -> float | None:
    if not timing or not timing.get("started_at") or not timing.get("finished_at"):
        return None
    start = datetime.fromisoformat(timing["started_at"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(timing["finished_at"].replace("Z", "+00:00"))
    return round((end - start).total_seconds(), 1)


def status(result: dict, has_trajectory: bool) -> str:
    """completed when the agent ended on its own and the verifier produced a reward."""
    if result.get("exception_info"):
        return "exception:" + (result["exception_info"].get("exception_type") or "unknown")
    if not has_trajectory:
        return "no_trajectory"
    if reward_of(result) is None:
        return "no_reward"
    return COMPLETED


def reward_of(result: dict) -> float | None:
    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    value = rewards.get("reward")
    return float(value) if isinstance(value, int | float) else None


def read_trial(path: Path) -> dict | None:
    result_path = path / "result.json"
    if not result_path.is_file():
        return None
    result = json.loads(result_path.read_text(encoding="utf-8"))
    trajectory_path = path / "agent" / "trajectory.json"
    document = json.loads(trajectory_path.read_text(encoding="utf-8")) if trajectory_path.is_file() else None
    task_id = result.get("task_id") or {}
    usage = result.get("agent_result") or {}
    reward = reward_of(result)
    row = {
        "trial": result.get("trial_name") or path.name,
        "instance_id": task_id.get("name") or str(result.get("task_name", "")).rsplit("/", 1)[-1],
        "model_name": ((result.get("agent_info") or {}).get("model_info") or {}).get("name", ""),
        "status": status(result, document is not None),
        "reward": "" if reward is None else reward,
        "target": reward is not None and reward >= 1.0,
        "input_tokens": usage.get("n_input_tokens") or 0,
        "output_tokens": usage.get("n_output_tokens") or 0,
        "agent_seconds": _seconds(result.get("agent_execution")),
    }
    if document is None:
        return {**row, **dict.fromkeys(ASSESSED, "")}
    assessed = assess_atif(document)
    return {
        **row,
        "category": assessed.category.value,
        "n_steps": assessed.n_steps,
        "n_product_files": len(assessed.product_files),
        "touched_tests": assessed.touched_tests,
        "last_product_edit": "" if assessed.last_product_edit is None else assessed.last_product_edit,
        "runs_after_edit": assessed.runs_after_edit,
        "tests_after_edit": assessed.tests_after_edit,
        "last_outcome": assessed.last_outcome.value if assessed.last_outcome else "",
        "claims_success": assessed.claims_success,
        "remote_fetches": remote_fetches(document),
    }


def read_job(job: Path) -> list[dict]:
    rows = [read_trial(p) for p in sorted(job.iterdir()) if p.is_dir()]
    return [r for r in rows if r is not None]


def job_meta(job: Path) -> dict:
    """Run settings from Harbor's job config, without endpoints or credentials."""
    config = json.loads((job / "config.json").read_text(encoding="utf-8"))
    agents = [
        {
            "name": a.get("name"),
            "model_name": a.get("model_name"),
            "api_format": a.get("model_api_format"),
            "kwargs": a.get("kwargs"),
            "env": a.get("env"),
        }
        for a in config.get("agents") or []
    ]
    datasets = [
        {k: d.get(k) for k in ("name", "ref", "task_names", "n_tasks")} for d in config.get("datasets") or []
    ]
    return {"job_name": config.get("job_name", job.name), "agents": agents, "datasets": datasets}


def summarise(rows: list[dict], meta: dict) -> dict:
    completed = [r for r in rows if r["status"] == COMPLETED]
    changed = [r for r in completed if r["category"] != Category.NO_PRODUCT_CHANGE]
    no_fetch = [r for r in changed if not r["remote_fetches"]]
    passing = [r for r in completed if r["category"] == REFERENCE]
    return {
        "meta": meta,
        "status_counts": dict(Counter(r["status"] for r in rows).most_common()),
        "completed": {
            "all": rate(completed),
            "by_category": {k: rate(v) for k, v in by(completed, "category").items()},
            "ran_passing_by_evidence": {
                "with_test_run": rate([r for r in passing if r["tests_after_edit"]]),
                "script_only": rate([r for r in passing if not r["tests_after_edit"]]),
            },
            "claims_success_by_category": {
                k: {
                    "claims": rate([r for r in v if r["claims_success"]]),
                    "no_claim": rate([r for r in v if not r["claims_success"]]),
                }
                for k, v in by(changed, "category").items()
            },
            "trials_with_remote_fetch": sum(1 for r in completed if r["remote_fetches"]),
            "stratified_odds_ratios": comparisons(changed, WITHIN_TASK),
            "sensitivity_without_remote_fetch": comparisons(no_fetch, WITHIN_TASK),
        },
    }


def write_rows(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def report(summary: dict) -> None:
    print("trial status:", ", ".join(f"{k} {v}" for k, v in summary["status_counts"].items()))
    done = summary["completed"]
    if not done["all"]["n"]:
        return
    print(f"completed trials: {done['all']['n']}, resolved {done['all']['resolved']}")
    print(f"{'category':<20}{'n':>6}{'resolved':>10}{'rate':>8}  95% CI")
    for name, r in done["by_category"].items():
        low, high = r["ci95"]
        print(f"{name:<20}{r['n']:>6}{r['resolved']:>10}{r['rate']:>8.3f}  [{low:.3f}, {high:.3f}]")
    print(f"trials with a remote fetch: {done['trials_with_remote_fetch']}")
    for section in ("stratified_odds_ratios", "sensitivity_without_remote_fetch"):
        for item in done[section]["within_instance"]:
            if item["odds_ratio"] is None:
                print(f"{section}: {item['comparison']}: undefined ({item['note']})")
                continue
            low, high = item["ci95"]
            print(
                f"{section}: {item['comparison']}: {item['odds_ratio']:.3f} "
                f"[{low:.3f}, {high:.3f}], strata {item['informative_strata']}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify the trials of a finished Harbor job")
    parser.add_argument("job", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if not (args.job / "config.json").is_file():
        print(f"not a Harbor job directory: {args.job}", file=sys.stderr)
        return 2

    meta = {
        **job_meta(args.job),
        "doneclaims": __version__,
        "code_sha256": code_digest(),
        "git": git_state(),
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    rows = read_job(args.job)
    summary = summarise(rows, meta)
    out = args.out or RESULTS / "phase2" / meta["job_name"]
    out.mkdir(parents=True, exist_ok=True)
    write_rows(rows, out / "trials.csv")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    report(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
