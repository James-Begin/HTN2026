# Sequitor: morning handoff

**Updated September 19, 2026.** This repository now contains a working, one-URL local demo, a [public recorded demo](https://james-begin.github.io/HTN2026/), and an offline fallback. The new browser app is Sequitor; the older Claimtrace research code remains in the repository. No Devpost submission has been made.

## What works

- `python3 sequitor_server.py` serves the built browser app and a small API at `http://127.0.0.1:8765`.
- A post URL or topic starts a bounded investigation. Direct OpenAI Responses API usage turns the seed into a measured exact phrase and a separate related-search query. X supplies daily counts and real source posts. A Baseten hosted model curates a few reactions for exploration.
- The default Dario Amodei run is cached: ten daily count buckets and eight days with retrieved posts, September 12–19. The peak measured phrase count is 9,571 on September 12. The default day includes 198 distinct retrieved candidate posts. These are not an exhaustive platform-wide corpus or definitive top-ten ranking.
- The browser supports day selection, captured-like and recency sorting, real authors and handles, post source links, recorded quote/reply references, a context drawer, and a data-scope drawer. It displays a small selected subset of model-curated offshoots. It does not present model suggestions as proof of influence or truth.
- `demo/recordings/sequitor-live.json` records real X counts and source posts for all populated saved days. `cd web && npm run build:offline` packages that run into `web/dist/sequitor-offline.html`, which needs no local server to display saved data.
- `npm ci` now works from the public npm registry. The local `.env` is ignored and is used only by the Python server; browser assets and the recorded run contain no provider keys.

## Run it

```bash
cd web && npm ci && npm run build
cd .. && python3 sequitor_server.py
```

Open `http://127.0.0.1:8765`. The saved run loads automatically. For the live-path demo, paste a post URL or topic and press **Explore live**. The default seed is cached, so exploring it again costs no additional X retrieval. Day switches within the saved run also reuse cached results. If the venue network is unreliable, use the saved view and keep a copy of `web/dist/sequitor-offline.html` on the presentation machine.

The production local URL was checked in a browser, including day switching and quote context. The offline HTML built successfully and contains the recorded data, but this assistant's browser session declined to open local `file://` pages; open that copy once in your ordinary browser before relying on it at the venue.

## Provider and data limits

The X server budget is hard-capped at 600 returned posts and 20 counts calls, an estimated $3.20 maximum using this repository's measured prices. The saved demo used 539 returned posts and one counts call: **$2.705 estimated X spend** in its ledger, plus approximately $0.03 of earlier exploratory count probes outside that ledger. The X account's own meter may lag. The remaining budget is intentionally small; do not clear `work/sequitor-cache.json` before judging because it stores both the results and the spend counters. A new seed can make paid calls; use one only when necessary.

The previously documented dedicated Baseten cross-encoder endpoint `q9p28o63` returned 404 with the supplied demo key, and the checkpoint is absent from this checkout. The current integration uses Baseten-hosted `openai/gpt-oss-120b` for curation. Describe it as hosted curation, not as the fine-tuned cross-encoder. OpenAI's separate direct API is used for discovery planning. The histogram measures one exact phrase; separately labelled related posts can appear in the feed without being included in those bars. The feed's “Popular” view ranks only retrieved candidates by likes captured at retrieval time. Search pagination and spend limits prevent a platform-wide top-ten claim.

## Deadline-critical work

1. **Before Saturday September 19 at 2:00 PM EDT:** create and actually submit the initial Devpost project; add the final team membership and exact badge ID; select **both OpenAI and Baseten sponsor prizes**. The event rules gathered during planning say these are locked at that time. Verify the live [official rules](https://hackthenorth2026.devpost.com/rules) in your logged-in event view before relying on this handoff. A saved draft is not the initial submission.
2. **Before Sunday September 20 at 8:00 AM EDT:** finish the Devpost page, screenshots/video, and final source link. Test the three-minute live presentation once with the cached default run and once with the offline backup. Bring your own power and local file copy.
3. Event rules from the planning review say code and design assets for the submission must be created during the hacking window and that a model may not be trained in advance. This repository includes pre-existing research and prototype code. State clearly what Sequitor-specific work was created during the event and check with organizers how to disclose or separate the older work. Do not present the old checkpoint or old benchmarks as new hackathon work.

## Suggested presentation

Open the default conversation; point to the 9,571 measured phrase mentions on September 12, then select an adjacent day and read a genuine disagreement or joke. Open its source or recorded context. Explain that OpenAI expands discovery beyond the literal phrase, Baseten curates a few retrieved reactions, and the UI preserves the actual posts. Close with the boundary that the chart is phrase-specific while the feed is a budgeted sample. Aim to complete the prepared path in three minutes to leave room in a five-minute judging slot.

## Remaining opportunities

The highest-value improvement is a short, clear demo video and a polished Devpost page. Use the public recorded URL for sponsor reviewers and the local server for a live provider demonstration. If there is extra time after submission, test one genuinely new seed and add richer quote/reply traversal, under the remaining X cap. Do not spend the morning retraining the unavailable cross-encoder or building new product surfaces.
