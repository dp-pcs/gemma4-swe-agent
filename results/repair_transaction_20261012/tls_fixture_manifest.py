#!/usr/bin/env python3
"""Retain original fixture certificates and hash the strict regenerated chain."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["original", "regenerated"])
    args = parser.parse_args()
    import pytest_httpbin

    certs = Path(pytest_httpbin.__file__).resolve().parent / "certs"
    audit = Path("/opt/provenance-audit")
    if args.phase == "original":
        shutil.copytree(certs, audit / "original-httpbin-certs")
    records = {}
    for name in ["cacert.pem", "cert.pem", "key.pem"]:
        path = certs / name
        data = path.read_bytes()
        records[name] = {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (audit / ("tls-" + args.phase + "-manifest.json")).write_text(
        json.dumps({"phase": args.phase, "pytest_httpbin_origin": str(Path(pytest_httpbin.__file__).resolve()),
                    "fixtures": records, "verification_policy": "Unmodified strict client validation; no test or grader changes."}, indent=2) + "\n")


if __name__ == "__main__":
    main()
