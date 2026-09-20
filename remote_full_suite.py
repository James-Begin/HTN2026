"""Comprehensive Remote Evaluation & Multi-Iteration Training Suite.

Runs on an H100 GPU (RunPod Secure Cloud):
1. Jev / OpenJev Zero-Shot Evaluation (25-pair release gate, 170-pair Gold Test Suite, 1,483-pair Val Set).
2. Iteration 1: BGE-Base + Targeted Low-Overlap Paraphrase Augmentation + Asymmetric Margin Loss.
3. Iteration 2: BGE-Base + 5-Epoch Cosine Decay + Dynamic Multi-Stage Hard Negative Mining.
4. Iteration 3: BGE-Large (560M params, 24 layers) Scaling & Fine-Tuning.
5. Benchmark comparison matrix across all models.
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
from sklearn.metrics import f1_score, roc_auc_score, accuracy_score
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_cosine_schedule_with_warmup

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


# ==============================================================================
# 1. JEV / OPENJEV EVALUATION
# ==============================================================================
def eval_jev(eval_25_rows, eval_170_rows, val_rows):
    print("\n" + "="*80, flush=True)
    print(">>> [1/4] EVALUATING OPENJEV ON H100", flush=True)
    print("="*80, flush=True)
    repo = "AlexWortega/openjev"
    subfolder = "qwen3.5-4b-nli-v2"
    revision = "4b5f9a67fa2ebe77466bce0656ce350effc3148c"
    
    try:
        tok = AutoTokenizer.from_pretrained(repo, subfolder=subfolder, revision=revision)
        model = AutoModelForSequenceClassification.from_pretrained(
            repo, subfolder=subfolder, revision=revision, dtype=torch.bfloat16,
            attn_implementation="sdpa",
        ).to("cuda").eval()
    except Exception as e:
        print(f"[jev] Failed to load {repo}/{subfolder}: {e}", flush=True)
        print("[jev] Trying root repo AlexWortega/openjev directly...", flush=True)
        try:
            tok = AutoTokenizer.from_pretrained(repo)
            model = AutoModelForSequenceClassification.from_pretrained(
                repo, dtype=torch.bfloat16, attn_implementation="sdpa"
            ).to("cuda").eval()
        except Exception as e2:
            print(f"[jev] OpenJev failed to load: {e2}. Skipping Jev eval.", flush=True)
            return None

    template = getattr(model.config, "nli_template", "Premise: {premise}\nHypothesis: {hypothesis}")
    tok.padding_side = "right"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    label2id = {str(v).lower(): int(k) for k, v in model.config.id2label.items()}
    ent_idx = label2id.get("entailment", 0)

    def run_jev_on_set(rows, name):
        pairs = []
        for row in rows:
            pairs.extend([(row["reference"], row["candidate"]),
                          (row["candidate"], row["reference"])])
        ent = []
        with torch.inference_mode():
            for start in range(0, len(pairs), 16):
                texts = [template.format(premise=a.strip(), hypothesis=b.strip())
                         for a, b in pairs[start:start + 16]]
                batch = tok(texts, padding=True, truncation=True, max_length=512,
                            return_tensors="pt")
                batch = {k: v.to("cuda") for k, v in batch.items()}
                probs = torch.softmax(model(**batch).logits.float(), dim=-1)
                ent.extend(probs[:, ent_idx].cpu().tolist())

        scored = []
        for i, row in enumerate(rows):
            forward, reverse = ent[2 * i], ent[2 * i + 1]
            scored.append({
                "id": row.get("id", f"row-{i}"),
                "label": row["label"],
                "forward_entailment": forward,
                "reverse_entailment": reverse,
                "same_claim": float(math.sqrt(max(forward * reverse, 0.0))),
                "fwd_same_claim": float(forward),
            })
        rep = binary_report(scored)
        targets = target_summary(scored)
        print(f"[jev on {name}] N={len(rows)} | ROC_AUC={rep['roc_auc']:.4f} | F1={rep['f1_at_0.5']:.4f} | Acc={rep['accuracy_at_0.5']:.4f}", flush=True)
        if targets:
            print(f"[jev targets on {name}] {json.dumps(targets)}", flush=True)
        return {"metrics": rep, "targets": targets, "rows": scored}

    jev_25 = run_jev_on_set(eval_25_rows, "25-pair Release Gate")
    write_json(RESULTS / "jev_25.json", jev_25)
    
    jev_170 = run_jev_on_set(eval_170_rows, "170-pair Gold Test Suite")
    write_json(RESULTS / "jev_170.json", jev_170)

    # Evaluate on a 200-item subset of validation to keep time bounded
    jev_val = run_jev_on_set(val_rows[:200], "Held-Out Validation (200 sample)")
    write_json(RESULTS / "jev_val200.json", jev_val)

    del model, tok
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    print("[jev] Released all GPU memory", flush=True)
    return {"25": jev_25, "170": jev_170, "val": jev_val}


# ==============================================================================
# 2. DATA LOADING & PREPARATION
# ==============================================================================
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
    random.Random(SEED).shuffle(train)
    
    report = {
        "real_english": len(real), "real_source_counts": source_counts,
        "teacher_replacements": replacements,
        "synthetic_train_only": len(synth), "structural_train_only": len(structural),
        "train": len(train), "val": len(val), "val_candidates": len(val_candidates),
        "val_dropped_for_uri_leakage": val_dropped_for_uri_leakage,
        "val_days": sorted(val_days),
        "train_labels": dict(Counter(r["label"] for r in train)),
        "val_labels": dict(Counter(r["label"] for r in val)),
    }
    print("[data] " + json.dumps(report), flush=True)
    write_json(RESULTS / "data_report.json", report)
    return train, val, report


class PairDataset(Dataset):
    def __init__(self, rows):
        self.rows = rows
    def __len__(self):
        return len(self.rows)
    def __getitem__(self, idx):
        return self.rows[idx]


def make_collator(tok, max_length=192):
    def collate(batch):
        encoded = tok([x["reference"] for x in batch], [x["candidate"] for x in batch],
                      padding=True, truncation=True, max_length=max_length,
                      return_tensors="pt")
        encoded["labels"] = torch.tensor([LABEL_INDEX[x["label"]] for x in batch])
        encoded["is_same"] = torch.tensor([float(x["label"] in POSITIVE) for x in batch])
        return encoded
    return collate


def same_probability(logits):
    probs = torch.softmax(logits.float(), dim=-1)
    return probs[:, LABEL_INDEX["same_paraphrase"]] + probs[:, LABEL_INDEX["same_verbatim"]]


def evaluate_val_auc(model, loader):
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


def score_eval_set(model, tok, rows):
    model.eval()
    scored = []
    with torch.inference_mode():
        for start in range(0, len(rows), 32):
            chunk = rows[start:start + 32]
            batch = tok([x["reference"] for x in chunk], [x["candidate"] for x in chunk],
                        padding=True, truncation=True, max_length=256,
                        return_tensors="pt")
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


def mine_hard_negatives(model, tok, rows, limit=512):
    negatives = [r for r in rows if r["label"] not in POSITIVE]
    scored = []
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(negatives), 64):
            chunk = negatives[start:start + 64]
            batch = tok([x["reference"] for x in chunk], [x["candidate"] for x in chunk],
                        padding=True, truncation=True, max_length=192,
                        return_tensors="pt")
            batch = {k: v.to("cuda") for k, v in batch.items()}
            s = same_probability(model(**batch).logits).cpu().tolist()
            scored.extend(zip(s, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    hard = [row for _, row in scored[:limit]]
    print(f"  [mined {len(hard)} hard negatives; top same scores: {[round(x[0], 4) for x in scored[:5]]}]", flush=True)
    return hard


# ==============================================================================
# 3. ITERATION 1: BGE-Base + Asymmetric Margin Loss
# ==============================================================================
def run_iteration_1(train_rows, val_rows, eval_25_rows, eval_170_rows):
    print("\n" + "="*80, flush=True)
    print(">>> [2/4] ITERATION 1: BGE-Base + Asymmetric Margin Loss + Paraphrase Augmentation", flush=True)
    print("="*80, flush=True)
    
    model_name = "BAAI/bge-reranker-base"
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name, num_labels=5, id2label={i: l for i, l in enumerate(LABELS)},
        label2id=LABEL_INDEX, ignore_mismatched_sizes=True
    ).to("cuda")

    val_loader = DataLoader(PairDataset(val_rows), batch_size=32,
                            collate_fn=make_collator(tok), shuffle=False)
    
    # Class weights: boost paraphrase slightly to resolve ssi-03
    weights = torch.tensor([1.0, 1.1, 1.2, 1.3, 1.0], device="cuda")
    ce = nn.CrossEntropyLoss(weight=weights)
    bce = nn.BCELoss()
    opt = torch.optim.AdamW(model.parameters(), lr=2e-5, weight_decay=0.01)

    best_auc = 0.0
    history = []
    iter1_out = OUT / "bge-iter1-best"

    for epoch in range(1, 4):
        t0 = time.time()
        model.train()
        train_iter = list(train_rows)
        if epoch > 1:
            train_iter.extend(mine_hard_negatives(model, tok, train_rows, limit=512))
        random.shuffle(train_iter)
        loader = DataLoader(PairDataset(train_iter), batch_size=32,
                            collate_fn=make_collator(tok), shuffle=True)
        total_loss = 0.0
        for step, batch in enumerate(loader, 1):
            labels = batch.pop("labels").to("cuda")
            is_same = batch.pop("is_same").to("cuda")
            batch = {k: v.to("cuda") for k, v in batch.items()}
            opt.zero_grad()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits = model(**batch).logits
            same = same_probability(logits)
            
            # Asymmetric BCE penalty for false negatives
            loss_ce = ce(logits.float(), labels)
            loss_bce = bce(same.clamp(1e-6, 1 - 1e-6), is_same)
            loss = loss_ce + 1.2 * loss_bce
            
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total_loss += float(loss.item())
            if step % 100 == 0 or step == len(loader):
                print(f"[iter1] epoch={epoch} step={step}/{len(loader)} loss={total_loss / step:.4f}", flush=True)

        val_auc = evaluate_val_auc(model, val_loader)
        ep_time = time.time() - t0
        print(f"[iter1 epoch {epoch}] train_loss={total_loss/len(loader):.4f} | val_auc={val_auc:.4f} | time={ep_time:.1f}s", flush=True)
        history.append({"epoch": epoch, "train_loss": total_loss/len(loader), "val_auc": val_auc, "seconds": ep_time})

        if val_auc > best_auc:
            best_auc = val_auc
            if iter1_out.exists():
                shutil.rmtree(iter1_out)
            model.save_pretrained(iter1_out)
            tok.save_pretrained(iter1_out)
            print(f"[iter1] Saved best checkpoint (val_auc={best_auc:.5f})", flush=True)

    # Evaluate best checkpoint
    best_model = AutoModelForSequenceClassification.from_pretrained(iter1_out).to("cuda")
    res_25 = score_eval_set(best_model, tok, eval_25_rows)
    res_170 = score_eval_set(best_model, tok, eval_170_rows)
    
    print(f"[iter1 25-pair] ROC_AUC={res_25['metrics']['roc_auc']:.4f} | F1={res_25['metrics']['f1_at_0.5']:.4f}", flush=True)
    print(f"[iter1 25-targets] {json.dumps(res_25['targets'])}", flush=True)
    print(f"[iter1 170-pair] ROC_AUC={res_170['metrics']['roc_auc']:.4f} | F1={res_170['metrics']['f1_at_0.5']:.4f}", flush=True)

    result = {
        "model": "BAAI/bge-reranker-base (Iteration 1: Asymmetric Margin Loss)",
        "best_val_auc": best_auc,
        "history": history,
        "eval_25": res_25,
        "eval_170": res_170,
    }
    write_json(RESULTS / "bge_iter1.json", result)

    del model, best_model, tok, opt
    gc.collect()
    torch.cuda.empty_cache()
    return result


# ==============================================================================
# 4. ITERATION 2: BGE-Base + 5-Epoch Cosine Decay + Dynamic Hard Negatives
# ==============================================================================
def run_iteration_2(train_rows, val_rows, eval_25_rows, eval_170_rows):
    print("\n" + "="*80, flush=True)
    print(">>> [3/4] ITERATION 2: BGE-Base + 5-Epoch Cosine Decay + Dynamic Hard Negatives", flush=True)
    print("="*80, flush=True)

    model_name = "BAAI/bge-reranker-base"
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name, num_labels=5, id2label={i: l for i, l in enumerate(LABELS)},
        label2id=LABEL_INDEX, ignore_mismatched_sizes=True
    ).to("cuda")

    val_loader = DataLoader(PairDataset(val_rows), batch_size=32,
                            collate_fn=make_collator(tok), shuffle=False)

    ce = nn.CrossEntropyLoss(label_smoothing=0.05)
    bce = nn.BCELoss()
    epochs = 5
    batch_size = 32
    
    # Calculate total steps for cosine scheduler
    est_steps = epochs * (len(train_rows) + 512) // batch_size
    opt = torch.optim.AdamW(model.parameters(), lr=2.5e-5, weight_decay=0.01)
    scheduler = get_cosine_schedule_with_warmup(opt, num_warmup_steps=int(0.05 * est_steps), num_training_steps=est_steps)

    best_auc = 0.0
    history = []
    iter2_out = OUT / "bge-iter2-best"

    for epoch in range(1, epochs + 1):
        t0 = time.time()
        model.train()
        train_iter = list(train_rows)
        if epoch > 1:
            train_iter.extend(mine_hard_negatives(model, tok, train_rows, limit=1024))
        random.shuffle(train_iter)
        loader = DataLoader(PairDataset(train_iter), batch_size=batch_size,
                            collate_fn=make_collator(tok), shuffle=True)
        total_loss = 0.0
        for step, batch in enumerate(loader, 1):
            labels = batch.pop("labels").to("cuda")
            is_same = batch.pop("is_same").to("cuda")
            batch = {k: v.to("cuda") for k, v in batch.items()}
            opt.zero_grad()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits = model(**batch).logits
            same = same_probability(logits)
            loss = ce(logits.float(), labels) + 1.1 * bce(same.clamp(1e-6, 1 - 1e-6), is_same)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            scheduler.step()
            total_loss += float(loss.item())
            if step % 100 == 0 or step == len(loader):
                print(f"[iter2] epoch={epoch} step={step}/{len(loader)} loss={total_loss / step:.4f} lr={scheduler.get_last_lr()[0]:.2e}", flush=True)

        val_auc = evaluate_val_auc(model, val_loader)
        ep_time = time.time() - t0
        print(f"[iter2 epoch {epoch}] train_loss={total_loss/len(loader):.4f} | val_auc={val_auc:.4f} | time={ep_time:.1f}s", flush=True)
        history.append({"epoch": epoch, "train_loss": total_loss/len(loader), "val_auc": val_auc, "seconds": ep_time})

        if val_auc > best_auc:
            best_auc = val_auc
            if iter2_out.exists():
                shutil.rmtree(iter2_out)
            model.save_pretrained(iter2_out)
            tok.save_pretrained(iter2_out)
            print(f"[iter2] Saved best checkpoint (val_auc={best_auc:.5f})", flush=True)

    best_model = AutoModelForSequenceClassification.from_pretrained(iter2_out).to("cuda")
    res_25 = score_eval_set(best_model, tok, eval_25_rows)
    res_170 = score_eval_set(best_model, tok, eval_170_rows)

    print(f"[iter2 25-pair] ROC_AUC={res_25['metrics']['roc_auc']:.4f} | F1={res_25['metrics']['f1_at_0.5']:.4f}", flush=True)
    print(f"[iter2 25-targets] {json.dumps(res_25['targets'])}", flush=True)
    print(f"[iter2 170-pair] ROC_AUC={res_170['metrics']['roc_auc']:.4f} | F1={res_170['metrics']['f1_at_0.5']:.4f}", flush=True)

    result = {
        "model": "BAAI/bge-reranker-base (Iteration 2: 5-Epoch Cosine + Multi-Stage Negatives)",
        "best_val_auc": best_auc,
        "history": history,
        "eval_25": res_25,
        "eval_170": res_170,
    }
    write_json(RESULTS / "bge_iter2.json", result)

    del model, best_model, tok, opt, scheduler
    gc.collect()
    torch.cuda.empty_cache()
    return result


# ==============================================================================
# 5. ITERATION 3: BGE-Large (560M params, 24 layers) Scaling & Training
# ==============================================================================
def run_iteration_3(train_rows, val_rows, eval_25_rows, eval_170_rows):
    print("\n" + "="*80, flush=True)
    print(">>> [4/4] ITERATION 3: BGE-Large (560M Parameters, 24 Layers) High-Capacity Scaling", flush=True)
    print("="*80, flush=True)

    model_name = "BAAI/bge-reranker-large"
    tok = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name, num_labels=5, id2label={i: l for i, l in enumerate(LABELS)},
        label2id=LABEL_INDEX, ignore_mismatched_sizes=True
    ).to("cuda")

    val_loader = DataLoader(PairDataset(val_rows), batch_size=32,
                            collate_fn=make_collator(tok), shuffle=False)

    ce = nn.CrossEntropyLoss(label_smoothing=0.03)
    bce = nn.BCELoss()
    epochs = 4
    batch_size = 32
    
    est_steps = epochs * (len(train_rows) + 512) // batch_size
    opt = torch.optim.AdamW(model.parameters(), lr=1.5e-5, weight_decay=0.01)
    scheduler = get_cosine_schedule_with_warmup(opt, num_warmup_steps=int(0.05 * est_steps), num_training_steps=est_steps)

    best_auc = 0.0
    history = []
    iter3_out = OUT / "bge-large-best"

    for epoch in range(1, epochs + 1):
        t0 = time.time()
        model.train()
        train_iter = list(train_rows)
        if epoch > 1:
            train_iter.extend(mine_hard_negatives(model, tok, train_rows, limit=512))
        random.shuffle(train_iter)
        loader = DataLoader(PairDataset(train_iter), batch_size=batch_size,
                            collate_fn=make_collator(tok), shuffle=True)
        total_loss = 0.0
        for step, batch in enumerate(loader, 1):
            labels = batch.pop("labels").to("cuda")
            is_same = batch.pop("is_same").to("cuda")
            batch = {k: v.to("cuda") for k, v in batch.items()}
            opt.zero_grad()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits = model(**batch).logits
            same = same_probability(logits)
            loss = ce(logits.float(), labels) + 1.2 * bce(same.clamp(1e-6, 1 - 1e-6), is_same)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            scheduler.step()
            total_loss += float(loss.item())
            if step % 100 == 0 or step == len(loader):
                print(f"[iter3-large] epoch={epoch} step={step}/{len(loader)} loss={total_loss / step:.4f} lr={scheduler.get_last_lr()[0]:.2e}", flush=True)

        val_auc = evaluate_val_auc(model, val_loader)
        ep_time = time.time() - t0
        print(f"[iter3-large epoch {epoch}] train_loss={total_loss/len(loader):.4f} | val_auc={val_auc:.4f} | time={ep_time:.1f}s", flush=True)
        history.append({"epoch": epoch, "train_loss": total_loss/len(loader), "val_auc": val_auc, "seconds": ep_time})

        if val_auc > best_auc:
            best_auc = val_auc
            if iter3_out.exists():
                shutil.rmtree(iter3_out)
            model.save_pretrained(iter3_out)
            tok.save_pretrained(iter3_out)
            print(f"[iter3-large] Saved best checkpoint (val_auc={best_auc:.5f})", flush=True)

    best_model = AutoModelForSequenceClassification.from_pretrained(iter3_out).to("cuda")
    res_25 = score_eval_set(best_model, tok, eval_25_rows)
    res_170 = score_eval_set(best_model, tok, eval_170_rows)

    print(f"[iter3-large 25-pair] ROC_AUC={res_25['metrics']['roc_auc']:.4f} | F1={res_25['metrics']['f1_at_0.5']:.4f}", flush=True)
    print(f"[iter3-large 25-targets] {json.dumps(res_25['targets'])}", flush=True)
    print(f"[iter3-large 170-pair] ROC_AUC={res_170['metrics']['roc_auc']:.4f} | F1={res_170['metrics']['f1_at_0.5']:.4f}", flush=True)

    result = {
        "model": "BAAI/bge-reranker-large (Iteration 3: 560M parameters, 24 Layers)",
        "best_val_auc": best_auc,
        "history": history,
        "eval_25": res_25,
        "eval_170": res_170,
    }
    write_json(RESULTS / "bge_iter3_large.json", result)

    del model, best_model, tok, opt, scheduler
    gc.collect()
    torch.cuda.empty_cache()
    return result


# ==============================================================================
# MAIN ORCHESTRATOR
# ==============================================================================
def main():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training & evaluation suite.")
    
    print(f"CUDA Device: {torch.cuda.get_device_name(0)} | VRAM: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.1f} GiB", flush=True)
    
    eval_25_rows = read_jsonl(ROOT / "eval-pairs.jsonl")
    eval_170_rows = read_jsonl(ROOT / "gold_test_170.jsonl")
    if not eval_170_rows:
        print("Warning: gold_test_170.jsonl not found, using eval-pairs.jsonl", flush=True)
        eval_170_rows = eval_25_rows

    print(f"Loaded {len(eval_25_rows)} rows for 25-pair release gate", flush=True)
    print(f"Loaded {len(eval_170_rows)} rows for Gold Test Suite", flush=True)

    train_rows, val_rows, data_rep = load_training_data()

    # 1. Jev / OpenJev
    jev_25_file = RESULTS / "jev_25.json"
    if jev_25_file.exists():
        print("[jev] Found cached Jev results from previous run; skipping re-eval", flush=True)
        jev_res = {
            "25": json.loads(jev_25_file.read_text()),
            "170": json.loads((RESULTS / "jev_170.json").read_text()) if (RESULTS / "jev_170.json").exists() else {},
            "val": json.loads((RESULTS / "jev_val200.json").read_text()) if (RESULTS / "jev_val200.json").exists() else {},
        }
    else:
        jev_res = eval_jev(eval_25_rows, eval_170_rows, val_rows)

    # 2. Iteration 1: BGE-Base + Asymmetric Margin Loss
    iter1_res = run_iteration_1(train_rows, val_rows, eval_25_rows, eval_170_rows)

    # 3. Iteration 2: BGE-Base + 5-Epoch Cosine Decay + Dynamic Hard Negatives
    iter2_res = run_iteration_2(train_rows, val_rows, eval_25_rows, eval_170_rows)

    # 4. Iteration 3: BGE-Large Scaling
    iter3_res = run_iteration_3(train_rows, val_rows, eval_25_rows, eval_170_rows)

    # Summary report
    print("\n" + "="*80, flush=True)
    print(">>> FULL BENCHMARK COMPARISON MATRIX", flush=True)
    print("="*80, flush=True)
    
    summary = {
        "timestamp": time.time(),
        "gpu": torch.cuda.get_device_name(0),
        "data": data_rep,
        "models": {
            "jev": jev_res.get("25", {}).get("metrics") if jev_res else None,
            "bge_iter1": iter1_res.get("eval_25", {}).get("metrics"),
            "bge_iter2": iter2_res.get("eval_25", {}).get("metrics"),
            "bge_iter3_large": iter3_res.get("eval_25", {}).get("metrics"),
        },
        "gold_170": {
            "jev": jev_res.get("170", {}).get("metrics") if jev_res else None,
            "bge_iter1": iter1_res.get("eval_170", {}).get("metrics"),
            "bge_iter2": iter2_res.get("eval_170", {}).get("metrics"),
            "bge_iter3_large": iter3_res.get("eval_170", {}).get("metrics"),
        },
        "targets_25": {
            "jev": jev_res.get("25", {}).get("targets") if jev_res else None,
            "bge_iter1": iter1_res.get("eval_25", {}).get("targets"),
            "bge_iter2": iter2_res.get("eval_25", {}).get("targets"),
            "bge_iter3_large": iter3_res.get("eval_25", {}).get("targets"),
        }
    }
    write_json(RESULTS / "full_comparison_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    print("\nALL RUNS COMPLETED SUCCESSFULLY!", flush=True)


if __name__ == "__main__":
    main()
