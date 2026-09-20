"""Conversation seed resolution without provider calls."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sequitor_server import Sequitor, recording_for_seed  # noqa: E402


TOMDALE = "2098435855857668156"
NAVIER = "2097374640582668336"
DREW = "2085392809385988130"
HF = "2079658951264920020"
ELON = "2098789109980332057"
DARIO = "2098773920774074715"


def post(tweet_id, text, quoted=None, parent=None, published="2026-09-08T17:00:00Z"):
    return {
        "id": tweet_id, "text": text, "publishedAt": published,
        "author": "x", "handle": "x", "quotedPostId": quoted, "parentId": parent,
    }


class TestRecordingForSeed(unittest.TestCase):
    def test_tomdale_fixture_anchors_on_openai(self):
        recorded = recording_for_seed(f"https://x.com/tomdale/status/{TOMDALE}")
        self.assertEqual(recorded["seedPost"]["id"], NAVIER)
        self.assertEqual(recorded["entryPost"]["id"], TOMDALE)
        self.assertEqual(recorded["anchorMethod"], "semantic")

    def test_drewhahn_fixture_anchors_on_huggingface_incident(self):
        recorded = recording_for_seed(f"https://x.com/drewhahn/status/{DREW}")
        self.assertEqual(recorded["seedPost"]["id"], HF)
        self.assertEqual(recorded["entryPost"]["id"], DREW)

    def test_elon_fixture_walks_to_dario(self):
        recorded = recording_for_seed(f"https://x.com/elonmusk/status/{ELON}")
        self.assertEqual(recorded["seedPost"]["id"], DARIO)
        self.assertEqual(recorded["entryPost"]["quotedPostId"], DARIO)

    def test_unknown_recorded_seed_uses_dario_demo(self):
        recorded = recording_for_seed("https://x.com/DarioAmodei/status/" + DARIO)
        self.assertEqual(recorded["seedPost"]["id"], DARIO)


class TestResolveConversationSeed(unittest.TestCase):
    def setUp(self):
        self.app = Sequitor()

    def test_quote_walk_skips_semantic_search(self):
        elon = post(ELON, "Dario is right", quoted=DARIO)
        dario = post(DARIO, "We Must Pace the Frontier")
        posts = {ELON: elon, DARIO: dario}
        self.app.fetch_anchor_post = lambda tweet_id: posts.get(tweet_id)
        self.app.openai_plan = lambda text: (_ for _ in ()).throw(AssertionError("quote walk should plan from the anchor"))
        # After the walk, openai_plan is called on Dario's text.
        planned = []

        def plan(text):
            planned.append(text)
            return {"planVersion": 5, "contextLabel": "pacing", "entities": ["Anthropic"],
                    "angles": [], "uncertainties": [], "volumePhrase": '"We Must Pace"',
                    "discoveryPhrase": None, "discoveryQueries": [], "expansionQueries": [],
                    "whyDiscovery": "", "referencedPostId": "", "isCommentary": False,
                    "anchorRationale": "", "model": "test"}

        self.app.openai_plan = plan
        result = self.app.resolve_conversation_seed(f"https://x.com/elonmusk/status/{ELON}")
        self.assertEqual(result["seed_post"]["id"], DARIO)
        self.assertEqual(result["entry_post"]["id"], ELON)
        self.assertEqual(result["anchor_method"], "quote-walk")
        self.assertTrue(any("Pace the Frontier" in text for text in planned))

    def test_tomdale_semantic_uses_verified_candidate(self):
        commentary = post(TOMDALE, "After 88 hours and ~10,000 coordinating agents, we're sharing a solution.")
        announcement = post(NAVIER, "We're sharing a solution to the Navier-Stokes Millennium Prize Problem.")
        self.app.fetch_anchor_post = lambda tweet_id: commentary if tweet_id == TOMDALE else (
            announcement if tweet_id == NAVIER else None)

        def plan(text):
            if "88 hours" in text:
                return {"planVersion": 5, "contextLabel": "agent math commentary",
                        "entities": ["OpenAI", "Navier-Stokes"], "angles": [], "uncertainties": [],
                        "volumePhrase": '"coordinating agents"', "discoveryPhrase": "Navier Stokes",
                        "discoveryQueries": ["Navier Stokes"], "expansionQueries": [],
                        "whyDiscovery": "", "referencedPostId": "", "isCommentary": True,
                        "anchorRationale": "paraphrase of the announcement", "model": "test"}
            return {"planVersion": 5, "contextLabel": "Navier-Stokes announcement",
                    "entities": ["OpenAI"], "angles": [], "uncertainties": [],
                    "volumePhrase": '"Navier-Stokes"', "discoveryPhrase": None,
                    "discoveryQueries": [], "expansionQueries": [], "whyDiscovery": "",
                    "referencedPostId": NAVIER, "isCommentary": True,
                    "anchorRationale": "original announcement", "model": "test"}

        self.app.openai_plan = plan
        self.app.semantic_anchor_candidates = lambda entry, _plan: [announcement]
        self.app.select_semantic_anchor = lambda entry, candidates: candidates[0]
        result = self.app.resolve_conversation_seed(f"https://x.com/tomdale/status/{TOMDALE}")
        self.assertEqual(result["seed_post"]["id"], NAVIER)
        self.assertEqual(result["entry_post"]["id"], TOMDALE)
        self.assertEqual(result["anchor_method"], "semantic")

    def test_drewhahn_semantic_uses_verified_candidate(self):
        commentary = post(DREW, "the agent is working in the sandbox meanwhile the agent")
        announcement = post(HF, "We're partnering with Hugging Face to investigate a security incident.")
        self.app.fetch_anchor_post = lambda tweet_id: commentary if tweet_id == DREW else (
            announcement if tweet_id == HF else None)
        self.app.openai_plan = lambda text: {
            "planVersion": 5, "contextLabel": "sandbox incident",
            "entities": ["OpenAI", "Hugging Face"], "angles": [], "uncertainties": [],
            "volumePhrase": '"the sandbox"', "discoveryPhrase": "Hugging Face",
            "discoveryQueries": ["Hugging Face"], "expansionQueries": [],
            "whyDiscovery": "", "referencedPostId": "", "isCommentary": True,
            "anchorRationale": "video riff on the incident", "model": "test",
        } if "sandbox" in text else {
            "planVersion": 5, "contextLabel": "Hugging Face incident",
            "entities": ["OpenAI"], "angles": [], "uncertainties": [],
            "volumePhrase": '"Hugging Face"', "discoveryPhrase": None,
            "discoveryQueries": [], "expansionQueries": [], "whyDiscovery": "",
            "referencedPostId": HF, "isCommentary": True, "anchorRationale": "", "model": "test",
        }
        self.app.semantic_anchor_candidates = lambda entry, _plan: [announcement]
        self.app.select_semantic_anchor = lambda entry, candidates: candidates[0]
        result = self.app.resolve_conversation_seed(f"https://x.com/drewhahn/status/{DREW}")
        self.assertEqual(result["seed_post"]["id"], HF)
        self.assertEqual(result["anchor_method"], "semantic")


if __name__ == "__main__":
    unittest.main()
