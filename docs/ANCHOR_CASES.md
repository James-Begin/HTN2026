# Conversation anchor cases

`tests/fixtures/anchor_cases.json` separates two kinds of anchor resolution:

- **Structural:** follow an explicit quoted-post or reply-parent edge to its root.
- **Semantic:** identify an announcement referenced by text or media when X exposes no
  quote/reply edge.

The Dario, Elon, and Wet Lab IDs are grounded in tracked recordings under
`demo/recordings/`. Compact recorded fixtures also exist for the two required
semantic pairs (`anchor-tomdale.json`, `anchor-drewhahn.json`) so the cinematic
demo can center the original OpenAI announcement without a live X search.
The deep Grok reply chain is grounded in the tracked `sequitor-live.json`
capture. Live syndication on 2026-09-20 confirmed both semantic entries expose
no quote/reply edge, so structural walk alone is not enough.

Recorded `/api/runs` with `mode=recorded` selects a fixture by status id when
one exists, otherwise the Dario capture. Unit tests never use the network.
`scripts/check_anchor_cases.py` is an optional structural-only live diagnostic
and remains off unless `SEQUITOR_LIVE_ANCHOR=1`.
