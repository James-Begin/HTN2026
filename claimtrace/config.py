"""Configuration and hard-won constants.

Every magic number here was measured against the live APIs, not guessed.
See README.md for the provenance of each.
"""
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------- credentials
X_BEARER = os.environ.get("X_BEARER", "")
BASETEN_API_KEY = os.environ.get("BASETEN_API_KEY", "")

# ---------------------------------------------------------------- X API facts
X_API = "https://api.x.com/2"

# Full archive genuinely starts here. Verified: tweet id 20 is 2006-03-21T20:50:14Z.
ARCHIVE_FLOOR = datetime(2006, 3, 21, tzinfo=timezone.utc)

# search/all rejects max_results outside [10, 500]. 1 returns HTTP 400.
SEARCH_MIN_RESULTS = 10
SEARCH_MAX_RESULTS = 500

# end_time cannot be "now" -> HTTP 400. Back it off.
END_TIME_SLACK_MINUTES = 5

# 300 requests / 15 min per app, per the rate-limit docs. Money does not move this.
# Both counts/all and search/all share the 300 figure.
X_RATE_WINDOW_REQUESTS = 300
X_RATE_WINDOW_SECONDS = 900
# Docs contradict themselves on whether 1/sec applies to counts. Assume it does.
X_MIN_REQUEST_INTERVAL = 1.05

# Billing, from the pricing page. Posts are per RESOURCE RETURNED, so a search
# that matches nothing costs nothing. Counts are FLAT per request.
COST_PER_POST_READ = 0.005
COST_PER_COUNTS_ALL = 0.010
COST_PER_COUNTS_RECENT = 0.005

# counts/all paginates at a fixed 31-day wall-clock window regardless of
# granularity, newest page first, paging backwards.
COUNTS_PAGE_DAYS = 31

# Engagement operators: the API wants these names. The web-search names
# min_faves / min_retweets are rejected with HTTP 400.
OP_MIN_LIKES = "min_likes"
OP_MIN_REPOSTS = "min_reposts"

# ------------------------------------------------------------ Baseten facts
BASETEN_INFERENCE = "https://inference.baseten.co/v1"

# Shared hosted models are capped at 120 requests/min (X-Ratelimit-Limit-Requests).
# They are for the few high-quality calls per query, never for bulk.
HOSTED_RPM_LIMIT = 120
HOSTED_SAFE_CONCURRENCY = 8      # measured: 8 is healthy, 64 collapses to 1.4 req/s

# Measured latency, p50, reasoning_effort="none":
#   inkling-small     167ms   TTFT 156ms   158 tok/s   <- best first-token
#   gpt-oss-120b      237ms   TTFT 377ms   227 tok/s   <- best throughput
#   Kimi-K2.7-Code    288ms
#   GLM-5.2-Fast      384ms
#   DeepSeek-V4-Flash 561ms   ** answered our real task WRONG **
#   GLM-5.3-Fast     1256ms   ** slowest despite the name **
MODEL_EXTRACT = "openai/gpt-oss-120b"          # quality + structured output
MODEL_COMPOSE = "thinkingmachines/inkling-small"  # lowest TTFT, user-facing

# reasoning_effort works. chat_template_args={"enable_thinking": False} does NOT.
REASONING_EFFORT = "none"

# Reasoning models still emit a few tokens even at effort=none. Too tight a
# max_tokens returns content=None with finish_reason="length", silently.
MIN_MAX_TOKENS = 64

# Dedicated cross-encoder. Measured on one L4: 88ms p50 for 32 pairs,
# 2851 pairs/sec at concurrency 32 (753/sec at 96, so 32 is the ceiling).
# The fine-tuned 5-class cross-encoder, deployed as a custom Truss.
# `qrpmm003` was the off-the-shelf 1-logit reranker on Baseten's TensorRT engine; it is
# kept as XENC_BASELINE_ID because it is the number the fine-tune is measured against.
XENC_MODEL_ID = os.environ.get("XENC_MODEL_ID", "q9p28o63")
XENC_ROUTE = os.environ.get("XENC_ROUTE", "environments/production/predict")
XENC_URL = os.environ.get(
    "CLAIMTRACE_XENC_URL",
    f"https://model-{XENC_MODEL_ID}.api.baseten.co/{XENC_ROUTE}")
XENC_BASELINE_ID = "qrpmm003"

