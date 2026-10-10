#!/data/data/com.termux/files/usr/bin/bash
# Start the local model server (llama.cpp) with 4GB-friendly settings.
# Keep this session running; use a second Termux session for the agent.
set -e
cd "$(dirname "$0")"

MODEL="${MODEL:-models/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf}"
PORT="${PORT:-8080}"
CTX="${CTX:-2048}"          # context size; raise to 4096 if your phone copes
THREADS="${THREADS:-4}"     # keep some CPU free for Android itself

if [ ! -f "$MODEL" ]; then
  echo "Model not found: $MODEL"
  echo "Run  bash install_termux.sh  first (or set MODEL=<path>)."
  exit 1
fi

echo "Serving $MODEL on http://127.0.0.1:$PORT (ctx=$CTX, threads=$THREADS)"
exec llama-server -m "$MODEL" --host 127.0.0.1 --port "$PORT" \
  -c "$CTX" -t "$THREADS" "$@"
