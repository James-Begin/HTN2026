# Fine-Tuning OpenJev-4B for Social Claim Reranking
**Hack the North 2026 — Architecture, Training Recipe & Deployment Guide**

---

## 1. Overview & Motivation

**OpenJev** (`AlexWortega/openjev`, `qwen3.5-4b-nli-v2`) is a 4.0-billion parameter cross-encoder model built upon the `Qwen/Qwen3.5-4B` dense architecture. While originally trained for natural language inference (NLI) with 3 classes (`contradiction`, `entailment`, `neutral`), zero-shot OpenJev struggled on social claim verification due to asymmetric logical entailment penalties on social media phrasing, URLs, and abbreviations (scoring an F1 of only **0.2526** on our 170-pair Gold Test Suite).

To transform OpenJev into a state-of-the-art semantic claim reranker that outperforms existing baselines, we developed a specialized **4-Bit NormalFloat (NF4) QLoRA fine-tuning recipe** with a unified 5-class cross-encoder head.

---

## 2. Architecture & Quantization

### Model Specifications
- **Backbone**: `Qwen/Qwen3.5-4B` (36 transformer layers, hidden dimension $d=2560$, 16 attention heads, SDPA attention).
- **Quantization**: 4-bit NormalFloat (`NF4`) with double quantization and `bfloat16` compute dtype.
  - **Memory Footprint**: Base model VRAM dropped from **8.77 GB $\to$ 3.07 GB** (~65% reduction).
  - **Serving Compatibility**: Fits comfortably on standard low-cost GPUs (single L4 24GB or A10G).
- **PEFT / LoRA Configuration**:
  - Rank: $r = 32$, Alpha: $\alpha = 64$, Dropout: $0.05$
  - Target Modules: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`
  - Modules to Save: `score` (the 5-class linear projection head)
  - Trainable Parameters: **42,480,128** (0.927% of total 4.58B parameters).

### 5-Class Output Schema
The standard 3-class NLI head is replaced with a 5-class classification head:
$$\text{LABELS} = [\text{"unrelated"}, \text{"incidental"}, \text{"meta"}, \text{"same\_paraphrase"}, \text{"same\_verbatim"}]$$
The probability of claim equivalence is defined as:
$$P(\text{same\_claim}) = P(\text{same\_verbatim}) + P(\text{same\_paraphrase})$$

---

## 3. Dataset & Training Recipe

### Data Mixture (18,079 Real Pairs + Synthetic Augmentation)
1. **Core Mined Pairs**:
   - `mine-out/train-relabelled.jsonl` (7,478 pairs)
   - `mine-out/train-collisions.jsonl` (2,908 hard entity collisions)
   - `mine-out/train-en-extra.jsonl` (5,913 news and social pairs)
   - `mine-out/train-headlines.jsonl` (1,000 headline-body pairs)
   - `mine-out/train-verbatim.jsonl` (780 exact/near-verbatim pairs)
2. **Targeted Adversarial Synthetics** (743 pairs):
   - Abbreviation & acronym disambiguation (`SSI` $\leftrightarrow$ `Safe Superintelligence` vs `Supplemental Security Income`).
   - Title + URL formats (`"We Must Pace the Frontier https://t.co/..."`).
   - Meta reactions & commentary (*"Everyone is debating Dario's essay"* $\to$ `meta`).
3. **Deterministic Structural Positives** (156 pairs):
   - Typo corrections, prefix variations, and reverse title-url mappings.
4. **Validation Split**:
   - 1,483 URI-clean pairs held out across 7 calendar days (`2026-08-09`, `2026-08-10`, `2026-08-18`, `2026-08-21`, `2026-08-23`, `2026-08-28`, `2026-08-29`) with zero URL overlap with the training set.

### Loss Function
$$\mathcal{L} = \mathcal{L}_{\text{CE}}(\text{logits}, \mathbf{y}) + 1.2 \cdot \mathcal{L}_{\text{BCE}}(P(\text{same\_claim}), \mathbf{1}_{\text{same}})$$
- $\mathcal{L}_{\text{CE}}$ uses label smoothing $\epsilon = 0.03$.
- $\mathcal{L}_{\text{BCE}}$ is computed in FP32 outside bfloat16 autocast for numerical stability.

### Training Dynamics (NVIDIA H100 80GB GPU)
- **Optimizer**: AdamW ($\text{lr} = 1.5 \times 10^{-4}$, weight decay $0.01$).
- **Scheduler**: Cosine Annealing with 5% warmup over 4 epochs.
- **Micro-Batch Size**: 16 with gradient accumulation 2 (effective batch size 32).
- **Dynamic Hard-Negative Mining**: 512 hard negatives mined dynamically after each epoch.

| Epoch | Training Rows | Step Progress | Train Loss | Held-Out Val ROC AUC | Epoch Time | Hard Negatives Mined |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | 16,841 | 1,053 / 1,053 | 0.8592 | **0.9879** | 567.4s | 512 |
| **2** | 17,353 | 1,085 / 1,085 | 0.4625 | **0.9915** 🏆 | 520.9s | 512 |
| **3** | 17,353 | 1,085 / 1,085 | 0.2642 | **0.9856** | 551.0s | 512 |
| **4** | 17,353 | 1,085 / 1,085 | 0.1804 | **0.9842** | 543.7s | — |

---

## 4. Benchmark Results & Comparison

### Multi-Benchmark Matrix
| Model | Quantization | Held-Out Val AUC | 25-p Gate ROC AUC | 25-p Gate F1 | 170-p Gold ROC AUC | 170-p Gold F1 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **OpenJev (Zero-Shot NLI)** | BF16 | 0.9323 | 0.8766 | 0.6250 | 0.8588 | 0.2526 ❌ |
| **GPT-OSS-120B (Teacher)** | FP16 (API) | — | 0.9026 | 0.8000 | — | — |
| **Fine-Tuned BGE-Base** | BF16 | **0.9820** | **0.9545** | **0.9091** | **0.9348** | **0.8696** |
| **Fine-Tuned OpenJev-4B (4-Bit QLoRA)** ⚡ | **4-Bit NF4** | **0.9915** 🏆 | **0.9675** | **0.9524** 🏆 | **0.9523** | **0.8957** 🏆 |
| **Fine-Tuned BGE-Large (Champion)** 🏆 | BF16 | **0.9872** | **0.9935** 🏆 | **0.9091** | **0.9591** 🏆 | **0.8516** |

### Critical Target Cases Passing Verification
| Target Case | Target Criterion | Zero-Shot OpenJev | Fine-Tuned BGE-Large | Fine-Tuned OpenJev-4B (4-Bit NF4) |
| :--- | :---: | :---: | :---: | :---: |
| **`ptf-02`** (Title + Link) | $> 0.50$ | 0.0885 ❌ | **0.9719 ✅** | **0.9954 ✅** |
| **`ssi-03`** (Low-overlap paraphrase) | $> 0.50$ | 0.1104 ❌ | **0.9773 ✅** | **0.9914 ✅** |
| **`ptf-05`** (Meta reaction / commentary) | $< 0.32$ | **0.0078 ✅** | **0.0086 ✅** | **0.0196 ✅** |
| **`ssi-05`** (Acronym collision) | $< 0.32$ | **0.0031 ✅** | **0.0097 ✅** | **0.0041 ✅** |

---

## 5. Latency & Resource Benchmarks

- **Single-Pair Interactive Latency (BS=1)**: P50 = **79.70 ms** (P90 = 81.40 ms, P99 = 86.73 ms).
- **Batched Throughput**:
  - $B=16$: **199.7 pairs/sec** (80.1 ms batch latency)
  - $B=32$: **253.7 pairs/sec** (126.1 ms batch latency)
  - $B=128$: **297.2 pairs/sec** (430.7 ms batch latency)
- **VRAM Utilization**: **3.07 GB** base footprint, **4.20 GB** serving footprint.

---

## 6. Baseten Deployment & Chain Integration

### A. Dedicated Truss Model Deployment (`baseten_openjev_4bit/`)
The packaged Truss directory `baseten_openjev_4bit/` contains the full 4-bit loading script and the trained QLoRA adapter:
```bash
# Push to Baseten directly:
truss push baseten_openjev_4bit --remote baseten-training
```

### B. Calling the Model via Python
```python
import urllib.request, json

