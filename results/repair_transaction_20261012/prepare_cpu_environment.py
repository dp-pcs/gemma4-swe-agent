#!/usr/bin/env python3
"""Prepare a separate Linux clone; freeze online explicitly, install offline only.

No GPU inspection, model startup, model download, test execution, or resource
creation. New outputs live below work-root/results/history_off_screen_20261011;
retained historical outputs are never rewritten.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import email
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

RUN_NAME = "repair_transaction_20261012"
SDK_HASHES = {
    "swegemma-0.2.11-py3-none-any.whl": "63f054a3d42eb6c582e2b42195f96b22f4b9ee69d6e42ae62cedeb4dd6cf5480",
    "adk_submission-0.2.13-py3-none-any.whl": "69642a13145151040fb96b483170f96cc7cff1d509851d21d08bc7a0ad3ef371",
    "adk_eval_core-0.1.0-py3-none-any.whl": "ca261146828a3d8ab0894b4766bc61a0905e3ef94f8eede17561a4a058404e1f",
}
SERVING_ROOTS = ["pip==25.3", "swegemma==0.2.11", "adk-submission==0.2.13",
                 "adk-eval-core==0.1.0", "vllm==0.19.1", "torch==2.10.0",
                 "torchaudio==2.10.0", "torchvision==0.25.0",
                 "opentelemetry-api==1.41.1", "opentelemetry-sdk==1.41.1",
                 "opentelemetry-exporter-otlp==1.41.1", "fastapi==0.135.1",
                 "prometheus-fastapi-instrumentator==7.1.0", "xgrammar==0.2.6"]
# Resolve supplied optional-wheel conflicts without altering core SDK/model wheels.
SERVING_COMPATIBILITY_OVERRIDES = {
    "opentelemetry-exporter-otlp": "1.41.1",
    "prometheus-fastapi-instrumentator": "7.1.0",
    "xgrammar": "0.2.6",
}
PYTEST_VERSION = "8.4.2"
BASE_ROOTS = ["pip==25.3", "pytest==" + PYTEST_VERSION, "pytest-timeout==2.1.0", "typer",
              "pdm-backend", "setuptools", "wheel", "poetry-core", "hatchling",
              "flit-core", "editables", "trustme", "pytest-cov", "pytest-mock",
              "typing-inspection==0.4.4"]
SANDBOX_PROFILE_ROOTS = {
    "framework": [],
    "httpbin": ["pytest-httpbin==2.0.0", "httpbin~=0.10.0"],
}
# Resolve HTTPX with its normal httpcore/h11 transport dependency closure.
# Keep pytest identical across the base and the precedence-taking import layer.
COMPATIBILITY_ROOTS = ["pytest==" + PYTEST_VERSION, "httpx==0.28.1",
                       "starlette==0.48.0", "pydantic==2.12.5",
                       "inline-snapshot==0.21.1", "dirty-equals==0.9.0",
                       "python-multipart==0.0.20", "Flask==2.2.5", "Werkzeug==2.2.3"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def file_record(path: Path) -> dict:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": sha256(path)}


def norm(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def wheel_record(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = [name for name in archive.namelist()
                 if name.count("/") == 1 and name.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise RuntimeError(f"Cannot identify wheel metadata: {path}")
        metadata = email.message_from_bytes(archive.read(names[0]))
    return {**file_record(path), "name": norm(metadata["Name"]),
            "version": metadata["Version"], "requires_python": metadata.get("Requires-Python"),
            "requires_dist": metadata.get_all("Requires-Dist", [])}


def write_lock(wheel_dir: Path, output: Path) -> list[dict]:
    records = [wheel_record(path) for path in sorted(wheel_dir.glob("*.whl"))]
    if not records:
        raise RuntimeError(f"No wheels downloaded into {wheel_dir}")
    names = [record["name"] for record in records]
    if len(names) != len(set(names)):
        raise RuntimeError(f"Multiple versions or wheel variants in {wheel_dir}")
    output.write_text("".join(f'{record["name"]}=={record["version"]} --hash=sha256:{record["sha256"]}\n'
                              for record in sorted(records, key=lambda row: row["name"])))
    save(output.with_suffix(".manifest.json"), records)
    return records


def resolve_snapshot(root: Path, task: dict) -> tuple[Path, Path | None, Path | None]:
    # Exact current SDK resolve_task_snapshot_paths ordering, without importing
    # any serving/model code during pre-install disk inventory.
    instance = task["instance_id"]
    fallback = root / "fallbacks" / f"{instance}.tgz"
    if fallback.exists():
        return fallback, None, None
    repo = re.sub(r"[/\\-]+", "_", task["repo"].strip()).strip("_")
    base = next((path for path in [root / "base_snapshots" / f"base_{repo}.tgz",
                                  root / f"base_{repo}.tgz"] if path.exists()), None)
    if base is not None:
        patch = next((path for path in [root / "patches" / f"{instance}.patch",
                                       root / f"{instance}.patch"] if path.exists()), None)
        if patch is not None:
            return base, base, patch if patch.stat().st_size else None
    direct = next((path for path in [root / f"{instance}.tgz", root / f"{instance}.tar.gz"]
                   if path.exists()), root / f"{instance}.tgz")
    return direct, None, None


def inventory(data: Path, output: Path) -> dict:
    tasks_file = data / "tasks.jsonl"
    tasks = [json.loads(line) for line in tasks_file.read_text().splitlines() if line.strip()]
    if len(tasks) != 129 or len({task["instance_id"] for task in tasks}) != 129:
        raise RuntimeError("Expected all 129 distinct public cases")
    cached = {}

    def record(path: Path | None):
        if path is None:
            return None
        key = str(path.resolve())
        if key not in cached:
            cached[key] = file_record(path) if path.is_file() and path.stat().st_size else {"path": key, "missing_or_empty": True}
        return cached[key]

    rows = []
    for task in tasks:
        short = task["repo"].split("/")[-1]
        slug = task["repo"].replace("/", "_")
        commit = task.get("base_commit", "")
        candidates = [f"{short}_{commit}", f"{slug}_{commit}", slug, short]
        paths = resolve_snapshot(data / "snapshots", task)
        graph = next((data / "graphs" / f"{name}.json" for name in candidates
                      if (data / "graphs" / f"{name}.json").is_file()), None)
        embedding = next((data / "embeddings" / f"{name}.npz" for name in candidates
                          if (data / "embeddings" / f"{name}.npz").is_file()), None)
        rows.append({"instance_id": task["instance_id"], "repo": task["repo"],
                     "base_commit": commit, "snapshot": record(paths[0]),
                     "base_snapshot": record(paths[1]), "incremental_patch": record(paths[2]),
                     "graph": record(graph), "embedding": record(embedding),
                     "available": paths[0].is_file() and paths[0].stat().st_size > 0
                                  and graph is not None and graph.stat().st_size > 100
                                  and embedding is not None and embedding.stat().st_size > 100})
    manifest = {"tasks": file_record(tasks_file), "count": len(rows),
                "available_count": sum(row["available"] for row in rows), "cases": rows,
                "scope": "Read-only presence/byte provenance, not snapshot reconstruction or grading eligibility."}
    save(output, manifest)
    return manifest


def protected_origins(root: Path) -> dict:
    paths = []
    for relative in ["competition_data/docker", "competition_data/sandbox"]:
        directory = root / relative
        if directory.exists():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    for relative in ["competition_data/tasks.jsonl", "submission_build/source_only_20261008/submission.zip",
                     "results/submission_strategy_20261009/thinking_without_history_submission.zip"]:
        path = root / relative
        if path.is_file():
            paths.append(path)
    for venv in root.glob(".venv*"):
        if not venv.is_dir():
            continue
        cfg = venv / "pyvenv.cfg"
        if cfg.is_file():
            paths.append(cfg)
        for sites in venv.glob("lib/python*/site-packages"):
            paths.extend(sites.glob("swegemma-*.dist-info/METADATA"))
            paths.extend(sites.glob("adk_submission-*.dist-info/METADATA"))
            paths.extend(sites.glob("adk_eval_core-*.dist-info/METADATA"))
            for package in ["swegemma", "adk_submission", "adk_eval_core"]:
                paths.extend((sites / package).rglob("*.py"))
    return {str(path.resolve()): file_record(path) for path in sorted(set(paths))}


class Setup:
    def __init__(self, args):
        self.args = args
        self.root = args.work_root.resolve()
        self.protected = args.protected_root.resolve()
        if self.root == self.protected or self.root.is_relative_to(self.protected):
            raise RuntimeError("work-root must be outside the retained original directory")
        self.run = self.root / "results" / RUN_NAME
        self.output = self.run / "cpu_setup" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8])
        self.output.mkdir(parents=True, exist_ok=False)
        self.log = (self.output / "setup.log").open("w", buffering=1)
        self.env = {**os.environ, "PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                    "PIP_CONFIG_FILE": os.devnull, "CUDA_VISIBLE_DEVICES": "",
                    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        self.env.pop("PYTHONPATH", None)
        self.env.pop("VIRTUAL_ENV", None)
        self.before = protected_origins(self.protected)
        save(self.output / "protected_origins_before.json", self.before)
        save(self.output / "arguments.json", {key: str(value) if isinstance(value, Path) else value
                                               for key, value in vars(args).items()})

    def command(self, words: list[str], capture: Path | None = None) -> str:
        words = [str(word) for word in words]
        self.log.write("\nCOMMAND " + shlex.join(words) + "\n")
        started = time.monotonic()
        chunks = []
        with subprocess.Popen(words, cwd=self.root, env=self.env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, bufsize=1) as process:
            for line in process.stdout:
                self.log.write(line)
                print(line, end="", flush=True)
                if capture is not None:
                    chunks.append(line)
            code = process.wait()
        self.log.write(f"EXIT {code} ELAPSED_SECONDS {time.monotonic() - started:.3f}\n")
        text = "".join(chunks)
        if capture is not None:
            capture.write_text(text)
        if code:
            raise RuntimeError(f"Command failed ({code}); full log: {self.output / 'setup.log'}")
        return text

    def finish(self, status: str, error: str | None = None):
        after = protected_origins(self.protected)
        save(self.output / "protected_origins_after.json", after)
        unchanged = self.before == after
        save(self.output / "status.json", {"status": status if unchanged else "rejected_origin_change",
                                           "error": error, "protected_origin_evidence_unchanged": unchanged,
                                           "evidence_scope": "Original task/setup/Docker/source ZIPs and historical SDK Python/metadata bytes; commands never target original paths for writes.",
                                           "no_model_startup": True, "no_tests": True, "no_resource_creation": True})
        self.log.close()
        if not unchanged:
            raise RuntimeError("Retained original origin evidence changed")


def linux_required():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise RuntimeError("Freeze/prepare require Linux x86_64, matching official cp312 wheels")


def freeze(setup: Setup):
    args = setup.args
    linux_required()
    if not args.allow_index_resolution:
        raise RuntimeError("freeze requires explicit --allow-index-resolution; later installation is strictly offline")
    official = args.wheelhouse.resolve()
    for name, expected in SDK_HASHES.items():
        path = official / name
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Missing/wrong supplied current SDK wheel: {path}")
    origins = [wheel_record(path) for path in sorted(official.glob("*.whl"))]
    supplied_manifest = official / "downloaded_wheels.json"
    supplied = json.loads(supplied_manifest.read_text())["wheels"]
    supplied_by_file = {row["name"]: row for row in supplied}
    if len(supplied_by_file) != 41 or len(origins) != 41:
        raise RuntimeError("Expected all 41 official wheels and parent-recorded download hashes")
    for row in origins:
        origin = supplied_by_file.get(Path(row["path"]).name)
        if origin is None or row["sha256"] != origin["sha256"] or row["bytes"] != origin["bytes"]:
            raise RuntimeError(f"Supplied official download provenance changed: {row['path']}")
    official_by_name = {row["name"]: row for row in origins}
    if not any(row["name"] == "vllm" and row["version"] == "0.19.1" for row in origins):
        raise RuntimeError("Fresh official vLLM 0.19.1 wheel must be supplied in --wheelhouse")
    if len({row["name"] for row in origins}) != len(origins):
        raise RuntimeError("Official wheelhouse contains duplicate distributions; do not mix old wheels")
    save(setup.output / "official_wheel_origins.json", origins)
    constraints = setup.output / "official_constraints.txt"
    constraints.write_text("".join(
        f'{row["name"]}=={SERVING_COMPATIBILITY_OVERRIDES.get(row["name"], row["version"])}\n'
        for row in origins))
    resolver = setup.output / "resolver-venv"
    setup.command([args.python_executable, "-m", "venv", str(resolver)])
    python = resolver / "bin" / "python"
    setup.command([python, "-c", "import sys; assert sys.version_info[:2] == (3,12), sys.version"])
    serving = setup.output / "serving_wheels"
    serving.mkdir()
    roots = setup.output / "serving_roots.txt"
    roots.write_text("\n".join(SERVING_ROOTS) + "\n")
    report = setup.output / "serving_resolution_report.json"
    setup.command([python, "-m", "pip", "install", "--dry-run", "--ignore-installed",
                   "--only-binary=:all:", "--index-url", "https://pypi.org/simple",
                   "--find-links", official, "--constraint", constraints, "--report", report,
                   "-r", roots])
    resolved = json.loads(report.read_text())["install"]
    pins = setup.output / "serving_resolved_pins.txt"
    download_requirements = []
    for item in resolved:
        name = norm(item["metadata"]["name"])
        origin = official_by_name.get(name)
        if origin is not None and origin["version"] == item["metadata"]["version"]:
            url = Path(origin["path"]).as_uri()
            digest = origin["sha256"]
        else:
            url = item["download_info"]["url"]
            digest = item["download_info"]["archive_info"]["hashes"]["sha256"]
        download_requirements.append(f"{name} @ {url} --hash=sha256:{digest}\n")
    pins.write_text("".join(download_requirements))
    setup.command([python, "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
                   "--require-hashes", "--dest", serving, "-r", pins])
    serving_records = write_lock(serving, setup.output / "serving_requirements.lock")
    locked = {row["name"]: row["version"] for row in serving_records}
    if locked != {norm(item["metadata"]["name"]): item["metadata"]["version"] for item in resolved}:
        raise RuntimeError("Downloaded dependency closure differs from recorded resolver report")
    for name, expected in SDK_HASHES.items():
        if sha256(serving / name) != expected:
            raise RuntimeError(f"Downloaded SDK wheel lost supplied organizer origin: {name}")
    cross = ["--python-version", "3.13", "--implementation", "cp", "--abi", "cp313", "--abi", "abi3", "--abi", "none"]
    for minor in range(5, 42):
        cross.extend(["--platform", f"manylinux_2_{minor}_x86_64"])
    cross.extend(["--platform", "manylinux2014_x86_64", "--platform", "linux_x86_64"])
    variants = {}
    base_roots = BASE_ROOTS + SANDBOX_PROFILE_ROOTS[args.sandbox_profile]
    for version in args.pygments_version or ["2.13.0"]:
        directory = setup.output / "sandbox" / args.sandbox_profile / ("pygments-" + version)
        for layer, requirements in [("base", base_roots), ("compatibility", COMPATIBILITY_ROOTS + ["Pygments==" + version])]:
            wheels = directory / (layer + "_wheels")
            wheels.mkdir(parents=True)
            requirements_file = directory / (layer + "_roots.txt")
            requirements_file.write_text("\n".join(requirements) + "\n")
            setup.command([python, "-m", "pip", "download", "--only-binary=:all:",
                           "--index-url", "https://pypi.org/simple", *cross,
                           "--dest", wheels, "-r", requirements_file])
            write_lock(wheels, directory / (layer + "_requirements.lock"))
        variants[version] = str(directory)
    save(setup.output / "frozen_stack.json", {"serving_lock": str(setup.output / "serving_requirements.lock"),
                                              "serving_wheels": str(serving), "sandbox_variants": variants,
                                              "sandbox_profile": args.sandbox_profile,
                                              "run_name": RUN_NAME,
                                              "official_constraints": str(constraints), "official_origins": origins,
                                              "serving_compatibility_overrides": SERVING_COMPATIBILITY_OVERRIDES,
                                              "resolution_is_explicit_not_scorer_parity": True})


def prepare(setup: Setup):
    args = setup.args
    linux_required()
    frozen_path = args.frozen_stack.resolve()
    frozen = json.loads(frozen_path.read_text())
    frozen_profile = frozen.get("sandbox_profile")
    if frozen_profile != args.sandbox_profile:
        raise RuntimeError(
            f"Frozen sandbox profile {frozen_profile!r} does not match requested "
            f"{args.sandbox_profile!r}; freeze a new explicitly profiled stack")
    lock = Path(frozen["serving_lock"])
    wheels = Path(frozen["serving_wheels"])
    expected = json.loads(lock.with_suffix(".manifest.json").read_text())
    for row in expected:
        path = wheels / Path(row["path"]).name
        if sha256(path) != row["sha256"]:
            raise RuntimeError(f"Frozen wheel changed: {path}")
    reference = args.reference_root.resolve()
    reference_names = ["docker/Dockerfile.public", "docker/Dockerfile.sandbox", "docker/imp.py",
                       "docker/telnetlib.py", "HARNESS_README.md", "sandbox/setup.py", "tasks.jsonl"]
    reference_sources = {}
    for name in reference_names:
        source = reference / name
        reference_sources[name] = source
    reference_records = {name: {**file_record(source), "fresh_public_download": True}
                         for name, source in reference_sources.items()}
    save(setup.output / "reference_origins.json", reference_records)
    comparison = {name: {"used_source": reference_records[name],
                         "copied_disk": file_record(args.data_root / name)
                         if (args.data_root / name).is_file() else None}
                  for name in reference_names}
    for record in comparison.values():
        record["byte_identical"] = record["copied_disk"] is not None and record["used_source"]["sha256"] == record["copied_disk"]["sha256"]
    save(setup.output / "fresh_reference_comparison.json", comparison)
    if sha256(args.data_root / "tasks.jsonl") != args.expected_tasks_sha256 or not comparison["tasks.jsonl"]["byte_identical"]:
        raise RuntimeError("Copied/fresh task corpus differs from frozen task hash; no controls or selection substitution")
    availability = inventory(args.data_root.resolve(), setup.output / "all_129_availability.json")
    if availability["available_count"] != 129:
        raise RuntimeError("Copied disk lacks some snapshots/graphs/embeddings; see all_129_availability.json. No case replacement.")
    # Fresh public setup references drive the SDK; large copied-disk assets
    # remain read-only and byte-identical.
    data_overlay = setup.output / "current_data"
    data_overlay.mkdir()
    for name in ["snapshots", "graphs", "embeddings", "wheels"]:
        (data_overlay / name).symlink_to((args.data_root / name).resolve(), target_is_directory=True)
    for name in reference_names:
        destination = data_overlay / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reference_sources[name], destination)
    venv = setup.root / ".venv-current"
    if venv.exists():
        raise RuntimeError("Refusing to modify an existing .venv-current; choose a new work-root")
    setup.command([args.python_executable, "-m", "venv", str(venv)])
    python = venv / "bin" / "python"
    setup.command([python, "-c", "import sys; assert sys.version_info[:2] == (3,12), sys.version"])
    setup.command([python, "-m", "pip", "install", "--no-index", "--find-links", wheels,
                   "--require-hashes", "--report", setup.output / "offline_install_report.json", "-r", lock])
    setup.command([python, "-m", "pip", "list", "--format=json"], setup.output / "dependency_versions.json")
    setup.command([python, "-m", "pip", "freeze", "--all"], setup.output / "dependency_versions.txt")
    helpers = Path(__file__).resolve().parent
    setup.command([python, helpers / "freeze_base_wheels.py", "--wheels", args.data_root / "wheels", "--output", setup.output / "base_layer"])
    docker = ["sudo", "-n", "docker"] if args.sudo_docker else ["docker"]
    if "@sha256:" in args.base_image:
        base_origin = args.base_image
    else:
        registry_manifest = setup.output / "base_registry_manifest.json"
        setup.command([*docker, "manifest", "inspect", "--verbose", args.base_image], registry_manifest)
        descriptors = json.loads(registry_manifest.read_text())
        if not isinstance(descriptors, list):
            descriptors = [descriptors]
        matches = [entry["Descriptor"]["digest"] for entry in descriptors
                   if entry.get("Descriptor", {}).get("platform", {}).get("os") == "linux"
                   and entry["Descriptor"]["platform"].get("architecture") == "amd64"]
        if len(matches) != 1:
            raise RuntimeError("Cannot uniquely freeze the Linux amd64 Python registry manifest")
        repository = args.base_image.rsplit(":", 1)[0]
        base_origin = repository + "@" + matches[0]
    # Pulling only by digest preserves every historical Docker tag.
    setup.command([*docker, "pull", base_origin])
    inspection = setup.output / "base_image_inspect.json"
    setup.command([*docker, "image", "inspect", base_origin], inspection)
    base = json.loads(inspection.read_text())[0]
    if base.get("Architecture") != "amd64" or base.get("Os") != "linux" or not any(
            value.startswith("PYTHON_VERSION=3.13.") for value in base["Config"].get("Env", [])):
        raise RuntimeError("Sandbox base is not an official Linux amd64 Python 3.13 environment")
    images = {}
    for version, variant_root in frozen["sandbox_variants"].items():
        variant = Path(variant_root)
        context = setup.output / ("docker-context-" + args.sandbox_profile + "-pygments-" + version)
        context.mkdir()
        target = context / "sandbox_wheels"
        target.mkdir()
        for layer in ["base", "compatibility"]:
            layer_lock = variant / (layer + "_requirements.lock")
            manifest = json.loads(layer_lock.with_suffix(".manifest.json").read_text())
            for row in manifest:
                wheel = variant / (layer + "_wheels") / Path(row["path"]).name
                if sha256(wheel) != row["sha256"]:
                    raise RuntimeError(f"Frozen sandbox wheel changed: {wheel}")
                destination = target / wheel.name
                if destination.exists() and sha256(destination) != row["sha256"]:
                    raise RuntimeError(f"Sandbox wheel origin collision: {destination}")
                shutil.copyfile(wheel, destination)
            shutil.copyfile(layer_lock, context / ("sandbox_requirements.lock" if layer == "base" else "compatibility_requirements.lock"))
        for name in ["Dockerfile.provenance", "container_provenance.py", "regenerate_httpbin_certificates.py", "tls_fixture_manifest.py"]:
            shutil.copyfile(helpers / name, context / name)
        for name in ["imp.py", "telnetlib.py"]:
            shutil.copyfile(reference / "docker" / name, context / name)
        shutil.copyfile(setup.output / "base_layer" / "frozen_base_site_packages.tar", context / "frozen_base_site_packages.tar")
        tag = "history-off-screen:" + setup.output.name.lower() + "-" + args.sandbox_profile + "-pygments-" + version
        setup.command([*docker, "build", "--progress=plain", "--build-arg", "BASE_IMAGE=" + base_origin,
                       "--build-arg", "SANDBOX_PROFILE=" + args.sandbox_profile,
                       "--build-arg", "PYGMENTS_VERSION=" + version, "-f", context / "Dockerfile.provenance", "-t", tag, context])
        image_file = setup.output / ("image-pygments-" + version + ".json")
        setup.command([*docker, "image", "inspect", tag], image_file)
        image = json.loads(image_file.read_text())[0]
        images[version] = {"image_tag": tag, "image_id": image["Id"], "inspect_path": str(image_file),
                           "sandbox_profile": args.sandbox_profile,
                           "base_digest": base_origin, "context_files": [file_record(path) for path in sorted(context.rglob("*")) if path.is_file()]}
    save(setup.output / "image_manifest.json", images)
    save(setup.output / "cpu_environment.json", {"venv": str(venv), "python": str(python), "data_root": str(data_overlay),
                                                 "data_origin_root": str(args.data_root.resolve()),
                                                 "model_root": str(args.model_root.resolve()) if args.model_root else None,
                                                 "sandbox_profile": args.sandbox_profile, "run_name": RUN_NAME,
                                                 "frozen_stack": file_record(frozen_path), "images": images,
                                                 "controls_not_yet_run": True, "gpu_not_authorized_by_this_helper": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inventory", "freeze", "prepare"])
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, default=Path("/home/davidproctor/competition"))
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument("--reference-root", type=Path)
    parser.add_argument("--expected-tasks-sha256", default="e4b3fd60f69dbc2b9213e54eeb9636db78aefe92c1d06269d73d9f5f8f3c8ad6")
    parser.add_argument("--python-executable", default="python3.12")
    parser.add_argument("--allow-index-resolution", action="store_true")
    parser.add_argument("--frozen-stack", type=Path)
    parser.add_argument("--pygments-version", action="append")
    parser.add_argument("--sandbox-profile", choices=sorted(SANDBOX_PROFILE_ROOTS), default="httpbin",
                        help="Sandbox dependency profile (default: httpbin); freeze and prepare must match")
    parser.add_argument("--base-image", default="python:3.13-slim")
    parser.add_argument("--sudo-docker", action="store_true")
    args = parser.parse_args()
    if args.action == "freeze" and args.wheelhouse is None:
        parser.error("freeze requires --wheelhouse containing fresh supplied official wheels")
    if args.action == "prepare" and args.frozen_stack is None:
        parser.error("prepare requires --frozen-stack from the explicit freeze stage")
    if args.action == "prepare" and args.reference_root is None:
        parser.error("prepare requires --reference-root from the small fresh official reference download")
    if not args.work_root.is_dir():
        parser.error("work-root must already exist on the parent-created clone")
    setup = Setup(args)
    try:
        if args.action == "inventory":
            result = inventory(args.data_root.resolve(), setup.output / "all_129_availability.json")
            if result["available_count"] != 129:
                raise RuntimeError("Missing corpus assets; no model/case substitution permitted")
        elif args.action == "freeze":
            freeze(setup)
        else:
            prepare(setup)
    except BaseException as error:
        setup.finish("failed", repr(error))
        raise
    else:
        setup.finish("prepared" if args.action == "prepare" else "recorded")
        print("CPU_PREPARATION_OUTPUT " + str(setup.output), flush=True)


if __name__ == "__main__":
    main()
