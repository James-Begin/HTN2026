import os
import json
import requests
import sys

sys.path.insert(0, "/Users/james/Documents/Codex/2026-09-19/re/work/HTN2026")
from eval.dataset import LABELS, LABEL_INDEX, POSITIVE_LABELS

BASETEN_API_KEY = os.environ.get("BASETEN_API_KEY")
if not BASETEN_API_KEY:
    raise RuntimeError("BASETEN_API_KEY must be set in the environment")
BASETEN_URL = "https://api.baseten.co/v1/queries"

# Test cases
test_cases = [
    ("ptf-02", 
     "We Must Pace the Frontier: I've written a new essay on why the AI industry should slow down, with a three-part plan",
     "We Must Pace the Frontier https://t.co/sezx1DnTZn",
     0.261, ">0.5"),
    
    ("ssi-03",
     "ssi are delayed after a catastrophic security incident discovered after seeing what happened with openai, order of magnitude more damage caused.",
     "Safe Superintelligence has pushed back its timeline following a serious breach",
     0.288, ">0.5"),
    
    ("ptf-05",
     "We Must Pace the Frontier: I've written a new essay on why the AI industry should slow down, with a three-part plan",
     "Elon, perhaps the last person I would've thought would agreed that we must pace the frontier",
     0.813, "<0.32"),
    
    ("ssi-05",
     "ssi are delayed after a catastrophic security incident discovered after seeing what happened with openai, order of magnitude more damage caused.",
     "Penalties for SSI are delayed about 12-18 months, but can cost you thousands",
     0.541, "<0.32"),
]

def call_jev(reference, candidate):
    """Call Jev API with structured questions."""
    state = {
        "reference": reference,
        "candidate": candidate
    }
    
    questions = {
        "is_unrelated": {
            "type": "bool",
            "description": "Are these two texts completely unrelated?"
        },
        "is_incidental": {
            "type": "bool", 
            "description": "Are these texts incidental - they share some tokens but express different meanings?"
        },
        "is_meta": {
            "type": "bool",
            "description": "Is the candidate a meta discussion/commentary about the reference?"
        },
        "is_same_paraphrase": {
            "type": "bool",
            "description": "Do these texts express the same claim/meaning but with different words?"
        },
        "is_same_verbatim": {
            "type": "bool",
            "description": "Do these texts express the same claim verbatim (identical or near-identical)?"
        }
    }
    
    payload = {
        "state": state,
        "questions": questions
    }
    
    headers = {
        "Authorization": f"Bearer {BASETEN_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(BASETEN_URL, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error calling Jev: {e}")
        return None

def evaluate_jev():
    """Evaluate Jev on our test cases."""
    print("="*70)
    print("EVALUATING JEV AS RERANKER")
    print("="*70)
    
    results = []
    
    for case_id, ref, cand, baseline, target in test_cases:
        print(f"\n{case_id}:")
        print(f"  Ref: {ref[:80]}...")
        print(f"  Cand: {cand[:80]}...")
        
        response = call_jev(ref, cand)
        
        if response and "data" in response:
            answers = response["data"]["answers"]
            
            # Calculate same_claim probability
            same_paraphrase = answers.get("is_same_paraphrase", {}).get("value", False)
            same_verbatim = answers.get("is_same_verbatim", {}).get("value", False)
            
            # Get probabilities
            same_paraphrase_prob = answers.get("is_same_paraphrase", {}).get("probability", 0)
            same_verbatim_prob = answers.get("is_same_verbatim", {}).get("probability", 0)
            
            same_claim_prob = same_paraphrase_prob + same_verbatim_prob
            
            print(f"  Answers: {answers}")
            print(f"  Same claim probability: {same_claim_prob:.3f}")
            
            improved = (same_claim_prob > baseline) if target == ">0.5" else (same_claim_prob < baseline)
            status = "✓" if improved else "✗"
            
            print(f"  Baseline: {baseline:.3f}, Target: {target}, Status: {status}")
            
            results.append({
                "case_id": case_id,
                "baseline": baseline,
                "jev_prob": same_claim_prob,
                "target": target,
                "improved": improved,
                "answers": answers
            })
    
    print("\n" + "="*70)
    improved_count = sum(1 for r in results if r["improved"])
    print(f"JEV Results: {improved_count}/{len(test_cases)} improved")
    print("="*70)
    
    return results

if __name__ == "__main__":
    evaluate_jev()
