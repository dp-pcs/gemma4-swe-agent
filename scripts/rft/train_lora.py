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

    import torch
    import torch.nn.functional as F
    from peft import LoraConfig, get_peft_model
    from transformers import AutoConfig, AutoModelForCausalLM, get_cosine_schedule_with_warmup

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    cfg = AutoConfig.from_pretrained(args.model)
    print("architectures:", getattr(cfg, "architectures", None))
    caps = [float(x) for x in str(args.max_memory_gib).split(",")]
    n_gpu = torch.cuda.device_count()
    if len(caps) == 1:
        caps = caps * n_gpu
    max_memory = {i: f"{caps[i]}GiB" for i in range(n_gpu)}
    load_kwargs = dict(dtype=torch.bfloat16, device_map="auto", max_memory=max_memory, attn_implementation="sdpa")
    print("max_memory:", max_memory)
    try:
        model = AutoModelForCausalLM.from_pretrained(args.model, **load_kwargs)
    except Exception as e:  # multimodal checkpoint without a causal-LM mapping
        print("AutoModelForCausalLM failed:", str(e)[:200], "-> trying AutoModelForImageTextToText")
        from transformers import AutoModelForImageTextToText

        model = AutoModelForImageTextToText.from_pretrained(args.model, **load_kwargs)
    print("device map:", {k: v for k, v in sorted(getattr(model, "hf_device_map", {}).items())
                          if k.endswith((".layers.0", ".layers.15", ".layers.30", ".layers.45", ".layers.59", "lm_head", "embed_tokens"))})
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
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
        hidden = body(input_ids=x).last_hidden_state[0]  # [T, H]
        # position t predicts token t+1
        tgt_pos = [t for t in range(len(ids) - 1) if labels[t + 1] != -100]
        if not tgt_pos:
            return None, 0
        pos = torch.tensor(tgt_pos, device=hidden.device)
        tgt = torch.tensor([labels[t + 1] for t in tgt_pos], device=head.weight.device)
        h = hidden.index_select(0, pos).to(head.weight.device)
        total = torch.zeros((), device=head.weight.device, dtype=torch.float32)
        for s in range(0, h.shape[0], 1024):
            logits = head(h[s: s + 1024]).float()
            total = total + F.cross_entropy(logits, tgt[s: s + 1024], reduction="sum")
        return total, len(tgt_pos)
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
                   "lr": sched.get_last_lr()[0], "elapsed_s": round(time.time() - t0)}
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
