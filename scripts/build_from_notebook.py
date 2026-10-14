"""Build a submission ZIP from the FILES dict literal in a public Kaggle notebook.

The notebook is parsed with ast and never executed. Writes the source tree,
a fresh submission.zip (agent.yaml at the root) and provenance.json.

Usage: python3 -I scripts/build_from_notebook.py NOTEBOOK.ipynb OUT_DIR SOURCE_URL
"""

import ast
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def extract_files(notebook: Path) -> dict[str, str]:
    nb = json.loads(notebook.read_text(encoding="utf-8"))
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "FILES"
            ):
                return ast.literal_eval(node.value)
    raise SystemExit("No FILES literal found")


def main() -> None:
    notebook, out_dir, source_url = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    if out_dir.exists():
        raise SystemExit(f"{out_dir} already exists; use a fresh directory")
    files = extract_files(notebook)
    src = out_dir / "source"
    for name, text in files.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    zip_path = out_dir / "submission.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(files):
            z.write(src / name, name)

    with zipfile.ZipFile(zip_path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    mismatched = [n for n in files if members.get(n) != (src / n).read_bytes()]
    if sorted(members) != sorted(files) or mismatched:
        raise SystemExit(f"ZIP/source mismatch: {mismatched}")

    provenance = {
        "built_utc": datetime.now(timezone.utc).isoformat(),
        "source_notebook": source_url,
        "notebook_sha256": hashlib.sha256(notebook.read_bytes()).hexdigest(),
        "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "members": {
            n: hashlib.sha256(b).hexdigest() for n, b in sorted(members.items())
        },
    }
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()
