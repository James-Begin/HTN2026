"""Training loop for the 5-class claim-equivalence cross-encoder.

The objective is deliberately NOT plain 5-way cross-entropy.

Measured label agreement against hand labels is 94% on the same-versus-not decision
and 74% on the exact subtype. So the two signals in the data are not equally
trustworthy, and treating them as if they were would fit noise in the head that
matters least. The loss is therefore:

    L = w_ce * weighted_CE(5-way) + w_bin * BCE(p_verbatim + p_paraphrase)

The second term optimises exactly the quantity the pipeline consumes, `same_claim`,
which is what every gate and every threshold in eval/ is defined on.

Selection is on ROC AUC plus a robust margin, not on accuracy and NOT on the raw
separation margin. Accuracy at a fixed cutoff is satisfiable by a model that is
useless at every other cutoff. But the raw margin is a min-max statistic, and on a
machine-labelled validation split it is set by whichever single row is mislabelled: a
checkpoint scoring AUC 0.987 reported a margin of -0.95, worse than the untrained
baseline, because 2 rows of 1,008 sat on the wrong side. Selecting on that would have
thrown away a good model.

The raw margin stays the GATE metric on eval/pairs.jsonl, where all 25 pairs are
hand-labelled and a single failure genuinely matters. Same statistic, different
trustworthiness of the underlying labels. The same metrics module is imported for
both, so the number selected on and the number reported are computed by identical
code.
"""
import os
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval import metrics as M  # noqa: E402
from eval.dataset import LABELS, POSITIVE_LABELS, Pair  # noqa: E402


@dataclass
class Config:
    base: str = "BAAI/bge-reranker-v2-m3"
    lr: float = 2e-5
    epochs: int = 3
    batch_size: int = 16
    grad_accum: int = 1
    max_length: int = 256
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    binary_loss_weight: float = 1.0
    ce_loss_weight: float = 1.0
    label_smoothing: float = 0.05
    dropout: Optional[float] = None
    seed: int = 0
    bf16: bool = True
    out: str = "runs/xenc"
    tags: List[str] = field(default_factory=list)

    def name(self) -> str:
        short = self.base.rsplit("/", 1)[-1]
        return (f"{short}_lr{self.lr:g}_bs{self.batch_size}_e{self.epochs}"
                f"_bin{self.binary_loss_weight:g}_ls{self.label_smoothing:g}")


class LengthGroupedBatches:
    """Batch sampler that groups examples of similar length.

    Measured on the English training set: true pair lengths are median 45 tokens, p90
    91, max 163, but RANDOM batching pads every batch to its own maximum and therefore
    processes **1.91x** the true token count. Length-grouped batching pads to 1.01x, so
    nearly half the compute was going into padding.

    Stochasticity is preserved by sorting only WITHIN a shuffled megabatch and then
    shuffling the batch order, rather than sorting globally. A globally sorted epoch
    would feed the model all the short pairs first, which correlates length with
    training order and biases the optimiser.

    Length uses a character-count proxy rather than tokenising up front: it correlates
    tightly with token count for this data and costs nothing.
    """

    def __init__(self, lengths, batch_size, mega=50, seed=0):
        self.lengths = lengths
        self.batch_size = batch_size
        self.mega = mega
        self.seed = seed
        self.epoch = 0

    def __len__(self):
        return (len(self.lengths) + self.batch_size - 1) // self.batch_size

    def __iter__(self):
        import random
        rng = random.Random(self.seed + self.epoch)
        self.epoch += 1
        idx = list(range(len(self.lengths)))
        rng.shuffle(idx)
        span = self.batch_size * self.mega
        batches = []
        for start in range(0, len(idx), span):
            chunk = sorted(idx[start:start + span], key=lambda i: self.lengths[i])
            for b in range(0, len(chunk), self.batch_size):
                batches.append(chunk[b:b + self.batch_size])
        rng.shuffle(batches)
        return iter(batches)


class PairDataset:
    def __init__(self, examples, tok, max_length):
        self.ex = examples
        self.tok = tok
        self.max_length = max_length

    def __len__(self):
        return len(self.ex)

    def __getitem__(self, i):
        return self.ex[i]

    def collate(self, batch):
        import torch
        enc = self.tok([b["reference"] for b in batch], [b["candidate"] for b in batch],
                       padding=True, truncation=True, max_length=self.max_length,
                       return_tensors="pt")
        enc["labels"] = torch.tensor([b["label"] for b in batch], dtype=torch.long)
        enc["is_same"] = torch.tensor([b["is_same"] for b in batch], dtype=torch.float)
        return enc


