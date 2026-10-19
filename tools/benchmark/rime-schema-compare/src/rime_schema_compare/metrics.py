"""Sentence match and character error rate (CER)."""

from __future__ import annotations


def levenshtein(a: str, b: str) -> int:
    """Classic O(len(a)*len(b)) DP; sufficient for sentence-length strings."""
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (0 if ca == cb else 1)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def sentence_exact_match(pred: str, gold: str) -> bool:
    return pred.strip() == gold.strip()


def cer_sentence(pred: str, gold: str) -> float:
    if not gold:
        return 0.0
    return levenshtein(pred, gold) / len(gold)
