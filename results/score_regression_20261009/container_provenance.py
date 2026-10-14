"""Reject grading against installed packages instead of the task snapshot."""
import importlib
import json
from pathlib import Path

import pytest

PACKAGES = {
    "requests": ["requests", "requests.sessions"],
    "fastapi": ["fastapi", "fastapi.routing"],
    "rich": ["rich", "rich.prompt"],
    "httpx": ["httpx", "httpx._client"],
}


def verify_imports():
    workspace = Path("/workspace").resolve()
    candidates = [
        (package, root / package)
        for package in PACKAGES
        for root in [workspace / "src", workspace]
        if (root / package / "__init__.py").is_file()
    ]
    if len(candidates) != 1:
        raise pytest.UsageError(f"Cannot identify one task source package: {candidates}")
    package, source = candidates[0]
    source = source.resolve()
    if not source.is_relative_to(workspace):
        raise pytest.UsageError(f"IMPORT_PROVENANCE_REJECTED source: {source}; expected below {workspace}")
    origins = {}
    for name in PACKAGES[package]:
        module = importlib.import_module(name)
        filename = getattr(module, "__file__", None)
        if not filename:
            raise pytest.UsageError(f"IMPORT_PROVENANCE_REJECTED {name}: missing file origin; expected {source}")
        origin = Path(filename).resolve()
        origins[name] = str(origin)
        if not origin.is_relative_to(source):
            raise pytest.UsageError(f"IMPORT_PROVENANCE_REJECTED {name}: {origin}; expected {source}")
    print("IMPORT_PROVENANCE " + json.dumps(origins, sort_keys=True), flush=True)


def pytest_sessionstart(session):
    verify_imports()


def pytest_collection_finish(session):
    verify_imports()
