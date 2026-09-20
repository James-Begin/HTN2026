# OpenJev LoRA adapter

LoRA adapter on [AlexWortega/openjev](https://huggingface.co/AlexWortega/openjev) for same-claim scoring.

Weights are not in git (`*.safetensors`). Tokenizer files are omitted too; load them from the base model when you serve this.

Training code: `train/`. Serving helper: `sequitor_openjev.py`.
