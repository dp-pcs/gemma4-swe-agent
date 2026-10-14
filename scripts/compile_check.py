"""Offline compile check of an extracted submission with the pinned organizer SDK.

Mirrors swegemma's agent_runner compile path: real SwegemmaContext tools, the
competition SubmissionLimits/GenerationConstraints, and a LiteLlm registry for the
declared model. Makes zero model requests. Also reads eval_config.yaml through
swegemma's EvalConfig budget fields.

Usage: python scripts/compile_check.py SUBMISSION_DIR
"""

import json
import sys
from pathlib import Path

import yaml
from adk_submission import compile_submission
from swegemma.cli import _build_cli_model_registry
from swegemma.config import build_submission_limits
from swegemma.context import SwegemmaContext


def main() -> None:
    sub = Path(sys.argv[1]).resolve()
    limits, constraints = build_submission_limits()
    models = _build_cli_model_registry(submission_dir=sub)
    ctx = SwegemmaContext(task_id="compile_check", repo="compile/check")
    agent = compile_submission(
        submission_dir=sub,
        tool_registry=ctx.create_tools(),
        model_registry=models,
        limits=limits,
        generation_constraints=constraints,
    )
    gen = agent.generate_content_config
    tools = [getattr(t, "name", None) or getattr(t, "__name__", type(t).__name__) for t in agent.tools]
    sub_agents = [a.name for a in getattr(agent, "sub_agents", [])]
    eval_cfg = yaml.safe_load((sub / "eval_config.yaml").read_text())["evaluation"]
    report = {
        "agent": agent.name,
        "class": type(agent).__name__,
        "model": getattr(agent.model, "model", str(agent.model)),
        "generation": gen.model_dump(exclude_none=True) if gen else None,
        "tools": tools,
        "sub_agents": sub_agents,
        "instruction_chars": len(agent.instruction or ""),
        "eval_config": eval_cfg,
        "model_requests": 0,
    }
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
