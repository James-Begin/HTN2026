"""Claim-equivalence cross-encoder, served as a custom Truss.

Why a custom server rather than the TensorRT engine builder:

  * The engine builder only accepts a checkpoint from HF, S3, GCS, Azure or a URL. The
    only AWS credentials on the build machine are an assumed production role belonging
    to someone else's infrastructure, and there is no Hugging Face token, so there was
    nowhere appropriate to stage 1.1GB of weights.
  * `base_model: encoder_bert` is documented as "for BERT-based models". This checkpoint
    is XLMRobertaForSequenceClassification, so engine support is unverified.

The response shape deliberately MIMICS Baseten's `/rerank` route: a list of
`{index, score}` sorted by index-aligned position. That means `claimtrace/baseten.py`
works against this endpoint with no change beyond the URL.

`score` is same-claim probability, p(same_paraphrase) + p(same_verbatim), which is
exactly the quantity every threshold and gate in eval/ is defined on. The full 5-class
distribution is returned alongside it, because the register (is this commentary? a
denial? an acronym collision?) is the thing a single relevance score cannot express.
"""
import os

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

# Must match eval/dataset.py LABELS exactly and in order. Asserted at load, because a
# permuted mapping would invert same-claim while every number still looked plausible.
LABELS = ["unrelated", "incidental", "meta", "same_paraphrase", "same_verbatim"]
POSITIVE = ("same_paraphrase", "same_verbatim")

MAX_LENGTH = 256
MAX_BATCH = 64


class Model:
    def __init__(self, **kwargs):
        self._data_dir = kwargs["data_dir"]
        self._model = None
        self._tok = None
        self._device = None
        self._pos_idx = None

    def load(self):
        path = str(self._data_dir)
        self._tok = AutoTokenizer.from_pretrained(path, use_fast=True)
        model = AutoModelForSequenceClassification.from_pretrained(
            path, dtype=torch.float16)
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        if self._device == "cpu":
            model = model.float()
        self._model = model.eval().to(self._device)

        order = [self._model.config.id2label[i] for i in range(len(LABELS))]
        if order != LABELS:
            raise RuntimeError(f"id2label {order} != {LABELS}")
        self._pos_idx = [LABELS.index(l) for l in POSITIVE]

    def _score(self, pairs):
        out = []
        for off in range(0, len(pairs), MAX_BATCH):
            chunk = pairs[off:off + MAX_BATCH]
            enc = self._tok([a for a, _ in chunk], [b for _, b in chunk],
                            padding=True, truncation=True, max_length=MAX_LENGTH,
                            return_tensors="pt").to(self._device)
            with torch.inference_mode():
                logits = self._model(**enc).logits
            probs = torch.softmax(logits.float(), dim=-1)
            same = probs[:, self._pos_idx].sum(dim=-1)
            for i in range(len(chunk)):
                out.append((float(same[i]),
                            {l: float(probs[i, k]) for k, l in enumerate(LABELS)}))
        return out

    def predict(self, request):
        """Accepts either the /rerank shape or an explicit pair list.

            {"query": "...", "texts": ["...", ...]}
            {"pairs": [["reference", "candidate"], ...]}
        """
        pairs = request.get("pairs")
        if pairs:
            pairs = [(str(a), str(b)) for a, b in pairs]
        else:
            query = request.get("query")
            texts = request.get("texts") or []
            if query is None or not texts:
                return {"error": "send {query, texts} or {pairs}"}
            pairs = [(str(query), str(t)) for t in texts]
        if not pairs:
            return {"data": []}

        scored = self._score(pairs)
        want_dist = bool(request.get("return_distribution", True))
        data = []
        for i, (same, dist) in enumerate(scored):
            row = {"index": i, "score": same}
            if want_dist:
                row["label"] = max(dist, key=dist.get)
                row["distribution"] = dist
            data.append(row)
        return {"data": data}
