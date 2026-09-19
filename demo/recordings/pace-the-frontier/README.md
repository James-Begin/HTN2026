# Pace the frontier — saved X source snapshot

This is the offline fallback for the frontend's first example. It contains actual public X embed payloads collected on **2026-09-19 at 01:31 EDT**, not invented tweet records or a recorded production/model run.

## Captured selection

| Source | Post | What the captured text establishes |
|---|---|---|
| roon / @tszzl | [2087370436959186977](https://x.com/tszzl/status/2087370436959186977) | Earlier use of the phrase. Not established as the earliest use or the essay's origin. |
| Dario Amodei | [2098773920774074715](https://x.com/DarioAmodei/status/2098773920774074715) | The author's essay announcement. The public embed truncates the long post. |
| Elon Musk | [2098789109980332057](https://x.com/elonmusk/status/2098789109980332057) | “Dario is right”; the payload quotes Dario's post. Not a concrete evaluator commitment. |
| Sam Altman | [2098811563415150910](https://x.com/sama/status/2098811563415150910) | Quotes Dario and announces independent-evaluator access. Not evidence of implementation. |
| Bernie Sanders | [2098847403134611522](https://x.com/SenSanders/status/2098847403134611522) | The captured excerpt says pacing is not enough. Its unseen tail is not reconstructed. |
| Demis Hassabis | [2098909516582490602](https://x.com/demishassabis/status/2098909516582490602) | Quotes Dario, supports the direction, and references a standards body. Not an embedded-evaluator commitment. |
| Tim Hwang | [2099145338678378958](https://x.com/timhwang/status/2099145338678378958) | Questions evaluator independence, knowledge and funding. No direct reply/quote relationship to Dario is established by the saved payload. |

The [original essay](https://darioamodei.com/post/we-must-pace-the-frontier) was also checked as a primary reference. Its full text is not bundled or substituted for missing tweet text.

## Files and verification

- `snapshot.json`: normalized source text and metadata, per-post capture times, collection limitations, source-discovery references, and raw-payload SHA-256 hashes.
- `raw/<post-id>.json`: original public syndication response bytes, including any quoted-post metadata. These are retained for audit, not requested by the browser at playback time.
- `collect.py`: explicit, bounded source collection through X's public syndication endpoint. No credentials, search API calls, or model calls.
- Frontend adapter: `../../../web/src/frontier-recording.ts`.

The collector checks each returned post ID and author handle, and cross-checks each publication timestamp against its Snowflake ID. Those checks support consistency of the saved records; they do not prove every statement in the posts is true. Hashes allow checking the saved artifacts for changes; they are not a signature from X.

Long-post excerpts are marked using the endpoint's `note_tweet` metadata. Raw post text is displayed unchanged. Likes are captured values, not current values. The frontend's editorial explanations are separate from source text and are explicitly **not model predictions**.

## Timeline scope

The saved selection contains **7 posts**: **1 in August 2026** and **6 in September 2026**. The frontend derives these counts from the source timestamps rather than hardcoding them. They are **counts of saved posts**, NOT X-wide query volume. Other months remain unavailable rather than zero. The selected sample is not exhaustive, representative, or evidence of source independence.

Complete activity measurements would require a separate, budgeted X search/counts collection. There was no `X_BEARER` configured during this collection, and no such measurements were attempted.

## Use the fallback

From the project root:

```bash
cd web
npm run dev
```

Choose **Dario's announcement** or click **Explore an example** with the input empty. The first example is the saved snapshot; the other examples remain explicitly simulated. The original post URL and the exact essay title are also accepted as aliases for this saved example.

Use **Show all**, **Replay**, the timeline, source context dialogs, and **About the data**. Export saves the currently revealed state and capture metadata. Playback timing is illustrative, not captured execution timing.

For a portable backup, build while development dependencies are available:

```bash
cd web
npm run build:offline
```

Copy `web/dist/claimtrace-offline.html` (relative to the project root) somewhere safe. Open that file directly in a browser even if the frontend hosting itself is down. The JavaScript, source snapshot, CSS and fonts are embedded: opening it needs no server, backend, model service, X request, remote image, or installed Node runtime. Clicking external source links still requires internet access. Build/dependency installation is not an offline operation, so prepare the file before the presentation. A later regular build clears `web/dist`; keep a separate presentation copy.

Alternatively, run `npm run preview` from `web` to serve the normal production build locally.

## Refresh deliberately

From the project root:

```bash
python3 demo/recordings/pace-the-frontier/collect.py
```

This makes public network requests and replaces the snapshot and raw captures only after all responses have been fetched and validated. It is not run automatically. Deleted/unavailable posts or changed handles cause collection to fail for manual review rather than being interpreted as evidence of deletion or silently replaced. Rebuild the frontend after a successful refresh. Preserve a copy of the presentation build before refreshing if you need the original captured version.

The public embed endpoint is undocumented and may stop responding. Existing saved assets do not depend on it remaining available.