def _same_prob(logits, torch):
    """p(same_verbatim) + p(same_paraphrase), the quantity the pipeline consumes."""
    probs = torch.softmax(logits.float(), dim=-1)
    idx = [LABELS.index(l) for l in sorted(POSITIVE_LABELS)]
    return probs[:, idx].sum(dim=-1), probs


@dataclass
class EvalResult:
    loss: float
    report: dict
    scores: List[float]

    @property
    def margin(self):
        return self.report.get("separation_margin")

    @property
    def robust(self):
        return self.report.get("robust_separation_p5")

    @property
    def selection_score(self):
        """What checkpoints are chosen on.

        NOT the raw separation margin. On a machine-labelled validation split that is
        a min-max statistic over noisy rows, and it rejected a checkpoint that scored
        ROC AUC 0.987 because two rows of 1,008 sat on the wrong side. AUC is
        threshold-free and robust to exactly that, and the robust margin breaks ties
        toward models whose score distributions are actually separated.
        """
        auc = self.report.get("roc_auc") or 0.0
        rob = self.report.get("robust_separation_p5") or 0.0
        return auc + 0.1 * rob


def evaluate(model, loader, device, torch, class_w=None):
    """Score the validation split and compute the SAME metrics as the release gate."""
    model.eval()
    preds, total_loss, n = [], 0.0, 0
    ce = torch.nn.CrossEntropyLoss(
        weight=None if class_w is None else torch.tensor(class_w, device=device))
    with torch.no_grad():
        for batch in loader:
            labels = batch.pop("labels").to(device)
            is_same = batch.pop("is_same").to(device)
            batch = {k: v.to(device) for k, v in batch.items()}
            logits = model(**batch).logits
            total_loss += float(ce(logits, labels)) * labels.size(0)
            n += labels.size(0)
            same, probs = _same_prob(logits, torch)
            for j in range(labels.size(0)):
                gold = LABELS[int(labels[j])]
                pair = Pair(id=f"v{len(preds)}", reference="", candidate="",
                            label=gold, confidence="machine")
                dist = {l: float(probs[j, k]) for k, l in enumerate(LABELS)}
                preds.append((pair, float(same[j]), dist))
    report = M.evaluate(preds)
    return EvalResult(total_loss / max(n, 1), report, [s for _, s, _ in preds])


