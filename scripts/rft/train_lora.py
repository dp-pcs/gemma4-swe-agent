"""Self-hosted LoRA SFT for the Gemma 4 31B agent on OpenAI-style tool-calling JSONL.

Renders each example with the model's own chat template (tools + reasoning_content +
tool messages), computes assistant-only loss masks by incremental rendering, and trains
a PEFT LoRA on the bf16 QAT twin (google/gemma-4-31B-it-qat-q4_0-unquantized) sharded
across all visible GPUs with device_map="auto". Saves a PEFT adapter directory
(adapter_config.json + adapter_model.safetensors) that vLLM can load as a LoRA module.

Usage:
  python train_lora.py --model /path/to/gemma4-bf16 --train sft_train.jsonl \
      [--eval sft_eval.jsonl] --out adapter_out [--rank 32] [--alpha 64] [--epochs 2] \
      [--lr 1e-4] [--max-len 16384] [--grad-accum 8] [--dry-run]
  --dry-run only renders/masks the data and prints statistics (CPU, tokenizer only).
"""

import argparse
import json
import math
import os
import random
import time
from pathlib import Path


THINK_RE = None


def render_example(tok, ex, max_len, mask_thinking=False):
    """Return (input_ids, labels) with labels on assistant turns only, or None if too long.

    With mask_thinking, the <|channel>...<channel|> thinking blocks inside assistant turns are
    excluded from the loss, so training teaches the actions (tool calls, final text) but not the
    length or content of the reasoning.
    """
    global THINK_RE
    import re

    if THINK_RE is None:
        THINK_RE = re.compile(r"<\|channel>.*?<channel\|>", re.S)
    msgs, tools = ex["messages"], ex.get("tools")
    full = tok.apply_chat_template(msgs, tools=tools, tokenize=False)
    enc = tok(full, add_special_tokens=False, return_offsets_mapping=True)
    ids, offs = enc["input_ids"], enc["offset_mapping"]
    if len(ids) > max_len:
        return None
    # Incremental rendering: the characters contributed by assistant message k are the suffix of
    # render(msgs[:k+1]) beyond render(msgs[:k]).
    spans, prev = [], 0
    for k, m in enumerate(msgs):
        cur = len(tok.apply_chat_template(msgs[: k + 1], tools=tools, tokenize=False))
        if m["role"] == "assistant":
            spans.append((prev, cur))
        prev = cur

    def in_assistant(c):
        return any(a <= c < b for a, b in spans)

    labels = [ids[i] if in_assistant(s) else -100 for i, (s, e) in enumerate(offs)]
    if mask_thinking:
        for mt in THINK_RE.finditer(full):
            a, b = mt.span()
            if in_assistant(a):
                for i, (s, e) in enumerate(offs):
                    if a <= s < b:
                        labels[i] = -100
    return ids, labels


