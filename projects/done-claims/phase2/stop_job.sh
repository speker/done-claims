#!/usr/bin/env bash
# Stops a running Harbor job, then removes the trial containers and networks it left behind.
# SIGINT lets running trials finish; SIGTERM after WAIT_SECONDS cancels them, and `resume_job.sh` reruns them.
# Usage: bash stop_job.sh JOB [WAIT_SECONDS]
set -uo pipefail
JOB=$1
WAIT=${2:-180}
PATTERN="(--job-name |jobs resume -p jobs/)$JOB( |$)"

pids=$(pgrep -f -- "$PATTERN")
if [ -n "$pids" ]; then
    kill -INT $pids
    for _ in $(seq 1 "$WAIT"); do
        pgrep -f -- "$PATTERN" >/dev/null || break
        sleep 1
    done
    if pgrep -f -- "$PATTERN" >/dev/null; then
        kill -TERM $pids 2>/dev/null
        for _ in $(seq 1 60); do
            pgrep -f -- "$PATTERN" >/dev/null || break
            sleep 1
        done
        echo "terminated $JOB"
    else
        echo "stopped $JOB"
    fi
else
    echo "no running Harbor process for job $JOB"
fi

cd ~/work/done-claims/jobs/"$JOB" 2>/dev/null || exit 0
trials=$(ls -d -- */ 2>/dev/null | tr 'A-Z' 'a-z')
removed=0
for c in $(docker ps -a --format '{{.Names}}' | grep '__env-main-1$'); do
    project=${c%-main-1}
    if grep -qx -- "${project%__env}/" <<<"$trials"; then
        timeout 60 docker rm -f "$c" >/dev/null 2>&1
        timeout 30 docker network rm "${project}_default" >/dev/null 2>&1
        removed=$((removed + 1))
    fi
done
echo "removed $removed leftover trial container(s) of $JOB"

# Each trial gets its own compose network; Docker's default address pools hold about 31, so
# networks left without containers make later trials fail with "address pools fully subnetted".
orphans=0
for net in $(docker network ls --format '{{.Name}}' | grep '__env_default$'); do
    if grep -qx -- "${net%__env_default}/" <<<"$trials" \
        && [ "$(docker network inspect -f '{{len .Containers}}' "$net" 2>/dev/null)" = 0 ]; then
        docker network rm "$net" >/dev/null 2>&1 && orphans=$((orphans + 1))
    fi
done
echo "removed $orphans orphaned trial network(s) of $JOB"
