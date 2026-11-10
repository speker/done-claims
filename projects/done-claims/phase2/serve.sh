#!/usr/bin/env bash
# Phase 2: serve an open model to Claude Code through vLLM's Anthropic Messages API.
# Usage on the measurement machine, after `~/bin/lease acquire`: bash serve.sh PROFILE GPU PORT
#   PROFILE is a directory under ~/models: gpt-oss-120b or qwen3.8-27b.
#   GPU is one index or a list such as 0,1; a list serves one replica with tensor parallelism across it.
# The server listens on the Docker bridge only; the API key stays in ~/.done-claims/vllm.key.
# CPUs 0-95 belong to done-claims and 96-191 to tr-quant (docs/AJANLAR.md, shared method item 4).
set -euo pipefail
PROFILE=$1
GPU=${2:-0}
PORT=${3:-8300}
IMAGE=vllm/vllm-openai@sha256:d825baf9ce4b1b6bfc5ecc7b79880c7e6748c65a72d697ce3d47607aafa84c6e
case "$PROFILE" in
  gpt-oss-120b) ARGS=(--tool-call-parser openai) ;;
  qwen3.8-27b) ARGS=(--tool-call-parser qwen3_coder --reasoning-parser qwen3 --language-model-only) ;;
  *) echo "unknown profile: $PROFILE" >&2; exit 2 ;;
esac
MODEL=$HOME/models/$PROFILE
NAME=done-claims-vllm-$PROFILE
TP=$(($(tr -cd , <<< "$GPU" | wc -c) + 1))
BRIDGE=$(ip -4 -o addr show docker0 | awk '{print $4}' | cut -d/ -f1 | head -1)
# A job keeps the endpoint it started with; BIND serves it on that address after docker0 has moved.
BRIDGE=${BIND:-$BRIDGE}

mkdir -p ~/.done-claims
chmod 700 ~/.done-claims
[ -s ~/.done-claims/vllm.key ] || (umask 077; openssl rand -hex 16 > ~/.done-claims/vllm.key)
VLLM_API_KEY=$(cat ~/.done-claims/vllm.key)
export VLLM_API_KEY

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --runtime=nvidia --gpus "\"device=$GPU\"" --ipc=host -e VLLM_API_KEY \
  --cpuset-cpus "${CPUS:-0-95}" \
  -p "$BRIDGE:$PORT:8000" -v "$MODEL:/model:ro" "$IMAGE" \
  --model /model --served-model-name "$PROFILE" --enable-auto-tool-choice "${ARGS[@]}" \
  --max-model-len 131072 --gpu-memory-utilization 0.90 --seed 0 --tensor-parallel-size "$TP" >/dev/null

for _ in $(seq 1 90); do
  if curl -sf "http://$BRIDGE:$PORT/health" >/dev/null; then
    echo "ready: http://$BRIDGE:$PORT model $PROFILE revision $(cat "$MODEL/.tamam" 2>/dev/null || echo unrecorded)"
    exit 0
  fi
  docker inspect -f '{{.State.Running}}' "$NAME" | grep -q true || { docker logs --tail 40 "$NAME"; exit 1; }
  sleep 10
done
echo "not ready after 15 minutes"
exit 1
