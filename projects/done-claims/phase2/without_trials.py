"""Copy a trials.csv without the trials named in a list, one trial name per line.

Usage, from projects/done-claims:
  uv run python phase2/without_trials.py TRIALS_CSV LIST OUT_CSV
For the phase 2b sensitivity analysis without the 38 stage-1 trials that ran on the one-GPU server
(PLAN.md, results/phase2b/stage1_one_gpu_trials.txt); run doneclaims.phase2b on the output.
"""

import csv
import sys
from pathlib import Path


def main() -> int:
    trials, names, out = (Path(a) for a in sys.argv[1:4])
    drop = {line.strip() for line in names.read_text(encoding="utf-8").splitlines() if line.strip()}
    with trials.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = reader.fieldnames
    kept = [r for r in rows if r["trial"] not in drop]
    missing = drop - {r["trial"] for r in rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(kept)
    print(f"{len(rows)} rows, dropped {len(rows) - len(kept)}, kept {len(kept)}")
    print(f"{len(missing)} listed trial(s) not found")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
