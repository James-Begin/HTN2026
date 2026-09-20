"""Comprehensive Latency, Throughput & Memory Benchmark across Reranker Architectures.

Measures:
1. Cold start model load time into VRAM.
2. Single-pair interactive latency (Batch size = 1): P50, P90, P95, P99, Mean, Std (over 100 requests).
3. Batched serving throughput & latency across batch sizes [1, 4, 8, 16, 32, 64, 128].
4. Peak VRAM utilization during inference.
"""
import gc
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import torch
from peft import PeftModel
from transformers import AutoModelForSequenceClassification, AutoTokenizer

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

LABELS = ["unrelated", "incidental", "meta", "same_paraphrase", "same_verbatim"]
LABEL_INDEX = {label: i for i, label in enumerate(LABELS)}

# Realistic social media claim query + candidate pairs from test set
BENCHMARK_PAIRS = [
    ("We Must Pace the Frontier: I've written a new essay on why the AI industry should slow down, with a three-part plan",
     "We Must Pace the Frontier https://t.co/sezx1DnTZn"),
    ("ssi are delayed after a catastrophic security incident discovered after seeing what happened with openai, order of magnitude more damage caused.",
     "Safe Superintelligence has pushed back its timeline following a serious breach"),
    ("We Must Pace the Frontier: I've written a new essay on why the AI industry should slow down, with a three-part plan",
     "Elon, perhaps the last person I would've thought would agreed that we must pace the frontier"),
    ("ssi are delayed after a catastrophic security incident discovered after seeing what happened with openai, order of magnitude more damage caused.",
     "Penalties for SSI are delayed about 12-18 months, but can cost you thousands"),
    ("OpenAI is restructuring from a non-profit foundation to a standard for-profit corporation with equity.",
     "OAI is officially transitioning its governance to a for-profit entity with public benefit status."),
    ("TSMC confirms 2nm GAAFET silicon wafer volume production is on schedule for late 2025 in Hsinchu.",
     "Taiwan Semiconductor says next-generation 2-nanometer chip fabrication remains on track for next year."),
    ("The DOJ is seeking a breakup of Google's search and ad tech businesses in landmark antitrust remedy proposal.",
     "Federal antitrust prosecutors at the Justice Department want a judge to force Alphabet to spin off Chrome and Android."),
    ("Meta releases Llama 4 weights and technical report under community open model license.",
     "Mark Zuckerberg announced the open weights release of Meta's next-generation Llama 4 foundation model.")
]


def measure_single_pair_latency(model, tok, is_openjev=False, n_runs=100):
    # Warmup
    pair = BENCHMARK_PAIRS[0]
    for _ in range(10):
        if is_openjev:
            text = f"Premise: {pair[0]}\nHypothesis: {pair[1]}"
            inputs = tok(text, return_tensors="pt", max_length=192, truncation=True, padding=True).to("cuda")
        else:
            inputs = tok(pair[0], pair[1], return_tensors="pt", max_length=192, truncation=True, padding=True).to("cuda")
        with torch.inference_mode():
            _ = model(**inputs).logits
    torch.cuda.synchronize()

    times_ms = []
    # Accurate CUDA event timing
    start_event = torch.cuda.Event(enable_timing=True)
    end_event = torch.cuda.Event(enable_timing=True)

    for i in range(n_runs):
        pair = BENCHMARK_PAIRS[i % len(BENCHMARK_PAIRS)]
        if is_openjev:
            text = f"Premise: {pair[0]}\nHypothesis: {pair[1]}"
            inputs = tok(text, return_tensors="pt", max_length=192, truncation=True, padding=True).to("cuda")
        else:
            inputs = tok(pair[0], pair[1], return_tensors="pt", max_length=192, truncation=True, padding=True).to("cuda")
        
        torch.cuda.synchronize()
        start_event.record()
        with torch.inference_mode():
            _ = model(**inputs).logits
        end_event.record()
        torch.cuda.synchronize()
        
        times_ms.append(start_event.elapsed_time(end_event))

    arr = np.array(times_ms)
    return {
        "p50_ms": float(np.percentile(arr, 50)),
        "p90_ms": float(np.percentile(arr, 90)),
        "p95_ms": float(np.percentile(arr, 95)),
        "p99_ms": float(np.percentile(arr, 99)),
        "mean_ms": float(np.mean(arr)),
        "std_ms": float(np.std(arr)),
        "min_ms": float(np.min(arr)),
        "max_ms": float(np.max(arr)),
    }


