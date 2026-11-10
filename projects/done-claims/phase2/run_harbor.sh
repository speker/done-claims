#!/usr/bin/env bash
# Phase 2: Claude Code on SWE-bench Verified through Harbor, against the local gpt-oss-120b server.
# Usage on the measurement machine, with a lease held and serve.sh running:
#   [MODEL=qwen3.8-27b PORT=8301] [TASK_ENV=1] [CLAUDE_BINARY=/abs/path/claude] [CONTEXT_TOKENS=131072] \
#   bash run_harbor.sh JOB_NAME ATTEMPTS CONCURRENCY [extra harbor run args, e.g. -i 'swe-bench/django__django-*']
# vLLM accepts the key only as a bearer token. Harbor routes a key whose source variable is
# ANTHROPIC_AUTH_TOKEN to the bearer header and blanks ANTHROPIC_API_KEY; any other source name
# lands in ANTHROPIC_API_KEY (x-api-key) and every request fails with 401. The key stays out of argv.
set -euo pipefail
JOB=$1
ATTEMPTS=$2
CONCURRENCY=$3
shift 3
CLAUDE_CODE_VERSION=2.1.318
MODEL=${MODEL:-gpt-oss-120b}
PORT=${PORT:-8300}
BRIDGE=$(ip -4 -o addr show docker0 | awk '{print $4}' | cut -d/ -f1 | head -1)
URL="http://$BRIDGE:$PORT"
ANTHROPIC_AUTH_TOKEN=$(cat ~/.done-claims/vllm.key)
export ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_API_KEY

# Claude Code asks for effort "high" by default. gpt-oss accepts it; the Qwen3.8 chat template accepts
# only xhigh (its default), medium and low, and vLLM rejects "high" with HTTP 400.
effort=()
case "$MODEL" in
  qwen3.8-27b) effort=(--ak reasoning_effort=xhigh) ;;
esac

model_env=()
for name in ANTHROPIC_MODEL ANTHROPIC_DEFAULT_OPUS_MODEL ANTHROPIC_DEFAULT_SONNET_MODEL \
  ANTHROPIC_DEFAULT_HAIKU_MODEL ANTHROPIC_SMALL_FAST_MODEL CLAUDE_CODE_SUBAGENT_MODEL; do
  model_env+=(--ae "$name=$MODEL")
done

# Phase 2b settings, off by default so phase 2a runs as it did.
# TASK_ENV=1: the agent's shell starts with the task's conda env first on PATH, as the verifier's does
# (`conda activate testbed`); phase 2a agents got the image's base Python 3.11 instead.
# CLAUDE_BINARY=path: a prebuilt Claude Code binary of the pinned version is mounted at
# /root/.local/bin/claude, so Harbor skips the per-container apt and npm install that saturated the disk.
setup=()
if [ "${TASK_ENV:-0}" = 1 ]; then
  setup+=(--ae "PATH=/opt/miniconda3/envs/testbed/bin:/opt/miniconda3/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
fi
if [ -n "${CLAUDE_BINARY:-}" ]; then
  setup+=(--ae DISABLE_AUTOUPDATER=1 --mounts
    "[{\"type\":\"bind\",\"source\":\"$CLAUDE_BINARY\",\"target\":\"/root/.local/bin/claude\",\"read_only\":true}]")
fi
# CONTEXT_TOKENS=n: Claude Code treats an unknown model as having a 200K window and compacts too late; past
# the server's limit every request fails with HTTP 400 and the trial ends in an API error.
if [ -n "${CONTEXT_TOKENS:-}" ]; then
  setup+=(--ae "CLAUDE_CODE_MAX_CONTEXT_TOKENS=$CONTEXT_TOKENS")
fi

cd ~/work/done-claims
~/.local/bin/harbor run -a claude-code -m "$MODEL" -d swe-bench/swe-bench-verified \
  --base-url "$URL" --api-key-name ANTHROPIC_AUTH_TOKEN --api-format anthropic_messages \
  --allow-agent-host "$BRIDGE" --ak "version=$CLAUDE_CODE_VERSION" --ak disable_web_search=true "${effort[@]}" \
  --ae CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 "${model_env[@]}" "${setup[@]}" \
  -k "$ATTEMPTS" -n "$CONCURRENCY" -o jobs --job-name "$JOB" -y "$@"
