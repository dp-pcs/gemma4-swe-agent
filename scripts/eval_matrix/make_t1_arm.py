"""Derive the T1 tool-call-reliability arm from the honghanhhh v3 recipe.

Every edit is an exact, assert-once string replacement on the v3 prompt so the
delta is auditable: no write_file or graph tools, edit_file restricted to short
colon-free targets with a heredoc Python script as the primary path otherwise,
first edit by call 8 with a get_status checkpoint, and small tool outputs.

Usage: python3 -I scripts/eval_matrix/make_t1_arm.py V3_SOURCE_DIR OUT_DIR
"""

import shutil
import sys
from pathlib import Path

EDITS = [
    (
        "- Never use `search_similar_code`, `get_code_neighbors` or `get_code_subgraph`. "
        "They return nothing useful.",
        "- Only five tools exist: `run_command`, `read_file`, `edit_file`, `get_status` and "
        "`submit_patch`. There is no `write_file` and there are no code-graph tools; ignore any "
        "mention of them. Create files only through `run_command` with a quoted heredoc, and only "
        "under /tmp unless the issue requires a new source module.",
    ),
    (
        "- Calls 1-8: locate and read. Calls 9-12: edit. You MUST have edited a source file by "
        "call 12. If you are unsure, make your best-guess edit in the most likely place now. "
        "A wrong edit can still be corrected. Pure reading cannot score.\n"
        "- Calls 13-20: verify and correct.\n"
        "- Call 20 onward: no new exploration. Check, fix, submit.",
        "- Calls 1-6: locate and read. Calls 7-8: edit. You MUST have edited a source file by "
        "call 8. If you are unsure, make your best-guess edit in the most likely place now. "
        "A wrong edit can still be corrected. Pure reading cannot score.\n"
        "- After call 6, call `get_status` once (it is free and does not count) and plan the "
        "remaining calls from the numbers it returns.\n"
        "- Calls 9-16: verify and correct.\n"
        "- Call 16 onward: no new exploration. Check, fix, submit.",
    ),
    (
        "- Batch only searches whose inputs are already known.",
        "- Keep every tool result small: pipe searches through `| head -40`, read at most 80 "
        "lines at a time, and run tests with `-x -q 2>&1 | tail -25`. Large outputs waste the "
        "context window and the clock.\n"
        "- Batch only searches whose inputs are already known.",
    ),
    (
        "- Use edit_file for changes to existing code. Copy old_string exactly from the source, "
        "including whitespace, and choose a short unique match. Use write_file only for a "
        "genuinely new source file that the issue requires.\n"
        "- If edit_file reports no match or multiple matches, read the exact source region and "
        "retry with a smaller unique snippet. Never repeat an identical failed edit. After two "
        "matching failures, use one inline Python script through run_command with a quoted "
        "heredoc; assert that the old text occurs exactly once before replacing it and writing "
        "the file. Preserve unrelated content and do not rewrite the file from memory.",
        "- Pick the edit tool by the text you are replacing. Use `edit_file` only when "
        "`old_string` is at most 3 lines, contains no colon (`:`), and is unique in the file; "
        "copy it exactly, including whitespace. In every other case (a `def`, `class`, `if`, "
        "`for`, `with` or `try` line, a dict literal, slice, annotation or f-string, or anything "
        "longer than 3 lines) do not call `edit_file`. Use one `run_command` with an inline "
        "Python script in a quoted heredoc that asserts the old text occurs exactly once, "
        "replaces it, and writes the file back:\n"
        "```\n"
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "p = Path('pkg/module.py'); s = p.read_text()\n"
        "old = '''    if value is None:\n"
        "        return default\n"
        "'''\n"
        "new = '''    if value is None or value == \"\":\n"
        "        return default\n"
        "'''\n"
        "assert s.count(old) == 1, s.count(old)\n"
        "p.write_text(s.replace(old, new))\n"
        "PY\n"
        "```\n"
        "- If `edit_file` reports a missing or malformed `old_string`, no match, or multiple "
        "matches, do not retry it; switch to the heredoc script at once. Never repeat an "
        "identical failed edit, and never rewrite a file from memory. For a genuinely new source "
        "file that the issue requires, write it with `cat > path <<'EOF'` through `run_command`.",
    ),
    (
        "then run `timeout 150 python -m pytest tests/path/test_x.py -x -q -k keyword`.",
        "then run `timeout 150 python -m pytest tests/path/test_x.py -x -q -k keyword 2>&1 | tail -25`.",
    ),
]

AGENT_YAML = """name: swe_agent
model: gemma-4-31b-it-qat-w4a16-ct
instruction: !include prompts/system.md
tools:
  - run_command
  - read_file
  - edit_file
  - get_status
  - submit_patch
generate_content_config: !include configs/sampling.yaml
"""


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    if out.exists():
        raise SystemExit(f"{out} already exists; use a fresh directory")
    prompt = (src / "prompts" / "system.md").read_text(encoding="utf-8")
    for old, new in EDITS:
        if prompt.count(old) != 1:
            raise SystemExit(f"expected exactly one occurrence, found {prompt.count(old)}: {old[:60]!r}")
        prompt = prompt.replace(old, new)
    (out / "prompts").mkdir(parents=True)
    (out / "configs").mkdir()
    (out / "prompts" / "system.md").write_text(prompt, encoding="utf-8")
    (out / "agent.yaml").write_text(AGENT_YAML, encoding="utf-8")
    shutil.copy(src / "eval_config.yaml", out / "eval_config.yaml")
    shutil.copy(src / "configs" / "sampling.yaml", out / "configs" / "sampling.yaml")
    print(f"wrote {out}: prompt {len(prompt)} chars ({len(EDITS)} edits applied)")


if __name__ == "__main__":
    main()
