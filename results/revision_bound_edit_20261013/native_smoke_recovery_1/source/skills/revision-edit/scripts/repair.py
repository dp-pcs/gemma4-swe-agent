#!/usr/bin/env python3
"""Bounded, source-only repository repair operations; Python standard library only."""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile


OUTPUT_LIMIT = 4800
REPLACEMENT_LIMIT = 1024 * 1024


class RepairError(Exception):
    pass


def emit(result):
    """Keep complete JSON, shortening values explicitly rather than slicing JSON."""
    result.setdefault("omitted", False)
    while len(json.dumps(result, ensure_ascii=True, separators=(",", ":"))) > OUTPUT_LIMIT:
        candidates = []

        def collect(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if isinstance(child, str) and len(child) > 80 and not key.endswith("revision"):
                        candidates.append((len(json.dumps(child)), value, key, child))
                    elif isinstance(child, list) and child:
                        candidates.append((len(json.dumps(child)), value, key, child))
                    if isinstance(child, dict):
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    if isinstance(child, dict):
                        collect(child)

        collect(result)
        if not candidates:
            result = {"ok": False, "error": "Result exceeds output limit", "omitted": True}
            break
        _, owner, key, value = max(candidates, key=lambda entry: entry[0])
        if isinstance(value, list):
            value.pop()
        else:
            owner[key] = value[:max(80, len(value) // 2)]
        result["omitted"] = True
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def text(data):
    return data.decode("utf-8", "replace")


def require_git(result):
    if result.returncode:
        raise RepairError(text(result.stderr).strip() or "git command failed")
    return result.stdout


def repository(value):
    root = Path(value).resolve(strict=True)
    if not root.is_dir():
        raise RepairError("--root must be a repository directory")
    top = text(require_git(git(root, "rev-parse", "--show-toplevel"))).strip()
    if Path(top).resolve() != root:
        raise RepairError("--root must be the repository top-level, not a subdirectory")
    return root


def source_path(root, name, must_exist=False):
    if not name or "\\" in name or "\x00" in name:
        raise RepairError("Invalid repository-relative path")
    parts = PurePosixPath(name).parts
    if PurePosixPath(name).is_absolute() or any(p in (".", "..") for p in name.split("/")):
        raise RepairError("Path must be repository-relative without traversal: " + name)
    current = root
    for part in parts:
        if part.lower() == ".git":
            raise RepairError(".git paths are prohibited")
        current = current / part
        if current.is_symlink():
            raise RepairError("Symlink paths are prohibited: " + name)
    if not current.resolve().is_relative_to(root):
        raise RepairError("Path escapes repository: " + name)
    if must_exist and not current.is_file():
        raise RepairError("Expected an existing regular file: " + name)
    if current.exists() and not current.is_file():
        raise RepairError("Expected a regular file: " + name)
    return current


def editable(name):
    parts = [part.lower() for part in PurePosixPath(name).parts]
    filename = parts[-1]
    prohibited_dirs = {"test", "tests", "testing", "testdata", "test_data", "fixtures",
                       "config", "configs", "configuration", ".github", ".git", ".gitlab"}
    if any(part in prohibited_dirs or part.startswith(("gold", "test_"))
           or part.endswith("_tests") or "harness" in part for part in parts):
        raise RepairError("Protected gold/test/config/harness path: " + name)
    if (filename.startswith("test_") or Path(filename).stem.endswith("_test")
            or filename in {"test.py", "tests.py", "conftest.py"} or filename.startswith("pytest")
            or filename in {"setup.cfg", "setup.py", "pyproject.toml", "tox.ini", "noxfile.py",
                            "makefile", "dockerfile", ".coveragerc", ".gitignore", ".gitattributes"}
            or filename.startswith("requirements")
            or filename.endswith((".yaml", ".yml", ".toml", ".ini", ".cfg", ".json"))
            or filename.startswith(("config.", "config_"))):
        raise RepairError("Protected test/config file: " + name)


def tracked_python(root):
    names = require_git(git(root, "ls-files", "-z", "--cached")).split(b"\x00")
    return sorted({os.fsdecode(name) for name in names if name and name.endswith(b".py")})


def locate(root, args):
    if not args.query:
        raise RepairError("Search query must not be empty")
    if args.symbol and not args.query.isidentifier():
        raise RepairError("--symbol requires one Python identifier")
    pattern = re.compile(r"(?<!\w)" + re.escape(args.query) + r"(?!\w)") if args.symbol else None
    matches = []
    omitted = False
    for name in tracked_python(root):
        path = source_path(root, name)
        if not path.exists():
            continue
        with path.open(encoding="utf-8", errors="replace") as stream:
            for number, line in enumerate(stream, 1):
                if (pattern.search(line) if pattern else args.query in line):
                    if len(matches) == args.limit:
                        omitted = True
                        break
                    matches.append({"path": name, "line": number, "text": line.rstrip("\r\n")})
        if omitted:
            break
    emit({"ok": True, "matches": matches, "omitted": omitted})
    return 0


def file_lines(data):
    """Split physical lines without changing any newline or final-line bytes."""
    lines = re.findall(rb"[^\r\n]*(?:\r\n|\r|\n|$)", data)
    if lines and not lines[-1]:
        lines.pop()
    return lines


def revision(data):
    return hashlib.sha256(data).hexdigest()


def read_source(path):
    data = path.read_bytes()
    data.decode("utf-8", "strict")
    return data


def inspect(root, args):
    if args.start < 1 or args.end < args.start or args.end - args.start + 1 > 200:
        raise RepairError("Range must be 1-based inclusive, ordered, and at most 200 lines")
    path = source_path(root, args.path, must_exist=True)
    data = read_source(path)
    raw_lines = file_lines(data)
    if args.end > len(raw_lines):
        raise RepairError("Requested range extends beyond end of file")
    lines = [{"line": number, "text": line.decode("utf-8").rstrip("\r\n")}
             for number, line in enumerate(raw_lines[args.start - 1:args.end], args.start)]
    emit({"ok": True, "path": args.path, "revision": revision(data),
          "total_lines": len(raw_lines), "lines": lines})
    return 0


def syntax(root, names):
    errors = []
    checked = []
    for name in names:
        path = source_path(root, name)
        if name.endswith(".py") and path.exists():
            checked.append(name)
            try:
                compile(path.read_bytes(), name, "exec")
            except (SyntaxError, ValueError) as exc:
                errors.append({"path": name, "line": getattr(exc, "lineno", None),
                               "error": str(exc)})
    return checked, errors


def revision_guard(root, name, expected):
    if expected != "missing" and not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise RepairError("Revision must be a 64-character lowercase SHA256, or missing for creation")
    path = source_path(root, name)
    data = read_source(path) if path.exists() else None
    actual = revision(data) if data is not None else "missing"
    if actual != expected:
        raise RepairError("Revision mismatch: expected " + expected + ", current " + actual)
    return path, data


def computed_diff(name, before, after):
    def git_lines(data):
        if not data:
            return []
        lines = data.decode("utf-8").split("\n")
        return [line + "\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    old = git_lines(before)
    new = git_lines(after)
    chunks = difflib.unified_diff(old, new,
                                  fromfile="a/" + name if before is not None else "/dev/null",
                                  tofile="b/" + name if after is not None else "/dev/null")
    output = []
    for chunk in chunks:
        output.append(chunk)
        if not chunk.endswith("\n"):
            output.append("\n\\ No newline at end of file\n")
    return "".join(output)


def replace(root, args):
    source_path(root, args.path)
    editable(args.path)
    replacement = args.replacement.encode("utf-8", "strict")
    if len(replacement) > REPLACEMENT_LIMIT:
        raise RepairError("Replacement must be at most 1 MiB of literal UTF-8")
    path, before = revision_guard(root, args.path, args.revision)
    if before is None:
        if args.start != 1 or args.end != 0:
            raise RepairError("Creation requires revision missing, START 1, END 0")
        after = replacement
        mode = 0o644
    else:
        lines = file_lines(before)
        insertion = args.end == args.start - 1
        if (args.start < 1 or args.start > len(lines) + (1 if insertion else 0)
                or args.end < args.start - 1 or args.end > len(lines)):
            raise RepairError("Range must select existing 1-based inclusive lines, or END=START-1 for insertion")
        after = b"".join(lines[:args.start - 1]) + replacement + b"".join(lines[args.end:])
        mode = stat.S_IMODE(path.stat().st_mode)
    if after == before:
        raise RepairError("Replacement makes no byte changes; not applied")
    checked = []
    if args.path.endswith(".py"):
        checked.append(args.path)
        try:
            compile(after, args.path, "exec")
        except (SyntaxError, ValueError) as exc:
            emit({"ok": False, "applied": False, "path": args.path,
                  "revision": args.revision, "error": "Replacement Python source has syntax errors",
                  "syntax_errors": [{"path": args.path, "line": getattr(exc, "lineno", None),
                                     "error": str(exc)}]})
            return 1
    diff = computed_diff(args.path, before, after)
    missing_dirs = []
    parent = path.parent
    while parent != root and not parent.exists():
        missing_dirs.append(parent)
        parent = parent.parent
    created_dirs = []
    temporary = None
    installed = False
    try:
        for directory in reversed(missing_dirs):
            directory.mkdir()
            created_dirs.append(directory)
        with tempfile.NamedTemporaryFile(prefix=".repair-", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(after)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
        # This is a stale-read guard, not synchronization with noncooperating writers.
        path, _ = revision_guard(root, args.path, args.revision)
        os.replace(temporary, path)
        installed = True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if not installed:
            for directory in reversed(created_dirs):
                directory.rmdir()
    emit({"ok": True, "applied": True, "changed": [args.path],
          "previous_revision": args.revision, "revision": revision(after),
          "total_lines": len(file_lines(after)), "syntax_checked": checked, "diff": diff})
    return 0


def remove(root, args):
    source_path(root, args.path)
    editable(args.path)
    if args.revision == "missing":
        raise RepairError("remove requires the SHA256 revision of an existing file")
    path, before = revision_guard(root, args.path, args.revision)
    diff = computed_diff(args.path, before, None)
    path, _ = revision_guard(root, args.path, args.revision)
    path.unlink()
    emit({"ok": True, "applied": True, "changed": [args.path],
          "previous_revision": args.revision, "revision": "missing", "diff": diff})
    return 0


def changed_names(root):
    changed = require_git(git(root, "diff", "--name-only", "-z", "HEAD", "--"))
    untracked = require_git(git(root, "ls-files", "--others", "--exclude-standard", "-z"))
    return sorted({os.fsdecode(name) for name in (changed + untracked).split(b"\x00") if name})


def check(root, args):
    names = changed_names(root)
    protected = []
    for name in names:
        source_path(root, name)
        try:
            editable(name)
        except RepairError as exc:
            protected.append(str(exc))
    checked, errors = syntax(root, names)
    result = {"ok": not (protected or errors), "changed": names,
              "syntax_checked": checked, "syntax_errors": errors, "protected_changes": protected}
    targets = args.pytest or []
    for target in targets:
        filename = target.split("::", 1)[0]
        if not filename.endswith(".py") or target.startswith("-"):
            raise RepairError("--pytest must select an existing .py file or file::node, never a directory")
        source_path(root, filename, must_exist=True)
    if protected or errors:
        result["pytest"] = "not run: fix protected changes or syntax errors first"
        emit(result)
        return 1
    if not targets:
        result["pytest"] = "not requested"
        emit(result)
        return 0
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    # Keep pytest cache/output outside the repository, and avoid compiling bytecode.
    with tempfile.TemporaryDirectory(prefix="repair-check-", dir="/tmp") as scratch:
        if Path(scratch).resolve().is_relative_to(root):
            raise RepairError("Cannot place pytest scratch outside --root")
        command = [sys.executable, "-m", "pytest", "-q", "--tb=short", "-o", "addopts=",
                   "-o", "cache_dir=" + scratch + "/cache", "--", *targets]
        with tempfile.TemporaryFile(dir=scratch) as output:
            try:
                run = subprocess.run(command, cwd=root, env=env, stdout=output,
                                     stderr=subprocess.STDOUT, timeout=args.timeout, check=False)
                code = run.returncode
            except subprocess.TimeoutExpired:
                code = 124
                result["timeout"] = True
            size = output.tell()
            output.seek(max(0, size - 2800))
            report = text(output.read())
    result.update(ok=code == 0, pytest_targets=targets, pytest_exit_code=code,
                  pytest_output=report, omitted=size > 2800)
    emit(result)
    return code


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RepairError(message)


def main():
    parser = Parser(description=__doc__)
    parser.add_argument("--root", default="/workspace", help="Explicit repository top-level (default: /workspace)")
    commands = parser.add_subparsers(dest="operation", required=True, parser_class=Parser)
    search = commands.add_parser("locate", help="Literal or identifier search in git-tracked Python")
    search.add_argument("query")
    search.add_argument("--symbol", action="store_true", help="Match an identifier with word boundaries")
    search.add_argument("--limit", type=int, default=20, choices=range(1, 101), metavar="1..100")
    view = commands.add_parser("inspect", help="Read an inclusive 1-based range, at most 200 lines")
    view.add_argument("path")
    view.add_argument("start", type=int)
    view.add_argument("end", type=int)
    apply = commands.add_parser("replace", help="Replace literal UTF-8 lines guarded by a file revision")
    apply.add_argument("path")
    apply.add_argument("revision")
    apply.add_argument("start", type=int)
    apply.add_argument("end", type=int)
    apply.add_argument("replacement", help="One literal argument; empty deletes the selected lines")
    delete = commands.add_parser("remove", help="Delete an existing editable file guarded by its revision")
    delete.add_argument("path")
    delete.add_argument("revision")
    verify = commands.add_parser("check", help="Report changed source, syntax, and optional focused pytest")
    verify.add_argument("--pytest", action="append", metavar="FILE[::NODE]", help="Repeat for explicitly selected targets")
    verify.add_argument("--timeout", type=int, default=60, choices=range(1, 61), metavar="1..60")
    args = None
    try:
        args = parser.parse_args()
        root = repository(args.root)
        return {"locate": locate, "inspect": inspect, "replace": replace,
                "remove": remove, "check": check}[args.operation](root, args)
    except (RepairError, OSError, UnicodeError) as exc:
        result = {"ok": False, "error": str(exc)}
        if args is not None and args.operation in ("replace", "remove"):
            result["applied"] = False
        emit(result)
        return 2


if __name__ == "__main__":
    sys.exit(main())
