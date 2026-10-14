#!/usr/bin/env python3
"""Bounded, source-only repository repair operations; Python standard library only."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile


OUTPUT_LIMIT = 4800
PATCH_LIMIT = 1024 * 1024


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
                    if isinstance(child, str) and len(child) > 80:
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


def git(root, *args, data=None):
    return subprocess.run(["git", "-C", str(root), *args], input=data,
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


def inspect(root, args):
    if args.start < 1 or args.end < args.start or args.end - args.start + 1 > 200:
        raise RepairError("Range must be 1-based inclusive, ordered, and at most 200 lines")
    path = source_path(root, args.path, must_exist=True)
    lines = []
    last = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for last, line in enumerate(stream, 1):
            if args.start <= last <= args.end:
                lines.append({"line": last, "text": line.rstrip("\r\n")})
            if last >= args.end:
                break
    if last < args.end:
        raise RepairError("Requested range extends beyond end of file")
    emit({"ok": True, "path": args.path, "lines": lines})
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


def patch(root, args):
    if args.diff_file:
        diff_path = Path(args.diff_file)
        if not diff_path.is_absolute():
            raise RepairError("--diff-file must be an absolute scratch-file path outside --root")
        diff_path = diff_path.resolve(strict=True)
        if diff_path.is_relative_to(root) or not diff_path.is_file():
            raise RepairError("--diff-file must be a regular scratch file outside --root")
        with diff_path.open("rb") as stream:
            data = stream.read(PATCH_LIMIT + 1)
    else:
        stream = getattr(sys.stdin, "buffer", sys.stdin)
        data = stream.read(PATCH_LIMIT + 1)
        if isinstance(data, str):
            data = data.encode("utf-8")
    if not data.strip() or len(data) > PATCH_LIMIT:
        raise RepairError("Provide a nonempty unified diff via stdin or --diff-file, at most 1 MiB")
    # Renames/copies, binary patches, and mode transitions are not source-text repairs.
    metadata = re.compile(rb"^(?:rename |copy |old mode |new mode |GIT binary patch|Binary files )", re.M)
    if metadata.search(data):
        raise RepairError("Only text edits/additions/deletions; no rename/copy/binary/mode changes")
    for mode in re.findall(rb"^(?:new|deleted) file mode (\d+)$", data, re.M):
        if mode not in (b"100644", b"100755"):
            raise RepairError("Only regular files may be added or deleted")
    stats = require_git(git(root, "apply", "--numstat", "-z", "--", data=data))
    # Validate both sides, not merely the destination reported by --numstat.
    remaining_old = remaining_new = 0
    header_paths = []
    for line in data.splitlines():
        if line.startswith(b"\\ No newline at end of file"):
            continue
        if remaining_old or remaining_new:
            if line.startswith(b" "):
                remaining_old -= 1
                remaining_new -= 1
            elif line.startswith(b"-"):
                remaining_old -= 1
            elif line.startswith(b"+"):
                remaining_new -= 1
            else:
                raise RepairError("Malformed unified diff hunk")
            continue
        hunk = re.match(rb"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@", line)
        if hunk:
            remaining_old = int(hunk.group(1) or b"1")
            remaining_new = int(hunk.group(2) or b"1")
        elif line.startswith((b"--- ", b"+++ ")):
            raw = line[4:].split(b"\t", 1)[0]
            if raw == b"/dev/null":
                continue
            if not raw.startswith((b"a/", b"b/")):
                raise RepairError("Use unquoted a/ and b/ repository-relative diff paths")
            name = os.fsdecode(raw.split(b"/", 1)[1])
            source_path(root, name)
            editable(name)
            header_paths.append(name)
    if remaining_old or remaining_new or not header_paths:
        raise RepairError("Incomplete unified diff")
    names = []
    for record in stats.split(b"\x00"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3 or fields[0] == b"-" or fields[1] == b"-" or not fields[2]:
            raise RepairError("Unsupported or malformed unified diff")
        name = os.fsdecode(fields[2])
        source_path(root, name)
        editable(name)
        if name not in names:
            names.append(name)
    if set(header_paths) != set(names):
        raise RepairError("Diff header paths disagree; renames are not supported")
    if not names:
        raise RepairError("Diff has no source changes")
    validation = git(root, "apply", "--check", "--", data=data)
    if validation.returncode:
        emit({"ok": False, "applied": False, "error": text(validation.stderr),
              "exit_code": validation.returncode})
        return validation.returncode
    before = {}
    missing_dirs = set()
    for name in names:
        path = source_path(root, name)
        before[name] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
        parent = path.parent
        while parent != root and not parent.exists():
            missing_dirs.add(parent)
            parent = parent.parent
    applied = git(root, "apply", "--", data=data)
    if applied.returncode:
        emit({"ok": False, "applied": False, "error": text(applied.stderr),
              "exit_code": applied.returncode})
        return applied.returncode
    try:
        checked, errors = syntax(root, names)
        if errors:
            raise RepairError("Patched Python source has syntax errors")
    except (RepairError, OSError) as exc:
        # Restore only paths touched by this patch, including their prior dirty contents.
        for name, previous in before.items():
            path = source_path(root, name)
            if previous is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(previous[0])
                path.chmod(previous[1])
        for directory in sorted(missing_dirs, key=lambda path: len(path.parts), reverse=True):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        emit({"ok": False, "applied": False, "rolled_back": True, "changed": names,
              "error": str(exc), "syntax_errors": locals().get("errors", [])})
        return 1
    emit({"ok": True, "applied": True, "changed": names, "syntax_checked": checked})
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
    apply = commands.add_parser("patch", help="Validate/apply a unified diff from stdin or external scratch")
    apply.add_argument("--diff-file", metavar="ABSOLUTE_PATH", help="Read-only diff transport outside --root (SDK has no stdin)")
    verify = commands.add_parser("check", help="Report changed source, syntax, and optional focused pytest")
    verify.add_argument("--pytest", action="append", metavar="FILE[::NODE]", help="Repeat for explicitly selected targets")
    verify.add_argument("--timeout", type=int, default=60, choices=range(1, 61), metavar="1..60")
    try:
        args = parser.parse_args()
        root = repository(args.root)
        return {"locate": locate, "inspect": inspect, "patch": patch, "check": check}[args.operation](root, args)
    except (RepairError, OSError, UnicodeError) as exc:
        emit({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
