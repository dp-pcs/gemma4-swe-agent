"""Convert resolved matrix traces into OpenAI-style tool-calling SFT examples.

One example per run: system instruction, task prompt, then alternating assistant
(reasoning + one tool call) and tool-result messages, ending with the final text.
Filters (all configurable): resolved runs only, no malformed or post-budget tool
calls, at most --per-task runs per task (fewest tool calls first), final context
at most --max-prompt-tokens.

Usage:
  python3 -I build_sft_jsonl.py OUT_DIR [OUT_DIR ...] --out sft.jsonl [--arms A B]
      [--per-task 3] [--max-prompt-tokens 16384] [--reasoning-field reasoning_content]
"""

import argparse
import collections
import glob
import json
import os
import sys

TOOLS = {
    "run_command": {
        "description": "Run a shell command in /workspace and return stdout, stderr and exit code.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]},
    },
    "read_file": {
        "description": "Read a file under /workspace, optionally a line range.",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["filepath"],
        },
    },
    "edit_file": {
        "description": "Replace an exact string in a file under /workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "allow_multiple": {"type": "boolean"},
            },
            "required": ["filepath", "old_string", "new_string"],
        },
    },
    "write_file": {
        "description": "Create or overwrite a file under /workspace.",
        "parameters": {
            "type": "object",
            "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}},
            "required": ["filepath", "content"],
        },
    },
    "get_status": {"description": "Return remaining time and tool-call budget.", "parameters": {"type": "object", "properties": {}}},
    "submit_patch": {"description": "Submit the current git diff of /workspace.", "parameters": {"type": "object", "properties": {}}},
}

BAD_OBSERVATION = ("mandatory input parameters", "BudgetExceeded", "Path traversal detected")


def tool_schemas(names):
    return [{"type": "function", "function": {"name": n, **TOOLS[n]}} for n in names if n in TOOLS]


def convert(trace_path, reasoning_field):
    trace = json.load(open(trace_path))
    steps = trace["steps"]
    messages, tools_used, last_prompt_tokens = [], [], 0
    for s in steps:
        src, ev = s["source"], (s.get("extra") or {}).get("event_type")
        if src == "system":
            messages.append({"role": "system", "content": s["message"]})
        elif src == "user":
            messages.append({"role": "user", "content": s["message"]})
        elif src == "agent":
            m = s.get("metrics") or {}
            last_prompt_tokens = max(last_prompt_tokens, m.get("prompt_tokens") or 0)
            calls = s.get("tool_calls") or []
            if not calls:
                messages.append({"role": "assistant", "content": s.get("message") or ""})
                continue
            if len(calls) != 1:
                return None, "multi_tool_call_step"
            tc = calls[0]
            args = tc.get("arguments")
            if not isinstance(args, dict):
                return None, "non_dict_arguments"
            obs = (s.get("observation") or {}).get("content", "") or ""
            if any(b in obs for b in BAD_OBSERVATION):
                return None, "bad_tool_result"
            tools_used.append(tc["function_name"])
            assistant = {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": tc.get("tool_call_id") or f"call_{len(messages)}",
                    "type": "function",
                    "function": {"name": tc["function_name"], "arguments": json.dumps(args, ensure_ascii=False)},
                }],
            }
            if s.get("message"):
                assistant[reasoning_field] = s["message"]
            messages.append(assistant)
            messages.append({"role": "tool", "tool_call_id": assistant["tool_calls"][0]["id"], "content": obs})
    if not any(m["role"] == "assistant" and "tool_calls" in m for m in messages):
        return None, "no_tool_calls"
    return {"messages": messages, "tools": tool_schemas(sorted(set(tools_used)) or list(TOOLS)),
            "_meta": {"last_prompt_tokens": last_prompt_tokens, "tool_calls": len(tools_used)}}, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dirs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--arms", nargs="*")
    ap.add_argument("--per-task", type=int, default=3)
    ap.add_argument("--max-prompt-tokens", type=int, default=16384)
    ap.add_argument("--reasoning-field", default="reasoning_content")
    ap.add_argument("--keep-meta", action="store_true")
    ap.add_argument("--task-file", help="Only include these task ids (e.g. the training split)")
    args = ap.parse_args()

    allowed = set(open(args.task_file).read().split()) if args.task_file else None
    candidates = []
    reasons = collections.Counter()
    for out_dir in args.out_dirs:
        for js in glob.glob(os.path.join(out_dir, "s*", "*", "*", "job_summary.json")):
            job = json.load(open(js))
            arm = job["arm"]
            if args.arms and arm not in args.arms:
                continue
            if allowed is not None and job["task_id"] not in allowed:
                reasons["not_in_task_file"] += 1
                continue
            if not job.get("resolved"):
                reasons["not_resolved"] += 1
                continue
            traces = glob.glob(os.path.join(os.path.dirname(js), "traces", "*.json"))
            if not traces:
                reasons["no_trace"] += 1
                continue
            example, why = convert(traces[0], args.reasoning_field)
            if example is None:
                reasons[why] += 1
                continue
            if example["_meta"]["last_prompt_tokens"] > args.max_prompt_tokens:
                reasons["too_long"] += 1
                continue
            candidates.append((job["task_id"], arm, example))

    by_task = collections.defaultdict(list)
    for task, arm, ex in candidates:
        by_task[task].append((ex["_meta"]["tool_calls"], arm, ex))
    kept = []
    for task, rows in by_task.items():
        rows.sort(key=lambda r: r[0])
        for _, arm, ex in rows[: args.per_task]:
            kept.append((task, arm, ex))
            reasons["kept"] += 1
        reasons["over_per_task_cap"] += max(0, len(rows) - args.per_task)

    with open(args.out, "w") as fh:
        for task, arm, ex in kept:
            if args.keep_meta:
                ex["_meta"].update({"task_id": task, "arm": arm})
            else:
                ex.pop("_meta", None)
            fh.write(json.dumps(ex, ensure_ascii=False) + "\n")

    tasks = len(by_task)
    per_arm = collections.Counter(arm for _, arm, _ in kept)
    toks = sum(ex.get("_meta", {}).get("last_prompt_tokens", 0) for _, _, ex in kept) if args.keep_meta else None
    print(f"examples written: {len(kept)}  distinct tasks: {tasks}  per arm: {dict(per_arm)}")
    print("filter reasons:", dict(reasons))
    if toks is not None:
        print(f"sum of final-context tokens (approx training tokens, loss on assistant turns only): {toks:,}")


if __name__ == "__main__":
    main()
