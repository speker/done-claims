"""Build the Hugging Face dataset folder of done-claims (serkanpeker/done-claims) in projects/done-claims/hub.

    uv run python build_hub.py      (from projects/done-claims)

The four tables go to hub/data/, one config each; every other result file keeps its place under hub/results/.
The card is hub/README.md, written by hand; its numbers come from RESULTS.md and phase2b/analysis.json.
Files come from git HEAD, so only committed results are uploaded.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
REPO = PROJECT.parents[1]
HUB = PROJECT / "hub"
TABLES = {
    "results/features.csv.gz": "data/phase1/features.csv.gz",
    "results/phase2/full-gptoss-instr/trials.csv": "data/phase2a/trials.csv",
    "results/phase2b/p2b-stage1/trials.csv": "data/phase2b/stage1.csv",
    "results/phase2b/p2b-stage2/trials.csv": "data/phase2b/stage2.csv",
}


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True).stdout


def main() -> None:
    for sub in ("data", "results"):
        shutil.rmtree(HUB / sub, ignore_errors=True)
    prefix = "projects/done-claims/"
    listing = git("ls-tree", "-r", "--name-only", "HEAD", "--", prefix + "results").decode()
    committed = [f[len(prefix):] for f in listing.split("\n") if f]
    for rel in committed:
        dst = HUB / TABLES.get(rel, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(git("show", f"HEAD:{prefix}{rel}"))
    print(f"{len(committed)} files from HEAD {git('rev-parse', '--short', 'HEAD').decode().strip()} -> {HUB} "
          f"({len(TABLES)} as data tables)")


if __name__ == "__main__":
    main()
