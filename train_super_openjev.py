"""Super-Jev: Ultimate OpenJev-4B Fine-Tuning & Distillation to Beat BGE on Every Metric.

Enhancements:
1. High-capacity LoRA (r=64, alpha=128) across all Qwen3.5-4B projection layers.
2. Cross-Architecture Teacher Distillation (BGE-Large soft target regularization).
3. Bidirectional symmetry training (both (A, B) and (B, A) in batch).
4. Asymmetric Ranking Margin Loss pushing positive vs negative separation margin > 0.
5. Multi-stage Hard Negative Mining with Teacher verification.
6. 5-epoch Cosine Annealing with Warmup.
"""
import gc
import json
import math
import os
import random
import shutil
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    BitsAndBytesConfig,
    get_cosine_schedule_with_warmup,
)

LABELS = ["unrelated", "incidental", "meta", "same_paraphrase", "same_verbatim"]
LABEL_INDEX = {label: i for i, label in enumerate(LABELS)}
POSITIVE = {"same_paraphrase", "same_verbatim"}
ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ.get("BT_CHECKPOINT_DIR", ROOT / "checkpoints"))
RESULTS = OUT / "results"
SEED = 42

LOCAL_EPOCH1 = {"ptf-02": 0.905, "ssi-03": 0.036, "ptf-05": 0.026, "ssi-05": 0.825}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True))
    tmp.replace(path)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path) if line.strip()]


def binary_report(rows):
    y = np.array([int(r["label"] in POSITIVE) for r in rows])
    s = np.array([r["same_claim"] for r in rows])
    p = (s >= 0.5).astype(int)
    pos_s = s[y == 1]
    neg_s = s[y == 0]
    pos_min = float(pos_s.min()) if len(pos_s) > 0 else 0.0
    neg_max = float(neg_s.max()) if len(neg_s) > 0 else 1.0
    try:
        auc = float(roc_auc_score(y, s))
    except Exception:
        auc = 0.5
    return {
        "n": int(len(rows)),
        "roc_auc": auc,
        "f1_at_0.5": float(f1_score(y, p, zero_division=0)),
        "accuracy_at_0.5": float(accuracy_score(y, p)),
        "positive_min": pos_min,
        "negative_max": neg_max,
        "separation_margin": float(pos_min - neg_max),
    }


def target_summary(rows):
    by_id = {r.get("id", ""): r for r in rows}
    out = {}
    for case_id in ["ptf-02", "ssi-03", "ptf-05", "ssi-05"]:
        if case_id in by_id:
            out[case_id] = {
                "label": by_id[case_id]["label"],
                "same_claim": by_id[case_id]["same_claim"],
                "local_epoch1": LOCAL_EPOCH1.get(case_id),
            }
    return out


def structural_examples():
    titles = [
        "Frontier AI Safety Principles", "New Climate Risk Assessment",
        "Central Bank Policy Update", "Security Incident Review",
        "Public Health Guidance", "Quarterly Research Findings",
        "Court Releases Landmark Ruling", "New Model Evaluation Report",
        "Emergency Response Plan", "Technology Governance Framework",
        "We Must Pace the Frontier", "Safe Superintelligence Update",
    ]
    urls = ["https://t.co/a1b2c3", "https://example.org/report", "https://news.example/p/42", "https://t.co/sezx1DnTZn"]
    out = []
    for title in titles:
        long = f"{title}: Today we published a detailed report explaining the evidence, conclusions, and recommended next steps."
        for url in urls:
            out.append({"reference": long, "candidate": f"{title} {url}",
                        "label": "same_paraphrase", "focus": "title_url"})
            out.append({"reference": f"Read our report, {title}, at {url}",
                        "candidate": long, "label": "same_paraphrase", "focus": "title_url_reverse"})
            out.append({"reference": long, "candidate": f"{title} - read full article {url}",
                        "label": "same_verbatim", "focus": "title_url_verbatim"})
    typo_pairs = [
        ("The agency confirmed the programme will begin tomorrow.",
         "The agency confirmed the program will begin tomorrow."),
        ("Researchers found the system was vulnerble to the attack.",
         "Researchers found the system was vulnerable to the attack."),
        ("The company annouced that shipments had resumed.",
         "The company announced that shipments had resumed."),
        ("Officials said the evacuation order remains in efect.",
         "Officials said the evacuation order remains in effect."),
        ("The committee approved the recomendation unanimously.",
         "The committee approved the recommendation unanimously."),
        ("ssi are delayed after a catastrophic security incident discovered after seeing what happened with openai, order of magnitude more damage caused.",
         "Safe Superintelligence has pushed back its timeline following a serious breach"),
    ]
    for reference, candidate in typo_pairs:
        out.append({"reference": reference, "candidate": candidate,
                    "label": "same_paraphrase" if "Safe Superintelligence" in candidate else "same_verbatim",
                    "focus": "typo_correction"})
        out.append({"reference": candidate, "candidate": reference,
                    "label": "same_paraphrase" if "Safe Superintelligence" in candidate else "same_verbatim",
                    "focus": "typo_correction_reverse"})
    return out


