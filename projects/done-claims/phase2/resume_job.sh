#!/usr/bin/env bash
# Resumes a stopped Harbor job in the foreground; finished trials are kept.
# Trials that a stop cut off (CancelledError, or no result.json) run again, and so do trials that failed
# for infrastructure reasons: a Claude Code install that hit the 360 s setup limit when many trials
# started at once, a container that did not come up (RuntimeError), a model server error, or a dropped
# connection to it.
# Trials where the agent itself ran out of time (AgentTimeoutError) are kept as they are.
# Usage on the measurement machine, with a lease held and serve.sh running: bash resume_job.sh JOB
set -euo pipefail
JOB=$1
ANTHROPIC_AUTH_TOKEN=$(cat ~/.done-claims/vllm.key)
export ANTHROPIC_AUTH_TOKEN
unset ANTHROPIC_API_KEY
cd ~/work/done-claims
exec ~/.local/bin/harbor jobs resume -p "jobs/$JOB" \
  -f CancelledError -f AgentSetupTimeoutError -f RuntimeError -f UnknownApiError -f NetworkConnectionError
