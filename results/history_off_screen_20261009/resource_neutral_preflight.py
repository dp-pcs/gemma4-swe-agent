#!/usr/bin/env python3
"""Inspect/import the real current local stack without loading a model or CUDA."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import traceback

EXPECTED = {"swegemma": "0.2.11", "adk-submission": "0.2.13", "adk-eval-core": "0.1.0",
            "vllm": "0.19.1", "torch": "2.10.0", "torchaudio": "2.10.0", "torchvision": "0.25.0"}
MODULES = ["torch", "torchvision", "torchaudio", "transformers", "swegemma", "adk_submission",
           "adk_eval_core", "vllm", "vllm._C", "vllm.reasoning.gemma4_reasoning_parser",
           "vllm.tool_parsers.gemma4_tool_parser", "vllm.model_executor.models.gemma4",
           "vllm.model_executor.models.gemma4_mm"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--protected-root", type=Path, default=Path("/home/davidproctor/competition"))
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(args.protected_root.resolve()):
        raise RuntimeError("Refusing to write preflight evidence in retained original root")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["PYTHONNOUSERSITE"] = "1"
    result = {"timestamp": datetime.now(timezone.utc).isoformat(), "python": sys.version,
              "executable": sys.executable, "prefix": sys.prefix, "versions": {},
              "imports": {}, "errors": [], "no_model_instantiation": True,
              "no_server_started": True, "network_downloads_disabled": True,
              "gpu_visibility": "hidden", "cuda_initialized_before": None,
              "cuda_initialized_after": None, "model_metadata": None}
    prefix = Path(sys.prefix).resolve()
    if prefix == Path(sys.base_prefix).resolve() or prefix.name != ".venv-current":
        result["errors"].append("Must run with the isolated .venv-current Python")
    if sys.version_info[:2] != (3, 12):
        result["errors"].append("Official serving wheelhouse requires the selected Python 3.12 stack")
    for name, expected in EXPECTED.items():
        try:
            distribution = importlib.metadata.distribution(name)
            location = Path(distribution.locate_file("")).resolve()
            result["versions"][name] = {"version": distribution.version, "root": str(location)}
            if distribution.version.split("+", 1)[0] != expected or not location.is_relative_to(prefix):
                result["errors"].append(f"Wrong version/origin for {name}: {distribution.version}, {location}")
        except Exception as error:
            result["errors"].append(f"Missing distribution {name}: {error}")
    if not result["errors"]:
        for name in MODULES:
            try:
                module = importlib.import_module(name)
                filename = getattr(module, "__file__", None)
                origin = Path(filename).resolve() if filename else None
                result["imports"][name] = {"origin": str(origin) if origin else None}
                if origin is None or not origin.is_relative_to(prefix):
                    raise RuntimeError(f"Import outside isolated venv: {name}: {origin}")
                if name == "torch":
                    result["cuda_initialized_before"] = module.cuda.is_initialized()
                    result["torch_compiled_cuda"] = module.version.cuda
                torch = sys.modules.get("torch")
                if torch is not None and torch.cuda.is_initialized():
                    raise RuntimeError(f"Import unexpectedly initialized CUDA: {name}")
            except Exception as error:
                result["imports"][name] = {"error": repr(error), "traceback": traceback.format_exc()}
                result["errors"].append(f"Import failed: {name}: {error}")
                # Imports are real; never replace a missing library or model module
                # with a shim or fake success. Later dependencies may still diagnose.
    torch = sys.modules.get("torch")
    if torch is not None:
        result["cuda_initialized_after"] = torch.cuda.is_initialized()
        if result["cuda_initialized_after"]:
            result["errors"].append("Resource-neutral invariant violated: CUDA initialized")
    if args.model_root:
        root = args.model_root.resolve()
        files = {}
        for name in ["config.json", "tokenizer_config.json", "generation_config.json",
                     "model.safetensors.index.json"]:
            path = root / name
            if path.is_file():
                files[name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
        result["model_metadata"] = {"root": str(root), "files": files}
        config = root / "config.json"
        if not config.is_file():
            result["errors"].append("Local model config.json missing; no model download attempted")
        else:
            try:
                result["model_metadata"]["config"] = json.loads(config.read_text())
            except Exception as error:
                result["errors"].append(f"Cannot read local model config: {error}")
    result["status"] = "resource_neutral_imports_ok" if not result["errors"] else "blocked"
    result["scope"] = "Real imports/ABI loading and local config bytes only, not GPU execution or model serving readiness. Missing libcuda on a CPU host is an explicit unresolved preflight result."
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "errors": result["errors"], "output": str(output)}))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
