#!/bin/bash
set -euo pipefail

echo "=== Checking GPU visibility ==="
nvidia-smi

echo "=== Disk status ==="
df -h /

echo "=== Installing base Python tooling ==="
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv unzip

echo "=== Installing kaggle CLI ==="
python3 -m pip install -q --user kaggle
export PATH="$HOME/.local/bin:$PATH"

mkdir -p ~/.kaggle
# access_token will be scp'd in separately before this runs

echo "=== Downloading competition data ==="
mkdir -p ~/competition && cd ~/competition
kaggle competitions download -c gemma-4-developer-agent -p ~/competition
unzip -o -q gemma-4-developer-agent.zip -d ~/competition/competition_data
rm gemma-4-developer-agent.zip

echo "=== Downloading wheelhouse ==="
mkdir -p ~/competition/wheelhouse && cd ~/competition/wheelhouse
kaggle datasets download -d metric/gemma-4-developer-agent-wheelhouse
unzip -o -q gemma-4-developer-agent-wheelhouse.zip
rm gemma-4-developer-agent-wheelhouse.zip

echo "=== Downloading Gemma 4 model weights (QAT quantized) ==="
mkdir -p ~/competition/model
cd ~/competition/model
kaggle models instances versions download google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct/1 --untar -p ~/competition/model

echo "=== Creating venv and installing harness ==="
cd ~/competition
python3 -m venv .venv
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q --find-links ./wheelhouse swegemma adk-submission adk-eval-core vllm

echo "=== Building docker sandbox image ==="
cd ~/competition/competition_data
cp docker/imp.py docker/telnetlib.py . 2>&1 || true
sudo docker build -f docker/Dockerfile.public -t swebench-sandbox:latest .

echo "=== Setup complete ==="
echo "Next: start vLLM server, then run swegemma eval"
