"""The claim-equivalence eval set: schema, loader, and validation.

Five classes, one softmax head. The label set is not arbitrary; each class exists
because a real run produced a case that the previous scheme could not express.

  same_verbatim    the same claim, same words. Retweets, copy-paste, quote-with-no-comment.
  same_paraphrase  the same claim, different words. Includes cross-lingual restatement.
  meta             ABOUT the claim rather than an instance of it. Endorsements,
                   disputes, jokes built on it, "source?" replies. The dangerous
                   class: it looks like corroboration and is not.
  incidental       shares surface tokens, means something unrelated. The Korean
                   honorific "-ssi", the Oklahoma fight song "Boomer Sooner",
                   Supplemental Security Income.
  unrelated        no meaningful overlap at all.

`same_claim` probability is p(same_verbatim) + p(same_paraphrase). Register falls
out of the argmax. One head serves cleanly on Baseten's embeddings engine; a
multi-head model would not.

The distinction that earns the scheme its keep is meta vs same_paraphrase. A
verify run counts corroborating posts. If "No public reports confirm any security
incident at SSI" counts as corroboration, the tool reports the opposite of the
truth.
"""
import json
import os
from dataclasses import dataclass, field
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PAIRS = os.path.join(HERE, "pairs.jsonl")

# Ordered. Index is the class index for a 5-way head, so do not reorder without
# retraining: a checkpoint's id2label must match this exactly.
LABELS = ["unrelated", "incidental", "meta", "same_paraphrase", "same_verbatim"]
LABEL_INDEX = {l: i for i, l in enumerate(LABELS)}

# The two classes that sum to same_claim.
POSITIVE_LABELS = {"same_verbatim", "same_paraphrase"}

# How much we trust our own gold label. `debatable` pairs are reported but never
# gate a release, because failing them may mean our label is wrong.
CONFIDENCES = ["certain", "likely", "debatable"]
GATING_CONFIDENCES = {"certain", "likely"}

# The accept threshold the pipeline uses today (pipeline.judge default).
THRESHOLD = 0.5


@dataclass
class Pair:
    id: str
    reference: str
    candidate: str
    label: str
    confidence: str = "certain"
    baseline: Optional[float] = None   # score from the off-the-shelf reranker
    note: str = ""
    group: str = field(default="")     # derived: the id prefix, e.g. "ssi"

    @property
    def gold_positive(self) -> bool:
        return self.label in POSITIVE_LABELS

    @property
    def gold_index(self) -> int:
        return LABEL_INDEX[self.label]

    @property
    def gates(self) -> bool:
        return self.confidence in GATING_CONFIDENCES


def load(path: str = DEFAULT_PAIRS) -> list:
    """Read and validate. Raises on a malformed set rather than scoring garbage."""
    pairs, seen = [], set()
    with open(path) as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as ex:
                raise ValueError(f"{path}:{lineno} is not valid JSON: {ex}") from None
            for req in ("id", "reference", "candidate", "label"):
                if not row.get(req):
                    raise ValueError(f"{path}:{lineno} missing required field {req!r}")
            if row["label"] not in LABEL_INDEX:
                raise ValueError(f"{path}:{lineno} unknown label {row['label']!r}; "
                                 f"expected one of {LABELS}")
            conf = row.get("confidence", "certain")
            if conf not in CONFIDENCES:
                raise ValueError(f"{path}:{lineno} unknown confidence {conf!r}")
            if row["id"] in seen:
                raise ValueError(f"{path}:{lineno} duplicate id {row['id']!r}")
            seen.add(row["id"])
            base = row.get("baseline")
            if base is not None and not 0.0 <= float(base) <= 1.0:
                raise ValueError(f"{path}:{lineno} baseline {base} outside [0,1]")
            pairs.append(Pair(
                id=row["id"], reference=row["reference"], candidate=row["candidate"],
                label=row["label"], confidence=conf,
                baseline=None if base is None else float(base),
                note=row.get("note", ""),
                group=row["id"].rsplit("-", 1)[0],
            ))
    if not pairs:
        raise ValueError(f"{path} contained no pairs")
    return pairs


def by_reference(pairs: list) -> dict:
    """Group candidates under a shared reference.

    Not cosmetic. A cross-encoder is scored as (query, [texts]) in one call, and
    the /rerank route on Baseten takes exactly that shape, so grouping is what
    makes a run one request per reference instead of one per pair.
    """
    groups = {}
    for p in pairs:
        groups.setdefault(p.reference, []).append(p)
    return groups


def summary(pairs: list) -> str:
    from collections import Counter
    lab = Counter(p.label for p in pairs)
    conf = Counter(p.confidence for p in pairs)
    have = sum(1 for p in pairs if p.baseline is not None)
    lines = [f"{len(pairs)} pairs, {len(by_reference(pairs))} distinct references, "
             f"{have} with a recorded baseline"]
    for l in LABELS:
        lines.append(f"  {l:<16s} {lab.get(l, 0):>3d}")
    lines.append("  " + "  ".join(f"{c}={conf.get(c, 0)}" for c in CONFIDENCES))
    return "\n".join(lines)
