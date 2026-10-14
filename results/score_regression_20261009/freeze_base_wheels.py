"""Stage the organizer's base wheel layer once, before compatibility pins."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from swegemma.harness.container_setup import _build_unpacked_wheels_tar, _inspect_wheels_dir

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--wheels", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
base_wheels, _, _, _ = _inspect_wheels_dir(args.wheels)
archive = _build_unpacked_wheels_tar(base_wheels, "sp_base", ".swegemma_base_injected")
args.output.mkdir(parents=True, exist_ok=True)
staged = args.output / "frozen_base_site_packages.tar"
shutil.copyfile(archive, staged)
digest = hashlib.sha256()
with staged.open("rb") as stream:
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
manifest = {"sha256": digest.hexdigest(), "bytes": staged.stat().st_size, "base_wheel_names": [wheel.name for wheel in base_wheels], "scope": "Same organizer wheel layer, seeded into the image before local compatibility pins; marker prevents later base-layer overwrites. Large dependency injection remains enabled."}
(args.output / "frozen_base_wheels.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"sha256": manifest["sha256"], "bytes": manifest["bytes"], "base_wheels": len(base_wheels)}))
