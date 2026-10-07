#!/bin/bash
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

echo "=== Installing harness (swegemma, adk-submission, adk-eval-core, vllm) ==="
cd ~/competition
source .venv/bin/activate
pip install -q --find-links ./wheelhouse swegemma adk-submission adk-eval-core vllm

echo "=== Building docker sandbox image ==="
cd ~/competition/competition_data
cp docker/imp.py docker/telnetlib.py . 2>&1 || true
sudo docker build -f docker/Dockerfile.public -t swebench-sandbox:latest .

echo "=== Setup complete ==="