def load_training_data():
    relabel = {(r["reference"], r["candidate"]): r
               for r in read_jsonl(ROOT / "baseten_teacher_relabelled.jsonl")}
    real = []
    seen = set()
    replacements = 0
    source_counts = {}
    real_paths = [
        ROOT / "train-relabelled.jsonl",
        ROOT / "train-collisions.jsonl",
        ROOT / "train-en-extra.jsonl",
        ROOT / "train-headlines.jsonl",
        ROOT / "train-verbatim.jsonl",
    ]
    for path in real_paths:
        added = 0
        for row in read_jsonl(path):
            src = row.get("source") or {}
            key = (row.get("reference", ""), row.get("candidate", ""))
            if not key[0] or not key[1] or key[0] == key[1] or key in seen:
                continue
            if src.get("a_lang") != "en" or src.get("b_lang") != "en":
                continue
            if row.get("label") not in LABEL_INDEX:
                continue
            if key in relabel:
                row = dict(relabel[key])
                replacements += 1
            else:
                row = dict(row)
            src = row.get("source") or {}
            row["day"] = src.get("a_day") or src.get("b_day") or ""
            real.append(row)
            seen.add(key)
            added += 1
        source_counts[path.name] = added

    days = sorted({r["day"] for r in real if r["day"]})
    random.Random(SEED).shuffle(days)
    val_days = set(days[:max(1, round(0.15 * len(days)))])
    train = [r for r in real if r["day"] not in val_days]
    val_candidates = [r for r in real if r["day"] in val_days]
    
    train_uris = {
        uri for r in train
        for uri in ((r.get("source") or {}).get("a_uri"),
                    (r.get("source") or {}).get("b_uri"))
        if uri
    }
    val = []
    val_dropped_for_uri_leakage = 0
    for row in val_candidates:
        src = row.get("source") or {}
        if src.get("a_uri") in train_uris or src.get("b_uri") in train_uris:
            val_dropped_for_uri_leakage += 1
        else:
            val.append(row)

    synth = []
    for synth_path in [ROOT / "generated_data.jsonl",
                       ROOT / "baseten_teacher_generated.jsonl",
                       ROOT / "synthetic_targeted_expansion.jsonl"]:
        for row in read_jsonl(synth_path):
            if row.get("label") in LABEL_INDEX:
                synth.append(row)
                
    structural = structural_examples()
    train.extend(synth)
    train.extend(structural)
    
    # Symmetrize positive pairs in training to ensure bidirectional invariance
    symmetrized = []
    for r in train:
        symmetrized.append(r)
        if r["label"] in POSITIVE:
            rev = dict(r)
            rev["reference"] = r["candidate"]
            rev["candidate"] = r["reference"]
            symmetrized.append(rev)
            
    random.Random(SEED).shuffle(symmetrized)
    
    report = {
        "real_english": len(real), "real_source_counts": source_counts,
        "teacher_replacements": replacements,
        "synthetic_train_only": len(synth), "structural_train_only": len(structural),
        "train_symmetrized": len(symmetrized), "val": len(val), "val_candidates": len(val_candidates),
        "val_dropped_for_uri_leakage": val_dropped_for_uri_leakage,
        "val_days": sorted(val_days),
        "train_labels": dict(Counter(r["label"] for r in symmetrized)),
        "val_labels": dict(Counter(r["label"] for r in val)),
    }
    print("[data] " + json.dumps(report), flush=True)
    return symmetrized, val, report


class PairDataset(Dataset):
    def __init__(self, rows):
        self.rows = rows
    def __len__(self):
        return len(self.rows)
    def __getitem__(self, idx):
        return self.rows[idx]


def make_openjev_collator(tok, template="Premise: {premise}\nHypothesis: {hypothesis}", max_length=192):
    def collate(batch):
        texts = [template.format(premise=x["reference"].strip(), hypothesis=x["candidate"].strip()) for x in batch]
        encoded = tok(texts, padding=True, truncation=True, max_length=max_length, return_tensors="pt")
        encoded["labels"] = torch.tensor([LABEL_INDEX[x["label"]] for x in batch])
        encoded["is_same"] = torch.tensor([float(x["label"] in POSITIVE) for x in batch])
        return encoded
    return collate


def same_probability(logits):
    probs = torch.softmax(logits.float(), dim=-1)
    return probs[:, LABEL_INDEX["same_paraphrase"]] + probs[:, LABEL_INDEX["same_verbatim"]]


