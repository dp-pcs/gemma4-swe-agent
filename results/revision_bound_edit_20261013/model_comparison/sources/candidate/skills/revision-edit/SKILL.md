---
name: revision-edit
description: Inspect revision-bound Python source, replace exact line ranges without authored diffs, and run focused checks offline.
---

# Revision edit

Use `run_skill_script(skill_name="revision-edit", file_path="scripts/repair.py", args=["--root", "/workspace", ...])`. `args` is a list of strings. Each operation returns bounded JSON: inspect `ok`, `applied`, and failure fields even if the SDK wraps failure as a warning. `omitted` marks shortened results. Script execution uses a temporary cwd: always supply `--root /workspace`.

- Locate identifier: `["--root", "/workspace", "locate", "function_name", "--symbol", "--limit", "12"]`. Literal text works without `--symbol`. Searches tracked Python files; at most100 matches.
- Inspect: `["--root", "/workspace", "inspect", "package/module.py", "40", "85"]`. Inclusive1-based range, at most200 lines. Returns numbered source, total_lines and a full-file SHA256 revision of the same exact bytes. This is not a line hash. Copy it exactly; do not calculate or abbreviate it.
- Replace: `["--root", "/workspace", "replace", "package/module.py", "COPIED_REVISION", "41", "42", "    return value.lower()\n"]`. Replace the inclusive range with literal UTF8 text in ONE list element. Do not supply old text, JSON inside the replacement, encoded text, a shell command or a unified diff. Include the required newline yourself; nothing silently adds a newline or converts CRLF. The executor generates the diff.
- Insert before line41: same replace syntax with START41 END40. Insert after EOF: START=total_lines+1 END=total_lines.
- Delete a range: replace with an empty final string. This leaves the file present.
- Create source: replace with revision `missing`, START1 END0 and full literal source. The path must not already exist.
- Remove an entire source file: `["--root", "/workspace", "remove", "package/obsolete.py", "COPIED_REVISION"]`.
- Check changed files/syntax: `["--root", "/workspace", "check"]`.
- Focused pytest: `["--root", "/workspace", "check", "--pytest", "tests/test_module.py::test_case", "--timeout", "60"]`. Repeat `--pytest` for selected existing files/nodes; timeout1–60seconds. No directories, arbitrary Python, commands, or unscoped suites.

Existing-file writes require the exact current revision. If it is stale, nothing changes: inspect again and revise the edit. Invalid bounds, traversal, symlinks, protected tests/config/gold/harness paths, oversized replacements and invalid Python are rejected before source changes. Existing dirty bytes outside the edited range and file permissions survive. Installation is atomic; a single writer is assumed. Revision checks detect stale edits between invocations, not synchronization with arbitrary concurrent writers.

Only the helper writes source. Never bypass rejection. Locate, inspect and check may read tests. A transient `.adk_exec_*.py` SDK wrapper may appear during check; do not edit it, the executor removes it. Focused pytest runs offline with cache/output outside the repository and preserves its exit status (timeout124). After verification, call submit_patch and end.
