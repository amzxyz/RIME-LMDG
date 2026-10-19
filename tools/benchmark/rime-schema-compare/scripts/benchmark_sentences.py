#!/usr/bin/env python3
"""
Benchmark whole-sentence decoding: split corpus → vendor input string → Rime → metrics.

Run from repository root, after `pip install -r requirements.txt` and submodule init:

  python scripts/benchmark_sentences.py
  python scripts/benchmark_sentences.py --corpus data/corpus/prose.txt
  python scripts/benchmark_sentences.py --corpus a.txt b.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from dataclasses import asdict

# Windows: 勿将 stderr 设为 UTF-8。多数 PowerShell/cmd 仍按 GBK(CP936) 解码控制台，
# 若 stderr 写 UTF-8 字节会导致 [INFO] 中文乱码。stdout 仍用 UTF-8 便于 JSON 含中文时一致编码。
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

from rime_schema_compare.benchmark_env import prepare_vendor_for_benchmark
from rime_schema_compare.config import DEFAULT_VENDORS, VendorConfig, resolve_rime_dll, repo_root, shared_data_dir
from rime_schema_compare.eval_synonyms import EvalSynonymConfig, load_eval_synonyms_config
from rime_schema_compare.metrics import levenshtein, sentence_exact_match
from rime_schema_compare.rime_runner import RimeDistroRunner
from rime_schema_compare.text_pipeline import (
    MIN_EVAL_HANZI_CHARS,
    extract_hanzi,
    is_pure_hanzi_segment,
    segment_has_ascii_digit_or_letter,
    sentence_to_continuous_pinyin,
    sentence_to_shape_code_prefix_input,
    split_sentences,
)

logger = logging.getLogger("benchmark_sentences")


def _setup_logging() -> None:
    if logger.handlers:
        return
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _pick_vendors(keys: Optional[List[str]]) -> List[VendorConfig]:
    if not keys:
        return list(DEFAULT_VENDORS)
    keyset = {k.strip().lower() for k in keys}
    out = [v for v in DEFAULT_VENDORS if v.key.lower() in keyset]
    if len(out) != len(keyset):
        found = {v.key.lower() for v in out}
        missing = keyset - found
        raise SystemExit(f"Unknown vendor key(s): {sorted(missing)}. Known: {[v.key for v in DEFAULT_VENDORS]}")
    return out


def _filter_unavailable_vendors(root: Path, vendors: List[VendorConfig]) -> List[VendorConfig]:
    out: List[VendorConfig] = []
    skipped: List[str] = []
    for vendor in vendors:
        vendor_dir = vendor.data_dir(root)
        input_dict = vendor.input_dict_path(root)
        missing_reason: Optional[str] = None
        if not vendor_dir.is_dir():
            missing_reason = f"目录不存在: {vendor_dir}"
        elif input_dict is not None and not input_dict.is_file():
            missing_reason = f"输入码表不存在: {input_dict}"

        if not missing_reason:
            out.append(vendor)
            continue

        if "_with_gram" in vendor.key:
            skipped.append(f"{vendor.key}（{missing_reason}）")
            continue

        raise SystemExit(f"Vendor {vendor.key} unavailable: {missing_reason}")

    if skipped:
        logger.warning(
            "[启动] 跳过 %d 套可选 with_gram 方案：%s",
            len(skipped),
            "；".join(skipped),
        )
    if not out:
        raise SystemExit("No available vendors to benchmark after filtering missing directories.")
    return out


def _vendor_input_label(vendor: VendorConfig) -> str:
    if vendor.input_mode == "pinyin":
        return "拼音全拼"
    if vendor.input_mode == "shape_code_prefix":
        return f"形码前 {vendor.input_code_prefix_len} 码"
    return vendor.input_mode


def _build_vendor_input(vendor: VendorConfig, text: str, root: Path) -> str:
    if vendor.input_mode == "pinyin":
        return sentence_to_continuous_pinyin(text)
    if vendor.input_mode == "shape_code_prefix":
        dict_path = vendor.input_dict_path(root)
        if dict_path is None:
            raise FileNotFoundError(f"{vendor.key} 未配置 input_dict_rel_path")
        if not dict_path.is_file():
            raise FileNotFoundError(f"{vendor.key} 形码字典不存在: {dict_path}")
        return sentence_to_shape_code_prefix_input(text, dict_path, vendor.input_code_prefix_len)
    raise ValueError(f"Unsupported input_mode for {vendor.key}: {vendor.input_mode}")


def default_corpus_files(root: Path) -> List[Tuple[Path, str]]:
    """All ``*.txt`` under ``data/corpus/``, sorted by path."""
    d = root / "data" / "corpus"
    if not d.is_dir():
        return []
    return sorted((p.resolve(), p.stem) for p in d.glob("*.txt") if p.is_file())


def _finalize_summary(stats: Dict[str, Dict[str, Any]], vendors: List[VendorConfig]) -> Dict[str, Any]:
    """Add human-facing rates: sentence = exact/total; character = 1 − (edits/gold_len) (micro, Levenshtein)."""
    summary: Dict[str, Any] = {}
    for v in vendors:
        st = stats[v.key]
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

        summary[v.key] = {
            **st,
            "sentence_exact_rate": exact_rate,
            "macro_cer_over_gold_chars": macro_cer,
            # 句子正确率：完全匹配的句数 / 参与评测的句数（与 sentence_exact_rate 相同，单位见 *_percent）
            "sentence_correct_count": st["exact_matches"],
            "sentence_total": n,
            "sentence_accuracy": exact_rate,
            "sentence_accuracy_percent": round(100.0 * exact_rate, 2) if n else 0.0,
            # 文字正确率（微观）：各句对金文做 Levenshtein，汇总 (总金文字数 − 总编辑距离) / 总金文字数
            "gold_character_total": denom,
            "edit_distance_total": edits,
            "character_accuracy": char_correct,
            "character_accuracy_percent": round(100.0 * char_correct, 2) if char_correct is not None else None,
            # 各句「1 − 本句编辑距离/本句金文字数」的平均（与上面微观加权可能略有不同）
            "character_accuracy_mean_of_sentences": mean_sent_char,
            "character_accuracy_mean_of_sentences_percent": round(100.0 * mean_sent_char, 2)
            if mean_sent_char is not None
            else None,
        }
    return summary


def _accumulate_char_metrics(
    st: Dict[str, Any],
    gold: str,
    pred: str,
    res_ok: bool,
    normalize,
) -> tuple[int, Optional[float]]:
    """Return (levenshtein_distance, cer for this sentence or None if no gold).

    ``normalize`` is applied to gold/pred before distance/CER (同义词等价评测).
    """
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
    L = len(g)
    st["cer_char_total_edits"] += dist
    st["cer_char_total_gold_len"] += L
    st["char_acc_sentence_sum"] += max(0.0, min(1.0, 1.0 - dist / L))
    st["char_acc_sentence_count"] += 1
    return dist, cer


def _summary_csv_rows_for_block(
    corpus_label: str,
    block: Dict[str, Any],
    vendors: List[VendorConfig],
) -> List[Dict[str, Any]]:
    rows_out: List[Dict[str, Any]] = []
    for v in vendors:
        s = block.get(v.key) or {}
        rows_out.append(
            {
                "corpus": corpus_label,
                "vendor": v.key,
                "sentence_total": s.get("sentence_total", 0),
                "sentence_correct": s.get("sentence_correct_count", 0),
                "sentence_accuracy_percent": s.get("sentence_accuracy_percent"),
                "gold_character_total": s.get("gold_character_total", 0),
                "edit_distance_total": s.get("edit_distance_total", 0),
                "character_accuracy_percent": s.get("character_accuracy_percent"),
                "character_accuracy_mean_of_sentences_percent": s.get(
                    "character_accuracy_mean_of_sentences_percent"
                ),
                "decode_failed": s.get("decode_failed", 0),
                "macro_cer": s.get("macro_cer_over_gold_chars"),
            }
        )
    return rows_out


def _write_summary_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _per_sentence_char_accuracy_percent(cer: Optional[float]) -> Optional[float]:
    if cer is None:
        return None
    return round(100.0 * max(0.0, min(1.0, 1.0 - float(cer))), 2)


def _sentence_grouped_fieldnames(vendors: List[VendorConfig]) -> List[str]:
    fn: List[str] = ["corpus", "index", "gold"]
    for v in vendors:
        fn.extend(
            [
                f"{v.key}_input",
                f"{v.key}_sentence_correct",
                f"{v.key}_character_accuracy_percent",
                f"{v.key}_prediction",
                f"{v.key}_error",
            ]
        )
    return fn


_LONG_CSV_FIELDS = (
    "corpus",
    "index",
    "vendor",
    "gold",
    "input",
    "prediction",
    "exact",
    "cer",
    "error",
)


def _build_long_rows_by_sentence(
    per_sentence: List[Dict[str, Any]],
    vendors: List[VendorConfig],
) -> List[Dict[str, Any]]:
    """Same columns as *_long.csv, rows ordered: sentence1×all vendors, sentence2×all vendors, …"""
    order: List[Tuple[Any, ...]] = []
    seen: Set[Tuple[Any, ...]] = set()
    for row in per_sentence:
        k = (row["corpus"], row["index"], row["gold"])
        if k not in seen:
            seen.add(k)
            order.append(k)

    by_key_vendor: Dict[Tuple[Tuple[Any, ...], str], Dict[str, Any]] = {}
    for row in per_sentence:
        k = (row["corpus"], row["index"], row["gold"])
        by_key_vendor[(k, row["vendor"])] = row

    out: List[Dict[str, Any]] = []
    vkeys = [v.key for v in vendors]
    for k in order:
        for vk in vkeys:
            r = by_key_vendor.get((k, vk))
            if r is not None:
                out.append(r)
    return out


def _write_long_csv_by_sentence(
    path: Path,
    per_sentence: List[Dict[str, Any]],
    vendors: List[VendorConfig],
) -> None:
    rows = _build_long_rows_by_sentence(per_sentence, vendors)
    fn = list(_LONG_CSV_FIELDS)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fn, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _exact_map_by_sentence(
    per_sentence: List[Dict[str, Any]],
    vendors: List[VendorConfig],
) -> Tuple[List[Tuple[Any, ...]], Dict[Tuple[Any, ...], Dict[str, bool]]]:
    """Sentence key order + per-vendor exact (missing vendor → False)."""
    order: List[Tuple[Any, ...]] = []
    seen: Set[Tuple[Any, ...]] = set()
    for row in per_sentence:
        k = (row["corpus"], row["index"], row["gold"])
        if k not in seen:
            seen.add(k)
            order.append(k)
    want = {v.key for v in vendors}
    by_key: Dict[Tuple[Any, ...], Dict[str, bool]] = {k: {vk: False for vk in want} for k in order}
    for row in per_sentence:
        k = (row["corpus"], row["index"], row["gold"])
        vk = row["vendor"]
        if vk in want:
            by_key[k][vk] = bool(row.get("exact"))
    return order, by_key


def _write_scheme_compare_txt(
    path: Path,
    *,
    generated_utc: str,
    mode: str,
    per_sentence: List[Dict[str, Any]],
    vendors: List[VendorConfig],
) -> None:
    """
    各方案「比其他方案多正确」的句子：独有判对 + 相对每个对手多判对。
    """
    order, by_key = _exact_map_by_sentence(per_sentence, vendors)
    vkeys = [v.key for v in vendors]
    lines: List[str] = [
        "=" * 72,
        "各方案相对其他方案的整句判对对比",
        "=" * 72,
        f"生成时间 (UTC): {generated_utc}",
        f"模式: {mode}",
        "",
        "说明:",
        "  · 「仅本方案判对」：该句仅当前方案整句与金文完全一致，其余参与对比的方案均未判对。",
        "  · 「相对 [X] 多判对」：当前方案判对且方案 X 未判对（不要求其他方案是否判对）。",
        "",
    ]
    for vk in vkeys:
        lines.append("-" * 72)
        lines.append(f"【{vk}】")
        others = [x for x in vkeys if x != vk]
        exclusive = [
            k
            for k in order
            if by_key[k].get(vk) and all(not by_key[k].get(o) for o in others)
        ]
        lines.append(
            f"· 仅本方案判对（其余 {len(others)} 个方案均未判对）: {len(exclusive)} 句"
        )
        if exclusive:
            for corpus, idx, gold in exclusive:
                lines.append(f"    [{corpus} #{idx}] {gold}")
        else:
            lines.append("    （无）")
        lines.append("")
        for o in others:
            wins = [k for k in order if by_key[k].get(vk) and not by_key[k].get(o)]
            lines.append(f"· 相对 [{o}] 多判对（本对、对方错）: {len(wins)} 句")
            if wins:
                for corpus, idx, gold in wins:
                    lines.append(f"    [{corpus} #{idx}] {gold}")
            else:
                lines.append("    （无）")
            lines.append("")
    lines.append("=" * 72)
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_sentence_grouped_rows(
    per_sentence: List[Dict[str, Any]],
    vendors: List[VendorConfig],
) -> List[Dict[str, Any]]:
    """One row per (corpus, index, gold); each vendor gets input / correct / char% / prediction / error columns."""
    order: List[Tuple[Any, ...]] = []
    seen: Set[Tuple[Any, ...]] = set()
    for row in per_sentence:
        k = (row["corpus"], row["index"], row["gold"])
        if k not in seen:
            seen.add(k)
            order.append(k)

    fieldnames = _sentence_grouped_fieldnames(vendors)
    groups: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for k in order:
        d: Dict[str, Any] = {fn: "" for fn in fieldnames}
        d["corpus"], d["index"], d["gold"] = k[0], k[1], k[2]
        groups[k] = d

    for row in per_sentence:
        k = (row["corpus"], row["index"], row["gold"])
        g = groups[k]
        vk = row["vendor"]
        g[f"{vk}_input"] = row.get("input", "") or ""
        g[f"{vk}_sentence_correct"] = "1" if row.get("exact") else "0"
        cer = row.get("cer")
        cer_f = float(cer) if isinstance(cer, (int, float)) else None
        cap = _per_sentence_char_accuracy_percent(cer_f)
        g[f"{vk}_character_accuracy_percent"] = "" if cap is None else str(cap)
        g[f"{vk}_prediction"] = row.get("prediction", "") or ""
        g[f"{vk}_error"] = row.get("error", "") or ""

    return [groups[k] for k in order]


def _write_sentence_grouped_csv(path: Path, per_sentence: List[Dict[str, Any]], vendors: List[VendorConfig]) -> None:
    rows = _build_sentence_grouped_rows(per_sentence, vendors)
    fn = _sentence_grouped_fieldnames(vendors)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fn, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _vendor_summary_lines(vkey: str, s: Dict[str, Any]) -> List[str]:
    sp = s.get("sentence_accuracy_percent")
    cp = s.get("character_accuracy_percent")
    sc = s.get("sentence_correct_count", 0)
    st = s.get("sentence_total", 0)
    lines = [
        f"  [{vkey}]",
        f"    句子正确率: {sp}%  ({sc}/{st} 句完全匹配)",
        f"    文字正确率: {cp}%  (全语料金文加权，基于 Levenshtein)",
    ]
    m = s.get("character_accuracy_mean_of_sentences_percent")
    if m is not None:
        lines.append(f"    文字正确率(逐句平均): {m}%")
    return lines


def _format_timings_lines(timings: Dict[str, Any], indent: str = "  ") -> List[str]:
    if not timings:
        return []
    lines: List[str] = [
        f"{indent}读取文件: {timings.get('read_text_ms', '—')} ms",
        f"{indent}分句: {timings.get('split_ms', '—')} ms",
        f"{indent}预过滤: {timings.get('prepare_segments_ms', '—')} ms",
    ]
    for vk, tv in sorted((timings.get("vendors") or {}).items()):
        if isinstance(tv, dict):
            input_part = f"输入串: {tv.get('input_ms', '—')} ms, " if tv.get("input_ms") is not None else ""
            so = tv.get("session_open_ms")
            so_part = f", 开会话+选方案: {so} ms" if so is not None else ""
            lines.append(
                f"{indent}[{vk}] {input_part}librime 加载: {tv.get('load_ms', '—')} ms{so_part}, "
                f"逐句解码: {tv.get('decode_ms', '—')} ms"
            )
    w = timings.get("write_artifacts_ms")
    if w is not None:
        lines.append(f"{indent}写出结果文件: {w} ms")
    return lines


def _write_report_txt(
    path: Path,
    *,
    generated_utc: str,
    rime_dll: str,
    corpus_files: Optional[Dict[str, str]],
    summary_by_corpus: Optional[Dict[str, Dict[str, Any]]],
    summary_overall: Dict[str, Any],
    vendors: List[VendorConfig],
    mode: str,
    timings_one_corpus: Optional[Dict[str, Any]] = None,
    timings_by_corpus: Optional[Dict[str, Dict[str, Any]]] = None,
    timings_wall_total_ms: Optional[float] = None,
    eval_synonyms_summary: Optional[str] = None,
) -> None:
    lines: List[str] = [
        "=" * 72,
        "Rime 多方案整句评测 — 摘要报告",
        "=" * 72,
        f"生成时间 (UTC): {generated_utc}",
        f"rime.dll: {rime_dll}",
        f"模式: {mode}",
        "",
    ]
    if corpus_files:
        lines.append("语料文件:")
        for stem, fp in sorted(corpus_files.items()):
            lines.append(f"  - {stem}: {fp}")
        lines.append("")

    lines.append("【总体】")
    for v in vendors:
        s = summary_overall.get(v.key) or {}
        lines.extend(_vendor_summary_lines(v.key, s))
        lines.append("")

    if summary_by_corpus:
        for stem in sorted(summary_by_corpus.keys()):
            lines.append("-" * 72)
            lines.append(f"【语料: {stem}】")
            block = summary_by_corpus[stem]
            for v in vendors:
                s = block.get(v.key) or {}
                lines.extend(_vendor_summary_lines(v.key, s))
                lines.append("")

    lines.append("=" * 72)
    if timings_one_corpus:
        lines.append("【耗时】")
        lines.extend(_format_timings_lines(timings_one_corpus))
        lines.append("")
    if timings_wall_total_ms is not None:
        lines.append(f"【总耗时】全流程墙钟约 {timings_wall_total_ms} ms（多语料）")
        lines.append("")
    if timings_by_corpus:
        lines.append("【各语料耗时】")
        for stem in sorted(timings_by_corpus.keys()):
            lines.append(f"  · {stem}")
            lines.extend(_format_timings_lines(timings_by_corpus[stem], indent="    "))
        lines.append("")
    lines.append("=" * 72)
    if eval_synonyms_summary:
        lines.append(f"同义词归一化（句级完全匹配与 CER 计算前）: {eval_synonyms_summary}")
        lines.append("")
    lines.append(
        "说明: 分句后仅「纯汉字」且不含 ASCII 数字/英文字母、汉字不少于 "
        f"{MIN_EVAL_HANZI_CHARS} 字的片段参与评测；其它片段已过滤。"
        "句子正确率 = 归一化后预测与金句完全一致的比例；"
        "文字正确率 = 全语料 (归一化后总字数−总编辑距离)/归一化后总字数。"
        "输入串按各 vendor 自身配置生成，可能是连续拼音，也可能是形码前缀串。"
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _aggregate_summaries(per_corpus: Dict[str, Dict[str, Any]], vendors: List[VendorConfig]) -> Dict[str, Any]:
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
    agg_stats: Dict[str, Dict[str, int]] = {v.key: {k: 0 for k in keys} for v in vendors}
    for _label, summ in per_corpus.items():
        for v in vendors:
            part = summ.get(v.key) or {}
            for k in keys:
                if k in ("char_acc_sentence_sum",):
                    agg_stats[v.key][k] += float(part.get(k, 0) or 0)
                else:
                    agg_stats[v.key][k] += int(part.get(k, 0))
    return _finalize_summary(agg_stats, vendors)


def _init_eval_synonyms(
    root: Path, explicit: Optional[Path]
) -> Tuple[EvalSynonymConfig, Path]:
    if explicit is not None:
        path = explicit if explicit.is_absolute() else (root / explicit)
    else:
        path = root / "data" / "eval_synonyms.json"
    return load_eval_synonyms_config(path), path


def run_benchmark(
    corpus_path: Path,
    out_dir: Path,
    rime_dll: Path,
    vendors: List[VendorConfig],
    corpus_label: str,
    progress_every: int,
    *,
    eval_synonyms: EvalSynonymConfig,
    eval_synonyms_path: Path,
    write_artifacts: bool = True,
    stamp: Optional[str] = None,
    artifact_base: Optional[str] = None,
) -> Dict[str, Any]:
    timings: Dict[str, Any] = {"vendors": {}}
    norm = eval_synonyms.normalize

    logger.info("[语料:%s] 读取 UTF-8: %s", corpus_label, corpus_path)
    t0 = time.perf_counter()
    text = corpus_path.read_text(encoding="utf-8")
    timings["read_text_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    logger.info("[语料:%s] 读取完成，耗时 %.2f ms", corpus_label, timings["read_text_ms"])

    t1 = time.perf_counter()
    raw_sents = split_sentences(text)
    timings["split_ms"] = round((time.perf_counter() - t1) * 1000, 2)
    logger.info(
        "[分句] 扫描分句（，“。” 与 “” 配对；小数 . 不切；丢弃含 、或《》的片段）完成，共 %d 个片段，耗时 %.2f ms",
        len(raw_sents),
        timings["split_ms"],
    )

    rows: List[Dict[str, Any]] = []
    stats: Dict[str, Dict[str, Any]] = {}

    runner = RimeDistroRunner(rime_dll)

    for v in vendors:
        stats[v.key] = {
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

    logger.info(
        "[预过滤] 开始: 纯汉字、无 ASCII 数字/字母、至少 %d 字",
        MIN_EVAL_HANZI_CHARS,
    )
    t_prep0 = time.perf_counter()
    prepared_base: List[Optional[Dict[str, Any]]] = []
    for i, seg in enumerate(raw_sents):
        piece = seg.strip()
        if not piece:
            prepared_base.append(None)
            continue
        if segment_has_ascii_digit_or_letter(piece):
            prepared_base.append(None)
            for v in vendors:
                stats[v.key]["skipped_mixed_content"] += 1
            continue
        if not is_pure_hanzi_segment(piece):
            prepared_base.append(None)
            for v in vendors:
                stats[v.key]["skipped_mixed_content"] += 1
            continue
        if len(piece) < MIN_EVAL_HANZI_CHARS:
            prepared_base.append(None)
            for v in vendors:
                stats[v.key]["skipped_too_short"] += 1
            continue
        gold = extract_hanzi(piece)
        if not gold:
            prepared_base.append(None)
            for v in vendors:
                stats[v.key]["skipped_no_hanzi"] += 1
            continue
        prepared_base.append({"index": i, "text": piece, "gold": gold})

    timings["prepare_segments_ms"] = round((time.perf_counter() - t_prep0) * 1000, 2)
    n_prepared = sum(1 for x in prepared_base if x is not None)
    n_skip = len(prepared_base) - n_prepared
    sk_h = stats[vendors[0].key]["skipped_no_hanzi"] if vendors else 0
    sk_m = stats[vendors[0].key]["skipped_mixed_content"] if vendors else 0
    sk_short = stats[vendors[0].key]["skipped_too_short"] if vendors else 0
    logger.info(
        "[预过滤] 完成: 耗时 %.2f ms | 候选 %d 句 | 跳过 %d 段（混合/非纯汉字或含 ASCII 数字字母: %d，"
        "纯汉字但不足 %d 字: %d，无汉字: %d）",
        timings["prepare_segments_ms"],
        n_prepared,
        n_skip,
        sk_m,
        MIN_EVAL_HANZI_CHARS,
        sk_short,
        sk_h,
    )

    try:
        root = repo_root()
        for v in vendors:
            ud_prep = v.data_dir(root)
            if ud_prep.is_dir():
                info = prepare_vendor_for_benchmark(ud_prep, v.schema_id)
                logger.info(
                    "[评测环境] %s 已移除 userdb %d 处；已合并 patch（禁用用户词库）→ %s",
                    v.key,
                    len(info["userdb_paths_removed"]),
                    info["custom_yaml"],
                )
            else:
                logger.warning("[评测环境] %s 用户目录不存在，跳过清理与 patch: %s", v.key, ud_prep)

        for v in vendors:
            st = stats[v.key]
            input_label = _vendor_input_label(v)
            logger.info("[输入串 %s] 开始: %s，共 %d 句", v.key, input_label, n_prepared)
            t_input0 = time.perf_counter()
            try:
                prepared_vendor: List[Dict[str, Any]] = []
                for slot in prepared_base:
                    if slot is None:
                        continue
                    raw_input = _build_vendor_input(v, slot["text"], root)
                    if not raw_input:
                        st["skipped_no_input"] += 1
                        continue
                    prepared_vendor.append(
                        {
                            "index": slot["index"],
                            "gold": slot["gold"],
                            "input": raw_input,
                        }
                    )
            except FileNotFoundError as e:
                input_ms = round((time.perf_counter() - t_input0) * 1000, 2)
                timings["vendors"][v.key] = {
                    "input_ms": input_ms,
                    "load_ms": 0.0,
                    "session_open_ms": 0.0,
                    "decode_ms": 0.0,
                }
                logger.warning("[输入串 %s] 失败: %.2f ms — %s", v.key, input_ms, e)
                continue
            input_ms = round((time.perf_counter() - t_input0) * 1000, 2)
            logger.info(
                "[输入串 %s] 完成: %s | 耗时 %.2f ms | 可解码 %d 句 | 缺少输入串 %d 句",
                v.key,
                input_label,
                input_ms,
                len(prepared_vendor),
                st["skipped_no_input"],
            )
            ud = v.data_dir()
            sd = shared_data_dir()
            logger.info(
                "[librime:加载方案 %s] 开始: schema_id=%s | shared_data_dir=%s | user_data_dir=%s",
                v.key,
                v.schema_id,
                sd,
                ud,
            )
            t_load0 = time.perf_counter()
            try:
                runner.switch_distro(v)
            except FileNotFoundError as e:
                for slot in prepared_vendor:
                    gold = slot["gold"]
                    st["sentences_total"] += 1
                    st["decode_failed"] += 1
                    _, cer = _accumulate_char_metrics(st, gold, "", False, norm)
                    rows.append(
                        {
                            "corpus": corpus_label,
                            "index": slot["index"],
                            "vendor": v.key,
                            "gold": gold,
                            "input": slot["input"],
                            "prediction": "",
                            "exact": False,
                            "cer": cer,
                            "error": str(e),
                        }
                    )
                load_ms = round((time.perf_counter() - t_load0) * 1000, 2)
                timings["vendors"][v.key] = {
                    "input_ms": input_ms,
                    "load_ms": load_ms,
                    "session_open_ms": 0.0,
                    "decode_ms": 0.0,
                }
                logger.warning(
                    "[librime:加载方案 %s] 失败: user_data_dir 不可用（耗时 %.2f ms）— %s",
                    v.key,
                    load_ms,
                    e,
                )
                continue

            load_ms = round((time.perf_counter() - t_load0) * 1000, 2)
            logger.info(
                "[librime:加载方案 %s] 完成，耗时 %.2f ms",
                v.key,
                load_ms,
            )
            logger.info(
                "[librime:解码 %s] 开始: 同一会话内逐句 feed_input + get_context（RimeSetInput 若可用），共 %d 句",
                v.key,
                len(prepared_vendor),
            )
            t_sess0 = time.perf_counter()
            session_ok = runner.begin_decode_batch()
            session_open_ms = round((time.perf_counter() - t_sess0) * 1000, 2)
            t_dec0 = time.perf_counter()
            done = 0
            try:
                if not session_ok:
                    logger.warning(
                        "[librime:解码 %s] 无法打开会话（create_session/select_schema），本方案全部记为解码失败",
                        v.key,
                    )
                    for slot in prepared_vendor:
                        st["sentences_total"] += 1
                        st["decode_failed"] += 1
                        gold = slot["gold"]
                        _, cer = _accumulate_char_metrics(st, gold, "", False, norm)
                        rows.append(
                            {
                                "corpus": corpus_label,
                                "index": slot["index"],
                                "vendor": v.key,
                                "gold": gold,
                                "input": slot["input"],
                                "prediction": "",
                                "exact": False,
                                "cer": cer,
                                "error": "batch_session_open_failed",
                            }
                        )
                        done += 1
                else:
                    for slot in prepared_vendor:
                        st["sentences_total"] += 1
                        res = runner.decode_input_in_batch(slot["input"])
                        pred = res.prediction if res.ok else ""
                        gold = slot["gold"]
                        if not res.ok:
                            st["decode_failed"] += 1
                        exact = res.ok and sentence_exact_match(norm(pred), norm(gold))
                        if exact:
                            st["exact_matches"] += 1
                        _, cer = _accumulate_char_metrics(st, gold, pred, res.ok, norm)

                        rows.append(
                            {
                                "corpus": corpus_label,
                                "index": slot["index"],
                                "vendor": v.key,
                                "gold": gold,
                                "input": slot["input"],
                                "prediction": pred,
                                "exact": exact,
                                "cer": cer,
                                "error": "" if res.ok else res.reason,
                            }
                        )
                        done += 1
                        if progress_every and done % progress_every == 0:
                            logger.info("[librime:解码 %s] 进度 %d / %d 句", v.key, done, len(prepared_vendor))
            finally:
                runner.end_decode_batch()

            decode_ms = round((time.perf_counter() - t_dec0) * 1000, 2)
            timings["vendors"][v.key] = {
                "input_ms": input_ms,
                "load_ms": load_ms,
                "session_open_ms": session_open_ms,
                "decode_ms": decode_ms,
            }
            logger.info(
                "[librime:解码 %s] 完成，本方案 %d 句 | 开会话+选方案 %.2f ms | 逐句解码 %.2f ms",
                v.key,
                done,
                session_open_ms,
                decode_ms,
            )
    finally:
        runner.close()

    logger.info("[汇总] 本语料各方案指标已计算")
    summary = _finalize_summary(stats, vendors)

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = artifact_base or f"benchmark_{corpus_label}_{stamp}"

    payload = {
        "generated_at_utc": stamp,
        "corpus_file": str(corpus_path),
        "corpus_label": corpus_label,
        "rime_dll": str(rime_dll),
        "vendors": [asdict(v) for v in vendors],
        "summary": summary,
        "per_sentence": rows,
        "timings": timings,
        "eval_synonyms": {
            "config_path": str(eval_synonyms_path.resolve())
            if eval_synonyms_path.is_file()
            else None,
            "rules_summary": eval_synonyms.summary_line(),
        },
    }

    if write_artifacts:
        t_w0 = time.perf_counter()
        logger.info("[写出结果] 写入 artifacts，前缀: %s", base)
        json_path = out_dir / f"{base}.json"
        csv_grouped = out_dir / f"{base}.csv"
        csv_long = out_dir / f"{base}_long.csv"
        csv_long_by_sentence = out_dir / f"{base}_long_by_sentence.csv"
        _write_sentence_grouped_csv(csv_grouped, rows, vendors)
        fn = list(_LONG_CSV_FIELDS)
        with csv_long.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fn)
            w.writeheader()
            for row in rows:
                w.writerow(row)
        _write_long_csv_by_sentence(csv_long_by_sentence, rows, vendors)
        path_scheme = out_dir / f"{base}_scheme_compare.txt"
        _write_scheme_compare_txt(
            path_scheme,
            generated_utc=stamp,
            mode=f"单语料 ({corpus_label})",
            per_sentence=rows,
            vendors=vendors,
        )
        sum_rows = _summary_csv_rows_for_block(corpus_label, summary, vendors)
        _write_summary_csv(out_dir / f"{base}_summary.csv", sum_rows)
        timings["write_artifacts_ms"] = round((time.perf_counter() - t_w0) * 1000, 2)
        payload["timings"] = timings
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_report_txt(
            out_dir / f"{base}_report.txt",
            generated_utc=stamp,
            rime_dll=str(rime_dll),
            corpus_files={corpus_label: str(corpus_path)},
            summary_by_corpus=None,
            summary_overall=summary,
            vendors=vendors,
            mode=f"单语料 ({corpus_label})",
            timings_one_corpus=timings,
            eval_synonyms_summary=eval_synonyms.summary_line(),
        )
        logger.info(
            "[写出结果] 完成: 耗时 %.2f ms | %s | %s | %s | %s | %s | %s_report.txt",
            timings["write_artifacts_ms"],
            json_path.name,
            csv_grouped.name,
            csv_long.name,
            csv_long_by_sentence.name,
            path_scheme.name,
            base,
        )

    return payload


def _write_combined_artifacts(
    out_dir: Path,
    stamp: str,
    base: str,
    payload: Dict[str, Any],
    vendors: List[VendorConfig],
    *,
    wall_clock_start: Optional[float] = None,
) -> None:
    t_write0 = time.perf_counter()
    logger.info("[写出结果] 合并 artifacts，前缀: %s", base)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{base}.json"
    csv_grouped = out_dir / f"{base}.csv"
    csv_long = out_dir / f"{base}_long.csv"
    csv_long_by_sentence = out_dir / f"{base}_long_by_sentence.csv"
    _write_sentence_grouped_csv(csv_grouped, payload["per_sentence"], vendors)
    fn = list(_LONG_CSV_FIELDS)
    with csv_long.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fn)
        w.writeheader()
        for row in payload["per_sentence"]:
            w.writerow(row)
    _write_long_csv_by_sentence(csv_long_by_sentence, payload["per_sentence"], vendors)
    path_scheme = out_dir / f"{base}_scheme_compare.txt"
    _write_scheme_compare_txt(
        path_scheme,
        generated_utc=stamp,
        mode="全部语料 (data/corpus/*.txt)",
        per_sentence=payload["per_sentence"],
        vendors=vendors,
    )
    _write_multi_summary_csv(
        out_dir / f"{base}_summary.csv",
        payload["summary_by_corpus"],
        payload["summary_overall"],
        vendors,
    )
    t_after_csv = time.perf_counter()
    payload["timings_csv_ms"] = round((t_after_csv - t_write0) * 1000, 2)

    t_j0 = time.perf_counter()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    t_j1 = time.perf_counter()
    j1 = round((t_j1 - t_j0) * 1000, 2)
    payload["timings_json_write_ms"] = j1
    payload["timings_combined_write_ms"] = round((t_j1 - t_write0) * 1000, 2)
    if wall_clock_start is not None:
        payload["timings_wall_total_ms"] = round(
            (t_j1 - wall_clock_start) * 1000, 2
        )

    t_r0 = time.perf_counter()
    _es = payload.get("eval_synonyms") or {}
    _write_report_txt(
        out_dir / f"{base}_report.txt",
        generated_utc=stamp,
        rime_dll=str(payload.get("rime_dll", "")),
        corpus_files=payload.get("corpus_files"),
        summary_by_corpus=payload["summary_by_corpus"],
        summary_overall=payload["summary_overall"],
        vendors=vendors,
        mode="全部语料 (data/corpus/*.txt)",
        timings_by_corpus=payload.get("timings_by_corpus"),
        timings_wall_total_ms=None,
        eval_synonyms_summary=_es.get("rules_summary"),
    )
    t_r1 = time.perf_counter()
    payload["timings_report_write_ms"] = round((t_r1 - t_r0) * 1000, 2)
    payload["timings_combined_write_ms"] = round((t_r1 - t_write0) * 1000, 2)
    if wall_clock_start is not None:
        payload["timings_wall_total_ms"] = round(
            (t_r1 - wall_clock_start) * 1000, 2
        )

    t_j2 = time.perf_counter()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    j2 = round((time.perf_counter() - t_j2) * 1000, 2)
    payload["timings_json_write_ms"] = round(j1 + j2, 2)
    payload["timings_combined_write_ms"] = round((time.perf_counter() - t_write0) * 1000, 2)
    if wall_clock_start is not None:
        payload["timings_wall_total_ms"] = round(
            (time.perf_counter() - wall_clock_start) * 1000, 2
        )

    _write_report_txt(
        out_dir / f"{base}_report.txt",
        generated_utc=stamp,
        rime_dll=str(payload.get("rime_dll", "")),
        corpus_files=payload.get("corpus_files"),
        summary_by_corpus=payload["summary_by_corpus"],
        summary_overall=payload["summary_overall"],
        vendors=vendors,
        mode="全部语料 (data/corpus/*.txt)",
        timings_by_corpus=payload.get("timings_by_corpus"),
        timings_wall_total_ms=payload.get("timings_wall_total_ms"),
        eval_synonyms_summary=_es.get("rules_summary"),
    )
    if wall_clock_start is not None:
        payload["timings_wall_total_ms"] = round(
            (time.perf_counter() - wall_clock_start) * 1000, 2
        )
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(
        "[写出结果] 合并完成: 写文件 %.2f ms | 墙钟总计 %.2f ms | %s | %s | %s | %s | %s",
        float(payload.get("timings_combined_write_ms", 0) or 0),
        float(payload.get("timings_wall_total_ms", 0) or 0),
        json_path.name,
        csv_grouped.name,
        csv_long.name,
        csv_long_by_sentence.name,
        path_scheme.name,
    )


def _write_multi_summary_csv(
    path: Path,
    summary_by_corpus: Dict[str, Dict[str, Any]],
    summary_overall: Dict[str, Any],
    vendors: List[VendorConfig],
) -> None:
    rows: List[Dict[str, Any]] = []
    for stem, block in summary_by_corpus.items():
        rows.extend(_summary_csv_rows_for_block(stem, block, vendors))
    rows.extend(_summary_csv_rows_for_block("ALL", summary_overall, vendors))
    _write_summary_csv(path, rows)


def main() -> None:
    _setup_logging()
    p = argparse.ArgumentParser(description="Rime whole-sentence decoding benchmark")
    p.add_argument(
        "--corpus",
        type=Path,
        nargs="*",
        default=None,
        help="UTF-8 text file(s). Omit to run all *.txt under data/corpus/.",
    )
    p.add_argument(
        "--label",
        type=str,
        default="",
        help="Tag for results when a single --corpus is given (default: file stem); ignored for multi-corpus runs",
    )
    p.add_argument("--out-dir", type=Path, default=Path("artifacts"), help="Output directory")
    p.add_argument("--rime-dll", type=str, default="", help="Override rime.dll path")
    p.add_argument(
        "--vendors",
        nargs="*",
        default=None,
        help="Subset of vendor keys: mingyuepinyin mingyuepinyin_with_gram rime_ice rime_ice_with_gram rime_frost rime_frost_with_gram wanxiang rime_wanxiang_with_gram rime_wubi_sentens_wubi86 rime_wubi_sentens_wubi86_with_gram rime_wubi_sentens_tiger rime_wubi_sentens_ziyuan",
    )
    p.add_argument("--progress-every", type=int, default=50, help="Print progress every N raw segments (0=off)")
    p.add_argument(
        "--eval-synonyms",
        type=Path,
        default=None,
        help="同义词评测 JSON（默认 data/eval_synonyms.json；文件不存在则用内置规则）",
    )
    args = p.parse_args()

    root = repo_root()
    logger.info("[启动] 仓库根目录: %s", root)
    out_dir = args.out_dir if args.out_dir.is_absolute() else root / args.out_dir
    dll = resolve_rime_dll(args.rime_dll or None)
    logger.info("[启动] rime.dll: %s", dll)
    sd0 = shared_data_dir(root)
    logger.info("[启动] 各方案共用的 shared_data_dir: %s", sd0)
    vendors = _filter_unavailable_vendors(root, _pick_vendors(args.vendors))
    logger.info(
        "[启动] 将对比 %d 套方案: %s",
        len(vendors),
        ", ".join(f"{v.key}(schema={v.schema_id})" for v in vendors),
    )
    syn_cfg, syn_path = _init_eval_synonyms(root, args.eval_synonyms)
    logger.info("[评测] 同义词归一化: %s", syn_cfg.summary_line())
    logger.info(
        "[评测] 同义词配置: %s",
        syn_path if syn_path.is_file() else f"{syn_path}（不存在，使用内置）",
    )

    corpora: List[Tuple[Path, str]]
    if args.corpus is None or len(args.corpus) == 0:
        corpora = default_corpus_files(root)
        if not corpora:
            raise SystemExit(f"No *.txt found under {root / 'data' / 'corpus'}")
        logger.info("[语料列表] 未传 --corpus，使用 data/corpus/*.txt 共 %d 个:", len(corpora))
        for p, stem in corpora:
            logger.info("[语料列表]   - %s → %s", stem, p)
    else:
        corpora = []
        for c in args.corpus:
            path = c if c.is_absolute() else root / c
            if not path.is_file():
                raise SystemExit(f"Corpus not found: {path}")
            corpora.append((path.resolve(), path.stem))
        logger.info("[语料列表] 指定 %d 个文件:", len(corpora))
        for p, stem in corpora:
            logger.info("[语料列表]   - %s → %s", stem, p)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if len(corpora) == 1:
        corpus_path, stem = corpora[0]
        label = args.label or stem
        payload = run_benchmark(
            corpus_path=corpus_path,
            out_dir=out_dir,
            rime_dll=dll,
            vendors=vendors,
            corpus_label=label,
            progress_every=args.progress_every,
            eval_synonyms=syn_cfg,
            eval_synonyms_path=syn_path,
            write_artifacts=True,
            stamp=stamp,
            artifact_base=f"benchmark_{label}_{stamp}",
        )
        print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
        art = f"benchmark_{label}_{stamp}"
        logger.info(
            "[结束] 单语料评测完成 | 方案对比: %s_scheme_compare.txt | 输出目录: %s",
            art,
            out_dir.resolve(),
        )
        return

    if args.label:
        logger.warning("[启动] --label 在多语料模式下会被忽略")

    logger.info(
        "[流程] 多语料模式: 依次执行 [分句]→[输入串]→[librime:各方案] 共 %d 轮，最后 [聚合]+[写出结果]",
        len(corpora),
    )
    all_rows: List[Dict[str, Any]] = []
    summary_by_corpus: Dict[str, Dict[str, Any]] = {}
    corpus_files: Dict[str, str] = {}
    timings_by_corpus: Dict[str, Dict[str, Any]] = {}
    t_wall = time.perf_counter()

    for idx, (corpus_path, stem) in enumerate(corpora, start=1):
        logger.info(
            ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"
        )
        logger.info(
            "[大步骤 %d/%d] 语料 «%s» — 将执行 [分句] [输入串] [librime×%d]",
            idx,
            len(corpora),
            stem,
            len(vendors),
        )
        part = run_benchmark(
            corpus_path=corpus_path,
            out_dir=out_dir,
            rime_dll=dll,
            vendors=vendors,
            corpus_label=stem,
            progress_every=args.progress_every,
            eval_synonyms=syn_cfg,
            eval_synonyms_path=syn_path,
            write_artifacts=False,
            stamp=stamp,
        )
        all_rows.extend(part["per_sentence"])
        summary_by_corpus[stem] = part["summary"]
        corpus_files[stem] = str(corpus_path)
        timings_by_corpus[stem] = part.get("timings") or {}

    logger.info("[聚合] 全部语料已跑完，正在合并各语料 summary → summary_overall …")
    t_agg0 = time.perf_counter()
    summary_overall = _aggregate_summaries(summary_by_corpus, vendors)
    aggregate_ms = round((time.perf_counter() - t_agg0) * 1000, 2)
    logger.info("[聚合] 完成，耗时 %.2f ms", aggregate_ms)
    base = f"benchmark_all_corpus_{stamp}"
    payload = {
        "generated_at_utc": stamp,
        "corpus_mode": "all",
        "corpus_files": corpus_files,
        "rime_dll": str(dll),
        "vendors": [asdict(v) for v in vendors],
        "summary_by_corpus": summary_by_corpus,
        "summary_overall": summary_overall,
        "per_sentence": all_rows,
        "timings_by_corpus": timings_by_corpus,
        "timings_aggregate_ms": aggregate_ms,
        "eval_synonyms": {
            "config_path": str(syn_path.resolve()) if syn_path.is_file() else None,
            "rules_summary": syn_cfg.summary_line(),
        },
    }
    _write_combined_artifacts(out_dir, stamp, base, payload, vendors, wall_clock_start=t_wall)

    print(json.dumps({"summary_by_corpus": summary_by_corpus, "summary_overall": summary_overall}, ensure_ascii=False, indent=2))
    logger.info(
        "[结束] 多语料评测完成 | 墙钟总计约 %.2f ms | 主 CSV: %s | 按句窄表: %s | 方案对比: %s | 摘要: %s",
        float(payload.get("timings_wall_total_ms", 0) or 0),
        f"{base}.csv",
        f"{base}_long_by_sentence.csv",
        f"{base}_scheme_compare.txt",
        f"{base}_report.txt",
    )


if __name__ == "__main__":
    main()