def measure_batch_throughput(model, tok, is_openjev=False, batch_sizes=[1, 4, 8, 16, 32, 64, 128]):
    results = {}
    
    for bs in batch_sizes:
        # Build batch
        batch_pairs = (BENCHMARK_PAIRS * (bs // len(BENCHMARK_PAIRS) + 1))[:bs]
        if is_openjev:
            texts = [f"Premise: {p[0]}\nHypothesis: {p[1]}" for p in batch_pairs]
            inputs = tok(texts, padding=True, truncation=True, max_length=192, return_tensors="pt").to("cuda")
        else:
            inputs = tok([p[0] for p in batch_pairs], [p[1] for p in batch_pairs],
                         padding=True, truncation=True, max_length=192, return_tensors="pt").to("cuda")
        
        # Warmup
        for _ in range(5):
            with torch.inference_mode():
                _ = model(**inputs).logits
        torch.cuda.synchronize()

        start_event = torch.cuda.Event(enable_timing=True)
        end_event = torch.cuda.Event(enable_timing=True)
        
        runs = 20 if bs <= 32 else 10
        total_time_ms = 0.0
        for _ in range(runs):
            torch.cuda.synchronize()
            start_event.record()
            with torch.inference_mode():
                _ = model(**inputs).logits
            end_event.record()
            torch.cuda.synchronize()
            total_time_ms += start_event.elapsed_time(end_event)

        avg_batch_time_ms = total_time_ms / runs
        pairs_per_sec = (bs * 1000.0) / avg_batch_time_ms
        latency_per_pair_ms = avg_batch_time_ms / bs
        
        results[str(bs)] = {
            "batch_size": bs,
            "avg_batch_latency_ms": round(avg_batch_time_ms, 2),
            "latency_per_pair_ms": round(latency_per_pair_ms, 3),
            "throughput_pairs_per_sec": round(pairs_per_sec, 1)
        }
    return results


def benchmark_model(name, load_fn, is_openjev=False):
    print(f"\n{'='*70}\nBenchmarking: {name}\n{'='*70}", flush=True)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    
    t0 = time.time()
    model, tok = load_fn()
    load_time_sec = time.time() - t0
    
    vram_after_load_mb = torch.cuda.memory_allocated() / (1024**2)
    print(f"  Model loaded in {load_time_sec:.2f}s | Base VRAM: {vram_after_load_mb:.1f} MB", flush=True)
    
    # 1. Single pair latency
    single_res = measure_single_pair_latency(model, tok, is_openjev=is_openjev, n_runs=100)
    print(f"  Single-Pair (BS=1): P50 = {single_res['p50_ms']:.2f} ms | P90 = {single_res['p90_ms']:.2f} ms | P99 = {single_res['p99_ms']:.2f} ms", flush=True)

    # 2. Batch scaling
    # For 4B models, cap max batch size at 64 to avoid out-of-bounds allocation during benchmark
    batch_sizes = [1, 4, 8, 16, 32, 64] if is_openjev else [1, 4, 8, 16, 32, 64, 128]
    batch_res = measure_batch_throughput(model, tok, is_openjev=is_openjev, batch_sizes=batch_sizes)
    
    peak_vram_mb = torch.cuda.max_memory_allocated() / (1024**2)
    print(f"  Peak VRAM during batching: {peak_vram_mb:.1f} MB ({peak_vram_mb/1024:.2f} GB)", flush=True)
    print(f"  Max Throughput: {max(r['throughput_pairs_per_sec'] for r in batch_res.values()):.1f} pairs/sec", flush=True)

    del model, tok
    gc.collect()
    torch.cuda.empty_cache()
    
    return {
        "model_name": name,
        "load_time_sec": round(load_time_sec, 2),
        "base_vram_mb": round(vram_after_load_mb, 1),
        "peak_vram_mb": round(peak_vram_mb, 1),
        "single_pair_latency": single_res,
        "batch_scaling": batch_res
    }


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required.")
    
    gpu_name = torch.cuda.get_device_name(0)
    print(f"Benchmarking on GPU: {gpu_name} (CUDA {torch.version.cuda})", flush=True)
    
    results = {
        "timestamp": time.time(),
        "gpu": gpu_name,
        "models": {}
    }

    # 1. BGE-Base (110M params)
    def load_bge_base():
        path = ROOT / "checkpoints/bge-iter1-best"
        if not path.exists():
            path = "BAAI/bge-reranker-base"
        tok = AutoTokenizer.from_pretrained(str(path))
        model = AutoModelForSequenceClassification.from_pretrained(
            str(path), num_labels=5, ignore_mismatched_sizes=True, torch_dtype=torch.bfloat16
        ).to("cuda").eval()
        return model, tok

    results["models"]["bge_base"] = benchmark_model("Fine-Tuned BGE-Base (110M)", load_bge_base, is_openjev=False)

    # 2. BGE-Large (560M params)
    def load_bge_large():
        path = ROOT / "checkpoints/bge-large-best"
        if not path.exists():
            path = "BAAI/bge-reranker-large"
        tok = AutoTokenizer.from_pretrained(str(path))
        model = AutoModelForSequenceClassification.from_pretrained(
            str(path), num_labels=5, ignore_mismatched_sizes=True, torch_dtype=torch.bfloat16
        ).to("cuda").eval()
        return model, tok

    results["models"]["bge_large"] = benchmark_model("Fine-Tuned BGE-Large (560M)", load_bge_large, is_openjev=False)

    # 3. Fine-Tuned OpenJev-4B (Qwen3.5-4B LoRA)
    def load_openjev_ft():
        repo = "AlexWortega/openjev"
        subfolder = "qwen3.5-4b-nli-v2"
        revision = "4b5f9a67fa2ebe77466bce0656ce350effc3148c"
        tok = AutoTokenizer.from_pretrained(repo, subfolder=subfolder, revision=revision)
        if tok.pad_token is None:
            tok.pad_token = tok.eos_token
        tok.padding_side = "right"
        base_model = AutoModelForSequenceClassification.from_pretrained(
            repo, subfolder=subfolder, revision=revision, num_labels=5,
            ignore_mismatched_sizes=True, torch_dtype=torch.bfloat16, attn_implementation="sdpa"
        ).to("cuda").eval()
        
        lora_path = ROOT / "checkpoints/openjev-finetuned-best"
        if lora_path.exists():
            model = PeftModel.from_pretrained(base_model, str(lora_path)).to("cuda").eval()
        else:
            model = base_model
        return model, tok

    results["models"]["openjev_4b_ft"] = benchmark_model("Fine-Tuned OpenJev-4B (LoRA)", load_openjev_ft, is_openjev=True)

    # Save summary JSON
    out_file = RESULTS / "latency_comparison.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nBenchmarking complete! Results saved to {out_file}", flush=True)


if __name__ == "__main__":
    main()
