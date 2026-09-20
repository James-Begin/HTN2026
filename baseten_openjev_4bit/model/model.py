import math
import os
from pathlib import Path
import torch
import torch.nn as nn
from peft import PeftModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer, BitsAndBytesConfig

LABELS = ["unrelated", "incidental", "meta", "same_paraphrase", "same_verbatim"]
LABEL_INDEX = {label: i for i, label in enumerate(LABELS)}
POSITIVE_LABELS = {"same_paraphrase", "same_verbatim"}
MODEL_DIR = Path(__file__).resolve().parent
ADAPTER_DIR = MODEL_DIR / "adapter"


class Model:
    def __init__(self, **kwargs):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.tok = None
        self.template = "Premise: {premise}\nHypothesis: {hypothesis}"

    def load(self):
        if self.device != "cuda":
            raise RuntimeError("CUDA deployment required for 4-bit OpenJev inference")

        base_path = "/models/openjev/qwen3.5-4b-nli-v2"
        if not os.path.exists(base_path):
            base_path = "AlexWortega/openjev"

        self.tok = AutoTokenizer.from_pretrained(
            base_path,
            subfolder="qwen3.5-4b-nli-v2" if base_path == "AlexWortega/openjev" else None
        )
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        self.tok.padding_side = "right"

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

        base_model = AutoModelForSequenceClassification.from_pretrained(
            base_path,
            subfolder="qwen3.5-4b-nli-v2" if base_path == "AlexWortega/openjev" else None,
            quantization_config=bnb_config,
            device_map="auto",
            attn_implementation="sdpa",
        )

        # Attach 5-class head
        in_features = base_model.score.in_features
        base_model.score = nn.Linear(in_features, 5, bias=False).to("cuda", dtype=torch.bfloat16)
        base_model.config.num_labels = 5
        base_model.config.id2label = {i: l for i, l in enumerate(LABELS)}
        base_model.config.label2id = LABEL_INDEX

        # Load fine-tuned LoRA weights
        if ADAPTER_DIR.exists():
            self.model = PeftModel.from_pretrained(base_model, str(ADAPTER_DIR)).eval()
        else:
            self.model = base_model.eval()

        print("Fine-Tuned 4-Bit OpenJev loaded successfully into VRAM.")

    @torch.inference_mode()
    def predict(self, model_input):
        """
        Accepts:
          {"pairs": [{"reference": "...", "candidate": "..."}, ...]}
        Returns:
          {"results": [{"same_claim_prob": float, "predicted_label": str, "distribution": dict}, ...]}
        """
        pairs = model_input.get("pairs", [])
        if not pairs:
            raise ValueError("Input 'pairs' must be a non-empty list of {reference, candidate} objects")

        texts = [
            self.template.format(
                premise=str(p.get("reference", "")).strip(),
                hypothesis=str(p.get("candidate", "")).strip()
            )
            for p in pairs
        ]

        # Batch encode
        batch = self.tok(
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt"
        ).to(self.device)

        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            logits = self.model(**batch).logits

        probs = torch.softmax(logits.float(), dim=-1).cpu().numpy()

        results = []
        for i, dist in enumerate(probs):
            p_same = float(dist[LABEL_INDEX["same_paraphrase"]] + dist[LABEL_INDEX["same_verbatim"]])
            pred_idx = int(dist.argmax())
            results.append({
                "same_claim_prob": round(p_same, 5),
                "predicted_label": LABELS[pred_idx],
                "distribution": {label: round(float(dist[j]), 5) for j, label in enumerate(LABELS)},
            })

        return {"results": results, "count": len(results)}
