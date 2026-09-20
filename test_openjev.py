"""
Test openjev as a reranker baseline
"""
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

print('Loading openjev model from HuggingFace...')
tokenizer = AutoTokenizer.from_pretrained('AlexWortega/openjev')
model = AutoModelForSequenceClassification.from_pretrained('AlexWortega/openjev')

print(f'Model loaded. Labels: {model.config.id2label}')
print(f'Num labels: {model.config.num_labels}')

# Test on failure cases
test_cases = [
    ('ptf-02', 
     "We Must Pace the Frontier: I've written a new essay on why the AI industry should slow down, with a three-part plan",
     'We Must Pace the Frontier https://t.co/sezx1DnTZn'),
    
    ('ssi-03',
     'ssi are delayed after a catastrophic security incident discovered after seeing what happened with openai, order of magnitude more damage caused.',
     'Safe Superintelligence has pushed back its timeline following a serious breach'),
    
    ('ptf-05',
     "We Must Pace the Frontier: I've written a new essay on why the AI industry should slow down, with a three-part plan",
     'Elon, perhaps the last person I would\'ve thought would agreed that we must pace the frontier'),
    
    ('ssi-05',
     'ssi are delayed after a catastrophic security incident discovered after seeing what happened with openai, order of magnitude more damage caused.',
     'Penalties for SSI are delayed about 12-18 months, but can cost you thousands'),
]

model.eval()
print('\nTesting on failure cases...')

for case_id, ref, cand in test_cases:
    inputs = tokenizer(ref, cand, return_tensors='pt', padding=True, truncation=True, max_length=256)
    with torch.no_grad():
        outputs = model(**inputs)
        probs = torch.softmax(outputs.logits, dim=-1)
    
    print(f'\n{case_id}:')
    for i, label in model.config.id2label.items():
        print(f'  {label}: {probs[0, i].item():.3f}')
