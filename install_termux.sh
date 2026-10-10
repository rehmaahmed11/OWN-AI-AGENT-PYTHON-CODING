#!/data/data/com.termux/files/usr/bin/bash
# One-shot installer for Termux (Android, ~4GB RAM).
# Usage:  bash install_termux.sh
set -e

echo "==> Updating packages"
pkg update -y && pkg upgrade -y

echo "==> Installing Python, git, wget, llama.cpp"
pkg install -y python git wget llama-cpp

echo "==> Requesting shared-storage access (tap ALLOW)"
termux-setup-storage || true

cd "$(dirname "$0")"
mkdir -p models workspace

MODEL_URL="${MODEL_URL:-https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf}"
MODEL_FILE="models/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"

if [ ! -f "$MODEL_FILE" ]; then
  echo "==> Downloading model (~1.0 GB): $MODEL_URL"
  echo "    (override with: MODEL_URL=<url> bash install_termux.sh)"
  wget -c "$MODEL_URL" -O "$MODEL_FILE"
else
  echo "==> Model already present: $MODEL_FILE"
fi

if [ ! -f agent_config.json ]; then
  cp agent_config.example.json agent_config.json
  echo "==> Created agent_config.json (edit it to add extra_roots later)"
fi

echo
echo "✅ Install complete. Next steps:"
echo "   1) Start the model server:   bash start_model.sh"
echo "   2) In a SECOND Termux session (swipe from left -> NEW SESSION):"
echo "      python own_agent.py doctor"
echo "      python own_agent.py \"Make a Flask website for a shoes company\""
