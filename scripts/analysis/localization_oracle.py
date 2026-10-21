#!/usr/bin/env python3
"""Offline localization oracle: which cheap heuristics would have surfaced the file(s) the real fix touched?

For every task in competition_data/tasks.jsonl we know the gold patch (files the real fix changed), the bug
report and the base commit. With a clone of each repository checked out at that commit we can score, with
no model runs at all:
  paths      files/modules named in the bug report
  trace      files named in a stack trace in the report
  grep@k     `git grep -l -F` for identifiers taken from the report, files ranked by #identifiers matched
  recent@N   files changed in the last N commits before the base commit
  logS@k     files touched by commits that added/removed the top identifiers (`git log -S`)
and, from local agent runs (agent.patch next to job_summary.json), how often the agent edited a gold file at
all and how resolution depends on that.

Usage: localization_oracle.py --tasks competition_data/tasks.jsonl --repos /tmp/repos \
         [--runs results/.../out_gates_v4/s*/T1_toolfix] [--json out.json]
"""
import argparse
import collections
import glob
import json
import os
import re
import subprocess
import sys

REPO_DIR = {"fastapi/fastapi": "fastapi", "Textualize/rich": "rich", "psf/requests": "requests", "encode/httpx": "httpx"}
# One run_command the agent can issue: recency score (last 50 commits, capped at 5) + 3 points per identifier hit,
# generic identifiers (> 40 files) ignored, tests excluded, top 10. IDENTS is replaced by quoted identifiers.
SHELL_LOCATE = r"""{ git log -n 50 --name-only --pretty=format: | grep -E '\.py$' | sort | uniq -c | awk '{c=$1; if (c>5) c=5; print c, $2}'; for i in IDENTS; do git grep -l -F -e "$i" -- '*.py' | awk -v n="$(git grep -l -F -e "$i" -- '*.py' | wc -l)" 'n>0 && n<=40 {print 3, $1}'; done; } | grep -vE '(^|/)tests?/|(^|/)test_[^/]*\.py$|_test\.py$|conftest\.py$' | awk '{s[$2]+=$1} END {for (f in s) print s[f], f}' | sort -rn | head -10"""
STOP = {"python", "fastapi", "rich", "requests", "httpx", "import", "return", "self", "none", "true", "false",
        "error", "value", "default", "class", "function", "method", "object", "type", "string", "example",
        "https", "http", "github", "com", "issue", "version", "pydantic", "starlette", "uvicorn", "pytest",
        "test", "tests", "file", "line", "code", "print", "console", "text", "table", "style", "color"}


def sh(repo, *args, timeout=60):
    try:
        return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout).stdout
    except subprocess.TimeoutExpired:
        return ""


def is_test(path):
    base = os.path.basename(path)
    return path.startswith("tests/") or "/tests/" in path or base.startswith("test_") or base.endswith("_test.py") \
        or base in ("conftest.py",)


def patch_files(patch):
    """Changed-file paths from a unified diff; the task patches carry only ---/+++ headers, git diffs also diff --git."""
    files = re.findall(r"^\+\+\+ b/(\S+)", patch or "", re.M) or [b for _, b in re.findall(r"^diff --git a/(\S+) b/(\S+)", patch or "", re.M)]
    out, seen = [], set()
    for f in files:
        if f not in seen:
            seen.add(f); out.append(f)
    return out


