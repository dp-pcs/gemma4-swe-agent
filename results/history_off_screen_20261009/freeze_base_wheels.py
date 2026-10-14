#!/usr/bin/env python3
"""Freeze SDK 0.2.11's real injection layer into an invocation-local cache."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import zipfile


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if importlib.metadata.version("swegemma") != "0.2.11":
        raise RuntimeError("Only the supplied current swegemma 0.2.11 may freeze this layer")
    # Never reuse the SDK's fixed sp_base.tar from another run or wheel origin.
    cache = output / "sdk-wheel-cache"
    cache.mkdir(exist_ok=False)
    tempfile.tempdir = str(cache)
    from swegemma.harness import container_setup

    base, large, _, _ = container_setup._inspect_wheels_dir(args.wheels.resolve())
    if not base:
        raise RuntimeError("No compatible organizer base wheels found")
    wheels = []
    expected = {".swegemma_base_injected"}
    for wheel in base:
        with zipfile.ZipFile(wheel) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"Corrupt wheel member: {wheel.name}:{bad_member}")
            expected.update(name.rstrip("/") for name in archive.namelist()
                            if not name.endswith((".pyc", "/RECORD"))
                            and ".data/" not in name and not name.endswith("/"))
        wheels.append({"path": str(wheel.resolve()), "name": wheel.name,
                       "sha256": digest(wheel), "bytes": wheel.stat().st_size})
    layer = container_setup._build_unpacked_wheels_tar(base, "sp_base", ".swegemma_base_injected")
    with tarfile.open(layer) as archive:
        actual = {member.name.removeprefix("./") for member in archive.getmembers()}
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(f"SDK staging dropped wheel members: {missing}")
    staged = output / "frozen_base_site_packages.tar"
    shutil.copyfile(layer, staged)
    source = Path(inspect.getsourcefile(container_setup)).resolve()
    manifest = {"sha256": digest(staged), "bytes": staged.stat().st_size,
                "swegemma_version": "0.2.11", "sdk_source": str(source),
                "sdk_source_sha256": digest(source), "base_wheels": wheels,
                "large_wheels_not_preseeded": {
                    name: {"path": str(path.resolve()), "name": path.name,
                           "sha256": digest(path), "bytes": path.stat().st_size}
                    for name, path in large.items()},
                "marker": ".swegemma_base_injected",
                "scope": "Unmodified SDK wheel staging; invocation-local cache; separate compatibility layer; dynamic large-wheel injection retained."}
    (output / "frozen_base_wheels.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"sha256": manifest["sha256"], "base_wheels": len(base)}))


if __name__ == "__main__":
    main()
