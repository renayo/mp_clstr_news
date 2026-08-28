"""Classification of matched clusters on the five registered axes (PREREGISTRATION.md §5).

    python -m mpclstr.classify --backend llm --model Qwen/Qwen2.5-7B-Instruct --revision <sha>
    python -m mpclstr.classify --backend nli --model facebook/bart-large-mnli
    python -m mpclstr.classify --backend dummy            # pipeline tests only

Input : classified/clusters_text.csv   (cluster_id, date, title, summary) — written by derive.py
Output: classified/clusters.csv        (cluster_id, p_<axis>_<label> ..., classifier, rubric_sha256)

The classifier is a deterministic function of the archived text: pinned
weights, greedy decoding, label probabilities read from the model's
next-token distribution restricted to the label words (LLM backend), or the
entailment scores of a zero-shot NLI model (NLI backend). The rubric text is
loaded from config/rubric.yaml and its SHA-256 is written into every output
row, so a change of prompt is visible in the data.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from . import config as C


# ------------------------------------------------------------------ prompts
def label_text(rubric: dict[str, Any], label: str) -> str:
    return rubric.get("label_text", {}).get(label, label)


def build_prompt(rubric: dict[str, Any], axis: str, title: str, summary: str) -> str:
    ax = rubric["axes"][axis]
    labels = ", ".join(label_text(rubric, l) for l in ax["labels"])
    return (f"{rubric['preamble'].strip()}\n\n"
            f"Axis: {axis}\n{ax['instruction'].strip()}\n\n"
            f"Title: {title.strip()}\nSummary: {summary.strip()}\n\n"
            f"Labels: {labels}\nAnswer with one label.")


# ----------------------------------------------------------------- backends
class DummyClassifier:
    """Deterministic pseudo-probabilities from a hash of the text. For tests only."""

    name = "dummy"

    def __init__(self, rubric: dict[str, Any]):
        self.rubric = rubric

    def probs(self, axis: str, title: str, summary: str) -> np.ndarray:
        labels = self.rubric["axes"][axis]["labels"]
        h = hashlib.sha256(f"{axis}|{title}|{summary}".encode()).digest()
        raw = np.array([h[i] + 1 for i in range(len(labels))], dtype=float)
        return raw / raw.sum()


class NLIClassifier:
    """Zero-shot NLI baseline (the rubric instruction is not consumed by this backend)."""

    def __init__(self, rubric: dict[str, Any], model: str, revision: str | None = None, device: int | str = -1):
        from transformers import pipeline  # lazy import
        self.rubric = rubric
        self.name = f"nli:{model}@{revision or 'default'}"
        self.pipe = pipeline("zero-shot-classification", model=model, revision=revision, device=device)

    def probs(self, axis: str, title: str, summary: str) -> np.ndarray:
        labels = self.rubric["axes"][axis]["labels"]
        cands = [label_text(self.rubric, l) for l in labels]
        out = self.pipe(f"{title}. {summary}", candidate_labels=cands, multi_label=False,
                        hypothesis_template="This news event is {}.")
        score = dict(zip(out["labels"], out["scores"]))
        p = np.array([score[c] for c in cands], dtype=float)
        return p / p.sum()


class LLMClassifier:
    """Pinned open-weights instruction model; label probabilities from next-token logits."""

    def __init__(self, rubric: dict[str, Any], model: str, revision: str | None = None, device: str | None = None,
                 dtype: str = "bfloat16"):
        import torch  # lazy import
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.rubric = rubric
        self.name = f"llm:{model}@{revision or 'default'}"
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(model, revision=revision)
        self.model = AutoModelForCausalLM.from_pretrained(model, revision=revision,
                                                          torch_dtype=getattr(torch, dtype))
        self.device = device or ("cuda" if torch.cuda.is_available() else
                                 "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
                                 else "cpu")
        self.model.to(self.device).eval()
        self._label_ids: dict[str, list[list[int]]] = {}

    def _ids_for(self, axis: str) -> list[list[int]]:
        if axis not in self._label_ids:
            ids = []
            for l in self.rubric["axes"][axis]["labels"]:
                word = label_text(self.rubric, l)
                variants = {word, word.capitalize(), " " + word, " " + word.capitalize()}
                first = sorted({self.tok.encode(v, add_special_tokens=False)[0] for v in variants})
                ids.append(first)
            self._label_ids[axis] = ids
        return self._label_ids[axis]

    def probs(self, axis: str, title: str, summary: str) -> np.ndarray:
        prompt = build_prompt(self.rubric, axis, title, summary)
        if getattr(self.tok, "chat_template", None):
            text = self.tok.apply_chat_template([{"role": "user", "content": prompt}],
                                                tokenize=False, add_generation_prompt=True)
        else:
            text = prompt + "\nAnswer:"
        enc = self.tok(text, return_tensors="pt").to(self.device)
        with self.torch.no_grad():
            logits = self.model(**enc).logits[0, -1].float()
        logp = self.torch.log_softmax(logits, dim=-1)
        scores = []
        for variants in self._ids_for(axis):
            scores.append(self.torch.logsumexp(logp[variants], dim=0).item())
        s = np.array(scores, dtype=float)
        s = np.exp(s - s.max())
        return s / s.sum()


def make_classifier(backend: str, rubric: dict[str, Any], model: str | None, revision: str | None, device=None):
    if backend == "dummy":
        return DummyClassifier(rubric)
    if backend == "nli":
        return NLIClassifier(rubric, model or "facebook/bart-large-mnli", revision, device if device is not None else -1)
    if backend == "llm":
        if not model:
            raise SystemExit("--model is required for the llm backend")
        return LLMClassifier(rubric, model, revision, device)
    raise SystemExit(f"unknown backend {backend}")


# ------------------------------------------------------------------ driver
def classify_frame(clf, rubric: dict[str, Any], text: pd.DataFrame, rubric_sha: str) -> pd.DataFrame:
    axes = rubric["axes"]
    rows = []
    for r in text.itertuples(index=False):
        row: dict[str, Any] = {"cluster_id": r.cluster_id}
        for axis, ax in axes.items():
            p = clf.probs(axis, str(r.title or ""), str(r.summary or ""))
            for l, v in zip(ax["labels"], p):
                row[f"p_{axis}_{l}"] = float(v)
        row["classifier"] = clf.name
        row["rubric_sha256"] = rubric_sha
        rows.append(row)
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Classify matched clusters on the five registered axes")
    ap.add_argument("--root", default=str(C.ROOT))
    ap.add_argument("--backend", choices=["dummy", "nli", "llm"], required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--revision", default=None, help="pinned model revision (commit hash)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--full", action="store_true", help="re-classify everything (default: only new clusters)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    rubric_path = root / "config" / "rubric.yaml"
    if not rubric_path.exists():
        rubric_path = C.RUBRIC_PATH          # the registered rubric shipped with the package
    rubric = C.load_rubric(rubric_path)
    rubric_sha = C.rubric_hash(rubric_path)
    src = root / "classified" / "clusters_text.csv"
    if not src.exists():
        print("classified/clusters_text.csv not found; run derive first", file=sys.stderr)
        return 2
    text = pd.read_csv(src).fillna("")
    out_path = root / "classified" / "clusters.csv"
    clf = make_classifier(args.backend, rubric, args.model, args.revision, args.device)
    prev = pd.DataFrame()
    if out_path.exists() and not args.full:
        prev = pd.read_csv(out_path)
        prev = prev[(prev["classifier"] == clf.name) & (prev["rubric_sha256"] == rubric_sha)]
        text = text[~text["cluster_id"].isin(prev["cluster_id"])]
    new = classify_frame(clf, rubric, text, rubric_sha)
    out = pd.concat([prev, new], ignore_index=True) if not prev.empty else new
    out.to_csv(out_path, index=False)
    print(f"classified {len(new)} new clusters with {clf.name}; {len(out)} rows in {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
