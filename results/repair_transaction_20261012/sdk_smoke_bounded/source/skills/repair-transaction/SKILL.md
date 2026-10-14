---
name: repair-transaction
description: Locate and inspect Python source, apply a source-only unified diff transactionally, and run an explicitly focused check.
---

# Repair transaction

Offline helper: Python standard library, workspace git/pytest only. Operations emit complete JSON under 4,800 characters. `omitted: true` flags bounded matching/source/failure output. Read `ok` and exit-code fields: the SDK may wrap nonzero exits as warnings when stdout exists.

## SDK invocation

Call `run_skill_script` with `skill_name="repair-transaction"`, `file_path="scripts/repair.py"`, and an **args list**, not `positional_args`. The pinned SDK runs materialized resources in a temporary sandbox cwd, not the repository. Always specify `--root /workspace`; never use host cwd or assume a persistent `/workspace/skills/...` path.

Examples of the complete args list:

- Literal locate: `["--root", "/workspace", "locate", "error text", "--limit", "12"]`.
- Identifier locate: `["--root", "/workspace", "locate", "function_name", "--symbol", "--limit", "12"]`. This is identifier-boundary text search, not AST symbol resolution.
- Inspect: `["--root", "/workspace", "inspect", "package/module.py", "40", "85"]`.
- Syntax/change check only: `["--root", "/workspace", "check"]`.
- Focused pytest: `["--root", "/workspace", "check", "--pytest", "tests/test_module.py::test_case", "--timeout", "60"]`. Repeat `--pytest FILE[::NODE]` for additional explicitly selected targets.

`locate` searches git-tracked `.py` files: 1–100 matches, default 20, explicit truncation. `inspect` requires a repository-relative regular file and 1-based inclusive range of at most 200 lines; returned lines are numbered. Neither operation traverses outside the root or crosses symlinks.

## Unified-diff patch

The pinned SDK's `run_skill_script` has no stdin input and its script path is temporary. Use the existing sandbox `run_command` tool to write **only the diff**, outside the repository, with a quoted heredoc:

```sh
cat > /tmp/repair-fix.patch <<'REPAIR_DIFF'
--- a/package/module.py
+++ b/package/module.py
@@ -1 +1 @@
-old_source_line
+new_source_line
REPAIR_DIFF
```

Replace the illustrative source paths and lines with the actual unified diff. Keep the delimiter quoted: shell expansion must not alter backslashes, regexes, quotes, or dollar signs. Then call:

```text
run_skill_script(
  skill_name="repair-transaction",
  file_path="scripts/repair.py",
  args=["--root", "/workspace", "patch", "--diff-file", "/tmp/repair-fix.patch"]
)
```

`--diff-file` reads an absolute regular scratch file **outside** `--root`, at most 1 MiB. It is a read-only transport; remove your own diff file afterward with `run_command`. There is no helper self-install, persistent mounted script, or encoded JSON replacement payload. For local/direct execution where the helper path is known, `python3 /absolute/path/to/repair.py --root /workspace patch <<'REPAIR_DIFF'` accepts the same literal unified diff on stdin. Both transports perform exactly the same validation and transaction.

Text edits/additions/deletions require unquoted `a/` and `b/` paths. Traversal, symlinks, binary patches, renames/copies, mode changes, and gold/test/config/harness/`.git` changes are prohibited. `git apply --check` precedes apply; malformed/rejected diffs do not mutate source. Changed Python compiles in memory without bytecode. Syntax failure restores only this patch's paths to their pre-patch contents, preserving prior user edits and removing newly created files/directories. Never bypass safeguards with another tool.

## Focused check and submission

`check` reports staged/unstaged changes, nonignored untracked files, changed `.py` syntax, and protected changes. The SDK's currently executing `.adk_exec_*.py` wrapper can appear in this report; its executor removes it before the next tool call. Do not modify SDK files. Without `--pytest`, no tests run. Targets must be existing `.py` files or `file.py::node`; directories/options/unscoped suites are rejected. Pytest timeout is 1–60 seconds, default 60, leaving room to report the result before the 90-second outer executor cap. Implicit pytest addopts are cleared; cache/output stay outside the repository. Bounded failures retain pytest's exit code (timeout: 124). Protected changes or syntax errors fail before pytest; preserve other people's edits. Then use the existing submission workflow; this skill does not submit or change baseline instructions.
