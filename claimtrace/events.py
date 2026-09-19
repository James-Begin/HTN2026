"""The event contract.

Every stage emits events instead of returning a blob. The terminal renderer and
(later) a browser consume the same stream, so there is one source of behaviour
rather than two implementations that drift.

Emitting is also what makes the slow path watchable: `probe` fires ~30 times
during a bisect and drives the window-narrowing animation, which turns a 66
second wait into the most interesting thing on screen.
"""
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------- event names
CLAIM = "claim"          # the input, resolved
RESOLVED = "resolved"    # tweet id -> state, handle, time
STAGE = "stage"          # a stage started
EXTRACT = "extract"      # anchor, premises, plausibility flags
SHAPE = "shape"          # the 30-day curve + derived stats
ROUTE = "route"          # VERIFY | LINEAGE | ABSTAIN
PROBE = "probe"          # one bisect step, ~30 per lineage run
EARLIEST = "earliest"    # the earliest matching post
SIGNAL = "signal"        # one corroboration measurement
PREMISE = "premise"      # one premise measured separately
CASCADE = "cascade"      # top posts by engagement
SCORE = "score"          # one cross-encoder judgement
HEADLINE = "headline"    # the single decisive number for this run
TOKEN = "token"          # a narrative delta, streamed
NOTE = "note"            # a non-fatal aside (skipped signal, fallback taken)
DONE = "done"            # spend + wall time
ERROR = "error"


@dataclass
class Event:
    kind: str
    data: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        return {"kind": self.kind, **self.data}


class Emitter:
    """Fan-out to any number of sinks. A sink is `fn(Event) -> None`."""

    def __init__(self, *sinks: Callable[[Event], None]):
        self._sinks: List[Callable[[Event], None]] = list(sinks)
        self.log: List[Event] = []

    def add(self, sink):
        self._sinks.append(sink)
        return self

    def emit(self, kind: str, **data):
        ev = Event(kind, data)
        self.log.append(ev)
        for s in self._sinks:
            s(ev)
        return ev

    # Convenience wrappers, so callers never hand-build a dict and typo a key.
    def claim(self, text, source=None):
        return self.emit(CLAIM, text=text, source=source)

    def resolved(self, tweet_id, state, handle=None, author_id=None,
                 created_at=None, media=0, tombstone=None):
        return self.emit(RESOLVED, tweet_id=tweet_id, state=state, handle=handle,
                         author_id=author_id, created_at=created_at,
                         media=media, tombstone=tombstone)

    def stage(self, n, name, note=None):
        return self.emit(STAGE, n=n, name=name, note=note)

    def extract(self, plan):
        return self.emit(EXTRACT, **plan)

    def shape(self, sh):
        return self.emit(SHAPE, **sh)

    def route(self, mode, why=None):
        return self.emit(ROUTE, mode=mode, why=why)

    def probe(self, n, phase, lo, hi, hit, span_seconds):
        return self.emit(PROBE, n=n, phase=phase, lo=lo, hi=hi, hit=hit,
                         span_seconds=span_seconds)

    def earliest(self, post, probes=None, state=None):
        return self.emit(EARLIEST, post=post, probes=probes, state=state)

    def signal(self, label, value, share=None, note=None):
        return self.emit(SIGNAL, label=label, value=value, share=share, note=note)

    def premise(self, claim, query, volume):
        return self.emit(PREMISE, claim=claim, query=query, volume=volume)

    def cascade(self, posts):
        return self.emit(CASCADE, posts=posts)

    def score(self, text, same_claim, accepted, created_at=None, likes=None,
              verdict=None, register=None):
        """`verdict` is accept|uncertain|reject and `register` is the 5-class argmax.
        Both are new with the fine-tune: a single relevance logit had neither."""
        return self.emit(SCORE, text=text, same_claim=same_claim, accepted=accepted,
                         created_at=created_at, likes=likes,
                         verdict=verdict, register=register)

    def headline(self, value, label, detail=None):
        """The one number a judge should remember from this run."""
        return self.emit(HEADLINE, value=value, label=label, detail=detail)

    def token(self, text):
        return self.emit(TOKEN, text=text)

    def note(self, text):
        return self.emit(NOTE, text=text)

    def done(self, spend, wall_ms, **extra):
        return self.emit(DONE, spend=spend, wall_ms=wall_ms, **extra)

    def error(self, message, fatal=False):
        return self.emit(ERROR, message=message, fatal=fatal)


class NullEmitter(Emitter):
    """For tests and library use: records nothing, renders nothing."""

    def emit(self, kind, **data):
        return Event(kind, data)


def json_sink(write):
    """Sink that writes newline-delimited JSON. This is the wire format a browser
    will consume over SSE, unchanged."""
    import json

    def sink(ev: Event):
        write(json.dumps(ev.as_dict(), default=str) + "\n")
    return sink