def identifiers(text):
    cands = collections.Counter()
    for tok in re.findall(r"`([^`\n]{2,80})`", text):
        for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", tok):
            cands[w] += 3
    for w in re.findall(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b", text):      # CamelCase
        cands[w] += 2
    for w in re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", text):          # snake_case
        cands[w] += 2
    for w in re.findall(r"\b[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)+\b", text):  # dotted paths
        cands[w.split(".")[-1]] += 1
    out = [w for w, _ in cands.most_common(40) if w.lower() not in STOP and len(w) >= 4]
    return out[:10]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--repos", required=True)
    ap.add_argument("--runs", nargs="*", default=[], help="run dirs (glob) containing <task>/agent.patch + job_summary.json")
    ap.add_argument("--json")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--shell", action="store_true", help="also score the exact SHELL_LOCATE pipeline the prompt carries")
    args = ap.parse_args()

    tasks = [json.loads(l) for l in open(args.tasks)]
    if args.limit:
        tasks = tasks[: args.limit]
    H = collections.defaultdict(lambda: {"hit": 0, "n": 0, "size": 0})
    per_task = {}
    skipped = collections.Counter()
    for t in tasks:
        repo = os.path.join(args.repos, REPO_DIR.get(t["repo"], ""))
        if not os.path.isdir(os.path.join(repo, ".git")):
            skipped["no_repo"] += 1
            continue
        targets = [f for f in patch_files(t["patch"]) if not is_test(f) and f.endswith(".py")]
        if not targets:
            skipped["no_source_target"] += 1
            continue
        if subprocess.run(["git", "-C", repo, "checkout", "-q", "--detach", t["base_commit"]], capture_output=True).returncode != 0:
            skipped["commit_missing"] += 1
            continue
        tset = set(targets)
        tbase = {os.path.basename(f) for f in targets}
        text = t["problem_statement"] or ""
        res = {"targets": targets}

        def score(name, files, k=None):
            files = [f for f in files if f and not is_test(f)]
            if k:
                files = files[:k]
            hit = any(f in tset or os.path.basename(f) in tbase for f in files)
            H[name]["hit"] += hit; H[name]["n"] += 1; H[name]["size"] += len(files)
            res[name] = {"hit": hit, "size": len(files)}

        # paths named in the report
        mentioned = [m.lstrip("./") for m in re.findall(r"\b[\w./-]+\.py\b", text)]
        score("paths", mentioned)
        # stack-trace files
        trace = [os.path.basename(m) for m in re.findall(r'File "([^"]+\.py)"', text)]
        score("trace", trace)
        # grep on identifiers
        idents = identifiers(text)
        res["identifiers"] = idents
        hits = collections.Counter()
        for ident in idents:
            out = sh(repo, "grep", "-l", "-F", "-e", ident, "--", "*.py")
            files = [f for f in out.split("\n") if f and not is_test(f)]
            if 0 < len(files) <= 40:
                for f in files:
                    hits[f] += 1
        ranked = [f for f, _ in hits.most_common()]
        for k in (1, 3, 5, 10):
            score(f"grep@{k}", ranked, k)
        # recent commits
        for n in (10, 20, 50):
            out = sh(repo, "log", "-n", str(n), "--name-only", "--pretty=format:", t["base_commit"])
            seen, files = set(), []
            for f in out.split("\n"):
                if f and f.endswith(".py") and f not in seen:
                    seen.add(f); files.append(f)
            score(f"recent@{n}commits", files)
        # feature history: commits that added/removed the top identifiers
        files, seen = [], set()
        for ident in idents[:3]:
            out = sh(repo, "log", "-n", "20", "-S", ident, "--name-only", "--pretty=format:", t["base_commit"], timeout=120)
            for f in out.split("\n"):
                if f and f.endswith(".py") and f not in seen:
                    seen.add(f); files.append(f)
        for k in (5, 10):
            score(f"logS@{k}", files, k)
        score("logS@all", files)
        logs_files = files
        # combinations: what a one-call "locate" step could put in front of the agent
        out = sh(repo, "log", "-n", "50", "--name-only", "--pretty=format:", t["base_commit"])
        recent50 = collections.Counter(f for f in out.split("\n") if f.endswith(".py") and not is_test(f))
        score("union(grep10,recent20,logS10)", list(dict.fromkeys(ranked[:10] + [f for f in recent50 if recent50[f] > 0][:0]
              + [f for f, _ in collections.Counter({f: c for f, c in recent50.items()}).most_common(20)] + logs_files[:10])))
        # ranked combo: identifier hits weighted 3, recency count (last 50 commits) weighted 1
        combo = collections.Counter()
        for f, c in hits.items():
            combo[f] += 3 * c
        for f, c in recent50.items():
            combo[f] += min(c, 5)
        combo_ranked = [f for f, _ in combo.most_common()]
        for k in (5, 10, 15):
            score(f"combo@{k}", combo_ranked, k)
        # grep hits restricted to files that changed in the last 50 commits (the intersection shortlist)
        inter = [f for f in ranked if f in recent50]
        score("grep∩recent50@all", inter)
        score("grep∩recent50@5", inter, 5)
        # the exact one-call shell pipeline the prompt will carry (identifiers filled in by the agent)
        if args.shell and idents:
            cmd = SHELL_LOCATE.replace("IDENTS", " ".join(f"'{i}'" for i in idents[:6]))
            try:
                out = subprocess.run(["bash", "-c", cmd], cwd=repo, capture_output=True, text=True, timeout=120).stdout
            except subprocess.TimeoutExpired:
                out = ""
            shell_files = [l.split()[-1] for l in out.strip().split("\n") if l.strip()]
            for k in (5, 10):
                score(f"shell@{k}", shell_files, k)
        per_task[t["instance_id"]] = res

    print(f"tasks scored: {len(per_task)}  skipped: {dict(skipped)}")
    print(f"{'heuristic':<18}{'recall':>8}{'mean files':>12}")
    for name in ("paths", "trace", "grep@1", "grep@3", "grep@5", "grep@10", "recent@10commits", "recent@20commits",
                 "recent@50commits", "logS@5", "logS@10", "logS@all", "union(grep10,recent20,logS10)",
                 "combo@5", "combo@10", "combo@15", "grep∩recent50@5", "grep∩recent50@all", "shell@5", "shell@10"):
        h = H[name]
        if h["n"]:
            print(f"{name:<18}{100*h['hit']/h['n']:>7.0f}%{h['size']/h['n']:>12.1f}")
    single = sum(1 for r in per_task.values() if len(r["targets"]) == 1)
    print(f"single-file fixes: {single}/{len(per_task)}; mean target files {sum(len(r['targets']) for r in per_task.values())/max(len(per_task),1):.2f}")

    # agent runs: did the agent edit a gold file?
    agent = {}
    for pattern in args.runs:
        for d in glob.glob(pattern):
            arm = os.path.basename(d.rstrip("/"))
            for js in glob.glob(os.path.join(d, "*", "job_summary.json")):
                task = os.path.basename(os.path.dirname(js))
                if task not in per_task:
                    continue
                j = json.load(open(js))
                try:
                    edited = [f for f in patch_files(open(os.path.join(os.path.dirname(js), "agent.patch")).read()) if not is_test(f)]
                except OSError:
                    edited = []
                tset = set(per_task[task]["targets"]); tbase = {os.path.basename(f) for f in tset}
                hit = any(f in tset or os.path.basename(f) in tbase for f in edited)
                a = agent.setdefault(arm, collections.Counter())
                a["runs"] += 1; a["edited"] += bool(edited); a["hit"] += hit
                a["resolved"] += bool(j.get("resolved")); a["resolved_hit"] += bool(j.get("resolved")) and hit
                a["resolved_miss"] += bool(j.get("resolved")) and not hit
    for arm, a in agent.items():
        n = a["runs"]
        print(f"{arm}: runs {n} | edited something {a['edited']/n:.0%} | edited a gold file {a['hit']/n:.0%} | "
              f"resolved {a['resolved']/n:.0%} (given gold-file edit {a['resolved_hit']/max(a['hit'],1):.0%}, "
              f"given no gold-file edit {a['resolved_miss']/max(n-a['hit'],1):.0%})")
    if args.json:
        json.dump({"heuristics": H, "agent": {k: dict(v) for k, v in agent.items()}, "per_task": per_task},
                  open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