def load_examples(tok, path, max_len, mask_thinking=False):
    rows = [json.loads(l) for l in open(path)]
    out, dropped = [], 0
    for ex in rows:
        r = render_example(tok, ex, max_len, mask_thinking)
        if r is None:
            dropped += 1
            continue
        out.append(r)
    return out, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--train", required=True)
    ap.add_argument("--eval")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--alpha", type=int, default=64)
    ap.add_argument("--dropout", type=float, default=0.05)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--max-len", type=int, default=24576)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-memory-gib", default="22",
                    help="per-GPU cap(s) for weight sharding, one value or a comma list per GPU "
                         "(e.g. 15,15,15,20); the rest is headroom for activations")
    ap.add_argument("--mask-thinking", action="store_true",
                    help="exclude <|channel>...<channel|> thinking blocks from the loss (train actions only)")
    ap.add_argument("--resume-adapter", help="PEFT adapter dir (e.g. OUT/epoch0) to continue from")
    ap.add_argument("--start-epoch", type=int, default=0, help="first epoch index to run when resuming")
    ap.add_argument("--layer-split", help="explicit decoder layers per GPU, e.g. 15,16,16,13 (overrides --max-memory-gib); "
                    "embed_tokens/lm_head go to GPU 0, final norm + vision/audio towers to the last GPU")
    ap.add_argument("--head-chunk", type=int, default=1024, help="supervised positions per lm_head chunk (logits are recomputed in backward)")
    ap.add_argument("--offload-ckpt", action="store_true",
                    help="reentrant gradient checkpointing with layer inputs saved on pinned CPU memory (saves ~0.2 GiB/layer at 20K tokens)")
    ap.add_argument("--mem-probe", action="store_true",
                    help="before training, run fwd+bwd on the longest and most-supervised examples and print per-GPU peak memory")
    ap.add_argument("--probe-only", action="store_true", help="exit after --mem-probe")
    ap.add_argument("--probe-max-gib", type=float, default=38.0, help="with --mem-probe: exit 3 (PROBE_FAIL) if any GPU peak exceeds this")
    args = ap.parse_args()

    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(args.model)
    train, dropped = load_examples(tok, args.train, args.max_len, args.mask_thinking)
    lens = sorted(len(i) for i, _ in train)
    sup = [sum(1 for x in l if x != -100) for _, l in train]
    print(f"train: {len(train)} examples ({dropped} dropped > {args.max_len} tokens); tokens min {lens[0]} "
          f"median {lens[len(lens)//2]} max {lens[-1]}; supervised tokens/example median {sorted(sup)[len(sup)//2]} "
          f"({100*sum(sup)/sum(lens):.0f}% of tokens); mask_thinking={args.mask_thinking}")
    evals = []
    if args.eval:
        evals, edrop = load_examples(tok, args.eval, args.max_len, args.mask_thinking)
        print(f"eval: {len(evals)} examples ({edrop} dropped)")
    if args.dry_run:
        ids, labels = train[0]
        first = next(i for i, x in enumerate(labels) if x != -100)
        print("first supervised span starts at token", first, "->", repr(tok.decode(ids[first:first + 40])))
        if args.mask_thinking:
            full = tok.decode(ids)
            n_blocks = len(THINK_RE.findall(full))
            sup_text = tok.decode([t for t, l in zip(ids, labels) if l != -100][:120])
            print(f"thinking blocks in example 0: {n_blocks}; supervised text begins: {sup_text[:300]!r}")
        return

    import contextlib

    import torch
    import torch.nn.functional as F
    import torch.utils.checkpoint
    from peft import LoraConfig, get_peft_model
    from transformers import AutoConfig, AutoModelForCausalLM, get_cosine_schedule_with_warmup

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    cfg = AutoConfig.from_pretrained(args.model)
    print("architectures:", getattr(cfg, "architectures", None))
    n_gpu = torch.cuda.device_count()
    from transformers import AutoModelForImageTextToText

    def auto_cls_call(fn_name, *a, **kw):
        try:
            return getattr(AutoModelForCausalLM, fn_name)(*a, **kw)
        except Exception as e:  # multimodal checkpoint without a causal-LM mapping
            print(f"AutoModelForCausalLM.{fn_name} failed:", str(e)[:200], "-> trying AutoModelForImageTextToText")
            return getattr(AutoModelForImageTextToText, fn_name)(*a, **kw)

    def explicit_device_map(split):
        """Place decoder layers by an explicit per-GPU count; embeddings/lm_head on GPU 0, norm + towers on the last GPU."""
        from accelerate import init_empty_weights

        with init_empty_weights():
            skel = auto_cls_call("from_config", cfg)
        layers_name = None
        for name, mod in skel.named_modules():
            if name.endswith("layers") and isinstance(mod, torch.nn.ModuleList) and len(mod) == sum(split):
                layers_name = name
                break
        if layers_name is None:
            raise SystemExit(f"--layer-split sums to {sum(split)} but no decoder ModuleList of that length was found")
        parent = layers_name.rsplit(".", 1)[0]
        last = max(i for i, c in enumerate(split) if c > 0)
        dm, bounds, acc = {}, [], 0
        for c in split:
            acc += c
            bounds.append(acc)
        for i in range(sum(split)):
            dm[f"{layers_name}.{i}"] = next(d for d, b in enumerate(bounds) if i < b)
        for cname, _ in skel.get_submodule(parent).named_children():
            if cname == "layers":
                continue
            dm[f"{parent}.{cname}"] = last if "norm" in cname else 0

        def assign_others(mod, prefix):
            for cname, cmod in mod.named_children():
                full = f"{prefix}.{cname}" if prefix else cname
                if full == parent:
                    continue
                if parent.startswith(full + "."):
                    assign_others(cmod, full)
                    continue
                dm[full] = 0 if (full == "lm_head" or "embed_tokens" in full) else last

        assign_others(skel, "")
        static = [0.0] * n_gpu
        tied = bool(getattr(cfg, "tie_word_embeddings", False))
        for pname, p in list(skel.named_parameters()) + list(skel.named_buffers()):
            key = next((k for k in dm if pname == k or pname.startswith(k + ".")), None)
            if key is None:
                raise SystemExit(f"device map does not cover {pname}")
            if not (tied and pname.startswith("lm_head")):
                static[dm[key]] += p.numel() * 2 / 2**30
        print("layer split:", split, "static bf16 GiB per GPU:", [round(s, 2) for s in static])
        print("non-layer placements:", {k: v for k, v in dm.items() if f"{layers_name}." not in k})
        return dm

    load_kwargs = dict(dtype=torch.bfloat16, attn_implementation="sdpa")
    if args.layer_split:
        split = [int(x) for x in args.layer_split.split(",")]
        if len(split) != n_gpu:
            raise SystemExit(f"--layer-split has {len(split)} entries but {n_gpu} GPUs are visible")
        load_kwargs["device_map"] = explicit_device_map(split)
    else:
        caps = [float(x) for x in str(args.max_memory_gib).split(",")]
        if len(caps) == 1:
            caps = caps * n_gpu
        max_memory = {i: f"{caps[i]}GiB" for i in range(n_gpu)}
        load_kwargs.update(device_map="auto", max_memory=max_memory)
        print("max_memory:", max_memory)
    model = auto_cls_call("from_pretrained", args.model, **load_kwargs)
    hdm = getattr(model, "hf_device_map", {}) or {}
    per_dev = {}
    for k, v in hdm.items():
        if ".layers." in k:
            per_dev[v] = per_dev.get(v, 0) + 1
    print("device map: layers per device", dict(sorted(per_dev.items())),
          {k: v for k, v in sorted(hdm.items()) if k.endswith(("lm_head", "embed_tokens", "norm")) or "tower" in k or "embed_vision" in k})
    # --offload-ckpt: reentrant checkpointing saves each layer's input via save_for_backward, which the
    # save_on_cpu hook (see supervised_loss) moves to pinned host memory; non-reentrant keeps it in a closure.
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": bool(args.offload_ckpt)})
    model.enable_input_require_grads()
    model.config.use_cache = False

    def find_body_and_head(m):
        """Locate the decoder body (returns hidden states) and the LM head."""
        head = m.get_output_embeddings()
        for path in ("model.language_model", "language_model.model", "language_model", "model"):
            obj = m
            try:
                for part in path.split("."):
                    obj = getattr(obj, part)
            except AttributeError:
                continue
            if hasattr(obj, "layers") or hasattr(obj, "embed_tokens"):
                print("decoder body:", path, type(obj).__name__)
                return obj, head
        raise SystemExit("could not locate the decoder body; inspect the model class")

    def supervised_loss(peft_model, ids, labels):
        """Cross-entropy only at supervised positions, lm_head applied in chunks (262K vocab)."""
        base = peft_model.get_base_model()
        body, head = find_body_and_head.cache if hasattr(find_body_and_head, "cache") else find_body_and_head(base)
        find_body_and_head.cache = (body, head)
        dev = next(body.parameters()).device
        x = torch.tensor([ids], device=dev)
        # position t predicts token t+1
        tgt_pos = [t for t in range(len(ids) - 1) if labels[t + 1] != -100]
        if not tgt_pos:
            return None, 0
        grad_on = torch.is_grad_enabled()
        saved_ctx = (torch.autograd.graph.save_on_cpu(pin_memory=True)
                     if (args.offload_ckpt and grad_on) else contextlib.nullcontext())

        def chunk_loss(hc, tc):
            return F.cross_entropy(head(hc).float(), tc, reduction="sum")

        C = args.head_chunk
        with saved_ctx:
            hidden = body(input_ids=x).last_hidden_state[0]  # [T, H]
            pos = torch.tensor(tgt_pos, device=hidden.device)
            tgt = torch.tensor([labels[t + 1] for t in tgt_pos], device=head.weight.device)
            h = hidden.index_select(0, pos).to(head.weight.device)
            total = torch.zeros((), device=head.weight.device, dtype=torch.float32)
            for s in range(0, h.shape[0], C):
                if grad_on:  # recompute the 262K-wide fp32 logits in backward instead of keeping every chunk alive
                    total = total + torch.utils.checkpoint.checkpoint(chunk_loss, h[s: s + C], tgt[s: s + C], use_reentrant=False)
                else:
                    total = total + chunk_loss(h[s: s + C], tgt[s: s + C])
        return total, len(tgt_pos)

    def gpu_peaks(reset=True):
        peaks = [round(torch.cuda.max_memory_allocated(i) / 2**30, 1) for i in range(n_gpu)]
        if reset:
            for i in range(n_gpu):
                torch.cuda.reset_peak_memory_stats(i)
        return peaks
    # Only the text decoder's projections: the vision/audio towers use Gemma4ClippableLinear
    # (not an nn.Linear) under the same names, which PEFT cannot wrap and we do not want to train.
    lcfg = LoraConfig(
        r=args.rank, lora_alpha=args.alpha, lora_dropout=args.dropout, bias="none", task_type="CAUSAL_LM",
        target_modules=r"^model\.language_model\..*\.(?:q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)$",
    )
    if args.resume_adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, args.resume_adapter, is_trainable=True)
        print("resumed adapter from", args.resume_adapter, "starting at epoch", args.start_epoch)
    else:
        model = get_peft_model(model, lcfg)
    model.print_trainable_parameters()

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=0.0, betas=(0.9, 0.999))
    steps_per_epoch = math.ceil(len(train) / args.grad_accum)
    total = steps_per_epoch * args.epochs
    sched = get_cosine_schedule_with_warmup(opt, num_warmup_steps=max(1, total // 10), num_training_steps=total)
    for _ in range(steps_per_epoch * args.start_epoch):  # advance the schedule past completed epochs
        sched.step()
    first_device = next(model.parameters()).device

    if args.mem_probe:
        n_sup = lambda i: sum(1 for x in train[i][1] if x != -100)  # noqa: E731
        cands = {"longest": max(range(len(train)), key=lambda i: len(train[i][0])),
                 "most_supervised": max(range(len(train)), key=n_sup)}
        worst = 0.0
        model.train()
        for tag, i in cands.items():
            gpu_peaks(reset=True)
            ids, labels = train[i]
            t1 = time.time()
            ls, k = supervised_loss(model, ids, labels)
            (ls / max(k, 1)).backward()
            peaks = gpu_peaks(reset=True)
            worst = max(worst, max(peaks))
            print(f"PROBE {tag}: tokens={len(ids)} supervised={k} loss={ls.item() / max(k, 1):.3f} "
                  f"peak_gib={peaks} secs={time.time() - t1:.0f}", flush=True)
            opt.zero_grad(set_to_none=True)
        print(f"PROBE_DONE worst_gib={worst} limit={args.probe_max_gib}", flush=True)
        if args.probe_only:
            return
        if worst > args.probe_max_gib:
            print("PROBE_FAIL: peak above limit; choose another --layer-split / --offload-ckpt", flush=True)
            raise SystemExit(3)

    def run_eval():
        if not evals:
            return None
        model.eval()
        tot, n = 0.0, 0
        with torch.no_grad():
            for ids, labels in evals:
                loss_sum, k = supervised_loss(model, ids, labels)
                if loss_sum is None:
                    continue
                tot += loss_sum.item()
                n += k
        model.train()
        return tot / max(n, 1)

    Path(args.out).mkdir(parents=True, exist_ok=True)
    log = open(Path(args.out) / "train_log.jsonl", "a")
    if args.start_epoch == 0:
        e0 = run_eval()
        print(f"eval loss before training: {e0}")
        log.write(json.dumps({"step": 0, "eval_loss": e0}) + "\n")
    model.train()
    step, t0 = steps_per_epoch * args.start_epoch, time.time()
    for epoch in range(args.start_epoch, args.epochs):
        order = list(range(len(train)))
        random.shuffle(order)
        for bi in range(0, len(order), args.grad_accum):
            batch = order[bi: bi + args.grad_accum]
            tok_count = sum(sum(1 for x in train[i][1][1:] if x != -100) for i in batch)
            loss_sum = 0.0
            for i in batch:
                ids, labels = train[i]
                ls, k = supervised_loss(model, ids, labels)
                if ls is None:
                    continue
                (ls / max(tok_count, 1)).backward()
                loss_sum += ls.item()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            sched.step()
            opt.zero_grad(set_to_none=True)
            step += 1
            rec = {"step": step, "epoch": epoch, "train_loss": loss_sum / max(tok_count, 1),
                   "lr": sched.get_last_lr()[0], "elapsed_s": round(time.time() - t0),
                   "peak_gib": gpu_peaks(reset=True)}
            log.write(json.dumps(rec) + "\n")
            log.flush()
            if step % 5 == 0 or step == total:
                print(json.dumps(rec), flush=True)
        e = run_eval()
        print(f"epoch {epoch} done: eval loss {e}", flush=True)
        log.write(json.dumps({"step": step, "epoch": epoch, "eval_loss": e}) + "\n")
        log.flush()
        model.save_pretrained(Path(args.out) / f"epoch{epoch}")
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    print("saved adapter to", args.out, os.listdir(args.out))


if __name__ == "__main__":
    main()
