"""Mining pipeline CLI.

    python3 -m mine.run collect --pages 5        # free, keyless, no GPU
    python3 -m mine.run pairs                    # offline, no cost
    python3 -m mine.run validate                 # labeller vs hand labels. DO THIS FIRST
    python3 -m mine.run label --limit 400        # consensus labelling, costs tokens
    python3 -m mine.run negatives --n 400        # free, no model call
    python3 -m mine.run stats                    # what is on disk

Order matters. `validate` gates `label`: if the labeller cannot reproduce hand
labels on eval/pairs.jsonl, it does not get to make new ones. The command prints a
refusal rather than a warning when agreement is too low.
"""
import argparse
import json
import os
import sys
from collections import Counter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
CORPUS = os.path.join(OUT, "corpus.jsonl")
TRAIN = os.path.join(OUT, "train-mined.jsonl")
NEG = os.path.join(OUT, "train-negatives.jsonl")
REPLIES = os.path.join(OUT, "train-replies.jsonl")
REPLIES2 = os.path.join(OUT, "train-replies2.jsonl")
COMBINED = os.path.join(OUT, "train-all.jsonl")
TRANSLATIONS = os.path.join(OUT, "translations.jsonl")

# The gate keys on BINARY same-claim agreement, averaged over several rounds.
#
# Not on exact 5-way agreement, and not on a single round. Measured over 5 rounds on
# 21 hand-labelled pairs:
#
#   exact 5-way   74.3%   item noise 9.5pt   <- subtype labels are NOISY
#   3-bucket      89.5%   item noise 6.7pt
#   binary same   94.3%   item noise 5.1pt   <- the decision the pipeline consumes
#
# A single round is not a measurement: the same prompt on the same pairs produced
# 85.7%, 90.0%, 95.2% and 81.0%, a spread entirely inside the +/-13 point binomial
# interval at n=21. An earlier version of this gate thresholded a single round at
# 0.85 and refused a labeller that was in fact fine, purely on noise.
#
# The gap between 94.3% binary and 74.3% exact is the important number. It says the
# same/not-same decision is reliable while the SUBTYPE is not, so training must not
# treat all five classes as equally trustworthy supervision.
MIN_BINARY_AGREEMENT = 0.90
VALIDATE_ROUNDS = 5


def _llm():
    from claimtrace.baseten import HostedLLM
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        sys.exit("BASETEN_API_KEY is not set")
    return HostedLLM(key)


def _load_corpus():
    from .bluesky import load
    if not os.path.exists(CORPUS):
        sys.exit(f"no corpus at {CORPUS}; run `python3 -m mine.run collect` first")
    return load(CORPUS)


# ---------------------------------------------------------------------- stages
def cmd_collect(args):
    from .collect import main
    argv = ["--days", str(args.days)]
    if args.pages:
        argv += ["--pages", str(args.pages)]
    if args.append:
        argv += ["--append"]
    return main(argv)


def cmd_pairs(args):
    from .pairs import build, stats
    cands = build(_load_corpus(), max_pairs=args.limit)
    print(stats(cands))
    return 0


def _progress(d, n, res, r, tot):
    if d == n:
        print(f"\r  round {r}/{tot} done", end="", flush=True)


def _run_validation(llm, rounds):
    from .label import validate_repeated
    res = validate_repeated(llm, rounds=rounds, progress=_progress)
    print()
    print(f"  {res['rounds']} rounds over {res['n']} hand-labelled pairs")
    for key, label in (("exact_agreement", "exact 5-way"),
                       ("bucket_agreement", "3-bucket   "),
                       ("binary_agreement", "binary same")):
        if res.get(key) is None:
            print(f"  {label} : n/a")
            continue
        print(f"  {label} : mean {res[key]:.1%}  "
              f"range {res[key + '_min']:.1%}-{res[key + '_max']:.1%}  "
              f"model sd {res[key + '_model_sd'] * 100:.1f}pt  "
              f"item se {res[key + '_item_se'] * 100:.1f}pt  "
              f"lower95 {res[key + '_lower95']:.1%}")
    if res["unstable_items"]:
        print(f"  unstable items ({len(res['unstable_items'])}/{res['n']}): "
              + ", ".join(res["unstable_items"]))
    print("  NOTE: item noise dominates model noise, so more rounds barely help.")
    print("        Only more hand labels tighten this. That is the real bottleneck.")
    return res


