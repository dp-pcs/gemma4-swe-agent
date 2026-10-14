Resolve the repository issue with a minimal, correct source patch. The issue is supplied in the session.

Load `revision-edit` once, then use `run_skill_script` with skill_name `revision-edit`, file_path `scripts/repair.py`, and an `args` list beginning `["--root", "/workspace"]`.

1. Locate the issue's symbol or inspect its known file. Read bounded relevant ranges, not repeated whole files. Tests may be inspected, never changed.
2. Inspect before editing. Copy the returned full-file `revision` exactly. Use `replace PATH REVISION START END REPLACEMENT` with literal replacement text as one args-list string. The executor builds the diff: do not write unified diff hunks, old_string, shell commands, or scratch files. Preserve line endings explicitly. Reinspect after a stale revision; fix rejected syntax before retrying.
3. Verify the consumer-visible behavior, including canonical outputs, exceptions/status codes, and boundary cases. Use `check --pytest FILE[::NODE]` for an existing focused test; never run an unscoped suite. A passing input-only check is not enough when the issue specifies an output contract. Do not repair unrelated dependency/test failures.
4. Run `check` to review changed files and syntax, then `submit_patch`. End after submitting the nonempty source-only fix.

The exposed tools are the revision-edit skill tools and submit_patch. There is no shell, legacy file writer, or analyzer escape hatch. Never invent a removed tool. Keep tests, gold files, configuration, SDK wrappers and reproduction files out of the patch. Executable documentation examples under docs_src may be edited. Do not refactor unrelated code.
