"""Shared corpus preparation and metric helpers for benchmark scripts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .eval_synonyms import EvalSynonymConfig, load_eval_synonyms_config
from .metrics import levenshtein
from .text_pipeline import (
    MIN_EVAL_HANZI_CHARS,
    extract_hanzi,
    is_pure_hanzi_segment,
    segment_has_ascii_digit_or_letter,
)


def default_corpus_files(root: Path) -> List[Tuple[Path, str]]:
    """All ``*.txt`` under ``data/corpus/``, sorted by path."""
    corpus_dir = root / "data" / "corpus"
    if not corpus_dir.is_dir():
        return []
    return sorted((p.resolve(), p.stem) for p in corpus_dir.glob("*.txt") if p.is_file())


def init_stats(vendor_keys: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    return {
        key: {
            "sentences_total": 0,
            "skipped_no_hanzi": 0,
            "skipped_no_input": 0,
            "skipped_mixed_content": 0,
            "skipped_too_short": 0,
            "decode_failed": 0,
            "exact_matches": 0,
            "cer_char_total_edits": 0,
            "cer_char_total_gold_len": 0,
            "char_acc_sentence_sum": 0.0,
            "char_acc_sentence_count": 0,
        }
        for key in vendor_keys
    }


def prepare_corpus_segments(
    raw_segments: Sequence[str],
    stats: Dict[str, Dict[str, Any]],
) -> List[Optional[Dict[str, Any]]]:
    """Filter raw segments and build the shared ``index/text/gold`` slots."""
    prepared: List[Optional[Dict[str, Any]]] = []
    vendor_keys = list(stats.keys())
    for i, seg in enumerate(raw_segments):
        piece = seg.strip()
        if not piece:
            prepared.append(None)
            continue
        if segment_has_ascii_digit_or_letter(piece) or not is_pure_hanzi_segment(piece):
            prepared.append(None)
            for key in vendor_keys:
                stats[key]["skipped_mixed_content"] += 1
            continue
        if len(piece) < MIN_EVAL_HANZI_CHARS:
            prepared.append(None)
            for key in vendor_keys:
                stats[key]["skipped_too_short"] += 1
            continue
        gold = extract_hanzi(piece)
        if not gold:
            prepared.append(None)
            for key in vendor_keys:
                stats[key]["skipped_no_hanzi"] += 1
            continue
        prepared.append({"index": i, "text": piece, "gold": gold})
    return prepared


def accumulate_char_metrics(
    st: Dict[str, Any],
    gold: str,
    pred: str,
    res_ok: bool,
    normalize,
) -> tuple[int, Optional[float]]:
    """Return ``(distance, cer)``; CER is ``None`` only when gold is empty."""
    g = normalize(gold)
    if not g:
        return 0, None
    if res_ok:
        p = normalize(pred)
        dist = levenshtein(p, g)
        cer = dist / len(g) if g else 0.0
    else:
        dist = len(g)
        cer = 1.0
    gold_len = len(g)
    st["cer_char_total_edits"] += dist
    st["cer_char_total_gold_len"] += gold_len
    st["char_acc_sentence_sum"] += max(0.0, min(1.0, 1.0 - dist / gold_len))
    st["char_acc_sentence_count"] += 1
    return dist, cer


def finalize_summary(stats: Dict[str, Dict[str, Any]], vendor_keys: Sequence[str]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    for key in vendor_keys:
        st = stats[key]
        n = st["sentences_total"]
        exact_rate = (st["exact_matches"] / n) if n else 0.0
        denom = st["cer_char_total_gold_len"]
        edits = st["cer_char_total_edits"]
        macro_cer = (edits / denom) if denom else None
        char_correct = None
        if denom and denom > 0:
            char_correct = max(0.0, min(1.0, (denom - edits) / denom))
        mean_sent_char = None
        cnt = st.get("char_acc_sentence_count", 0)
        if cnt:
            mean_sent_char = st["char_acc_sentence_sum"] / cnt
        summary[key] = {
            **st,
            "sentence_exact_rate": exact_rate,
            "macro_cer_over_gold_chars": macro_cer,
            "sentence_correct_count": st["exact_matches"],
            "sentence_total": n,
            "sentence_accuracy": exact_rate,
            "sentence_accuracy_percent": round(100.0 * exact_rate, 2) if n else 0.0,
            "gold_character_total": denom,
            "edit_distance_total": edits,
            "character_accuracy": char_correct,
            "character_accuracy_percent": round(100.0 * char_correct, 2) if char_correct is not None else None,
            "character_accuracy_mean_of_sentences": mean_sent_char,
            "character_accuracy_mean_of_sentences_percent": round(100.0 * mean_sent_char, 2)
            if mean_sent_char is not None
            else None,
        }
    return summary


def aggregate_summaries(
    per_corpus: Dict[str, Dict[str, Any]],
    vendor_keys: Sequence[str],
) -> Dict[str, Any]:
    keys = (
        "sentences_total",
        "skipped_no_hanzi",
        "skipped_no_input",
        "skipped_mixed_content",
        "skipped_too_short",
        "decode_failed",
        "exact_matches",
        "cer_char_total_edits",
        "cer_char_total_gold_len",
        "char_acc_sentence_sum",
        "char_acc_sentence_count",
    )
    agg_stats: Dict[str, Dict[str, Any]] = {key: {k: 0 for k in keys} for key in vendor_keys}
    for summary in per_corpus.values():
        for key in vendor_keys:
            part = summary.get(key) or {}
            for stat_key in keys:
                if stat_key == "char_acc_sentence_sum":
                    agg_stats[key][stat_key] += float(part.get(stat_key, 0) or 0)
                else:
                    agg_stats[key][stat_key] += int(part.get(stat_key, 0))
    return finalize_summary(agg_stats, vendor_keys)


def init_eval_synonyms(root: Path, explicit: Optional[Path]) -> Tuple[EvalSynonymConfig, Path]:
    if explicit is not None:
        path = explicit if explicit.is_absolute() else (root / explicit)
    else:
        path = root / "data" / "eval_synonyms.json"
    return load_eval_synonyms_config(path), path