def cmd_validate(args):
    llm = _llm()
    res = _run_validation(llm, args.rounds)
    ok = (res["binary_agreement"] or 0) >= MIN_BINARY_AGREEMENT
    print(f"\n  {'TRUSTED' if ok else 'NOT TRUSTED'} for bulk labelling "
          f"(needs mean binary agreement >= {MIN_BINARY_AGREEMENT:.0%})")
    if not ok:
        print("  Sharpen the prompt or hand-label more pairs before labelling at scale.")
    with open(os.path.join(OUT, "validation.json"), "w") as fh:
        json.dump(res, fh, indent=2, default=str)
    print(f"  saved {os.path.join(OUT, 'validation.json')}")
    return 0


def cmd_label(args):
    from .label import apply_to, collapse, label_consensus, write_rows
    from .pairs import build

    llm = _llm()
    if not args.skip_validate:
        res = _run_validation(llm, VALIDATE_ROUNDS)
        agree = res["binary_agreement"] or 0
        if agree < MIN_BINARY_AGREEMENT:
            sys.exit(f"\n  refusing to label: mean binary agreement {agree:.1%} < "
                     f"{MIN_BINARY_AGREEMENT:.0%}. Fix the prompt or add hand labels.")
        print(f"\n  gate passed: mean binary agreement {agree:.1%}")

    cands = build(_load_corpus())
    if args.cross_lingual_only:
        cands = [c for c in cands if c.cross_lingual]
    cands = cands[:args.limit]
    print(f"  labelling {len(cands)} candidates, {args.rounds} rounds each")

    def prog(d, n, res_, r, tot):
        if d % 25 == 0 or d == n:
            print(f"\r  round {r}/{tot}: {d}/{n}", end="", flush=True)

    kept, dropped = label_consensus(llm, [(c.id, c.a_text, c.b_text) for c in cands],
                                    rounds=args.rounds,
                                    min_confidence=args.min_confidence,
                                    progress=prog)
    print()
    print(f"  kept {len(kept)}/{len(cands)} = {len(kept) / max(len(cands), 1):.0%}"
          f"   dropped {dict(dropped)}")
    print("  labels:  " + ", ".join(f"{k}={v}" for k, v in
                                    Counter(k.label for k in kept).most_common()))
    print("  buckets: " + ", ".join(f"{k}={v}" for k, v in
                                    Counter(collapse(k.label) for k in kept).most_common()))
    n = write_rows(apply_to(cands, kept), args.out)
    print(f"  wrote {n} rows -> {args.out}")
    print("  " + llm.report())
    return 0


def cmd_translate(args):
    """Translate non-Latin posts so they can JOIN. Never used as training text.

    Without this, non-Latin outlets contribute posts that pair with nothing: Al
    Jazeera Arabic carried Latin tokens in 0 of 25 posts and Asahi in 1 of 15, and
    the candidate join runs on shared rare tokens.
    """
    from . import translate as T
    from .bluesky import save

    posts = _load_corpus()
    targets = [p for p in posts if T.needs_translation(p)]
    print(f"  {len(targets)} non-Latin posts of {len(posts)} need a join bridge")
    if not targets:
        return 0
    llm = _llm()

    def prog(d, n):
        if d % 50 == 0 or d == n:
            print(f"\r  translating {d}/{n}", end="", flush=True)

    got = T.translate_posts(llm, targets, progress=prog)
    print()
    T.save(got, args.out)
    landed = T.apply_to_posts(posts, got)
    save(posts, CORPUS)
    print(f"  {len(got)} translations, {landed} attached to the corpus")
    print("  " + llm.report())
    return 0


def cmd_replies(args):
    """Replies to news posts, the only source of `meta` we have.

    Feed mining produced 1,466 same_paraphrase and 34 meta, because newsrooms report
    events rather than commenting on each other's claims. Replies invert that:
    measured yield is 22% meta from 167 labelled rows.
    """
    from .bluesky import Bluesky
    from .label import apply_to, collapse, label_consensus, write_rows
    from .replies import fetch, pick_roots

    posts = _load_corpus()
    roots = pick_roots(posts, n=args.roots, seed=args.seed)
    print(f"  {len(roots)} roots across {len(set(r.day for r in roots))} days")
    bs = Bluesky()

    def fprog(i, n, got):
        if i % 50 == 0 or i == n:
            print(f"\r  fetching {i}/{n} roots -> {got} pairs", end="", flush=True)

    cands = fetch(bs, roots, per_root=args.per_root, progress=fprog)
    print(f"\n  {len(cands)} reply pairs   {bs.report()}")
    if not cands:
        return 0

    llm = _llm()

    def lprog(d, n, res, r, tot):
        if d % 50 == 0 or d == n:
            print(f"\r  labelling {d}/{n}", end="", flush=True)

    kept, dropped = label_consensus(llm, [(c.id, c.a_text, c.b_text) for c in cands],
                                    rounds=args.rounds,
                                    min_confidence=args.min_confidence,
                                    progress=lprog)
    print()
    print(f"  kept {len(kept)}/{len(cands)}   dropped {dict(dropped)}")
    print("  labels:  " + ", ".join(f"{k}={v}" for k, v in
                                    Counter(k.label for k in kept).most_common()))
    print("  buckets: " + ", ".join(f"{k}={v}" for k, v in
                                    Counter(collapse(k.label) for k in kept).most_common()))
    n = write_rows(apply_to(cands, kept), args.out)
    print(f"  wrote {n} rows -> {args.out}")
    print("  " + llm.report())
    return 0