# Measured on the deployed endpoint, batch 32, real headline text:
#   batch 1   125ms p50      batch 32  160ms p50, 200 pairs/s
#   batch 8   123ms p50      batch 64  237ms p50, 270 pairs/s
# Throughput 181 pairs/s at concurrency 1, rising to 434 at concurrency 16.
# The off-the-shelf 1-logit model on the TensorRT engine did 2,851 pairs/s, so the
# fine-tune costs about 6.6x. That is affordable here: a run scores ~50 pairs, which
# is 0.12s against a 14-66s wall time dominated by X API calls.
XENC_CONCURRENCY = 16
XENC_BATCH = 32
XENC_PAIRS_PER_SEC = 434

# TWO thresholds, not one, because a single cutoff cannot express what this tool needs.
# A false accept is the expensive error: verify mode COUNTS corroborating posts, so
# scoring commentary or a denial as a restatement makes the output assert the opposite of
# the truth. A missed paraphrase only loses a citation, and the "uncertain" band means
# most misses are not even lost, they are shown to a human with a "?" instead of hidden.
#
# THRESHOLDS ARE MODEL-SPECIFIC AND MUST BE RE-DERIVED ON EVERY RETRAIN. Re-labelling the
# training data shifted the whole score scale down once already, and silently broke an
# inherited threshold. Derive from `train/calibrate.py` plus a held-out sample, never
# inherit from a previous checkpoint.
#
# Calibrated 2026-09-17 for `runs/sweep-en/en-m3` (English-only), on 145 combined
# blind-labelled English pairs: the 77-pair in-window holdout plus the 68-pair FRESH
# temporal holdout (days collected strictly after training data ends, so genuinely
# unseen). Not yet the deployed checkpoint; re-derive again before or after deploying it.
#
# What decided ACCEPT: at 0.55, 4 of 58 accepted pairs were false accepts. Read by hand:
#   0.9843  "Charges to be dropped" vs "tell judge why charge should be out" -- DEBATABLE,
#           outcome vs the procedural step that leads to it; defensible either way.
#   0.6594  Kosovo sentencing vs "supporters gather following the verdict" -- REAL miss,
#           a reaction-to-the-verdict report is not the sentencing itself.
#   0.5738  two DIFFERENT AI-risk polls (ecological footprint vs "destroying humanity")
#           -- REAL miss, pattern-matched on generic "poll: Americans worried about AI".
#   0.5576  von der Leyen on drone/sabotage security vs on migrant flows -- REAL miss,
#           same speaker, unrelated policy topics, likely keyed on the named entity alone.
# Raising ACCEPT to 0.70 removes all three real misses and keeps only the debatable one,
# at the cost of moving 16 more pairs from auto-accept into the recoverable uncertain
# band (58 -> 42 accepted; precision 93.1% -> 97.6%). Verified this still clears every
# unlock and regression pair in eval/pairs.jsonl at 0.70.
#
# What decided REJECT: swept 0.02-0.20 against the same 145 pairs. It barely moves; 4
# genuine paraphrases sit at scores no reasonable reject threshold reaches (as low as
# 0.0141), and hand-reading them found 3 of 4 are themselves debatable labels (elaboration
# read as restatement, a market-reaction headline read as the rate-hike claim, a follow-up
# detail read as a restatement) rather than clean model failures. Pushing reject down
# toward that floor to chase them is a bad trade regardless: at reject=0.014, 37 easy
# negatives flood into "uncertain" to rescue only 4 positives, which drowns the band's
# actual purpose -- surfacing genuinely ambiguous pairs for a human, not everything.
# 0.15 is already close to where the curve flattens (0.10 sends 1 negative to uncertain
# to rescue 0 positives), so it is left unchanged.
XENC_ACCEPT = float(os.environ.get("XENC_ACCEPT", "0.70"))   # precision 0.976 on 145 pairs
XENC_REJECT = float(os.environ.get("XENC_REJECT", "0.15"))   # unchanged; already near-flat
XENC_LABELS = ["unrelated", "incidental", "meta", "same_paraphrase", "same_verbatim"]

# ------------------------------------------------------------------- budgets
# Hard ceiling per run, in posts read. The usage meter lags behind reality, so
# local counting is authoritative and this is deliberately conservative.
DEFAULT_POST_BUDGET = 400

# Route thresholds on the 30-day daily curve.
SPIKE_RATIO = 8.0        # peak / median >= this means "something happened"
RECENT_SPIKE_DAYS = 3    # spike inside this window -> verification mode
MIN_TOTAL_FOR_LINEAGE = 25
# Volume strictly before the spike day. Non-zero history means there is a lineage
# to trace. Caught by test: a recency-first rule mis-routed a 16,679-post claim
# Measured: essay TITLE has pre_spike=3 (no history), the PHRASE has 16,664
# (a clear ramp of 4/14/37/76/59). Same event, two queries, two correct routes.
MIN_PRE_SPIKE_FOR_LINEAGE = 5
