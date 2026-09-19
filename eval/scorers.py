"""Scorers. Each one turns (reference, [candidates]) into same-claim scores, so the
same eval runs against a recorded baseline, the deployed endpoint, or a local
checkpoint with no change to the metrics.

A scorer returns [(score, probs_or_None)] aligned to the input candidates:
  score  same-claim probability in [0,1]
  probs  the full 5-class distribution, when the model has one. A single-logit
         reranker has no register opinion, so it returns None and the per-class
         confusion is skipped rather than faked.
"""
import os
import time

from .dataset import LABELS

# The local scorer touches a GPU. The cards on this box are shared, so an
# accidental `--scorer local` must not claim one. Opt in explicitly.
GPU_OPT_IN = "CLAIMTRACE_ALLOW_GPU"


class ReplayScorer:
    """Replays the `baseline` field. No network, no GPU, no cost.

    Exists so the harness itself can be tested and so every future run has a fixed
    comparison point. Pairs with no recorded baseline are reported as skipped
    rather than defaulted to zero, which would flatter any new model.
    """

    name = "replay"

    def __init__(self, pairs):
        self._by_id = {p.id: p.baseline for p in pairs}

    def score(self, reference, candidates):
        return [(self._by_id.get(c.id), None) for c in candidates]

    def report(self):
        have = sum(1 for v in self._by_id.values() if v is not None)
        return f"replay: {have}/{len(self._by_id)} pairs had a recorded baseline"


class BasetenScorer:
    """The currently deployed cross-encoder. One request per reference.

    This is the number to beat. It costs a few cents and needs the deployment
    awake, so it is not the default.
    """

    name = "baseten"

    def __init__(self, api_key=None, url=None):
        from claimtrace import config as C
        from claimtrace.baseten import CrossEncoder
        key = api_key or os.environ.get("BASETEN_API_KEY")
        if not key:
            raise RuntimeError("BASETEN_API_KEY is not set")
        self._xe = CrossEncoder(key, url or C.XENC_URL)

    def score(self, reference, candidates):
        scores = self._xe.score(reference, [c.candidate for c in candidates])
        return [(float(s), None) for s in scores]

    def report(self):
        return self._xe.report()


class DeployedScorer:
    """The fine-tune as deployed on Baseten, via a custom Truss `/predict` route.

    Separate from BasetenScorer because the routes differ in kind. BEI's `/rerank`
    returns one relevance logit; this returns a 5-class distribution plus the
    same-claim sum, so it can also report the register. The request shape is kept
    identical to `/rerank` so `claimtrace/baseten.py` needs only a URL change.
    """

    name = "deployed"

    def __init__(self, url=None, api_key=None, batch=64, timeout=120):
        self._url = (url or os.environ.get("CLAIMTRACE_XENC_URL") or "").rstrip("/")
        if not self._url:
            raise RuntimeError("set CLAIMTRACE_XENC_URL to the /predict endpoint")
        self._key = api_key or os.environ.get("BASETEN_API_KEY")
        if not self._key:
            raise RuntimeError("BASETEN_API_KEY is not set")
        self.batch = batch
        self.timeout = timeout
        self.calls = 0
        self.pairs = 0

    def score(self, reference, candidates):
        import json as _json
        import urllib.request
        texts = [c.candidate for c in candidates]
        out = [None] * len(texts)
        for off in range(0, len(texts), self.batch):
            chunk = texts[off:off + self.batch]
            body = _json.dumps({"query": reference, "texts": chunk,
                                "return_distribution": True}).encode()
            req = urllib.request.Request(
                self._url, data=body,
                headers={"Authorization": f"Api-Key {self._key}",
                         "Content-Type": "application/json"})
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        d = _json.loads(resp.read())
                    break
                except Exception:
                    if attempt == 3:
                        raise
                    time.sleep(3 * (attempt + 1))
            for row in d["data"]:
                out[off + row["index"]] = (float(row["score"]),
                                           row.get("distribution"))
            self.calls += 1
            self.pairs += len(chunk)
        return out

    def report(self):
        return f"deployed: {self.calls} requests, {self.pairs} pairs"


class LocalScorer:
    """A local HuggingFace checkpoint.

    Handles both head shapes deliberately:
      1 logit   sigmoid, a plain relevance reranker. No register opinion.
      5 logits  softmax over LABELS, same_claim = p(same_verbatim) + p(same_paraphrase).

    The label order is read from the checkpoint's own id2label and cross-checked
    against ours. A silent permutation there would invert the metric while every
    number still looked plausible, and Baseten's engine build also fails outright
    without id2label, so getting it wrong breaks serving too.
    """

    name = "local"

    def __init__(self, path, device=None, batch_size=16, max_length=256):
        if os.environ.get(GPU_OPT_IN) != "1":
            raise RuntimeError(
                f"LocalScorer needs {GPU_OPT_IN}=1. The GPUs on this machine are "
                "shared; set it only when a card is genuinely free."
            )
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self.batch_size = batch_size
        self.max_length = max_length
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path)
        self.model.eval().to(self.device)

        cfg_labels = getattr(self.model.config, "id2label", None) or {}
        self.n_labels = int(self.model.config.num_labels)
        self.order = None
        if self.n_labels > 1:
            got = [cfg_labels[i] for i in sorted(cfg_labels, key=int)] if cfg_labels else []
            if sorted(got) != sorted(LABELS):
                raise RuntimeError(
                    f"checkpoint id2label {got} does not match the eval label set "
                    f"{LABELS}. Fix the checkpoint: Baseten's engine build also "
                    "fails without a correct id2label."
                )
            self.order = got
        self.name = f"local:{os.path.basename(str(path).rstrip('/'))}"

    def score(self, reference, candidates):
        torch = self._torch
        texts = [c.candidate for c in candidates]
        out = []
        for off in range(0, len(texts), self.batch_size):
            chunk = texts[off:off + self.batch_size]
            enc = self.tok([reference] * len(chunk), chunk, padding=True,
                           truncation=True, max_length=self.max_length,
                           return_tensors="pt").to(self.device)
            with torch.no_grad():
                logits = self.model(**enc).logits
            if self.n_labels == 1:
                for v in torch.sigmoid(logits.squeeze(-1)).tolist():
                    out.append((float(v), None))
            else:
                probs = torch.softmax(logits.float(), dim=-1).tolist()
                for row in probs:
                    dist = {lab: float(p) for lab, p in zip(self.order, row)}
                    same = dist.get("same_verbatim", 0.0) + dist.get("same_paraphrase", 0.0)
                    out.append((same, dist))
        return out

    def report(self):
        return f"{self.name}: {self.n_labels}-way head on {self.device}"


def build(kind, pairs, **kw):
    if kind == "replay":
        return ReplayScorer(pairs)
    if kind == "baseten":
        return BasetenScorer(**kw)
    if kind == "local":
        return LocalScorer(**kw)
    if kind == "deployed":
        return DeployedScorer(**kw)
    raise ValueError(f"unknown scorer {kind!r}; expected replay, baseten, local or deployed")
