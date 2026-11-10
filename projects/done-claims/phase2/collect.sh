#!/usr/bin/env bash
# Packs the files the analysis reads from a finished Harbor job into export/JOB.tar.gz.
# Refuses if the vLLM key appears anywhere in the job directory.
# Usage: bash collect.sh JOB
set -euo pipefail

JOB=$1
ROOT=~/work/done-claims
KEY=$(cat ~/.done-claims/vllm.key)

cd "$ROOT/jobs"
leaks=$(grep -rlF -- "$KEY" "$JOB" | wc -l || true)
if [ "$leaks" -ne 0 ]; then
    echo "key found in $leaks file(s) under jobs/$JOB; not exporting" >&2
    exit 3
fi

mkdir -p "$ROOT/export"
find "$JOB" \( -path "$JOB/result.json" -o -path "$JOB/config.json" \
    -o -path "$JOB/*/result.json" -o -path "$JOB/*/config.json" -o -path "$JOB/*/exception.txt" \
    -o -path "$JOB/*/agent/trajectory.json" -o -path "$JOB/*/verifier/reward.txt" \) -type f -print0 \
    | tar --null -czf "$ROOT/export/$JOB.tar.gz" -T -
echo "export/$JOB.tar.gz $(du -h "$ROOT/export/$JOB.tar.gz" | cut -f1) $(tar -tzf "$ROOT/export/$JOB.tar.gz" | wc -l) files"
