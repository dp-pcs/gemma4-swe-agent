"""Build an evaluation arm that runs a prompt tree with a LoRA adapter attached.

Copies SOURCE_DIR (e.g. the T1 tree), adds adapters/<name>/{adapter_config.json,
adapter_model.safetensors} from ADAPTER_DIR, and sets `adapter: <name>` on the root agent,
exactly as a competition submission would carry it. The harness then routes the agent's
requests to the vLLM LoRA module of the same name, so the serving side needs
LORA_MODULES="<name>=<path to adapters/<name>>" when starting serve.sh.

Usage: python3 -I make_lora_arm.py SOURCE_DIR ADAPTER_DIR OUT_DIR [--name swe_rft_h1]
"""

import argparse
import json
import shutil
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("adapter", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--name", default="swe_rft_h1")
    args = ap.parse_args()
    if args.out.exists():
        raise SystemExit(f"{args.out} already exists; use a fresh directory")
    cfg = json.load(open(args.adapter / "adapter_config.json"))
    weights = args.adapter / "adapter_model.safetensors"
    if not weights.exists():
        raise SystemExit("adapter_model.safetensors missing (only .safetensors adapters are allowed)")
    if cfg.get("r", 0) > 128:
        raise SystemExit(f"LoRA rank {cfg['r']} exceeds the harness limit of 128")

    shutil.copytree(args.source, args.out)
    dest = args.out / "adapters" / args.name
    dest.mkdir(parents=True)
    shutil.copy(args.adapter / "adapter_config.json", dest / "adapter_config.json")
    shutil.copy(weights, dest / "adapter_model.safetensors")

    agent = args.out / "agent.yaml"
    text = agent.read_text()
    lines = [l for l in text.splitlines() if not l.startswith("adapter:")]
    idx = next(i for i, l in enumerate(lines) if l.startswith("model:"))
    lines.insert(idx + 1, f"adapter: {args.name}")
    agent.write_text("\n".join(lines) + "\n")

    size = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(f"wrote {args.out}: adapter {args.name} r={cfg.get('r')} alpha={cfg.get('lora_alpha')} "
          f"targets={cfg.get('target_modules')} | tree {size/1e6:.1f} MB (limit 3 GiB)")
    print(f"serve with: LORA_MODULES='{args.name}={args.out.resolve()}/adapters/{args.name}' bash serve.sh")


if __name__ == "__main__":
    main()
