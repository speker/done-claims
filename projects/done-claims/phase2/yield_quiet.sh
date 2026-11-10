#!/usr/bin/env bash
# Runs next to a long Harbor job and hands the machine to quiet-window measurements (KARARLAR #20).
# A quiet measurement is waiting when some session is blocked in `lease wait --mode quiet`, or when
# tr-serve's night_quiet.sh runs inside its 22:00-06:59 window (it takes the quiet lease itself once
# every GPU is idle). If done-claims has then held the only active lease for ten minutes, this stops
# the job, the vLLM server and the lease; once the quiet lease has come and gone, or another session
# takes a shared lease again, it takes GPU 0 back, restarts vLLM and resumes the job. It also pins
# trial containers to CPUs 0-95, keeps the lease from expiring, and releases everything when the job
# ends. It stops everything at once if the kernel starts piling up blocked processes (6 Nov: stuck
# `runc init` left ~2,700 processes in D state) or trials keep failing for infrastructure reasons.
# Usage on the measurement machine: [BIND=ip] [GPU=0,1] nohup bash yield_quiet.sh JOB LEASE_ID > yield-JOB.log 2>&1 &
set -uo pipefail
JOB=$1
LEASE=$2
ROOT=~/work/done-claims
OWNER=done-claims
MODEL=gpt-oss-120b
GPU=${GPU:-0}
PORT=8300
CPUS=0-95
BIND=${BIND:-}
MAX_BLOCKED=300
MAX_FAILURES=10
NOTE="faz 2 $JOB: vLLM gpt-oss-120b + Harbor/Claude Code"
log() { printf '[%s] %s\n' "$(date '+%F %T')" "$*"; }

# One line per active lease: id owner mode minutes_left
leases() {
    python3 - <<'EOF'
import json, os
from datetime import datetime, timezone
path = os.path.join(os.environ.get("LEASE_DIR", os.path.expanduser("~/.h200-lease")), "leases.json")
now = datetime.now(timezone.utc)
try:
    entries = json.load(open(path, encoding="utf-8"))
except FileNotFoundError:
    entries = []
for e in entries:
    left = (datetime.fromisoformat(e["expires"]) - now).total_seconds() / 60
    if left > 0:
        print(e["id"], e["owner"], e["mode"], int(left))
EOF
}
night() {
    local h
    h=$(date +%-H)
    [ "$h" -ge 22 ] || [ "$h" -lt 7 ]
}
quiet_pending() {
    pgrep -f -- 'lease wait .*--mode quiet' >/dev/null || { night && pgrep -f -- 'night_quiet\.sh' >/dev/null; }
}
pin_trials() {
    local c
    for c in $(docker ps --format '{{.Names}}' | grep '__env-main-1$'); do
        [ "$(docker inspect -f '{{.HostConfig.CpusetCpus}}' "$c" 2>/dev/null)" = "$CPUS" ] && continue
        timeout 30 docker update --cpuset-cpus "$CPUS" "$c" >/dev/null 2>&1
    done
}
# Trials of this job that failed for infrastructure reasons in the last ten minutes. Setup timeouts are
# left out: they come in bursts when Ubuntu mirrors slow down under 16 parallel `apt-get install nodejs`
# (7 Nov, 14:53-14:59), harm nothing on this machine, and the retry passes rerun them.
recent_failures() {
    find "$ROOT/jobs/$JOB" -mindepth 2 -maxdepth 2 -name result.json -mmin -10 -print0 2>/dev/null \
        | xargs -0 -r grep -lE '"exception_type": ?"(RuntimeError|UnknownApiError|NetworkConnectionError)"' \
        | wc -l
}
emergency_stop() {
    log "emergency stop: $1"
    bash "$ROOT/stop_job.sh" "$JOB" 30 | while read -r line; do log "$line"; done
    timeout 60 docker stop -t 30 "done-claims-vllm-$MODEL" >/dev/null 2>&1 && log "vLLM stopped"
    ~/bin/lease release "$LEASE" >/dev/null && log "lease $LEASE released"
    exit 2
}
strikes=0
# Python processes are left out of the count: an agent running Django's whole suite with one worker
# per CPU puts a hundred of them in D state on the slow disk for minutes (8 Nov), while the 6 Nov hang
# blocked runc, container health checks and kernel workers.
guard() {
    local blocked failures
    blocked=$(ps -eo stat=,comm= | awk '$1 ~ /^D/ && $2 !~ /^python/' | wc -l)
    if [ "$blocked" -gt "$MAX_BLOCKED" ]; then strikes=$((strikes + 1)); else strikes=0; fi
    [ "$strikes" -ge 3 ] && emergency_stop "$blocked non-Python processes in D state for three minutes"
    failures=$(recent_failures)
    [ "$failures" -ge "$MAX_FAILURES" ] && emergency_stop "$failures infrastructure failures in ten minutes"
}
quiet_active() { leases | awk '$3 == "quiet" {found = 1} END {exit !found}'; }
others_active() { leases | awk -v o="$OWNER" '$2 != o {found = 1} END {exit !found}'; }
job_running() { pgrep -f -- "(--job-name |jobs resume -p jobs/)$JOB( |$)" >/dev/null; }
# Trials that resume_job.sh would run again: infrastructure failures, not agent behaviour.
retryable() {
    python3 - "$ROOT/jobs/$JOB" <<'EOF'
import glob, json, sys
retry = {"CancelledError", "AgentSetupTimeoutError", "RuntimeError", "UnknownApiError", "NetworkConnectionError"}
n = 0
for path in glob.glob(sys.argv[1] + "/*/result.json"):
    try:
        info = json.load(open(path)).get("exception_info") or {}
    except (OSError, ValueError):
        continue
    n += info.get("exception_type") in retry
print(n)
EOF
}

