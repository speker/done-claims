#!/usr/bin/env bash
# Prints "<finished trials> <ended>" for a Harbor job; ended is 1 once the yield watcher logged the job's end.
# Usage: bash job_done.sh JOB
JOB=$1
ROOT=~/work/done-claims
f=$(find "$ROOT/jobs/$JOB" -mindepth 2 -maxdepth 2 -name result.json 2>/dev/null | wc -l)
e=$(grep -c "$JOB is not running any more" "$ROOT/yield-$JOB.log" 2>/dev/null)
echo "$f ${e:-0}"
