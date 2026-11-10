#!/usr/bin/env bash
# Phase 2: check the local Anthropic-compatible endpoint before a Harbor run.
# Usage on the measurement machine: bash check_endpoint.sh MODEL [PORT]
set -uo pipefail
MODEL=$1
PORT=${2:-8300}
BRIDGE=${BIND:-$(ip -4 -o addr show docker0 | awk '{print $4}' | cut -d/ -f1 | head -1)}
URL="http://$BRIDGE:$PORT"
KEY=$(cat ~/.done-claims/vllm.key)
BODY='{"model":"'$MODEL'","max_tokens":2000,"messages":[{"role":"user","content":"Reply with the single word: ready"}]}'
TOOL_BODY='{"model":"'$MODEL'","max_tokens":2000,
  "tools":[{"name":"Bash","description":"Run a shell command","input_schema":{"type":"object",
    "properties":{"command":{"type":"string"}},"required":["command"]}}],
  "messages":[{"role":"user","content":"List the files in the current directory with the Bash tool."}]}'

for _ in $(seq 1 60); do
  curl -sf "$URL/health" >/dev/null && break
  sleep 10
done
curl -sf "$URL/health" >/dev/null || { echo "health: not ready"; exit 1; }
echo "health: ok"

for header in "Authorization: Bearer $KEY" "x-api-key: $KEY" "X-No-Key: none"; do
  code=$(curl -s -m 180 -o /tmp/done-claims-reply.json -w '%{http_code}' "$URL/v1/messages" \
    -H "$header" -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' -d "$BODY")
  echo "${header%%:*}: HTTP $code $(head -c 200 /tmp/done-claims-reply.json)"
done

curl -s -m 300 -o /tmp/done-claims-tool.json "$URL/v1/messages" -H "Authorization: Bearer $KEY" \
  -H 'anthropic-version: 2023-06-01' -H 'content-type: application/json' -d "$TOOL_BODY"
python3 - <<'EOF'
import json
reply = json.load(open("/tmp/done-claims-tool.json"))
blocks = [b.get("type") for b in reply.get("content") or []]
calls = [b.get("input") for b in reply.get("content") or [] if b.get("type") == "tool_use"]
print("tool check: blocks", blocks, "stop_reason", reply.get("stop_reason"), "tool input", calls[:1])
EOF

curl -s https://registry.npmjs.org/@anthropic-ai/claude-code/latest |
  python3 -c 'import json, sys; print("claude-code latest on npm:", json.load(sys.stdin)["version"])'
