"""Split the hash-pinned serving lock into official-wheelhouse and PyPI halves.

vm_setup.sh installs the official-wheelhouse members offline (their bytes differ
from PyPI) and the rest from PyPI under the same hashes. This writes
OUT/official.lock, OUT/pypi.lock and copies the matching wheels into OUT.

Usage: python3 -I scripts/eval_matrix/split_lock.py serving_requirements.lock WHEELHOUSE_DIR OUT_DIR
"""

import hashlib
import shutil
import sys
from pathlib import Path


def main() -> None:
    lock, wheelhouse, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    by_hash = {}
    for whl in wheelhouse.glob("*.whl"):
        by_hash[hashlib.sha256(whl.read_bytes()).hexdigest()] = whl
    official, pypi = [], []
    for line in lock.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        digest = line.split("--hash=sha256:", 1)[1].split()[0]
        if digest in by_hash:
            official.append(line)
            shutil.copy(by_hash[digest], out / by_hash[digest].name)
        else:
            pypi.append(line)
    (out / "official.lock").write_text("\n".join(official) + "\n")
    (out / "pypi.lock").write_text("\n".join(pypi) + "\n")
    print(f"official: {len(official)}  pypi: {len(pypi)}  wheels copied to {out}")


if __name__ == "__main__":
    main()
