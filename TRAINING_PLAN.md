# Hack the North 2026 - Reranker Model Training Plan

## Current Status
- Dataset: 18,948 pairs from mine-out-data.zip
- Eval set: 25 hand-labelled pairs (release gate)
- Best checkpoint: runs/xenc-best (missing from checkout)
- Issue: Dedicated Baseten endpoint q9p28o63 returns 404

## Known Failure Modes (from eval set)
1. **ptf-03 (Arabic restatement)**: 0.012 → needs >0.5
2. **ssi-03 (English paraphrase)**: 0.288 → needs >0.5  
3. **ptf-02 (title+link)**: 0.261 → needs >0.5
4. **ptf-05 (false accept)**: 0.813 → needs <0.32 (abstain band)
5. **ssi-05 (acronym collision)**: 0.034 → spiked to 0.541, needs <0.32

## Creative H100 Training Strategy (English-Only)

### Phase 0: Targeted Data Preparation
- **Extract English-only training data**: ~12,000 rows (from 18,948 total)
- **Generate targeted adversarial examples**:
  1. **Title+link pairs** (address ptf-02)
  2. **Acronym collisions** (address ssi-05) 
  3. **False positives** (address ptf-05 - commentary about reactions)
  4. **Low-overlap paraphrases** (address ssi-03)
  5. **Short vs long form** (address all length asymmetry issues)
- **Hard negative mining**: Find semantically similar but different claims

### Phase 1: H100 Training (Baseten)
- Use H100 80GB for faster iteration
- Creative techniques:
  1. **Curriculum Learning**: Start with easy pairs, progress to hard negatives
  2. **Hard Negative Mining**: Actively find and train on model mistakes
  3. **Mixout Regularization**: Better than dropout for transformers
  4. **Meta-label Smoothing**: Dynamic smoothing based on confidence
  5. **Temperature Annealing**: Start low (sharp), end high (smooth)
  6. **Contrastive Loss**: Explicitly push same/non-same apart
  7. **Focal Loss**: Focus on hard examples
  8. **Label Refinement**: Use model to re-label uncertain training data

### Phase 2: Ensemble & Distillation
- Train multiple seeds/checkpoints
- Distill knowledge to single deployable model
- Calibrate threshold on held-out data

### Phase 3: Baseten Deployment
- Deploy as dedicated cross-encoder on L4
- Target: 2,851 pairs/sec throughput
- Verify with eval set before submission

## Immediate Next Steps (Next 2 Hours)

1. **Prepare augmented training data** targeting failure cases
2. **Create H100 training script** with all creative techniques  
3. **Run quick local sanity check** (CPU, small batch)
4. **Package for Baseten submission**
5. **Monitor training** and iterate based on validation

## Success Criteria
- All 5 failure cases move to correct side of threshold
- ROC AUC > 0.95 on eval set
- Separation margin > 0 (robust)
- Deployable to Baseten with <5 min cold start