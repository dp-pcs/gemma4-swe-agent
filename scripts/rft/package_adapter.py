"""Normalize a PEFT LoRA adapter for the competition harness / vLLM.

- casts weights to bf16 (the starter-kit adapters are bf16; halves the size)
- rewrites adapter_config.json: target_modules as an explicit list, base_model_name_or_path set
  to the competition alias, local paths removed
- verifies tensor names use the layout the starter kit's adapters use
  (base_model.model.model.language_model.layers.N...)

Usage: python package_adapter.py IN_DIR OUT_DIR [--base google/gemma-4-31b-it-qat-w4a16-ct] [--keep-fp32]
"""

import argparse
import json
import re
from pathlib import Path

TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--base", default="google/gemma-4-31b-it-qat-w4a16-ct")
    ap.add_argument("--keep-fp32", action="store_true")
    args = ap.parse_args()

    import torch
    from safetensors.torch import load_file, save_file

    tensors = load_file(str(args.src / "adapter_model.safetensors"))
    bad = [k for k in tensors if not k.startswith("base_model.model.model.language_model.layers.")]
    if bad:
        raise SystemExit(f"unexpected tensor names (first: {bad[0]})")
    found = sorted({re.search(r"\.(\w+_proj)\.lora_", k).group(1) for k in tensors})
    if not args.keep_fp32:
        tensors = {k: v.to(torch.bfloat16).contiguous() for k, v in tensors.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    save_file(tensors, str(args.out / "adapter_model.safetensors"), metadata={"format": "pt"})

    cfg = json.load(open(args.src / "adapter_config.json"))
    cfg["target_modules"] = [t for t in TARGETS if t in found]
    cfg["base_model_name_or_path"] = args.base
    cfg["inference_mode"] = True
    for k in ("revision",):
        cfg[k] = None
    json.dump(cfg, open(args.out / "adapter_config.json", "w"), indent=2)
    size = (args.out / "adapter_model.safetensors").stat().st_size
    print(f"wrote {args.out}: {len(tensors)} tensors, {size/1e6:.0f} MB, r={cfg.get('r')} alpha={cfg.get('lora_alpha')} "
          f"targets={cfg['target_modules']} base={cfg['base_model_name_or_path']}")


if __name__ == "__main__":
    main()
