#!/usr/bin/env python3
"""Download small public setup references, not the competition archive."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import traceback
import zipfile

from prepare_cpu_environment import file_record, save

COMPETITION = "gemma-4-developer-agent"
REFERENCES = ["docker/Dockerfile.public", "docker/Dockerfile.sandbox", "docker/imp.py",
              "docker/telnetlib.py", "HARNESS_README.md", "sandbox/setup.py", "tasks.jsonl"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protected-root", type=Path, default=Path("/home/davidproctor/competition"))
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(args.protected_root.resolve()):
        raise RuntimeError("Refusing to download into retained original root")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"timestamp": datetime.now(timezone.utc).isoformat(), "status": "downloading",
                "competition": COMPETITION, "files": [], "no_competition_archive_download": True,
                "no_model_download": True, "no_upload": True}
    try:
        from kaggle.api.kaggle_api_extended import KaggleApi
        api = KaggleApi()
        api.authenticate()
        listing, token = {}, None
        while True:
            response = api.competition_list_files(COMPETITION, page_token=token, page_size=100)
            listing.update({row.name: {"name": row.name, "total_bytes": row.total_bytes,
                                      "creation_date": str(row.creation_date)} for row in response.files})
            token = response.next_page_token
            if not token:
                break
        save(output / "official_competition_file_listing.json", listing)
        for index, name in enumerate(REFERENCES):
            if name not in listing:
                raise RuntimeError(f"Required fresh public reference unavailable: {name}")
            payload_dir = output / "download_payloads" / str(index)
            payload_dir.mkdir(parents=True)
            command = ["kaggle", "competitions", "download", "-c", COMPETITION,
                       "-f", name, "-p", str(payload_dir)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=600)
            (payload_dir / "download.log").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f"Targeted reference download failed: {name}; see {payload_dir / 'download.log'}")
            payloads = [path for path in payload_dir.iterdir() if path.is_file() and path.name != "download.log"]
            if len(payloads) != 1:
                raise RuntimeError(f"Unexpected download payloads for {name}: {payloads}")
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            payload = payloads[0]
            if zipfile.is_zipfile(payload):
                with zipfile.ZipFile(payload) as archive:
                    members = [row for row in archive.infolist() if not row.is_dir()]
                    if len(members) != 1 or Path(members[0].filename).name != destination.name:
                        raise RuntimeError("Single-reference download returned an unexpected multi-file archive")
                    with archive.open(members[0]) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
            else:
                shutil.copyfile(payload, destination)
            if destination.stat().st_size != listing[name]["total_bytes"]:
                raise RuntimeError(f"Official listed reference size mismatch: {name}")
            manifest["files"].append({**file_record(destination), "official_file": listing[name]})
            save(output / "reference_download_manifest.json", manifest)
        manifest["status"] = "downloaded"
    except BaseException as error:
        manifest.update(status="failed", error=repr(error), traceback=traceback.format_exc())
        save(output / "reference_download_manifest.json", manifest)
        raise
    else:
        save(output / "reference_download_manifest.json", manifest)
        print(json.dumps({"downloaded": len(manifest["files"]), "output": str(output)}))


if __name__ == "__main__":
    main()
