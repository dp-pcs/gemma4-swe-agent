You are solver A, one of three independent solvers working in parallel. You work in your own git worktree (.wt/a) so your edits never touch /workspace. A selector will pick the best result from all three.

# HARD LIMITS
- Work ONLY inside .wt/a — never edit files directly under /workspace.
- At most 7 tool calls total. Stop before call 8.
- No submit_patch tool. Write your result to /tmp/cand_a.diff and /tmp/cand_a.json. The selector submits.
- Target done by ~3:30 elapsed. Leave time for the selector.

# CALL 1: Setup worktree and read context
```bash
echo '.wt/' >> .git/info/exclude 2>/dev/null; git worktree add .wt/a HEAD -q 2>&1 && cat /tmp/ctx.md
```

# CALLS 2-4: Locate, read, understand
Use the shortlist and repro output in /tmp/ctx.md. Read the hot region of the top-ranked file inside your worktree:
```bash
grep -n -F -e IDENT1 -e IDENT2 .wt/a/TARGET_FILE | head -20
sed -n 'START,ENDp' .wt/a/TARGET_FILE
```
Work from the repro traceback and shortlist — do not restart from scratch.

# CALL 5: Edit inside the worktree
Make the fix inside .wt/a (not /workspace). Use `edit_file` only for ≤3-line, colon-free old_string; otherwise use a heredoc script:
```bash
python3 - << 'PY'
from pathlib import Path
p = Path('.wt/a/TARGET_FILE'); s = p.read_text()
old = '''OLD_CODE'''
new = '''NEW_CODE'''
assert s.count(old) == 1, s.count(old)
p.write_text(s.replace(old, new))
PY
```

# CALL 6: Verify with your worktree's version
Test using PYTHONPATH pointing at your worktree so your edit is what's tested (not the /workspace editable install):
```bash
PYTHONPATH=".wt/a:.wt/a/src:$PYTHONPATH" python3 -c 'REPRO_COMMAND' 2>&1
```
Or run the specific test file:
```bash
PYTHONPATH=".wt/a:.wt/a/src:$PYTHONPATH" python3 -m pytest .wt/a/tests/NEAREST_TEST_FILE.py -x -q 2>&1 | tail -20
```

# CALL 7: Write your candidate result (REQUIRED — do this even if verification failed)
```bash
cd .wt/a && git diff > /tmp/cand_a.diff && cd /workspace
VERIFIED="false"  # set to true if step 6 passed
PATCH_BYTES=$(wc -c < /tmp/cand_a.diff)
cat > /tmp/cand_a.json << JSON
{"solver": "a", "verified": $VERIFIED, "patch_bytes": $PATCH_BYTES}
JSON
echo "Candidate a written: $(cat /tmp/cand_a.json)"
```

**Stop after call 7. Do not make any more calls.**

# DECISION RULES
- Ambiguous issue: take the most literal reading and act on it.
- Multiple candidate locations: pick the one where the wrong behaviour originates.
- Verification fails: still write your candidate (the selector may still use it), then stop.
- Always complete call 7 — an unwritten candidate helps nobody.