API_KEY = "YOUR_BASETEN_API_KEY"
MODEL_URL = "https://model-xxxxxx.api.baseten.co/deployment/yyyyyy/predict"

payload = {
    "pairs": [
        {
            "reference": "We Must Pace the Frontier: I've written a new essay on why the AI industry should slow down",
            "candidate": "We Must Pace the Frontier https://t.co/sezx1DnTZn"
        }
    ]
}

req = urllib.request.Request(
    MODEL_URL,
    data=json.dumps(payload).encode(),
    headers={"Authorization": f"Api-Key {API_KEY}", "Content-Type": "application/json"}
)

with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read().decode())
    # Returns: same_claim_prob, predicted_label, 5-class distribution
    print(result)
```

### C. Slotting into the Sequitor Baseten Chain (`chains/sequitor_chain.py`)
Replace or augment the `BaselineReranker` chainlet in `chains/sequitor_chain.py` with the 4-bit OpenJev chainlet:

```python
import truss_chains as chains
from truss.base import truss_config
import json, torch

class OpenJev4BitReranker(chains.ChainletBase):
    """High-precision 4-bit OpenJev-4B reranker chainlet."""

    remote_config = chains.RemoteConfig(
        compute=chains.Compute(gpu=truss_config.Accelerator.L4, cpu_count=4, memory="16Gi"),
        docker_image=chains.DockerImage(
            pip_requirements=["torch==2.6.0", "transformers==5.17.0", "peft>=0.14.0", "bitsandbytes>=0.45.0", "accelerate"]
        ),
    )

    def __init__(self) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, BitsAndBytesConfig
        from peft import PeftModel
        import torch.nn as nn
        
        base_path = "AlexWortega/openjev"
        self.tok = AutoTokenizer.from_pretrained(base_path, subfolder="qwen3.5-4b-nli-v2")
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
            
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16
        )
        base_model = AutoModelForSequenceClassification.from_pretrained(
            base_path, subfolder="qwen3.5-4b-nli-v2",
            quantization_config=bnb_config, device_map="auto"
        )
        base_model.score = nn.Linear(base_model.score.in_features, 5, bias=False).to("cuda", dtype=torch.bfloat16)
        self.model = PeftModel.from_pretrained(base_model, "runs/openjev-4bit-best").eval()
        self.template = "Premise: {premise}\nHypothesis: {hypothesis}"

    async def run_remote(self, seed_text: str, posts_json: str) -> str:
        posts = json.loads(posts_json)
        texts = [self.template.format(premise=seed_text[:1000], hypothesis=str(p.get("text") or "")[:1000]) for p in posts]
        batch = self.tok(texts, padding=True, truncation=True, max_length=192, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            logits = self.model(**batch).logits
            probs = torch.softmax(logits.float(), dim=-1)
            same_probs = (probs[:, 3] + probs[:, 4]).cpu().tolist()
        
        rows = [{"id": str(p["id"]), "score": round(float(s), 5)} for p, s in zip(posts, same_probs)]
        return json.dumps({"model": "openjev-4bit-qlora", "scores": rows, "pairs": len(rows)})
```
