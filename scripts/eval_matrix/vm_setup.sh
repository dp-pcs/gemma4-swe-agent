#!/usr/bin/env bash
# One-time environment setup on a clone of the gemma-agent-dev disk.
# Expects the upload bundle extracted at ~/matrix (see README in this directory).
set -euo pipefail
M=$HOME/matrix
cd "$M"

if [ ! -x "$M/.venv/bin/python" ]; then
  python3.12 -m venv "$M/.venv"
fi
source "$M/.venv/bin/activate"
pip install -q --upgrade pip==25.3
# Exact serving closure from the 2026-10-13 frozen manifest (hash-checked).
# Official-wheelhouse members are not all byte-identical to PyPI, so they install
# offline from the preserved copies; the rest come from PyPI under the same hashes.
O=$HOME/official_up
[ -d "$O" ] || tar -xf "$HOME/official_up.tar" -C "$HOME"
pip install -q --no-deps --require-hashes --no-index --find-links "$O" -r "$O/official.lock"
pip install -q --no-deps --require-hashes -r "$O/pypi.lock"
# Organizer SDK wheels (swegemma is the 2026-10-12 re-release).
pip install -q --no-deps "$M"/wheels/*.whl
python -c "import vllm, swegemma, adk_submission, google.adk; print('vllm', vllm.__version__, 'adk', google.adk.__version__)"

# Grading/agent sandbox image (framework profile), pinned by ID.
IMG=sha256:04716dc0a4b958ebd7b8f5bb313e350d9437088e0c84d17e7e72cb05a6a819e0
if ! docker image inspect "$IMG" >/dev/null 2>&1; then
  docker load -i "$M/sandbox_image.tar"
fi
docker tag "$IMG" swegemma-framework:matrix
docker image inspect swegemma-framework:matrix --format '{{.Id}}'

D=$HOME/competition/competition_data
sha256sum "$D/tasks.jsonl"
ls "$D/snapshots" | wc -l
ls "$D/wheels" | wc -l
nvidia-smi -L 2>/dev/null || echo "no GPU on this VM"
echo SETUP_OK
