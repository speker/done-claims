"""Pinned source dataset and local paths."""

from pathlib import Path

REPO = "nebius/SWE-agent-trajectories"
REVISION = "68195a1450865274106246d0d0296a1d6807b88e"
SHARD_COUNT = 12
COLUMNS = ["instance_id", "model_name", "target", "exit_status", "trajectory", "generated_patch"]

PROJECT = Path(__file__).resolve().parents[1]
CACHE = PROJECT.parents[1] / "data" / "cache" / "done-claims"
RESULTS = PROJECT / "results"


def shard_name(index: int) -> str:
    return f"data/train-{index:05d}-of-{SHARD_COUNT:05d}.parquet"


def shard_path(index: int) -> Path:
    return CACHE / shard_name(index)
