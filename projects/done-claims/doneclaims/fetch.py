"""Download the pinned dataset revision into data/cache/done-claims (git-ignored).

Usage, from projects/done-claims: uv run python -m doneclaims.fetch [--shards N]
"""

import argparse
import sys

from huggingface_hub import hf_hub_download

from .data import CACHE, REPO, REVISION, SHARD_COUNT, shard_name


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the pinned trajectory shards")
    parser.add_argument("--shards", type=int, default=SHARD_COUNT)
    args = parser.parse_args()
    if not 1 <= args.shards <= SHARD_COUNT:
        parser.error(f"--shards must be between 1 and {SHARD_COUNT}")
    for index in range(args.shards):
        path = hf_hub_download(
            REPO, shard_name(index), repo_type="dataset", revision=REVISION, local_dir=CACHE, token=False
        )
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
