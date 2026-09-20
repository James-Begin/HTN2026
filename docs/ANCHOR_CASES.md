# Anchor cases

When the pasted post is commentary, Sequitor tries to center the conversation on a source post.

- **Structural:** follow a quote or reply parent to its root.
- **Semantic:** search for an announcement the text is talking about, when X has no quote/reply edge.

Fixtures live in `tests/fixtures/anchor_cases.json`. Recorded runs (`mode=recorded`) pick a capture by status id, or fall back to the Dario recording. Tests do not hit the network.

`SEQUITOR_LIVE_ANCHOR=1 python3 scripts/check_anchor_cases.py` is an optional live check.