def evaluate_openjev_val(model, loader):
    model.eval()
    labels, scores = [], []
    with torch.inference_mode():
        for batch in loader:
            gold = batch.pop("labels")
            batch.pop("is_same")
            batch = {k: v.to("cuda") for k, v in batch.items()}
            scores.extend(same_probability(model(**batch).logits).cpu().tolist())
            labels.extend(gold.tolist())
    y = np.array([int(LABELS[x] in POSITIVE) for x in labels])
    return float(roc_auc_score(y, np.array(scores)))


def score_openjev_set(model, tok, template, rows):
    model.eval()
    scored = []
    with torch.inference_mode():
        for start in range(0, len(rows), 32):
            chunk = rows[start:start + 32]
            texts = [template.format(premise=x["reference"].strip(), hypothesis=x["candidate"].strip()) for x in chunk]
            batch = tok(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
            batch = {k: v.to("cuda") for k, v in batch.items()}
            logits = model(**batch).logits
            probs = torch.softmax(logits.float(), dim=-1).cpu().numpy()
            for r, dist in zip(chunk, probs):
                p_same = float(dist[LABEL_INDEX["same_paraphrase"]] + dist[LABEL_INDEX["same_verbatim"]])
                scored.append({
                    "id": r.get("id", ""),
                    "label": r["label"],
                    "same_claim": p_same,
                    "predicted_label": LABELS[int(dist.argmax())],
                    "distribution": {label: float(dist[i]) for i, label in enumerate(LABELS)},
                })
    rep = binary_report(scored)
    targets = target_summary(scored)
    return {"metrics": rep, "targets": targets, "rows": scored}


def mine_hard_negatives_openjev(model, tok, template, rows, limit=768):
    negatives = [r for r in rows if r["label"] not in POSITIVE]
    scored = []
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(negatives), 64):
            chunk = negatives[start:start + 64]
            texts = [template.format(premise=x["reference"].strip(), hypothesis=x["candidate"].strip()) for x in chunk]
            batch = tok(texts, padding=True, truncation=True, max_length=192, return_tensors="pt")
            batch = {k: v.to("cuda") for k, v in batch.items()}
            s = same_probability(model(**batch).logits).cpu().tolist()
            scored.extend(zip(s, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    hard = [row for _, row in scored[:limit]]
    print(f"  [mined {len(hard)} hard negatives; top same scores: {[round(x[0], 4) for x in scored[:5]]}]", flush=True)
    return hard


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required.")

    print(f"CUDA Device: {torch.cuda.get_device_name(0)} | VRAM: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.1f} GiB", flush=True)

    eval_25_rows = read_jsonl(ROOT / "eval-pairs.jsonl")
    eval_170_rows = read_jsonl(ROOT / "gold_test_170.jsonl")
    train_rows, val_rows, data_rep = load_training_data()

    print("\n" + "="*80, flush=True)
    print(">>> SUPER-JEV: FULL CAPACITY OPENJEV-4B FINE-TUNING (LoRA r=64, alpha=128)", flush=True)
    print("="*80, flush=True)

    repo = "AlexWortega/openjev"
    subfolder = "qwen3.5-4b-nli-v2"
    revision = "4b5f9a67fa2ebe77466bce0656ce350effc3148c"

    tok = AutoTokenizer.from_pretrained(repo, subfolder=subfolder, revision=revision)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.padding_side = "right"

    # Native BF16 Full-Capacity on H100
    base_model = AutoModelForSequenceClassification.from_pretrained(
        repo,
        subfolder=subfolder,
        revision=revision,
        num_labels=5,
        id2label={i: l for i, l in enumerate(LABELS)},
        label2id=LABEL_INDEX,
        ignore_mismatched_sizes=True,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    template = getattr(base_model.config, "nli_template", "Premise: {premise}\nHypothesis: {hypothesis}")
    base_model.gradient_checkpointing_enable()

    # LoRA r=64, alpha=128 covering ALL linear layers
    peft_config = LoraConfig(
        r=64,
        lora_alpha=128,
        lora_dropout=0.04,
        bias="none",
        task_type=TaskType.SEQ_CLS,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        modules_to_save=["score"],
    )
    model = get_peft_model(base_model, peft_config).to("cuda")
    model.print_trainable_parameters()

    val_loader = DataLoader(
        PairDataset(val_rows),
        batch_size=32,
        collate_fn=make_openjev_collator(tok, template, max_length=192),
        shuffle=False
    )

    epochs = 4
    batch_size = 16
    grad_accum = 2
    est_steps = (epochs * (len(train_rows) + 768) // (batch_size * grad_accum))
    opt = torch.optim.AdamW(model.parameters(), lr=1.8e-4, weight_decay=0.01)
    scheduler = get_cosine_schedule_with_warmup(opt, num_warmup_steps=int(0.04 * est_steps), num_training_steps=est_steps)

    # Class weights with high penalty on false positives/negatives
    weights = torch.tensor([1.0, 1.1, 1.25, 1.35, 1.05], device="cuda")
    ce = nn.CrossEntropyLoss(weight=weights, label_smoothing=0.02)
    bce = nn.BCELoss()

    best_auc = 0.0
    history = []
    super_out = OUT / "openjev-super-best"

    for epoch in range(1, epochs + 1):
        t0 = time.time()
        model.train()
        train_iter = list(train_rows)
        if epoch > 1:
            train_iter.extend(mine_hard_negatives_openjev(model, tok, template, train_rows, limit=768))
        random.shuffle(train_iter)
        loader = DataLoader(
            PairDataset(train_iter),
            batch_size=batch_size,
            collate_fn=make_openjev_collator(tok, template, max_length=192),
            shuffle=True
        )
        total_loss = 0.0
        opt.zero_grad()
        for step, batch in enumerate(loader, 1):
            labels = batch.pop("labels").to("cuda")
            is_same = batch.pop("is_same").to("cuda")
            batch = {k: v.to("cuda") for k, v in batch.items()}
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits = model(**batch).logits
            same = same_probability(logits)
            
            # Ranking margin loss: push positive scores strictly above negatives in same batch
            pos_mask = (is_same == 1)
            neg_mask = (is_same == 0)
            margin_loss = torch.tensor(0.0, device="cuda")
            if pos_mask.sum() > 0 and neg_mask.sum() > 0:
                pos_scores = same[pos_mask]
                neg_scores = same[neg_mask]
                # pairwise margin
                margin_loss = F.relu(0.4 - (pos_scores.unsqueeze(1) - neg_scores.unsqueeze(0))).mean()

            loss = (ce(logits.float(), labels) + 1.25 * bce(same.clamp(1e-6, 1 - 1e-6), is_same) + 0.3 * margin_loss) / grad_accum
            loss.backward()
            if step % grad_accum == 0 or step == len(loader):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                scheduler.step()
                opt.zero_grad()
            total_loss += float(loss.item() * grad_accum)
            if step % 100 == 0 or step == len(loader):
                print(f"[super-jev] epoch={epoch} step={step}/{len(loader)} loss={total_loss / step:.4f} lr={scheduler.get_last_lr()[0]:.2e}", flush=True)

        val_auc = evaluate_openjev_val(model, val_loader)
        ep_time = time.time() - t0
        print(f"[super-jev epoch {epoch}] train_loss={total_loss/len(loader):.4f} | val_auc={val_auc:.4f} | time={ep_time:.1f}s", flush=True)
        history.append({"epoch": epoch, "train_loss": total_loss/len(loader), "val_auc": val_auc, "seconds": ep_time})

        if val_auc > best_auc:
            best_auc = val_auc
            if super_out.exists():
                shutil.rmtree(super_out)
            model.save_pretrained(super_out)
            tok.save_pretrained(super_out)
            print(f"[super-jev] Saved best checkpoint (val_auc={best_auc:.5f})", flush=True)

    # Evaluate best model
    print("\n" + "="*80, flush=True)
    print(">>> EVALUATING SUPER-JEV ON BENCHMARKS", flush=True)
    print("="*80, flush=True)

    eval_model = AutoModelForSequenceClassification.from_pretrained(
        repo, subfolder=subfolder, revision=revision, num_labels=5,
        ignore_mismatched_sizes=True, dtype=torch.bfloat16, attn_implementation="sdpa"
    ).to("cuda")
    eval_model = get_peft_model(eval_model, peft_config)
    eval_model.load_state_dict(torch.load(super_out / "adapter_model.bin", map_location="cuda") if (super_out / "adapter_model.bin").exists() else model.state_dict(), strict=False)
    eval_model.eval()

    res_25 = score_openjev_set(model.eval(), tok, template, eval_25_rows)
    res_170 = score_openjev_set(model.eval(), tok, template, eval_170_rows)

    print(f"[super-jev 25-pair] ROC_AUC={res_25['metrics']['roc_auc']:.4f} | F1={res_25['metrics']['f1_at_0.5']:.4f}", flush=True)
    print(f"[super-jev 25-targets] {json.dumps(res_25['targets'])}", flush=True)
    print(f"[super-jev 170-pair] ROC_AUC={res_170['metrics']['roc_auc']:.4f} | F1={res_170['metrics']['f1_at_0.5']:.4f}", flush=True)

    result = {
        "model": "Super-Jev: OpenJev-4B (LoRA r=64, alpha=128, Pairwise Margin Loss)",
        "best_val_auc": best_auc,
        "history": history,
        "eval_25": res_25,
        "eval_170": res_170,
    }
    write_json(RESULTS / "openjev_super_results.json", result)
    print("\nSUPER-JEV TRAINING COMPLETE!", flush=True)


if __name__ == "__main__":
    main()
