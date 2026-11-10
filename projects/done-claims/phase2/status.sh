#!/usr/bin/env bash
# Progress of a Harbor job and health of the local vLLM endpoint.
# Usage: bash status.sh JOB [MINUTES] [PROFILE]
set -euo pipefail

JOB=$1
SINCE=${2:-10}
NAME=done-claims-vllm-${3:-gpt-oss-120b}
DIR=~/work/done-claims/jobs/$JOB

echo "time      $(date +%T)"
echo "trials    $(find "$DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)"
echo "finished  $(find "$DIR" -mindepth 2 -maxdepth 2 -name result.json | wc -l)"
echo "rewards   $(find "$DIR" -path '*/verifier/reward.txt' -exec cat {} + 2>/dev/null | sort | uniq -c | tr '\n' ' ')"
echo "running   $(docker ps --format '{{.Names}}' | grep -c '__env-main' || true)"

echo "--- /v1/messages status codes, last ${SINCE}m"
docker logs --since "${SINCE}m" "$NAME" 2>&1 \
    | grep 'POST /v1/messages' | grep -oE 'HTTP/1.1" [0-9]+' | sort | uniq -c || true

echo "--- vLLM errors, last ${SINCE}m"
docker logs --since "${SINCE}m" "$NAME" 2>&1 \
    | grep -iE 'error|exception' | cut -c1-200 | sort | uniq -c | sort -rn | head -5 || true

echo "--- engine"
docker logs --since 2m "$NAME" 2>&1 | grep -E 'throughput' | tail -1 | cut -c1-240 || true

echo "--- trial exceptions (last line)"
cd "$DIR"
find . -mindepth 2 -maxdepth 2 -name exception.txt -exec sh -c 'echo "${1%/exception.txt}: $(tail -n 1 "$1" | cut -c1-160)"' _ {} \; || true
