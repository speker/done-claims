#!/usr/bin/env bash
# Starts a phase 2b Harbor job under the pre-registered conditions (PLAN.md) with the yield watcher.
# Usage on the measurement machine: [GPUS=0,1] bash start_2b.sh JOB ATTEMPTS [harbor -i filters ...]
# Takes GPUS with a shared lease, serves gpt-oss-120b on the Docker bridge, runs 12 trials at a time.
set -uo pipefail
JOB=$1
ATTEMPTS=$2
shift 2
GPUS=${GPUS:-0,1}
ROOT=~/work/done-claims
INSTRUCTION="Resolve the issue above by changing the code in the repository in your current working directory."
cd "$ROOT"

if [ -e "jobs/$JOB" ]; then
    echo "jobs/$JOB exists; resume it with resume_job.sh instead" >&2
    exit 1
fi
lease=$(~/bin/lease acquire --owner done-claims --gpus "$GPUS" --mode shared --hours 6 \
    --note "faz 2 $JOB: vLLM gpt-oss-120b + Harbor/Claude Code" 2>/dev/null | awk 'NR == 1 {print $1}')
[ -n "$lease" ] || { echo "no lease for GPU $GPUS" >&2; ~/bin/lease list >&2; exit 1; }
echo "lease $lease"
if ! curl -sf -o /dev/null "http://$(ip -4 -o addr show docker0 | awk '{print $4}' | cut -d/ -f1 | head -1):8300/health"; then
    CPUS=0-95 bash serve.sh gpt-oss-120b "$GPUS" 8300 || { ~/bin/lease release "$lease"; exit 1; }
fi
TASK_ENV=1 CLAUDE_BINARY="$ROOT/claude-bin/claude" CONTEXT_TOKENS=131072 \
    nohup bash run_harbor.sh "$JOB" "$ATTEMPTS" 12 "$@" --extra-instruction "$INSTRUCTION" \
    >> "$JOB.log" 2>&1 < /dev/null &
sleep 60
if ! pgrep -f -- "--job-name $JOB( |$)" >/dev/null; then
    echo "$JOB did not start; see $JOB.log" >&2
    tail -5 "$JOB.log" >&2
    exit 1
fi
GPU=$GPUS nohup bash yield_quiet.sh "$JOB" "$lease" >> "yield-$JOB.log" 2>&1 < /dev/null &
sleep 2
echo "$JOB running; watcher: $(tail -1 "yield-$JOB.log")"