def cmd_combine(args):
    """Merge every source into one training file, deduplicated, with a class report."""
    seen, rows = set(), []
    for path in (TRAIN, REPLIES, REPLIES2, NEG):
        if not os.path.exists(path):
            print(f"  (missing) {os.path.basename(path)}")
            continue
        n = 0
        for line in open(path):
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r["reference"], r["candidate"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
            n += 1
        print(f"  {n:>6d} from {os.path.basename(path)}")
    if not rows:
        sys.exit("  nothing to combine")
    labs = Counter(r["label"] for r in rows)
    with open(args.out, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n  {len(rows)} rows -> {args.out}")
    for k, v in labs.most_common():
        print(f"    {k:<16s} {v:>5d}  {v / len(rows):>5.1%}")
    xl = sum(1 for r in rows if (r.get("source") or {}).get("cross_lingual"))
    print(f"  cross-lingual {xl} = {xl / len(rows):.0%}")
    machine = sum(1 for r in rows if r.get("confidence") == "machine")
    print(f"  machine-labelled {machine}, structural {len(rows) - machine}")
    return 0


def cmd_negatives(args):
    from . import negatives
    from .label import write_rows
    cands = negatives.build(_load_corpus(), n=args.n, seed=args.seed)
    n = write_rows(negatives.as_rows(cands), args.out)
    print(f"  {n} structural negatives -> {args.out}   (no model call, $0.00)")
    return 0


def cmd_stats(args):
    for path in (CORPUS, TRAIN, REPLIES, REPLIES2, NEG, COMBINED):
        if not os.path.exists(path):
            print(f"  {'(missing)':<12s} {path}")
            continue
        rows = [json.loads(l) for l in open(path) if l.strip()]
        labs = Counter(r.get("label", "-") for r in rows)
        xl = sum(1 for r in rows
                 if (r.get("source") or {}).get("cross_lingual"))
        print(f"  {len(rows):>6d} rows  {os.path.basename(path):<24s} "
              f"cross-lingual {xl:<5d} {dict(labs.most_common())}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("collect", help="pull outlet feeds from Bluesky (free)")
    p.add_argument("--days", type=int, default=45, help="common floor date")
    p.add_argument("--pages", type=int, default=None, help="fixed cap, overrides budget")
    p.add_argument("--append", action="store_true")
    p.set_defaults(fn=cmd_collect)

    p = sub.add_parser("pairs", help="build candidate pairs (offline)")
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(fn=cmd_pairs)

    p = sub.add_parser("validate", help="labeller vs hand labels")
    p.add_argument("--rounds", type=int, default=VALIDATE_ROUNDS)
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("label", help="consensus-label candidates (costs tokens)")
    p.add_argument("--limit", type=int, default=400)
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--min-confidence", type=float, default=0.9)
    p.add_argument("--cross-lingual-only", action="store_true")
    p.add_argument("--skip-validate", action="store_true",
                   help="skip the trust gate. Not recommended.")
    p.add_argument("--out", default=TRAIN)
    p.set_defaults(fn=cmd_label)

    p = sub.add_parser("negatives", help="random structural negatives (free)")
    p.add_argument("--n", type=int, default=400)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=NEG)
    p.set_defaults(fn=cmd_negatives)

    p = sub.add_parser("replies", help="reply pairs, the meta source")
    p.add_argument("--roots", type=int, default=400)
    p.add_argument("--per-root", type=int, default=6)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--min-confidence", type=float, default=0.9)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default=REPLIES)
    p.set_defaults(fn=cmd_replies)

    p = sub.add_parser("translate", help="bridge non-Latin posts so they can join")
    p.add_argument("--out", default=TRANSLATIONS)
    p.set_defaults(fn=cmd_translate)

    p = sub.add_parser("combine", help="merge all sources into one training file")
    p.add_argument("--out", default=COMBINED)
    p.set_defaults(fn=cmd_combine)

    p = sub.add_parser("stats", help="what is on disk")
    p.set_defaults(fn=cmd_stats)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
