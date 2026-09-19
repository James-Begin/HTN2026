"""Baseten clients: hosted models for language work, dedicated cross-encoder for volume.

The split is not stylistic. Measured facts:
  * Hosted Model APIs are capped at 120 requests/MINUTE (X-Ratelimit-Limit-Requests).
    Good for a handful of calls per query. Useless for bulk.
  * A dedicated L4 cross-encoder does 2851 pairs/SECOND with no shared cap.
    That is a ~1400x gap, and it is why the dedicated deployment is load-bearing.
"""
import json
import time
import urllib.request

from . import config as C


class HostedLLM:
    """Baseten Model APIs, OpenAI-compatible."""

    def __init__(self, api_key: str, model: str = C.MODEL_EXTRACT):
        if not api_key:
            raise ValueError("BASETEN_API_KEY is empty")
        self._key = api_key
        self.model = model
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0

    def chat(self, messages, max_tokens: int = 512, model: str = None,
             effort: str = C.REASONING_EFFORT, json_mode: bool = False,
             stream: bool = False):
        payload = {
            "model": model or self.model,
            "messages": messages,
            # Too small a budget silently returns content=None with
            # finish_reason="length", because reasoning tokens land first.
            "max_tokens": max(max_tokens, C.MIN_MAX_TOKENS),
        }
        if effort:
            # This works. chat_template_args={"enable_thinking": False} does not.
            payload["reasoning_effort"] = effort
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if stream:
            payload["stream"] = True

        req = urllib.request.Request(
            f"{C.BASETEN_INFERENCE}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
        )
        if stream:
            return self._stream(req)

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req) as resp:
                    d = json.loads(resp.read())
                break
            except urllib.error.HTTPError as e:
                text = e.read().decode()[:200]
                if e.code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise RuntimeError(f"Baseten HTTP {e.code}: {text}") from None
        else:
            raise RuntimeError("Baseten: rate limited out")

        self.calls += 1
        u = d.get("usage", {})
        self.prompt_tokens += u.get("prompt_tokens", 0)
        self.completion_tokens += u.get("completion_tokens", 0)
        self.reasoning_tokens += u.get("completion_tokens_details", {}).get("reasoning_tokens", 0)
        msg = d["choices"][0]["message"]
        content = msg.get("content")
        if not content:
            raise RuntimeError(
                f"empty content, finish_reason={d['choices'][0].get('finish_reason')} "
                f"(raise max_tokens; reasoning consumed the budget)"
            )
        return content

    def _stream(self, req):
        """Yields content deltas. Chunks with empty `choices` must be skipped."""
        self.calls += 1
        with urllib.request.urlopen(req) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                try:
                    ch = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                choices = ch.get("choices") or []
                if not choices:
                    continue
                piece = (choices[0].get("delta") or {}).get("content")
                if piece:
                    yield piece

    def json_call(self, system: str, user: str, max_tokens: int = 900) -> dict:  # noqa: D401
        """Structured extraction with a repair retry, since JSON mode only
        guarantees well-formedness, not shape."""
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        raw = self.chat(msgs, max_tokens=max_tokens, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start:end + 1])
            raise

    def report(self) -> str:
        return (f"llm: {self.calls} calls, {self.prompt_tokens}p/{self.completion_tokens}c tokens "
                f"({self.reasoning_tokens} reasoning)")


class CrossEncoder:
    """The fine-tuned 5-class cross-encoder.

    Request shape is identical to Baseten's `/rerank` route, `{query, texts}` in and
    `[{index, score}]` out, so this client did not change when the model did. What is
    new is `distribution`: `/rerank` returns one relevance logit, while a sequence
    classifier returns all five classes, and the register is the thing a single
    relevance score cannot express.

    `score` is same-claim probability, p(same_paraphrase) + p(same_verbatim).
    """

    def __init__(self, api_key: str, url: str = C.XENC_URL):
        self._key = api_key
        # A full route is configured now rather than assembled, because the custom
        # server answers on /predict and the old BEI deployment on /rerank.
        self._url = url if url.rstrip("/").split("/")[-1] in ("predict", "rerank", "sync") \
            else url.rstrip("/") + "/rerank"
        self.calls = 0
        self.pairs = 0
        self.last_distributions = []

    def score(self, query: str, texts, batch: int = C.XENC_BATCH, want_dist: bool = False):
        """Returns scores aligned to the input order of `texts`."""
        if not texts:
            return []
        out = [0.0] * len(texts)
        dists = [None] * len(texts)
        for off in range(0, len(texts), batch):
            chunk = texts[off:off + batch]
            body = json.dumps({"query": query, "texts": chunk,
                               "return_distribution": bool(want_dist),
                               "return_text": False}).encode()
            req = urllib.request.Request(
                self._url, data=body,
                headers={"Authorization": f"Api-Key {self._key}",
                         "Content-Type": "application/json"},
            )
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(req) as resp:
                        d = json.loads(resp.read())
                    break
                except urllib.error.HTTPError as e:
                    text = e.read().decode()[:160]
                    # A scaled-to-zero replica needs waking; retry patiently.
                    if e.code in (429, 503, 529):
                        time.sleep(4 * (attempt + 1))
                        continue
                    raise RuntimeError(f"cross-encoder HTTP {e.code}: {text}") from None
            else:
                raise RuntimeError("cross-encoder unreachable after retries")

            rows = d if isinstance(d, list) else d.get("data", [])
            for item in rows:
                out[off + item["index"]] = item["score"]
                if item.get("distribution"):
                    dists[off + item["index"]] = item["distribution"]
            self.calls += 1
            self.pairs += len(chunk)
        self.last_distributions = dists
        return out

    def report(self) -> str:
        return f"xenc: {self.calls} calls, {self.pairs} pairs"
