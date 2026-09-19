# Mining real claim pairs

Training data for the claim-equivalence cross-encoder, harvested from real posts
rather than generated. Free, keyless, no GPU.

```
python3 -m mine.run collect --days 45     # 34 outlets to a common floor date, free
python3 -m mine.run translate             # bridge non-Latin posts so they can join
python3 -m mine.run pairs                 # build candidates, offline
python3 -m mine.run validate              # labeller vs hand labels. DO THIS FIRST
python3 -m mine.run label --limit 9874    # label event pairs, costs tokens
python3 -m mine.run replies --roots 400   # the meta source, costs tokens
python3 -m mine.run negatives --n 400     # structural negatives, no model call
python3 -m mine.run combine               # merge, dedupe, report class balance
python3 -m unittest tests.test_mine       # 59 tests, no network
```

## What came out

| Source | Rows | Cost |
|---|---|---|
| 59,580 posts from 34 outlets, 8 languages | — | $0.00 |
| event pairs, labelled | 9,142 | tokens |
| reply pairs, labelled | 7,306 | tokens |
| structural negatives | 2,500 | $0.00 |
| **combined, deduplicated** | **18,948** | |

| Class | Rows | Share |
|---|---|---|
| `same_paraphrase` | 6,545 | 34.5% |
| `incidental` | 5,471 | 28.9% |
| `unrelated` | 5,377 | 28.4% |
| `meta` | 1,436 | 7.6% |
| `same_verbatim` | 119 | 0.6% |

**6,343 rows are cross-lingual**, 33% of the set, across eight language pairs:

| Pair | Rows | Pair | Rows |
|---|---|---|---|
| `en-fr` | 1,555 | `de-fr` | 362 |
| `de-en` | 988 | `en-it` | 353 |
| `en-es` | 667 | `es-fr` | 238 |
| `en-nl` | 374 | `en-pt` | 231 |

Median Jaccard on `same_paraphrase` is 0.146, and the 10th percentile is 0.046. That
low tail is the point: those are pairs no lexical heuristic could match.

All Bluesky reads were free. The only spend was labelling and translation tokens,
roughly 12M in and 1.3M out on `gpt-oss-120b`.

### `same_verbatim` is thin on purpose

119 rows, 0.6%. This is a real property of the corpus rather than a collection
failure: newsrooms rewrite rather than republish, so genuine cross-outlet verbatim
pairs barely exist. Padding it was considered and rejected. The available free
sources, such as a post's text against its own embed title, differ only by an
appended shortener, so they sit at Jaccard near 1.0 and teach nothing the served
model does not already do at 0.999. Class weighting in training is the right fix, not
data that inflates a count without adding signal.

`validate` gates `label`. If the labeller cannot reproduce hand labels on
`eval/pairs.jsonl`, `label` refuses to run rather than warning.

---

## Why mine instead of generate

`same_paraphrase` is the one class with no free label source. Retweets give
verbatim pairs, quote-tweets give meta, same-phrase-different-era gives collisions,
random pairing gives unrelated. Nothing marks two posts as the same claim in
different words, which is exactly why the served model fails at it.

Generating that class introduces distribution error: train on generated paraphrases
and evaluate on generated paraphrases, and you have measured how well the model
learned the generator's habits. Mining introduces label noise instead, which is
smaller and, unlike distribution error, measurable.

So the rule is **the model labels real text, it never writes text.**

## Two things drive yield, and neither is more pages

The first scale-up was nearly wasted effort, which is worth recording. Tripling the
corpus from 4,473 to 13,412 posts raised candidates only from 1,896 to 2,673, a 41%
gain on a 200% increase in data.

**Date-range OVERLAP is the binding constraint, not corpus size.** Pairs can only
form where outlets cover the same days, and outlets file at wildly different rates.
At a flat 15 pages each, Reuters covered 11 days and AFP covered three months, so
every extra AFP page landed outside the intersection and contributed nothing. Paging
to a common FLOOR DATE instead of a common page count is the fix.

**Outlet count matters quadratically**, because candidates come from cross-outlet
pairs. Nine outlets give 36 pairs; 34 give 561.

| | Outlets | Posts | Candidates | Cross-lingual |
|---|---|---|---|---|
| flat page count | 9 | 13,412 | 2,673 | 1,156 |
| common floor, 45 days | 34 | 59,580 | 9,874 | 4,415 |

619 requests for the second collection. Still free.

Cross-lingual pairs now span eight language pairs rather than three: `en-fr` 1,076,
`de-en` 678, `en-es` 348, `de-fr` 277, `en-it` 269, plus Japanese via the bridge.

## The join key is a shared event, not a shared link

