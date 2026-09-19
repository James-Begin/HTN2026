"""Model construction, with Baseten's serving constraints baked in from step one.

Four requirements, all discovered the hard way and none optional:

  1. Save via `AutoModelForSequenceClassification`. The embeddings engine expects
     that head shape.
  2. `id2label` must be set EXPLICITLY. The engine build FAILS without it, and a
     permuted mapping would invert every metric while the numbers still looked
     plausible. `eval/scorers.py` cross-checks it on load for the same reason.
  3. Weights stay fp16, bf16 or fp32. Pre-quantized checkpoints are rejected.
  4. Ship a fast `tokenizer.json`.

Getting these wrong is only discovered at deploy time, ~4 minutes into an engine
build, which is why they are asserted here instead.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.dataset import LABELS  # noqa: E402

# bge-reranker-v2-m3 is a cross-encoder ALREADY trained for pair relevance, so this
# is a head swap plus continued training rather than learning the task from scratch.
# It is multilingual (XLM-R based), which is kept deliberately even while training on
# English only: the eval set's worst failure is an Arabic paraphrase at 0.012, and a
# multilingual base retains some chance of transfer that an English-only base cannot.
DEFAULT_BASE = "BAAI/bge-reranker-v2-m3"

# Smaller and faster, for the sweep to compare against. The cross-encoder is the
# inference hot path at 2,851 pairs/sec on one L4, so size is not a free parameter.
ALTERNATES = ["BAAI/bge-reranker-base", "cross-encoder/ms-marco-MiniLM-L-12-v2"]


def build(base: str = DEFAULT_BASE, dropout: float = None):
    """Return (model, tokenizer) with a 5-way head and a correct label mapping."""
    import torch
    from transformers import (AutoModelForSequenceClassification, AutoTokenizer)

    tok = AutoTokenizer.from_pretrained(base, use_fast=True)
    if not tok.is_fast:
        raise RuntimeError(f"{base} has no fast tokenizer; Baseten needs tokenizer.json")

    id2label = {i: l for i, l in enumerate(LABELS)}
    label2id = {l: i for i, l in enumerate(LABELS)}
    kwargs = dict(num_labels=len(LABELS), id2label=id2label, label2id=label2id,
                  ignore_mismatched_sizes=True)
    if dropout is not None:
        kwargs["classifier_dropout"] = dropout

    model = AutoModelForSequenceClassification.from_pretrained(
        base, dtype=torch.float32, **kwargs)

    # Assert rather than trust. A silently permuted mapping is the failure that would
    # look like a bad model instead of a bad config.
    got = [model.config.id2label[i] for i in range(len(LABELS))]
    if got != LABELS:
        raise RuntimeError(f"id2label mismatch: {got} != {LABELS}")
    return model, tok


def save(model, tok, path: str) -> None:
    """Save in the shape the engine build expects, then verify it round-trips."""
    os.makedirs(path, exist_ok=True)
    model.save_pretrained(path, safe_serialization=True)
    tok.save_pretrained(path)

    if not os.path.exists(os.path.join(path, "tokenizer.json")):
        raise RuntimeError(f"{path} has no tokenizer.json; the engine build needs one")
    import json
    cfg = json.load(open(os.path.join(path, "config.json")))
    if not cfg.get("id2label"):
        raise RuntimeError(f"{path}/config.json has no id2label; the build will FAIL")
    order = [cfg["id2label"][str(i)] for i in range(len(LABELS))]
    if order != LABELS:
        raise RuntimeError(f"saved id2label order {order} != {LABELS}")
