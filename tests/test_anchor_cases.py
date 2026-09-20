import asyncio
import importlib
import inspect
import json
import re
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "anchor_cases.json"
STATUS_ID = re.compile(r"/status/(\d+)(?:[/?#]|$)")


def load_cases():
    with FIXTURE.open(encoding="utf-8") as handle:
        return json.load(handle)


def fixture_walk(entry_id, posts):
    """Reference structural walk: quotes take precedence, then reply parents."""
    current_id = entry_id
    seen = set()
    while current_id not in seen:
        seen.add(current_id)
        post = posts[current_id]
        next_id = post.get("quotedPostId") or post.get("parentId")
        if not next_id:
            return current_id
        current_id = next_id
    raise AssertionError(f"cycle in fixture graph at {current_id}")


def import_anchor_module():
    try:
        return importlib.import_module("sequitor_anchor.conversation_anchor")
    except ImportError:
        try:
            package = importlib.import_module("sequitor_anchor")
        except ImportError:
            return None
        return getattr(package, "conversation_anchor", None)


def find_resolver(module):
    if callable(module):
        return module
    for name in (
        "resolve_conversation_anchor",
        "resolve_anchor",
        "find_conversation_anchor",
        "conversation_anchor",
        "walk_to_anchor",
    ):
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    raise AssertionError("conversation-anchor module has no recognized resolver")


def invoke_resolver(resolver, entry_id, posts):
    """Adapt the fixture mock to common resolver argument names."""
    def fetch_post(post_id):
        if isinstance(post_id, dict):
            post_id = post_id["id"]
        match = STATUS_ID.search(str(post_id))
        key = match.group(1) if match else str(post_id)
        return posts.get(key)

    values = {
        "entry_id": entry_id,
        "entryId": entry_id,
        "post_id": entry_id,
        "postId": entry_id,
        "tweet_id": entry_id,
        "tweetId": entry_id,
        "entry_post": posts[entry_id],
        "post": posts[entry_id],
        "fetch_post": fetch_post,
        "get_post": fetch_post,
        "post_fetcher": fetch_post,
        "fetcher": fetch_post,
        "fetch": fetch_post,
    }
    signature = inspect.signature(resolver)
    kwargs = {
        name: values[name]
        for name, parameter in signature.parameters.items()
        if name in values
        and parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    missing = [
        name
        for name, parameter in signature.parameters.items()
        if parameter.default is inspect.Parameter.empty
        and parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        and name not in kwargs
    ]
    if missing:
        # The conventional minimal contract is resolver(entry_id, fetch_post).
        result = resolver(entry_id, fetch_post)
    else:
        result = resolver(**kwargs)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result


def result_id(result):
    if isinstance(result, str):
        match = STATUS_ID.search(result)
        return match.group(1) if match else result
    if isinstance(result, dict):
        for key in ("anchorId", "anchor_id", "expectedAnchorId", "id"):
            if result.get(key):
                return str(result[key])
        for key in ("anchor", "post"):
            if isinstance(result.get(key), dict) and result[key].get("id"):
                return str(result[key]["id"])
    for key in ("anchor_id", "anchorId", "id"):
        value = getattr(result, key, None)
        if value:
            return str(value)
    raise AssertionError(f"cannot extract anchor id from resolver result: {result!r}")


class AnchorCaseFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()

    def test_fixture_has_unique_well_formed_cases(self):
        self.assertGreaterEqual(len(self.cases), 5)
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertIn(
                    case["kind"],
                    {"quote", "reply", "semantic-reference", "self"},
                )
                self.assertIsInstance(case["live"], bool)
                self.assertTrue(case["notes"])

    def test_ids_match_status_urls(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                entry_match = STATUS_ID.search(case["entryUrl"])
                anchor_match = STATUS_ID.search(case["expectedAnchorUrl"])
                self.assertIsNotNone(entry_match)
                self.assertIsNotNone(anchor_match)
                self.assertEqual(entry_match.group(1), case["entryId"])
                self.assertEqual(anchor_match.group(1), case["expectedAnchorId"])

    def test_semantic_references_are_not_self_anchors(self):
        semantic_cases = [
            case for case in self.cases if case["kind"] == "semantic-reference"
        ]
        self.assertTrue(semantic_cases)
        for case in semantic_cases:
            with self.subTest(case=case["id"]):
                self.assertNotIn("graph", case)
                self.assertNotEqual(case["entryId"], case["expectedAnchorId"])

    def test_fixture_graphs_walk_to_expected_anchor(self):
        graph_cases = [case for case in self.cases if "graph" in case]
        self.assertTrue(graph_cases)
        for case in graph_cases:
            with self.subTest(case=case["id"]):
                posts = case["graph"]["posts"]
                self.assertIn(case["entryId"], posts)
                self.assertIn(case["expectedAnchorId"], posts)
                self.assertEqual(
                    fixture_walk(case["entryId"], posts),
                    case["expectedAnchorId"],
                )


ANCHOR_MODULE = import_anchor_module()


@unittest.skipIf(
    ANCHOR_MODULE is None,
    "sequitor_anchor.conversation_anchor is not importable",
)
class ConversationAnchorContractTests(unittest.TestCase):
    def test_mocked_structural_walks(self):
        resolver = find_resolver(ANCHOR_MODULE)
        for case in load_cases():
            if case["kind"] not in {"quote", "reply", "self"}:
                continue
            with self.subTest(case=case["id"]):
                posts = case["graph"]["posts"]
                resolved = invoke_resolver(resolver, case["entryId"], posts)
                self.assertEqual(result_id(resolved), case["expectedAnchorId"])


if __name__ == "__main__":
    unittest.main()
