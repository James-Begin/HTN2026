import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sequitor_anchor import (choose_semantic_anchor, conversation_anchor,  # noqa: E402
                             tweet_id_from_url)


class TestConversationAnchor(unittest.TestCase):
    def test_quote_walk_prefers_referenced_conversation(self):
        # Example shape: tomdale/2098435855857668156 quotes
        # OpenAI/2097374640582668336. The ids are data, never code branches.
        entry = {"id": "2098435855857668156",
                 "quotedPostId": "2097374640582668336",
                 "parentId": "2098000000000000000"}
        quoted = {"id": "2097374640582668336", "text": "original announcement"}
        parent = {"id": "2098000000000000000", "text": "unrelated parent"}
        posts = {post["id"]: post for post in (quoted, parent)}

        result = conversation_anchor(entry, posts.get)

        self.assertIs(result["entry"], entry)
        self.assertIs(result["anchor"], quoted)
        self.assertEqual(result["hops"], 1)
        self.assertEqual(result["method"], "quote-walk")

    def test_reply_walk_reaches_root(self):
        root = {"id": "2097000000000000000"}
        parent = {"id": "2098000000000000000", "parentId": root["id"]}
        entry = {"id": "2099000000000000000", "parentId": parent["id"]}
        posts = {post["id"]: post for post in (root, parent)}

        result = conversation_anchor(entry, posts.get)

        self.assertIs(result["anchor"], root)
        self.assertEqual(result["hops"], 2)
        self.assertEqual(result["method"], "reply-walk")

    def test_cycle_stops_without_refetching_entry(self):
        entry = {"id": "2099000000000000000", "quotedPostId": "2098000000000000000"}
        quoted = {"id": "2098000000000000000", "parentId": entry["id"]}
        fetched = []

        result = conversation_anchor(entry, lambda post_id: fetched.append(post_id) or quoted)

        self.assertIs(result["anchor"], quoted)
        self.assertEqual(result["hops"], 1)
        self.assertEqual(fetched, [quoted["id"]])

    def test_missing_fetch_keeps_last_verified_post(self):
        entry = {"id": "2099000000000000000", "quotedPostId": "2098000000000000000"}

        result = conversation_anchor(entry, lambda _post_id: None)

        self.assertIs(result["anchor"], entry)
        self.assertEqual(result["hops"], 0)
        self.assertEqual(result["method"], "self")


class TestSemanticAnchor(unittest.TestCase):
    def test_verified_semantic_id_is_accepted(self):
        # Example shape: drewhahn/2085392809385988130 describes the incident
        # announced at OpenAI/2079658951264920020.
        entry = {"id": "2085392809385988130"}
        original = {"id": "2079658951264920020", "text": "incident announcement"}

        chosen = choose_semantic_anchor(
            entry, {"referenced_post_id": original["id"]},
            lambda post_id: original if post_id == original["id"] else None,
        )

        self.assertIs(chosen, original)

    def test_semantic_id_is_rejected_when_fetch_fails(self):
        entry = {"id": "2085392809385988130"}

        chosen = choose_semantic_anchor(
            entry, {"referenced_post_id": "2079658951264920020"}, lambda _post_id: None,
        )

        self.assertIs(chosen, entry)

    def test_malformed_semantic_id_is_rejected_without_fetch(self):
        entry = {"id": "2085392809385988130"}
        fetched = []

        chosen = choose_semantic_anchor(
            entry, {"referenced_post_id": "not-a-status-id"},
            lambda post_id: fetched.append(post_id),
        )

        self.assertIs(chosen, entry)
        self.assertEqual(fetched, [])

    def test_verified_status_url_is_accepted(self):
        entry = {"id": "2085392809385988130"}
        original = {"id": "2079658951264920020"}
        suggestion = {"referenced_url": "https://x.com/OpenAI/status/2079658951264920020?s=20"}

        self.assertEqual(tweet_id_from_url(suggestion["referenced_url"]), original["id"])
        self.assertIs(choose_semantic_anchor(entry, suggestion, lambda _post_id: original), original)


if __name__ == "__main__":
    unittest.main()