keep_lease() {
    local left
    left=$(leases | awk -v id="$LEASE" '$1 == id {print $4}')
    if [ -z "$left" ]; then
        log "lease $LEASE is gone; taking a new one"
        LEASE=$(~/bin/lease acquire --owner "$OWNER" --gpus "$GPU" --mode shared --hours 4 --note "$NOTE" | awk 'NR == 1 {print $1}')
    elif [ "$left" -lt 60 ]; then
        ~/bin/lease extend "$LEASE" --hours 3 >/dev/null && log "lease $LEASE extended by 3 h"
    fi
}

pause() {
    log "a quiet measurement is waiting and only done-claims holds a lease; pausing $JOB"
    bash "$ROOT/stop_job.sh" "$JOB" 60 | while read -r line; do log "$line"; done
    docker stop -t 30 "done-claims-vllm-$MODEL" >/dev/null 2>&1 && log "vLLM stopped"
    ~/bin/lease release "$LEASE" >/dev/null && log "lease $LEASE released"
}

wait_for_quiet_window() {
    local seen=0 start
    start=$(date +%s)
    while :; do
        if quiet_active; then
            [ "$seen" = 0 ] && log "quiet lease taken"
            seen=1
        elif [ "$seen" = 1 ]; then
            log "quiet lease released"
            return
        elif others_active; then
            log "another session took a shared lease, so the machine will not go quiet; resuming"
            return
        elif ! quiet_pending; then
            log "the quiet waiter left without taking a lease"
            return
        fi
        if [ $(($(date +%s) - start)) -gt 43200 ]; then
            log "still waiting after 12 h; resuming anyway"
            return
        fi
        sleep 30
    done
}

resume() {
    LEASE=$(~/bin/lease wait --owner "$OWNER" --gpus "$GPU" --mode shared --hours 6 --timeout-min 720 \
        --note "$NOTE" | awk 'NR == 1 {print $1}')
    [ -n "$LEASE" ] || { log "no lease for GPU $GPU; giving up"; exit 1; }
    log "lease $LEASE taken"
    CPUS=$CPUS BIND=$BIND bash "$ROOT/serve.sh" "$MODEL" "$GPU" "$PORT" | while read -r line; do log "$line"; done
    nohup bash "$ROOT/resume_job.sh" "$JOB" >> "$ROOT/$JOB.log" 2>&1 < /dev/null &
    sleep 60
    job_running && log "$JOB resumed" || { log "$JOB did not resume; see $JOB.log"; exit 1; }
}

log "watching $JOB with lease $LEASE"
retries=0
# tr-serve takes one shared lease per model, with short gaps between them; yield only when the
# machine has been free of other leases for YIELD_AFTER seconds in a row.
YIELD_AFTER=${YIELD_AFTER:-600}
free_since=
while :; do
    if ! job_running; then
        left=$(retryable)
        if [ "$left" -gt 0 ] && [ "$retries" -lt 3 ]; then
            retries=$((retries + 1))
            log "$JOB ended with $left trial(s) to retry; resume pass $retries"
            nohup bash "$ROOT/resume_job.sh" "$JOB" >> "$ROOT/$JOB.log" 2>&1 < /dev/null &
            sleep 60
            continue
        fi
        log "$JOB is not running any more ($left retryable trial(s) left); releasing GPU $GPU"
        docker stop -t 30 "done-claims-vllm-$MODEL" >/dev/null 2>&1
        ~/bin/lease release "$LEASE" >/dev/null
        exit 0
    fi
    if quiet_pending && ! others_active; then
        free_since=${free_since:-$(date +%s)}
        if [ $(($(date +%s) - free_since)) -ge "$YIELD_AFTER" ]; then
            pause
            wait_for_quiet_window
            resume
            free_since=
        fi
    else
        free_since=
    fi
    guard
    keep_lease
    pin_trials
    sleep 60
done
