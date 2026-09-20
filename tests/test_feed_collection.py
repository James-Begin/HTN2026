"""Bounded 500-post feed collection without provider calls."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sequitor_server as server  # noqa: E402
from sequitor_server import Sequitor, cap_feed, recording_for_seed  # noqa: E402


ELON = "2098789109980332057"
DARIO = "2098773920774074715"


def x_row(tweet_id, text="hello world"):
    return {
        "id": str(tweet_id),
        "text": text,
        "created_at": "2026-09-08T17:00:00.000Z",
        "author_id": "1",
        "public_metrics": {"like_count": 1, "retweet_count": 0, "reply_count": 0},
        "referenced_tweets": [],
        "conversation_id": str(tweet_id),
        "sequitor_author": {"username": "x", "name": "X", "profile_image_url": ""},
    }


class PagingX:
    def __init__(self, pages):
        self.pages = pages
        self.posts_read = 0
        self.calls = []
        self.spend = 0

    def search(self, query, start, end, max_results=10, token=None):
        self.calls.append({"max_results": max_results, "token": token, "query": query})
        rows, nxt = self.pages[token]
        taken = rows[:max_results]
        self.posts_read += len(taken)
        return taken, nxt if len(taken) == len(rows) else "more"


class TestCapFeed(unittest.TestCase):
    def test_pins_seed_and_entry_then_highest_likes(self):
        seed = {"id": "s", "likes": 1, "publishedAt": "2026-09-08T00:00:00Z"}
        entry = {"id": "e", "likes": 2, "publishedAt": "2026-09-08T01:00:00Z"}
        posts = [
            {"id": "a", "likes": 9, "publishedAt": "2026-09-08T02:00:00Z"},
            {"id": "b", "likes": 8, "publishedAt": "2026-09-08T03:00:00Z"},
            {"id": "c", "likes": 7, "publishedAt": "2026-09-08T04:00:00Z"},
            seed,
        ]
        capped = cap_feed(posts, seed, entry, limit=3)
        self.assertEqual([post["id"] for post in capped], ["s", "e", "a"])

    def test_feed_target_is_five_hundred(self):
        self.assertEqual(server.FEED_TARGET, 500)
        self.assertEqual(server.PERIOD_SCHEMA, 6)
        self.assertEqual(server.ANCHOR_VERSION, 2)


class TestSearchPagination(unittest.TestCase):
    def setUp(self):
        self.app = Sequitor()
        self.app.save = lambda: None

    def test_search_walks_next_token_until_limit(self):
        pages = {
            None: ([x_row(i) for i in range(100)], "tok1"),
            "tok1": ([x_row(i) for i in range(100, 200)], "tok2"),
            "tok2": ([x_row(i) for i in range(200, 250)], None),
        }
        self.app.x = PagingX(pages)
        posts, truncated = self.app.search('"hello world"', "2026-09-08", limit=250)
        self.assertEqual(len(posts), 250)
        self.assertFalse(truncated)
        self.assertEqual(len(self.app.x.calls), 3)
        self.assertEqual(self.app.x.calls[0]["max_results"], 250)
        self.assertEqual(self.app.x.calls[1]["token"], "tok1")

    def test_search_stops_at_limit_even_when_more_pages_exist(self):
        pages = {
            None: ([x_row(i) for i in range(100)], "tok1"),
            "tok1": ([x_row(i) for i in range(100, 200)], "tok2"),
        }
        self.app.x = PagingX(pages)
        posts, truncated = self.app.search('"hello world"', "2026-09-08", limit=120)
        self.assertEqual(len(posts), 120)
        self.assertTrue(truncated)
        self.assertEqual(len(self.app.x.calls), 2)


class TestElonRecordingDensity(unittest.TestCase):
    def test_elon_fixture_reuses_dario_conversation(self):
        recorded = recording_for_seed(f"https://x.com/elonmusk/status/{ELON}")
        self.assertEqual(recorded["seedPost"]["id"], DARIO)
        self.assertEqual(recorded["entryPost"]["id"], ELON)
        self.assertGreaterEqual(len(recorded["posts"]), 200)


if __name__ == "__main__":
    unittest.main()