Shared outlinks were the original plan. The data killed it. Outlets link their own
article and Reuters shortens to `reut.rs`, so two outlets covering one event share
no URL at all. Of 4,473 posts, exactly one pair exceeded Jaccard 0.85.

What works is rare-token overlap in a narrow time window. Independent newsrooms
reuse the proper nouns and the numbers and almost nothing else.

> Rescuers searching for **140** people after **Indonesia** passenger ship sinks
> **Indonesian** rescue crews searching for **140** people after ferry hit bad weather

Two thresholds, because only entities survive translation. Same-language pairs need
three shared rare tokens; cross-language pairs need two. Demanding three throws away
most true cross-lingual pairs.

## What this yields that generation cannot

**Cross-lingual pairs, real and free.** An English and a French report of the Amazon
cargo plane crash, Jaccard 0.069, labelled `same_paraphrase` at confidence 0.97.
That is the shape of the worst measured failure, where Arabic coverage of an essay
announcement scored 0.012.

**Same-topic-different-claim hard negatives, also free.** These cannot be
convincingly invented:

| Post A | Post B | Truth |
|---|---|---|
| Shelton *will face* Zverev in the final | Zverev *claims* first US Open | different claims |
| Oasis 2027 tour, Stade de France dates | Oasis 2027 tour, Knebworth return | same claim |

Both sit near Jaccard 0.04. Lexical overlap cannot separate them, so the labeller
is doing real work rather than rubber-stamping a heuristic.

---

## Crossing a script boundary needs a translation bridge

The rare-token join is Latin-bound, and the measurement is stark:

| Outlet | Posts with Latin tokens | With Western digits |
|---|---|---|
| Al Jazeera Arabic | 0 of 25 | 1 of 25 |
| Asahi (Japanese) | 1 of 15 | 4 of 15 |

"Dario Amodei" is "داريو أمودي" in Arabic. So a non-Latin post can never share a
token with an English one, and adding non-Latin outlets would contribute posts that
pair with nothing at all.

The bridge gives each non-Latin post one English translation, used **solely to
compute the join**. The stored pair keeps the original text and the label is decided
on the original. Three properties follow, and all three matter:

- No generated text enters training. The Japanese side of a pair is real Japanese.
- Language detection reads the ORIGINAL, never the translation. Reading the
  translation would relabel every Japanese post as English and collapse
  `cross_lingual` to False, destroying the exact signal being mined.
- A wrong translation costs a rejected candidate, not a corrupted label, because the
  labeller still judges the real texts. The failure mode is lost yield.

It works. 835 posts bridged, 184 cross-script candidates, 141 of them English to
Japanese:

| Post A | Post B | Joined on |
|---|---|---|
| Yayoi Kusama, who splashed polka dots across art world, dies at 97 | 前衛芸術家の草間彌生さん死去、97歳 | polka, dots, 97 |
| Philippine VP Duterte posts bail after arrest order | フィリピン副大統領、大統領を脅迫した容疑　保釈金で逮捕は回避 | duterte, bail, marcos |

### But Arabic is not sourceable here, which is the case that motivated it

Al Jazeera Arabic has 1,614 posts and is **dormant since 2026-01-03**, months before
any usable floor date. No active Arabic news outlet was found on Bluesky at all.
Hankyoreh looked like a Korean source and turned out to be their English edition,
detected as English on 247 of 253 posts.

So the bridge is built and validated on Japanese, and the Arabic failure that
motivated it still needs a different source. Bluesky's user base is heavily Western;
this is a property of the platform, not of the method.

## Language detection covers nine languages, script first

Script is checked before the stopword vote because a Unicode block is unambiguous
where function words are shared. Kana is checked before kanji, since kanji alone
cannot separate Japanese from Chinese and kana can. A 15% share threshold stops one
quoted Arabic word from flipping an English headline.

**Both the stopword and accent sets are made disjoint automatically.** Hand
maintenance failed twice. First "de" and "la" across French and Spanish. Then adding
Portuguese introduced "está", which is also Spanish, and "El niño está aquí" began
detecting as Portuguese because `pt` matched two shared words while `es` matched one.
Likewise "à" is French and Italian, "ç" French and Portuguese, "á" Spanish and
Portuguese. Computing the overlap and stripping it removes the whole bug class, and
two tests now pin the property.

## The labeller had to earn the job

It was validated against the hand-labelled eval set before being allowed to label
anything, and it failed the first attempt. Reading the disagreements showed most of
the fault was in the class definitions, not the model, so six boundary rules were
added, each traceable to a specific disagreement: compare against what A asserts
rather than what A is about; treat spelling fixes as verbatim; prefer incidental over
unrelated whenever a shared entity can be named; a bare title carries the claim; a
denial is always meta; and an acronym referring to a different thing is always
incidental.

