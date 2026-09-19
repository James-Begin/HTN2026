"""Build saved semantic-fan features locally; no hosted inference or credentials.

Run: python3 demo/recordings/build_conversation_space.py
Then --offline reuses downloaded weights and cached embeddings/bases in ignored work/.
Requires numpy, onnxruntime and tokenizers; does not require torch.

Recipe verified against https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
and https://huggingface.co/Xenova/all-MiniLM-L6-v2: tokenizer special tokens,
256-token truncation, attention-masked mean pooling, then unit normalization.
Captured text is not cleaned, expanded with context, or replaced by input text.

This English-oriented compact encoder is a lossy prototype on a multilingual,
partly excerpted capture. Angular proximity is NOT clustering, stance, agreement,
truth, community membership, or evidence of influence. Only seed-relative radius
has an exact distance interpretation; pairwise visual distances do not.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

ROOT = Path(__file__).resolve().parents[2]
RECORDINGS = ROOT / "demo" / "recordings"
WORK = ROOT / "work" / "conversation-space"
OUTPUT = RECORDINGS / "conversation-space.json"
REPO = "Xenova/all-MiniLM-L6-v2"
REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
MODEL = f"{REPO}@{REVISION}; onnx/model_quantized.onnx; ONNX Runtime CPU"
LIMIT = 256
POLICY = (
    "captured-text-verbatim-v1; tokenizer.json special tokens; right-truncate=256; "
    "single-input inference; attention-masked mean pooling including special tokens; L2 normalize"
)
BASIS_POLICY = "centered-residual-PCA-SVD-v1; raw-residual-projection; max-absolute-loading-positive"
METHOD = (
    f"{POLICY}. Frozen {BASIS_POLICY}. u=e-dot(e,seed)*seed; "
    "r=sqrt((1-cosine)/2); theta=atan2(dot(u,b2),dot(u,b1)); "
    "y=r*cos(theta), z=r*sin(theta). directionQuality is the fraction of residual "
    "squared norm retained in the angular plane (zero at the reference); null y/z "
    "means unavailable direction. Prototype: English-oriented compact encoder on "
    "multilingual, sometimes excerpted captures; truncation may lose content. "
    "Angles are lossy and corpus-dependent, NOT clusters, stance, agreement, truth, "
    "community membership, or influence; pairwise visual distance is not semantic distance."
)
DARIO_ID = "2098773920774074715"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_hash(text: str) -> str:
    return sha(text.encode("utf-8"))


def real_post(post: dict) -> bool:
    return (
        str(post.get("id", "")).isdigit()
        and isinstance(post.get("text"), str)
        and bool(post["text"].strip())
        and post.get("scope") not in {"input", "seed-text"}
    )


def collect(captures: list[dict]) -> tuple[dict[str, dict], set[str], dict[str, float]]:
    """Top-level, all periods, supplement; final explicit seeds win by ID."""
    records = []
    seeds = []
    for capture in captures:
        records.extend(capture.get("posts", []))
        for period in capture.get("savedPeriods", {}).values():
            records.extend(period.get("posts", []))
        if capture.get("seedPost"):
            seeds.append(capture["seedPost"])
    posts, texts, likes = {}, set(), {}
    for post in records + seeds:
        if not real_post(post):
            continue
        post_id = str(post["id"])
        posts[post_id] = post
        texts.add(post["text"])
        likes[post_id] = max(likes.get(post_id, 0), float(post.get("likes") or 0))
    return posts, texts, likes


def model_file(name: str, offline: bool) -> Path:
    path = WORK / "model" / REVISION / name
    if not path.exists():
        if offline:
            raise RuntimeError(f"Model file missing in offline mode: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {REPO}/{name}", flush=True)
        temporary = path.with_suffix(path.suffix + ".download")
        try:
            with urlopen(f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}", timeout=90) as source:
                with temporary.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
            temporary.replace(path)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"Model download failed; no substitute embeddings: {name}") from exc
    return path


def embed(texts: set[str], offline: bool) -> dict[str, tuple[np.ndarray, bool]]:
    cache = WORK / "embeddings" / text_hash(MODEL + POLICY)
    cache.mkdir(parents=True, exist_ok=True)
    result = {}
    tokenizer = session = None
    computed = 0
    for text in sorted(texts, key=text_hash):
        key = text_hash(text)
        path = cache / f"{key}.npz"
        if path.exists():
            with np.load(path, allow_pickle=False) as saved:
                vector = saved["vector"]
                truncated = bool(saved["inputTruncated"])
        else:
            if session is None:
                tokenizer = Tokenizer.from_file(str(model_file("tokenizer.json", offline)))
                tokenizer.no_padding()
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                options.inter_op_num_threads = 1
                session = ort.InferenceSession(
                    str(model_file("onnx/model_quantized.onnx", offline)),
                    sess_options=options, providers=["CPUExecutionProvider"],
                )
            tokenizer.no_truncation()
            count = len(tokenizer.encode(text, add_special_tokens=True).ids)
            tokenizer.enable_truncation(max_length=LIMIT, direction="right")
            encoded = tokenizer.encode(text, add_special_tokens=True)
            inputs = {
                "input_ids": np.array([encoded.ids], dtype=np.int64),
                "attention_mask": np.array([encoded.attention_mask], dtype=np.int64),
                "token_type_ids": np.array([encoded.type_ids], dtype=np.int64),
            }
            outputs = session.run(None, {item.name: inputs[item.name] for item in session.get_inputs()})
            tokens = outputs[0]
            assert tokens.ndim == 3 and tokens.shape[1] == len(encoded.ids)
            mask = inputs["attention_mask"][..., None]
            vector = ((tokens * mask).sum(axis=1) / mask.sum(axis=1))[0].astype(np.float64)
            norm = np.linalg.norm(vector)
            assert np.isfinite(vector).all() and norm > 0
            vector /= norm
            truncated = count > LIMIT
            np.savez(path, vector=vector, inputTruncated=truncated, originalTokenCount=count)
            computed += 1
            if computed % 100 == 0:
                print(f"Embedded {computed} new distinct texts", flush=True)
        assert vector.ndim == 1 and np.isfinite(vector).all()
        assert abs(float(np.linalg.norm(vector)) - 1) < 1e-8
        result[key] = (vector, truncated)
    print(f"Distinct texts: {len(texts)}; new inference: {computed}; cache hits: {len(texts) - computed}")
    return result


def layout(posts: dict[str, dict], reference_id: str, embeddings: dict) -> dict:
    reference_hash = text_hash(posts[reference_id]["text"])
    seed = embeddings[reference_hash][0]
    # Each distinct final captured text contributes once to calibration.
    hashes = sorted({text_hash(post["text"]) for post in posts.values()})
    vectors = np.stack([embeddings[key][0] for key in hashes])
    residuals = vectors - (vectors @ seed)[:, None] * seed
    calibration = json.dumps([MODEL, POLICY, BASIS_POLICY, reference_hash, hashes], separators=(",", ":"))
    basis_path = WORK / "bases" / f"{text_hash(calibration)}.npz"
    basis_path.parent.mkdir(parents=True, exist_ok=True)
    if basis_path.exists():
        with np.load(basis_path, allow_pickle=False) as saved:
            basis, valid = saved["basis"], bool(saved["valid"])
    else:
        _, singular, vt = np.linalg.svd(residuals - residuals.mean(axis=0), full_matrices=False)
        valid = len(singular) >= 2 and singular[1] > max(1e-8, singular[0] * 1e-8)
        basis = vt[:2].copy()
        for component in basis:
            if component[np.argmax(np.abs(component))] < 0:
                component *= -1
        np.savez(basis_path, basis=basis, valid=valid, calibration=calibration)
    basis_id = sha(calibration.encode() + basis.astype("<f8").tobytes())
    features = {}
    for post_id, post in sorted(posts.items()):
        key = text_hash(post["text"])
        vector, truncated = embeddings[key]
        cosine = float(np.clip(vector @ seed, -1, 1))
        residual = vector - cosine * seed
        projected = basis @ residual
        residual_norm = float(np.linalg.norm(residual))
        projected_norm = float(np.linalg.norm(projected))
        quality = min(1.0, (projected_norm / residual_norm) ** 2) if residual_norm > 1e-8 and valid else 0.0
        y = z = None
        if key == reference_hash:
            cosine, y, z, quality = 1.0, 0.0, 0.0, 0.0
        elif valid and projected_norm > 1e-8 and quality > 1e-12:
            radius = math.sqrt((1 - cosine) / 2)
            theta = math.atan2(float(projected[1]), float(projected[0]))
            y, z = radius * math.cos(theta), radius * math.sin(theta)
        features[post_id] = {
            "text": post["text"], "textHash": key, "cosine": cosine,
            "y": y, "z": z, "directionQuality": quality, "inputTruncated": truncated,
        }
    return {
        "referencePostId": reference_id, "referenceTextHash": reference_hash,
        "basisId": basis_id, "features": features,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Never download model files")
    args = parser.parse_args()
    names = ["sequitor-live.json", "dario-humor.json", "anthropic-wet-lab.json"]
    raw = {name: (RECORDINGS / name).read_bytes() for name in names}
    captures = {name: json.loads(data) for name, data in raw.items()}
    dario, dario_texts, _ = collect([captures[names[0]], captures[names[1]]])
    wetlab, wetlab_texts, wetlab_likes = collect([captures[names[2]]])
    assert DARIO_ID in dario and wetlab
    wetlab_id = min(wetlab, key=lambda key: (-wetlab_likes[key], key))
    embeddings = embed(dario_texts | wetlab_texts, args.offline)
    artifact = {
        "schemaVersion": 1, "model": MODEL, "method": METHOD,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "captureHashes": {f"demo/recordings/{name}": sha(data) for name, data in raw.items()},
        "layouts": {
            DARIO_ID: layout(dario, DARIO_ID, embeddings),
            wetlab_id: layout(wetlab, wetlab_id, embeddings),
        },
    }
    for reference_id, item in artifact["layouts"].items():
        assert item["features"][reference_id]["y"] == item["features"][reference_id]["z"] == 0
        for feature in item["features"].values():
            assert -1 <= feature["cosine"] <= 1 and 0 <= feature["directionQuality"] <= 1
            assert feature["textHash"] == text_hash(feature["text"])
            assert (feature["y"] is None) == (feature["z"] is None)
            if feature["y"] is not None:
                radius_squared = feature["y"] ** 2 + feature["z"] ** 2
                assert radius_squared <= 1 + 1e-12
                assert abs(radius_squared - (1 - feature["cosine"]) / 2) < 1e-12
        print(f"Reference {reference_id}: {len(item['features'])} posts; "
              f"truncated={sum(f['inputTruncated'] for f in item['features'].values())}; "
              f"direction unavailable={sum(f['y'] is None for f in item['features'].values())}")
    assert all((RECORDINGS / name).read_bytes() == data for name, data in raw.items())
    OUTPUT.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
