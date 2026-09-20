# CLI demo cases

Claimtrace CLI cases in `demo/cases.jsonl`. Saved Sequitor UI captures are under `demo/recordings/`.

```bash
python3 cli.py --url https://x.com/i/status/869766994899468288
```

| # | Mode | Notes |
| --- | --- | --- |
| 1 | verify | Mostly retweets of one original |
| 2 | lineage | Phrase history vs the essay title |
| 3 | resolve | Deleted root next to a live follow-up (free, keyless) |
| 4 | lineage | First tweet, id 20 |
| 5 | lineage | Typo as fingerprint |
| 6 | resolve | Claim is in an image; CLI refuses (free) |
| 7 | resolve | Identity is `author_id`, not the handle (free) |
| 8 | judge-only | A denial is not corroboration |

Cases 3, 6, and 7 do not use the paid X search API.