Averaged over 5 rounds on 21 hand-labelled pairs:

| Agreement | mean | range | model noise | item noise | lower 95% |
|---|---|---|---|---|---|
| exact 5-way | 74.3% | 71.4-76.2% | 2.6pt | 9.5pt | 55.5% |
| 3-bucket | 89.5% | 85.7-95.2% | 4.0pt | 6.7pt | 76.0% |
| binary same-claim | 94.3% | 90.5-100% | 4.0pt | 5.1pt | 83.8% |

### A single round is not a measurement

The same prompt on the same pairs produced bucket agreement of 85.7%, 90.0%, 95.2%
and 81.0% on four separate occasions. That 14-point spread sits entirely inside the
binomial interval at n=21, which is about ±13 points, so the set cannot distinguish
81% from 95%.

This is not a small caveat. An earlier version of this gate thresholded a single
round at 85% and **refused a labeller that was in fact fine**, purely on noise. And
an earlier draft of this file quoted 80% exact agreement from one lucky run; the
five-round mean is 74.3%. Any single number from this set is a draw, not a result.

Item noise dominates model noise on every metric, so averaging more rounds is nearly
useless. Only hand-labelling more pairs tightens the estimate. That is the real
bottleneck in this whole pipeline.

### The gap between 94.3% and 74.3% is the finding that matters

Binary same-claim agreement is reliable. Subtype agreement is not. Five of 21 items
flip label between rounds, and they cluster on genuinely ambiguous cases where the
hand label is also shaky.

The implication for training is direct: **the five class labels are not equally
trustworthy supervision.** The same/not-same distinction can be trained on
confidently; the subtype cannot. Treating all five as equally certain would fit noise
in the head that matters least.

The three buckets are `same`, `meta`, `not_same`. `incidental` and `unrelated`
collapse together because nothing downstream distinguishes them. `meta` stays alone
because confusing it with a positive inverts a verify run's conclusion, which is the
most expensive mistake this model can make.

### Two filters, both measured

| Filter | n | bucket agreement | binary |
|---|---|---|---|
| none | 20 | 90.0% | 95.0% |
| two rounds concur | 18 | 94.4% | 100% |
| confidence ≥ 0.95 | 9 | 100% | 100% |

Where two independent rounds disagree, agreement with hand labels is 50%, a coin
flip. So inconsistent rows carry no information and are dropped rather than
downweighted.

Both filters land on the same 94.4%, so bulk labelling runs **one round with a 0.9
confidence floor** rather than two rounds, at half the cost and half the wall time.
Consensus stays available via `--rounds 2` for a higher-precision pass over a
subset, and it is worth using on anything destined for the eval gate.

### Throughput is capped, and blasting past the cap is slower than pacing to it

| Concurrency | Burst rate | Responses lost |
|---|---|---|
| 8 | 430/min | none |
| 16 | 231/min | none |
| 32 | 153/min | 9 of 32 |

Concurrency 8 is optimal and more is actively harmful, which matches the note in
`claimtrace/baseten.py` that 64 collapses entirely.

But a 32-pair burst is not a run. The hosted Model API caps at 120 requests a
minute, so a sustained job at 430/min collects 429s, and each one costs a fixed two
to four second sleep. The first attempt at this ran at **30 requests a minute, four
times slower than simply pacing to the cap.** A token bucket at 110/min fixes it.
The lesson generalises: when a documented rate limit exists, pace to it rather than
discovering it through backoff.

### The honest caveat

The prompt was tuned three times against these same 21 pairs, so even the five-round
mean is optimistic. The rules added are principled rather than fitted to individual
examples, which is why they should generalise, but nothing here establishes that they
do. A fresh held-out set the prompt was never tuned against is required before any of
these numbers can be quoted as accuracy.

The architectural protection is what makes proceeding reasonable anyway: mined rows
are marked `machine` and are training data only. Nothing machine-labelled ever enters
`eval/pairs.jsonl`. So label noise degrades training, which shows up as a worse
checkpoint, and it cannot corrupt the measurement that decides whether to ship.

### Noise that is visible in the output, stated rather than hidden

Spot-checking the lowest-overlap cross-lingual `same_paraphrase` rows shows the
expected error concentrated in one place: replies that ELABORATE on a claim get
called restatements. A French reply reading "this kind of model that roams locally
but needs access to your data" under an English post about an AI assistant's privacy
risks was labelled `same_paraphrase`, where boundary rule 1 says it is `meta`. Roughly
324 reply-derived rows carry that risk. It matches the measured 74% exact against 94%
binary agreement, and it is another reason training should weight the same/not-same
objective above the subtype.

---

## Facts measured against live data

