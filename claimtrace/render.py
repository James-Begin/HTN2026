"""Terminal renderer. Consumes the event stream and draws.

Design targets, in order:
  1. Legible from three metres on a projector.
  2. Something changes every couple of seconds. Never a dead spinner.
  3. One decisive number, rendered large, per run.

The bisect animation is the centrepiece: ~30 probes collapsing twenty years of
archive down to two seconds, drawn as a staircase so the whole search stays
visible after it finishes.
"""
import shutil
import sys
from datetime import datetime, timezone

from . import events as E
from .xapi import ARCHIVE_FLOOR_TS as FLOOR

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
GREY = "\033[90m"

BLOCKS = " ▁▂▃▄▅▆▇█"


def _w(default=80):
    try:
        return min(shutil.get_terminal_size().columns, 100)
    except Exception:
        return default


def _fmt_n(v):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:,.1f}"
    return f"{v:,}"


def _human_span(seconds):
    s = abs(seconds)
    if s >= 31557600:
        return f"{s / 31557600:.1f}y"
    if s >= 86400:
        return f"{s / 86400:.0f}d"
    if s >= 3600:
        return f"{s / 3600:.0f}h"
    if s >= 60:
        return f"{s / 60:.0f}m"
    return f"{s:.0f}s"


class TerminalRenderer:
    """A sink for Emitter. Stateful because a few panels need context."""

    def __init__(self, out=sys.stdout, colour=True):
        self.out = out
        self.colour = colour and out.isatty()
        self.width = _w()
        self._probe_rows = 0
        self._axis = None
        self._in_narrative = False
        self._signals = []
        self._raw = None

    # ------------------------------------------------------------------ helpers
    def _c(self, code, text):
        return f"{code}{text}{RESET}" if self.colour else str(text)

    def p(self, line=""):
        self.out.write(line + "\n")
        self.out.flush()

    def rule(self, n, name, note=None):
        bar = "─" * max(0, self.width - len(name) - 8)
        tail = f"  {self._c(DIM, note)}" if note else ""
        self.p(f"\n{self._c(BOLD, f'{n} {name.upper()}')} {self._c(GREY, bar)}{tail}")

    # ------------------------------------------------------------------- panels
    def _header(self, text, source=None):
        w = self.width
        self.p(self._c(GREY, "╭" + "─" * (w - 2) + "╮"))
        body = text.replace("\n", " ")
        for i in range(0, min(len(body), (w - 4) * 2), w - 4):
            chunk = body[i:i + w - 4]
            self.p(self._c(GREY, "│ ") + self._c(BOLD, chunk.ljust(w - 4)) + self._c(GREY, " │"))
        if source:
            self.p(self._c(GREY, "│ ") + self._c(DIM, source.ljust(w - 4)) + self._c(GREY, " │"))
        self.p(self._c(GREY, "╰" + "─" * (w - 2) + "╯"))

    def _barchart(self, curve, rows=5):
        """Vertical bar chart of the daily curve. The money visual."""
        if not curve:
            return
        vals = [c for _, c in curve]
        peak = max(vals) or 1
        label_w = len(f"{peak:,}") + 1
        for r in range(rows, 0, -1):
            hi = peak * r / rows
            lo = peak * (r - 1) / rows
            axis = f"{peak:,}".rjust(label_w) if r == rows else " " * label_w
            line = ""
            for v in vals:
                if v >= hi:
                    line += "█"
                elif v > lo:
                    frac = (v - lo) / (hi - lo)
                    line += BLOCKS[max(1, int(frac * 8))]
                else:
                    line += " "
            self.p(f"  {self._c(GREY, axis)} {self._c(CYAN, line)}")
        self.p(f"  {'0'.rjust(label_w)} {self._c(GREY, '└' + '─' * (len(vals) - 1))}")
        self.p(f"  {' ' * label_w} {self._c(DIM, curve[0][0])}"
               f"{' ' * max(1, len(vals) - 21)}{self._c(DIM, curve[-1][0])}")

    def _probe_row(self, n, lo, hi, hit, span_seconds, phase):
        """One line of the collapsing-window staircase.

        The axis auto-zooms. At full 20-year scale the window becomes sub-pixel
        after about six probes, so once it would render narrower than two
        characters we rebase the axis around it and mark the new scale. Without
        this the last twenty rows all look identical.
        """
        axis_w = max(20, self.width - 36)
        if self._axis is None:
            self._axis = (FLOOR, datetime.now(timezone.utc).timestamp())

        alo, ahi = self._axis
        if (hi - lo) / max(ahi - alo, 1) * axis_w < 2:
            # Padding must be a FRACTION of the window, not a multiple. At 4x and
            # 24x the window landed back under 2 chars immediately and the axis
            # re-based on every probe. At 0.5x the window fills half the axis, so
            # one zoom survives about four halvings.
            pad = max((hi - lo) * 0.5, 0.5)
            self._axis = (lo - pad, hi + pad)
            alo, ahi = self._axis
            self.p(f"  {self._c(DIM, '   ' + '╌' * axis_w)} "
                   f"{self._c(YELLOW, 'zoom ' + _human_span(ahi - alo))}")

        span = max(ahi - alo, 1)
        a = int(max(0.0, (lo - alo) / span) * axis_w)
        b = max(a + 1, int(min(1.0, (hi - alo) / span) * axis_w))
        bar = (self._c(GREY, "·" * a)
               + self._c(GREEN if hit else RED, "█" * (b - a))
               + self._c(GREY, "·" * max(0, axis_w - b)))
        mark = self._c(GREEN, "HIT ") if hit else self._c(RED, "miss")
        self.p(f"  {self._c(DIM, f'{n:02d}')} {self._c(DIM, phase[0])} "
               f"{bar} {mark} {self._c(BOLD, _human_span(span_seconds).rjust(6))}")
        self._probe_rows += 1

    def _hbar(self, label, value, share, width=26):
        filled = int((share or 0) * width)
        bar = self._c(BLUE, "█" * filled) + self._c(GREY, "░" * (width - filled))
        pct = f"{share * 100:5.1f}%" if share is not None else "     "
        self.p(f"  {label:<20s} {_fmt_n(value):>9s}  {bar} {pct}")

    def _headline(self, value, label, detail):
        """The one number to remember. Deliberately loud."""
        w = self.width
        val = str(value)
        self.p()
        self.p(self._c(BOLD + YELLOW, "  " + "▁" * (w - 4)))
        self.p(f"  {self._c(BOLD + YELLOW, val)}   {self._c(BOLD, label)}")
        if detail:
            self.p(f"  {self._c(DIM, detail[:w - 4])}")
        self.p(self._c(BOLD + YELLOW, "  " + "▔" * (w - 4)))

    # -------------------------------------------------------------------- sink
    def __call__(self, ev):
        k, d = ev.kind, ev.data

        if k == E.CLAIM:
            self._header(d["text"], d.get("source"))

        elif k == E.RESOLVED:
            st = d["state"]
            colour = GREEN if st == "LIVE" else (RED if st == "DELETED" else YELLOW)
            bits = [self._c(colour, f"[{st}]")]
            if d.get("handle"):
                bits.append(f"@{d['handle']}")
            if d.get("author_id"):
                bits.append(self._c(DIM, f"id {d['author_id']}"))
            if d.get("created_at"):
                bits.append(self._c(DIM, str(d["created_at"])[:19]))
            if d.get("media"):
                bits.append(self._c(YELLOW, f"{d['media']} image(s)"))
            self.p("  " + " ".join(bits))
            if d.get("tombstone"):
                self.p(f"  {self._c(DIM, d['tombstone'][:self.width - 4])}")

        elif k == E.STAGE:
            self.rule(d["n"], d["name"], d.get("note"))

        elif k == E.EXTRACT:
            conf = d.get("anchor_confidence")
            quoted = '"' + d["anchor"] + '"'
            vol = d.get("anchor_volume_12mo")
            lift = d.get("anchor_lift")
            if vol is not None:
                info = f"{vol:,} posts/12mo"
                if lift is not None:
                    info += f", lift {lift:.0%}"
            else:
                info = f"conf {conf}" if conf else ""
            tail = self._c(DIM, info)
            self.p(f"  anchor      {self._c(BOLD + CYAN, quoted)}   {tail}")
            if d.get("anchor_rejected"):
                self.p(f"  {self._c(DIM, 'rejected    ' + ', '.join(d['anchor_rejected'][:2]))}")
            for key, colour in (("morphology", DIM), ("negatives", DIM)):
                if d.get(key):
                    self.p(f"  {key:<11s} {self._c(colour, ', '.join(d[key][:3]))}")
            for p in (d.get("premises") or [])[:3]:
                self.p(f"  premise     {self._c(DIM, str(p.get('claim'))[:self.width - 16])}")
            for f in (d.get("plausibility") or [])[:3]:
                self.p(f"  {self._c(YELLOW, '⚠ flag')}      {f[:self.width - 16]}")

        elif k == E.SHAPE:
            self._barchart(d.get("curve") or [])
            self.p(f"  total {self._c(BOLD, _fmt_n(d['total_30d']))}"
                   f"   peak {self._c(BOLD, _fmt_n(d['peak']))} on {d.get('peak_day')}"
                   f"   pre-spike {self._c(BOLD, _fmt_n(d.get('pre_spike_total')))}"
                   f"   ratio {_fmt_n(d.get('spike_ratio'))}x")

        elif k == E.ROUTE:
            mode = d["mode"]
            colour = {"VERIFY": CYAN, "LINEAGE": BLUE, "ABSTAIN": YELLOW}.get(mode, BOLD)
            self.p(f"\n  {self._c(BOLD + colour, '→ ' + mode)}"
                   f"  {self._c(DIM, d.get('why') or '')}")

        elif k == E.PROBE:
            self._probe_row(d["n"], d["lo"], d["hi"], d["hit"],
                            d["span_seconds"], d["phase"])

        elif k == E.EARLIEST:
            post = d.get("post")
            if not post:
                self.p(f"  {self._c(YELLOW, 'no matching post found')}")
                return
            self.p(f"\n  earliest    {self._c(BOLD + GREEN, post['created_at'])}"
                   f"   {self._c(DIM, 'id ' + str(post['id']))}")
            self.p(f"              {post['text'][:self.width - 16]!r}")
            pm = post.get("public_metrics") or {}
            likes = pm.get("like_count", 0)
            meta = f"likes {likes:,}   probes {d.get('probes')}"
            self.p(f"              {self._c(DIM, meta)}")

        elif k == E.SIGNAL:
            if d["label"] == "raw 7d":
                self._raw = d["value"]
                self.p(f"  {d['label']:<20s} {_fmt_n(d['value']):>9s}")
            else:
                share = d.get("share")
                if share is None and self._raw and d["value"] is not None:
                    share = d["value"] / max(self._raw, 1)
                self._hbar(d["label"], d["value"], share)
            if d.get("note"):
                self.p(f"  {self._c(DIM, d['note'])}")

        elif k == E.PREMISE:
            self.p(f"  {'premise':<20s} {_fmt_n(d['volume']):>9s}  "
                   f"{self._c(DIM, d['claim'][:self.width - 36])}")

        elif k == E.CASCADE:
            for post in d["posts"][:8]:
                pm = post.get("public_metrics") or {}
                likes = f"L{pm.get('like_count', 0):>8,}"
                self.p(f"  {post['created_at'][5:16]}  {self._c(BOLD, likes)}"
                       f"  {post['text'][:self.width - 30]!r}")

        elif k == E.SCORE:
            verdict = d.get("verdict")
            mark = {"accept": self._c(GREEN, "✓"),
                    "uncertain": self._c(YELLOW, "?"),
                    "reject": self._c(GREY, "·")}.get(
                        verdict, self._c(GREEN, "✓") if d["accepted"] else " ")
            sc = d["same_claim"]
            colour = {"accept": GREEN, "uncertain": YELLOW, "reject": GREY}.get(
                verdict, GREEN if sc >= 0.5 else (YELLOW if sc >= 0.2 else GREY))
            reg = d.get("register")
            # The register is flagged loudly when it is `meta`, because commentary or a
            # denial counted as corroboration is this tool's worst failure mode.
            tag = ""
            if reg:
                tag = self._c(RED if reg == "meta" else DIM, f" [{reg}]")
            self.p(f"  {mark} {self._c(colour, f'{sc:.4f}')}{tag}  "
                   f"{d['text'][:self.width - 26]!r}")

        elif k == E.HEADLINE:
            self._headline(d["value"], d["label"], d.get("detail"))

        elif k == E.TOKEN:
            if not self._in_narrative:
                self._in_narrative = True
                self.out.write("  ")
            self.out.write(d["text"].replace("\n", "\n  "))
            self.out.flush()

        elif k == E.NOTE:
            self.p(f"  {self._c(DIM, '· ' + d['text'])}")

        elif k == E.DONE:
            if self._in_narrative:
                self.p()
            self.p()
            self.p(self._c(DIM, f"  spend ${d['spend']:.3f}   wall {d['wall_ms'] / 1000:.1f}s"
                                + "".join(f"   {k2} {v}" for k2, v in d.items()
                                          if k2 not in ("spend", "wall_ms"))))

        elif k == E.ERROR:
            self.p(f"\n  {self._c(RED + BOLD, 'ERROR')} {d['message']}")
