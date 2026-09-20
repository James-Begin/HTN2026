# Baseten H100 Training Blockers and Launch Runbook

Updated: 2026-09-19 22:34 UTC

## Current blockers

Both provided Baseten API keys authenticate to the same sole team:

- Team: `htn2026`
- Team ID: `3yrgklq`

Training submission reaches Baseten but returns:

```text
HTTP 403: You are not authorized for Baseten training.
POST https://api.baseten.co/v1/teams/3yrgklq/training_projects
```

A custom OpenJev L4 deployment reaches Baseten but returns:

```text
You must add a payment method to deploy models.
```

Hosted Model APIs are enabled and working. They were successfully used for teacher
data generation and a GPT-OSS-120B baseline.

## Required account changes

In the Baseten workspace for team `htn2026`:

1. Enable **Training Jobs** access for the team/API key.
2. Add a payment method if custom model deployment is also desired.

Training is the only required change for the prepared H100 job. A payment method is
needed only for the optional standalone Jev endpoint.

## Prepared H100 job

Directory: `baseten_remote/`

The upload is about 15 MB and deliberately excludes all local checkpoints and the
`runs/` directory. It requests:

- 1x H100
- 64 GiB host RAM
- 30 GiB checkpoint volume
- Scale: one sequential job
- CUDA-only guard (will refuse CPU fallback)

Work performed remotely:

1. Evaluate `AlexWortega/openjev/qwen3.5-4b-nli-v2` bidirectionally.
2. Release Jev GPU memory.
3. Fine-tune `BAAI/bge-reranker-base` for three epochs.
4. Mine the top 512 false-positive negatives after each epoch and oversample them in
   the next epoch.
5. Select the BGE checkpoint using day-held-out validation ROC AUC.
6. Evaluate the selected checkpoint once on all 25 hand-labeled release pairs.
7. Persist Jev, BGE, and comparison JSON plus deployable BGE weights.

Training input:

- 7,491 real English rows before split.
- 84 teacher-reviewed real rows replace noisy original labels.
- 431 synthetic adversarial rows.
- 70 deterministic title/URL and typo-correction positives.
- 994 clean validation rows after dropping 49 URI-leaking candidates.
- Zero post-URI overlap between train and validation.
- The hand-labeled eval set is not used for training or checkpoint selection.

## Submit after Training access is enabled

The current Truss install is isolated under `/tmp/btctl`; recreate it if the machine
has restarted:

```bash
python3 -m venv /tmp/btctl
/tmp/btctl/bin/pip install 'truss==0.18.30'
```

Authenticate without printing the key:

```bash
/tmp/btctl/bin/truss --non-interactive login \
  --api-key "$BASETEN_API_KEY" --remote baseten
```

Submit:

```bash
cd /Users/james/Documents/Codex/2026-09-19/re/work/HTN2026/baseten_remote
/tmp/btctl/bin/truss --non-interactive train push config.py \
  --remote baseten \
  --job-name sequitor-jev-bge-compare
```

The command prints the training job ID. Monitor with:

```bash
/tmp/btctl/bin/truss train view --remote baseten --non-interactive
/tmp/btctl/bin/truss train logs --remote baseten --job-id <JOB_ID>
/tmp/btctl/bin/truss train metrics --remote baseten --job-id <JOB_ID>
```

## Optional Jev endpoint

Directory: `baseten_jev/`

This is an L4 deployment, not H100, to minimize cost. It loads the public OpenJev 4B
checkpoint through BDN and returns forward/reverse NLI probabilities plus symmetric
`same_claim` probability.

After adding a payment method:

```bash
cd /Users/james/Documents/Codex/2026-09-19/re/work/HTN2026/baseten_jev
/tmp/btctl/bin/truss --non-interactive push . \
  --remote baseten \
  --model-name sequitor-openjev \
  --deployment-name jev-baseline \
  --no-wait --output json
```

## Results available now

`runs/baseten-gpt-oss-120b-baseline.json`:

- ROC AUC: 0.9026
- F1 at 0.5: 0.80
- `ssi-03`: 0.72 (passes)
- `ssi-05`: 0.02 (passes)
- `ptf-05`: 0.05 (passes)
- `ptf-02`: 0.15 (fails)

Known local BGE epoch-1 target scores (not reloaded locally):

- `ptf-02`: 0.905 (passes)
- `ssi-03`: 0.036 (fails)
- `ptf-05`: 0.026 (passes)
- `ssi-05`: 0.825 (fails)

The models have complementary errors, supporting the targeted hard-negative and
low-overlap training design in the prepared H100 job.
