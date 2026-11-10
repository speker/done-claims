"""Replaces Harbor's random trial names in committed result files with stable aliases.

Usage, from projects/done-claims:
  uv run python phase2/alias_trials.py RESULTS_DIR STAGE_TAG [FILE ...]
RESULTS_DIR holds the trials.csv that doneclaims.harbor wrote. Each trial becomes
<instance_id>__<STAGE_TAG>-<NN>, numbered per issue in the order of the original names. The mapping goes to
data/cache/done-claims/phase2/<results dir name>-trial-alias.csv, outside git, so audit tools can still find
transcripts. Harbor's random suffixes can spell short strings that the repository's privacy scan blocks.
The listed files (default: trials.csv) are rewritten in place; running it again on aliased files is a no-op.
"""

import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

CACHE = Path(__file__).resolve().parents[3] / "data/cache/done-claims/phase2"


def main() -> int:
    results, tag, *files = sys.argv[1:]
    results = Path(results)
    trials_csv = results / "trials.csv"
    rows = list(csv.DictReader(trials_csv.open(encoding="utf-8")))
    mapping_path = CACHE / f"{results.name}-trial-alias.csv"
    if mapping_path.exists():
        mapping = {r["trial"]: r["alias"] for r in csv.DictReader(mapping_path.open(encoding="utf-8"))}
    else:
        by_issue = defaultdict(list)
        for r in rows:
            by_issue[r["instance_id"]].append(r["trial"])
        mapping = {
            trial: f"{issue}__{tag}-{n:02d}"
            for issue, trials in by_issue.items()
            for n, trial in enumerate(sorted(trials), 1)
        }
        CACHE.mkdir(parents=True, exist_ok=True)
        with mapping_path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["trial", "alias"])
            w.writerows(sorted(mapping.items()))
    for name in files or ["trials.csv"]:
        path = results / name
        text = path.read_text(encoding="utf-8")
        for trial, alias in mapping.items():
            text = text.replace(trial, alias)
        path.write_bytes(text.encode("utf-8"))
        print(f"{path}: {sum(alias in text for alias in mapping.values())} aliases")
    check = io.StringIO((results / "trials.csv").read_text(encoding="utf-8"))
    assert all(r["trial"] in mapping.values() for r in csv.DictReader(check)), "unaliased trial left"
    print(f"mapping: {mapping_path} ({len(mapping)} trials)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
