# Demo cases

Eight cases in `demo/cases.jsonl`, every id independently verified, zero fabricated.

```
python3 cli.py "$(python3 -c "import json;print(json.loads(open('demo/cases.jsonl').readline())['input'])")"
python3 cli.py --url https://x.com/i/status/869766994899468288   # case 3, free
```

| # | Mode | Beat | Cost |
|---|---|---|---|
| 1 | verify | 98% retweets against 1 original: amplification, not reporting | ~$0.44 |
| 2 | lineage | the earliest instance predates the famous essay by a month | ~$0.19 |
| 3 | resolve | a deleted root sitting next to a live follow-up | **free** |
| 4 | lineage | the first tweet ever, id 20, found by bisection | ~$0.19 |
| 5 | lineage | a typo is a better fingerprint than the sentence | ~$0.19 |
| 6 | resolve | the tool refuses when the claim is in an image | **free** |
| 7 | resolve | identity is the author id, never the handle | **free** |
| 8 | judge-only | a denial is not corroboration | ~free |

## Read this before demoing

**Cases 3, 6 and 7 cost nothing and cannot fail.** They are keyless, they hit the
syndication endpoint rather than the paid API, and their outcome is fixed by history.
Case 3 is the strongest single beat in the whole project: a post deleted nine years ago,
located to within 0.27 seconds by decoding the id offline, sitting six hours away from a
live follow-up that retrieval will happily hand you as if it were the origin.

**Cases 1, 2, 4 and 5 will drift, and case 1 may change route entirely.** Routing keys on
30-day volume, and all the September 2026 events have aged out of that window. The same
SSI claim measured VERIFY at two hours old and LINEAGE a day later. **Re-run every paid
case the morning of the demo** and be ready to drop any that now ABSTAIN.

**Case 4 is the one that once cost $8.50.** "just setting up my twttr" is reposted at
every platform launch, so the archive is dense with copies and the earliest day IS an
explosion day. It only works because the bisect never paginates. Worth saying out loud,
because "misses are free" is the economic insight the whole design rests on.

**Case 8 is the honest one to lead with on model quality.** It needs no X spend and it
shows the thing the fine-tune actually bought. Untrained rerankers score some commentary
above 0.94, which would count a denial as corroboration; the fine-tune caps `meta` at
0.0264.

## What the fine-tune is and is not worth claiming

On the 77-pair English holdout, labelled blind:

| | AUC | ECE | precision | recall |
|---|---|---|---|---|
| untrained 568M | 0.9478 | 0.1165 | 0.8947 | 0.8293 |
| fine-tuned | 0.9790 | 0.0544 | 0.9737 | 0.9024 |

Do claim: calibration halved, precision up 8 points, and `meta` suppression from 0.9833
to 0.0264, which no base-model choice achieved.

Do NOT claim a large ranking win. AUC moves 0.031 on English, because untrained
rerankers already handle same-language English pairs well. Their real weakness was
cross-lingual, and that is out of scope now.

Do NOT present the 25-pair gate as independent evidence. Those cases were curated *as
known failures* and then training data was built targeting their shapes, so 3-of-3 there
is partly true by construction. The 77-pair blind holdout is the number to quote.

## Known gaps a sharp question will find

- **The composer can hallucinate.** One run invented a corporate commitment absent from
  the evidence. The groundedness verifier is designed and unbuilt.
- **X only.** The origin of a viral tweet is usually not a tweet. Bluesky, the Reddit
  archive and the Wayback index are all free and unimplemented in the pipeline, though
  Bluesky is used heavily for training data.
- **`en-m3` is not deployed.** Baseten holds an older cross-lingual checkpoint and is
  switched off. Pushing takes about 12 minutes, and accept/reject thresholds must be
  re-derived for the new checkpoint first because score scales shift between them.