def train(cfg: Config, train_rows, val_rows, log=print):
    import torch
    from torch.utils.data import DataLoader
    from transformers import get_linear_schedule_with_warmup

    from . import model as MB
    from .data import class_weights, to_examples

    torch.manual_seed(cfg.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        # THE THREAD OPTIMUM IS MODEL-DEPENDENT, and both ends of the range hurt.
        # Measured on this box, 192 cores, AVX2 only, no AMX, on real batches:
        #
        #   bge-reranker-base   278M   16: 1.12s/step   48: 1.52   96: 2.80
        #   bge-reranker-v2-m3  568M   16: 6.79s/step   32: 3.30   48: 3.02
        #                              64: 2.51 (best)  80: 3.49   96: 3.41  128: 3.47
        #
        # It also depends on SEQUENCE LENGTH. After length-grouped batching cut the mean
        # batch from 123 tokens to 61, the same 568M model reversed completely:
        #   16: 5.34s/step (best)   32: 10.58   64: 27.06
        # Less compute per step means parallelisation overhead dominates sooner. So the
        # optimum is a function of model size AND batch shape, and 16 is the safe default.
        #
        # So the small model wants 16 and the large one wants 64, a 2.7x difference on the
        # large model between the two settings. Transformer training on CPU is
        # memory-bandwidth bound, and the point where extra threads stop buying bandwidth
        # and start costing synchronisation moves with the model's arithmetic per byte.
        # Having 192 cores does not help either way; nothing above 64 was ever fastest.
        # SET THIS PER MODEL. The default suits the small one.
        n = int(os.environ.get("CLAIMTRACE_CPU_THREADS", "16"))
        # CAP OPENMP TOO. `torch.set_num_threads` sets only torch's intra-op pool;
        # oneDNN and MKL spawn their OWN pools sized from nproc, which was 192 here. So
        # 64 torch threads each fanning out to a 192-wide OMP pool is self-inflicted
        # oversubscription. Observed consequence: a run consumed 3.8 epochs' worth of CPU
        # time to finish 1 epoch, burning the rest on barrier spinning, while the box was
        # separately at load 360. Set both, and set them BEFORE the pools are created.
        os.environ.setdefault("OMP_NUM_THREADS", str(n))
        os.environ.setdefault("MKL_NUM_THREADS", str(n))
        os.environ.setdefault("OPENBLAS_NUM_THREADS", str(n))
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        torch.set_num_threads(n)
        torch.set_num_interop_threads(1) if torch.get_num_interop_threads() != 1 else None
        log(f"  cpu training, {torch.get_num_threads()} threads, OMP capped at {n}")
    model, tok = MB.build(cfg.base, dropout=cfg.dropout)
    model.to(device)

    cw = class_weights(train_rows)
    tr_ds = PairDataset(to_examples(train_rows), tok, cfg.max_length)
    va_ds = PairDataset(to_examples(val_rows), tok, cfg.max_length)
    workers = 0 if device == "cpu" else 2
    tr_len = [len(e["reference"]) + len(e["candidate"]) for e in tr_ds.ex]
    tr = DataLoader(tr_ds, collate_fn=tr_ds.collate, num_workers=workers,
                    batch_sampler=LengthGroupedBatches(tr_len, cfg.batch_size,
                                                       seed=cfg.seed))
    va_bs = max(cfg.batch_size, 32)
    va_len = [len(e["reference"]) + len(e["candidate"]) for e in va_ds.ex]
    va = DataLoader(va_ds, collate_fn=va_ds.collate, num_workers=workers,
                    batch_sampler=LengthGroupedBatches(va_len, va_bs, seed=0))

    steps = max(1, len(tr) // cfg.grad_accum) * cfg.epochs
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    sched = get_linear_schedule_with_warmup(opt, int(steps * cfg.warmup_ratio), steps)
    ce = torch.nn.CrossEntropyLoss(weight=torch.tensor(cw, device=device),
                                   label_smoothing=cfg.label_smoothing)
    bce = torch.nn.BCELoss()
    amp = torch.bfloat16 if (cfg.bf16 and device == "cuda") else torch.float32

    log(f"  {cfg.name()}")
    log(f"  {len(train_rows)} train / {len(val_rows)} val, {steps} steps, device {device}")
    log(f"  class weights: " + ", ".join(f"{l}={w:.2f}" for l, w in zip(LABELS, cw)))

    best = None
    history = []
    for epoch in range(1, cfg.epochs + 1):
        model.train()
        t0, running = time.time(), 0.0
        opt.zero_grad(set_to_none=True)
        for step, batch in enumerate(tr, 1):
            labels = batch.pop("labels").to(device)
            is_same = batch.pop("is_same").to(device)
            batch = {k: v.to(device) for k, v in batch.items()}
            with torch.autocast(device_type="cuda", dtype=amp, enabled=(amp != torch.float32)):
                logits = model(**batch).logits
            same, _ = _same_prob(logits, torch)
            loss = (cfg.ce_loss_weight * ce(logits.float(), labels)
                    + cfg.binary_loss_weight * bce(same.clamp(1e-6, 1 - 1e-6), is_same))
            (loss / cfg.grad_accum).backward()
            running += float(loss)
            if step % cfg.grad_accum == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)

        res = evaluate(model, va, device, torch, cw)
        at = res.report["at_threshold"]
        row = {"epoch": epoch, "train_loss": running / max(len(tr), 1),
               "val_loss": res.loss, "margin": res.margin,
               "robust_margin": res.robust, "selection": res.selection_score,
               "roc_auc": res.report["roc_auc"], "ece": res.report["ece"],
               "binary_f1": at["f1"], "precision": at["precision"],
               "recall": at["recall"],
               "coverage_at_perfect": res.report["max_coverage_at_perfect_precision"],
               "secs": time.time() - t0}
        history.append(row)
        log(f"  epoch {epoch}  loss {row['train_loss']:.4f}/{row['val_loss']:.4f}  "
            f"auc {row['roc_auc']:.4f}  robust {row['robust_margin']:+.4f}  "
            f"margin {row['margin']:+.4f}  F1 {row['binary_f1']:.4f}  "
            f"ECE {row['ece']:.4f}  sel {row['selection']:.4f}  {row['secs']:.0f}s")

        if best is None or res.selection_score > best["selection"]:
            best = {"epoch": epoch, "margin": res.margin, "robust": res.robust,
                    "selection": res.selection_score, "report": res.report}
            MB.save(model, tok, cfg.out)
            log(f"    saved (best selection score) -> {cfg.out}")

    return {"config": cfg.__dict__, "history": history, "best": best,
            "class_weights": cw}
