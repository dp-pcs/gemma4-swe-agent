"""Build a submission ZIP from the FILES dict literal in a public Kaggle notebook.

The notebook is parsed with ast and never executed. Writes the source tree,
a fresh submission.zip (agent.yaml at the root) and provenance.json.

Usage: python3 -I scripts/build_from_notebook.py NOTEBOOK.ipynb OUT_DIR SOURCE_URL
"""

import ast
import hashlib
import json
import sys
import textwrap
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def _const_str(node: ast.AST, env: dict[str, str]) -> str | None:
    """Statically evaluate a string expression built from literals and prior constants."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _const_str(node.left, env), _const_str(node.right, env)
        return None if a is None or b is None else a + b
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            s = str(v.value) if isinstance(v, ast.Constant) else _const_str(v.value, env)
            if s is None:
                return None
            parts.append(s)
        return "".join(parts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr in ("strip", "lstrip", "rstrip") and not node.args:
            s = _const_str(node.func.value, env)
            return None if s is None else getattr(s, node.func.attr)()
        if node.func.attr == "dedent" and len(node.args) == 1:
            s = _const_str(node.args[0], env)
            return None if s is None else textwrap.dedent(s)
        if node.func.attr == "loads" and len(node.args) == 1:
            s = _const_str(node.args[0], env)
            return None if s is None else s
    return None


def extract_files(notebook: Path) -> dict[str, str]:
    nb = json.loads(notebook.read_text(encoding="utf-8"))
    env: dict[str, str] = {}
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        try:
            tree = ast.parse("".join(cell["source"]))
        except SyntaxError:
            continue
        for node in tree.body:
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                continue
            name, value = node.targets[0].id, node.value
            if name != "FILES":
                s = _const_str(value, env)
                if s is not None:
                    env[name] = s
                continue
            if isinstance(value, ast.Call) and getattr(value.func, "attr", None) == "loads":
                raw = _const_str(value.args[0], env)
                if raw is None:
                    raise SystemExit("FILES = json.loads(...) argument is not a literal")
                return json.loads(raw)
            if isinstance(value, ast.Dict):
                files = {}
                for k, v in zip(value.keys, value.values):
                    kk, vv = _const_str(k, env), _const_str(v, env)
                    if kk is None or vv is None:
                        raise SystemExit(f"Unresolvable FILES entry: {ast.dump(k)[:80]}")
                    files[kk] = vv
                return files
            return ast.literal_eval(value)
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