**Bluesky, 2026-09-19 01:31 EDT.** `searchPosts` returns 403 without auth, blocked at the
BunnyCDN edge rather than by the API, so retrying never helps. `getAuthorFeed` and
`getProfile` do work keyless and paginate by cursor. So mining is account-driven,
not query-driven.

**`record.langs` cannot be trusted.** Le Monde tags every French post `["en"]`, 500
of 500 wrong. AFP omits it on 496 of 498 and posts French on a nominally English
account, so the account is not the language either. Reuters omits it on 472 of 500.
Trusting that one field turned French-French pairs into "cross-lingual" training
data, silently poisoning the pair type the project most needs to fix.

Stopword voting plus an accent tiebreak gets 99.8% against editorial language across
4,473 posts. The accent fallback exists because short headlines carry only function
words shared between French and Spanish, so the vote ties and the default wins.

**Candidate yield is bounded by date-range overlap, not corpus size.** Tripling the
corpus from 4,473 to 13,412 posts raised candidates only from 1,896 to 2,673,
because the extra pages extend backward where outlets no longer overlap. Reuters
covers 11 days in 1,500 posts while AFP covers three months. To scale, page the
high-volume outlets back until every outlet spans the same window.

**Truncated JSON is a real failure mode.** At `max_tokens=220` roughly one response
in forty was cut mid-string. The label sits at the front of the object so it
survives, and a regex salvage recovers it rather than discarding a good label.

---

## `meta` needs replies, because newsrooms do not comment

Feed mining produced 1,466 `same_paraphrase` rows and 34 `meta`. That is structural,
not bad luck. Outlets report events; they do not post commentary about each other's
claims. So the feed corpus cannot teach the class.

Adding replies took `meta` from 34 to 231 rows, 2.3% of the set to 5.9%.

Replies can, and `getPostThread` is keyless and free. A reply to a news post is
almost always about the claim rather than an instance of it, and it is where DENIALS
live, which is the most expensive confusion this model can make. Measured yield over
167 labelled reply pairs:

| Label | Rows | Share |
|---|---|---|
| `incidental` | 427 | 41% |
| `unrelated` | 383 | 37% |
| `meta` | 197 | 19% |
| `same_paraphrase` | 26 | 3% |

1,169 reply pairs came from 400 requests, all free, of which 1,033 survived the
confidence filter. A 19% meta rate is low, but it is 19% of a free and effectively
unbounded supply, and it is the only supply there is.

The non-meta majority is not waste, it is a finding about the class scheme. Replies
like "can't wait for him to die so we can move on" under a Trump story are reactions
to the *subject*, not responses to the *claim*, and the labeller puts them in
`unrelated` at high confidence. That is defensible: such a reply never looks like
corroboration, so it does not need the `meta` treatment. But it means "reply" and
"meta" are not synonyms, and replies must be labelled rather than assumed.

`same_verbatim` is also thin at 41 rows. Bluesky reposts would supply it structurally
and for free, and the collector currently skips them deliberately. It is left thin on
purpose: the served model already scores verbatim pairs at 0.999, so more of that
class is the least valuable data available.

## Class balance needs the structural negatives

Mined candidates are selected for shared entities in a narrow time window, which is
a same-event filter, so the distribution skews positive. On a stratified sample of
106 candidates: 57% `same_paraphrase`, 11% `unrelated`.

Random cross-week, cross-outlet pairs supply the missing negative mass at no cost
and with no model call, since the label follows from the construction. Three guards
prevent a false negative: at most one shared rare token, Jaccard at most 0.08, and
at least seven days apart.

One side effect matters more than it looks. The random negatives come out 56%
cross-lingual, which is necessary: if every cross-lingual pair in training were
positive, the model would learn that a different language means the same claim.

## Layout

```
mine/outlets.py     34 curated accounts, 8 languages, with rejected ones recorded
mine/translate.py   English bridge for non-Latin scripts, for MATCHING only
mine/bluesky.py     keyless reader, cursor pagination, post flattening
mine/text.py        tokenisation, language detection, overlap measures
mine/pairs.py       candidate generation via an inverted index on rare tokens
mine/negatives.py   structural negatives by guarded random pairing
mine/label.py       the labelling prompt, consensus filter, and validation gate
mine/collect.py     corpus collection
mine/replies.py     reply pairs via getPostThread, the only `meta` source
mine/run.py         CLI: collect|pairs|validate|label|replies|negatives|combine|stats
mine/out/           corpus and labelled rows, gitignored
tests/test_mine.py  52 tests, no network, no GPU
```

Output rows use the same schema as `eval/pairs.jsonl`, so a mined row can be
promoted into the gate after hand verification with no reshaping. `confidence` is
`machine` for labelled rows and `structural` for negatives, so an audit can always
tell which rows a model touched.
