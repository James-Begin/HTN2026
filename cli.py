#!/usr/bin/env python3
"""claimtrace - where did this claim come from, and does anyone corroborate it.

  python cli.py "some claim text"
  python cli.py --url https://x.com/user/status/2099253016847090149
  python cli.py "claim" --mode lineage --budget 400
  python cli.py "claim" --json > run.ndjson      # the wire format a browser reads

The CLI is deliberately thin. All behaviour lives in the pipeline and is observed
through the event stream, so the terminal renderer and a future web UI consume the
same truth rather than drifting apart.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claimtrace import config as C                                  # noqa: E402
from claimtrace.baseten import CrossEncoder, HostedLLM              # noqa: E402
from claimtrace.events import Emitter, json_sink                    # noqa: E402
from claimtrace.pipeline import run                                 # noqa: E402
from claimtrace.render import BOLD, DIM, RESET, TerminalRenderer    # noqa: E402
from claimtrace.resolve import LIVE, NONEXISTENT, resolve           # noqa: E402
from claimtrace.xapi import BudgetExceeded, XClient                 # noqa: E402


def load_input(args, emit):
    """Return claim text, or exit with a finding.

    A DELETED post is not an error. The id proves it existed and the Snowflake
    timestamp proves when, so we report that and stop.
    """
    if not args.url:
        return args.claim

    r = resolve(args.url)
    emit.resolved(r.tweet_id, r.state, handle=r.handle, author_id=r.author_id,
                  created_at=r.created_at, media=len(r.media), tombstone=r.tombstone)

    if r.state == NONEXISTENT:
        raise SystemExit(f"\n  id {r.tweet_id} never existed.\n")
    if r.state != LIVE:
        when = f" posted {r.created_at:%Y-%m-%dT%H:%M:%SZ}" if r.created_at else ""
        raise SystemExit(
            f"\n  {BOLD}FINDING: this post is {r.state}.{RESET}{when}\n"
            f"  The id resolves, so it provably existed and provably no longer does.\n"
            f"  Paste the text, recoverable from retweets, to trace it anyway.\n")

    prose = r.text.split("https://")[0].strip()
    if not prose and r.media:
        raise SystemExit(
            f"\n  {BOLD}This post has no prose{RESET} - {len(r.media)} image(s) only.\n"
            f"  A text pipeline cannot read it. Paste the claim text instead.\n"
            f"  (The most-liked tweet in history is exactly this shape.)\n")
    return r.text


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("claim", nargs="?", help="claim text")
    ap.add_argument("--url", help="tweet URL to resolve instead")
    ap.add_argument("--mode", choices=["auto", "verify", "lineage"], default="auto")
    ap.add_argument("--budget", type=int, default=C.DEFAULT_POST_BUDGET,
                    help="hard ceiling on posts read")
    ap.add_argument("--min-likes", type=int, default=2000, help="cascade threshold")
    ap.add_argument("--list", dest="authority_list", help="X List id of trusted sources")
    ap.add_argument("--json", action="store_true", help="emit NDJSON instead of drawing")
    ap.add_argument("--no-colour", action="store_true")
    a = ap.parse_args()

    if a.json:
        emit = Emitter(json_sink(sys.stdout.write))
    else:
        emit = Emitter(TerminalRenderer(colour=not a.no_colour))

    text = load_input(a, emit)
    if not text:
        ap.error("provide claim text or --url")

    t0 = time.time()
    llm = HostedLLM(C.BASETEN_API_KEY)
    xe = CrossEncoder(C.BASETEN_API_KEY)
    x = XClient(C.X_BEARER, post_budget=a.budget)

    try:
        run(text, emit, llm, xe, x, mode=a.mode, min_likes=a.min_likes,
            authority_list=a.authority_list, source=a.url)
    finally:
        emit.done(x.spend, (time.time() - t0) * 1000,
                  posts=x.posts_read, counts=x.counts_calls, llm_calls=llm.calls)


if __name__ == "__main__":
    try:
        main()
    except BudgetExceeded as e:
        print(f"\n  {BOLD}BUDGET STOP{RESET} {e}\n", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print(f"\n  {DIM}interrupted{RESET}", file=sys.stderr)
        sys.exit(130)
