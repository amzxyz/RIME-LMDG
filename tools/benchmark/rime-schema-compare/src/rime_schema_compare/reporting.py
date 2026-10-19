"""Shared artifact writers for benchmark scripts."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .text_pipeline import MIN_EVAL_HANZI_CHARS


def _vendor_key(vendor: Any) -> str:
    if isinstance(vendor, str):
        return vendor
    key = getattr(vendor, "key", None)
    if isinstance(key, str) and key:
        return key
    raise TypeError(f"Unsupported vendor entry: {vendor!r}")


def summary_csv_rows_for_block(
    corpus_label: str,
    block: Dict[str, Any],
    vendors: Sequence[Any],
) -> List[Dict[str, Any]]:
    rows_out: List[Dict[str, Any]] = []
    for vendor in vendors:
        key = _vendor_key(vendor)
        s = block.get(key) or {}
        rows_out.append(
            {
                "corpus": corpus_label,
                "vendor": key,
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


def write_summary_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
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


def _sentence_grouped_fieldnames(vendors: Sequence[Any]) -> List[str]:
    fieldnames: List[str] = ["corpus", "index", "gold"]
    for vendor in vendors:
        key = _vendor_key(vendor)
        fieldnames.extend(
            [
                f"{key}_input",
                f"{key}_sentence_correct",
                f"{key}_character_accuracy_percent",
                f"{key}_prediction",
                f"{key}_error",
            ]
        )
    return fieldnames


LONG_CSV_FIELDS = (
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


def write_long_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(LONG_CSV_FIELDS))
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _build_long_rows_by_sentence(
    per_sentence: List[Dict[str, Any]],
    vendors: Sequence[Any],
) -> List[Dict[str, Any]]:
    order: List[Tuple[Any, ...]] = []
    seen: Set[Tuple[Any, ...]] = set()
    for row in per_sentence:
        key = (row["corpus"], row["index"], row["gold"])
        if key not in seen:
            seen.add(key)
            order.append(key)

    by_key_vendor: Dict[Tuple[Tuple[Any, ...], str], Dict[str, Any]] = {}
    for row in per_sentence:
        key = (row["corpus"], row["index"], row["gold"])
        by_key_vendor[(key, row["vendor"])] = row

    out: List[Dict[str, Any]] = []
    vendor_keys = [_vendor_key(v) for v in vendors]
    for key in order:
        for vendor_key in vendor_keys:
            row = by_key_vendor.get((key, vendor_key))
            if row is not None:
                out.append(row)
    return out


def write_long_csv_by_sentence(
    path: Path,
    per_sentence: List[Dict[str, Any]],
    vendors: Sequence[Any],
) -> None:
    rows = _build_long_rows_by_sentence(per_sentence, vendors)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(LONG_CSV_FIELDS), extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _exact_map_by_sentence(
    per_sentence: List[Dict[str, Any]],
    vendors: Sequence[Any],
) -> Tuple[List[Tuple[Any, ...]], Dict[Tuple[Any, ...], Dict[str, bool]]]:
    order: List[Tuple[Any, ...]] = []
    seen: Set[Tuple[Any, ...]] = set()
    for row in per_sentence:
        key = (row["corpus"], row["index"], row["gold"])
        if key not in seen:
            seen.add(key)
            order.append(key)
    want = {_vendor_key(v) for v in vendors}
    by_key: Dict[Tuple[Any, ...], Dict[str, bool]] = {key: {vk: False for vk in want} for key in order}
    for row in per_sentence:
        key = (row["corpus"], row["index"], row["gold"])
        vendor_key = row["vendor"]
        if vendor_key in want:
            by_key[key][vendor_key] = bool(row.get("exact"))
    return order, by_key


def write_scheme_compare_txt(
    path: Path,
    *,
    generated_utc: str,
    mode: str,
    per_sentence: List[Dict[str, Any]],
    vendors: Sequence[Any],
    title: str = "各方案相对其他方案的整句判对对比",
) -> None:
    order, by_key = _exact_map_by_sentence(per_sentence, vendors)
    vendor_keys = [_vendor_key(v) for v in vendors]
    lines: List[str] = [
        "=" * 72,
        title,
        "=" * 72,
        f"生成时间 (UTC): {generated_utc}",
        f"模式: {mode}",
        "",
        "说明:",
        "  · 「仅本方案判对」：该句仅当前方案整句与金文完全一致，其余参与对比的方案均未判对。",
        "  · 「相对 [X] 多判对」：当前方案判对且方案 X 未判对（不要求其他方案是否判对）。",
        "",
    ]
    for vendor_key in vendor_keys:
        lines.append("-" * 72)
        lines.append(f"【{vendor_key}】")
        others = [x for x in vendor_keys if x != vendor_key]
        exclusive = [
            key for key in order if by_key[key].get(vendor_key) and all(not by_key[key].get(o) for o in others)
        ]
        lines.append(f"· 仅本方案判对（其余 {len(others)} 个方案均未判对）: {len(exclusive)} 句")
        if exclusive:
            for corpus, idx, gold in exclusive:
                lines.append(f"    [{corpus} #{idx}] {gold}")
        else:
            lines.append("    （无）")
        lines.append("")
        for other in others:
            wins = [key for key in order if by_key[key].get(vendor_key) and not by_key[key].get(other)]
            lines.append(f"· 相对 [{other}] 多判对（本对、对方错）: {len(wins)} 句")
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
    vendors: Sequence[Any],
) -> List[Dict[str, Any]]:
    order: List[Tuple[Any, ...]] = []
    seen: Set[Tuple[Any, ...]] = set()
    for row in per_sentence:
        key = (row["corpus"], row["index"], row["gold"])
        if key not in seen:
            seen.add(key)
            order.append(key)

    fieldnames = _sentence_grouped_fieldnames(vendors)
    groups: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for key in order:
        row: Dict[str, Any] = {fn: "" for fn in fieldnames}
        row["corpus"], row["index"], row["gold"] = key[0], key[1], key[2]
        groups[key] = row

    for row in per_sentence:
        key = (row["corpus"], row["index"], row["gold"])
        grouped = groups[key]
        vendor_key = row["vendor"]
        grouped[f"{vendor_key}_input"] = row.get("input", "") or ""
        grouped[f"{vendor_key}_sentence_correct"] = "1" if row.get("exact") else "0"
        cer = row.get("cer")
        cer_f = float(cer) if isinstance(cer, (int, float)) else None
        cap = _per_sentence_char_accuracy_percent(cer_f)
        grouped[f"{vendor_key}_character_accuracy_percent"] = "" if cap is None else str(cap)
        grouped[f"{vendor_key}_prediction"] = row.get("prediction", "") or ""
        grouped[f"{vendor_key}_error"] = row.get("error", "") or ""

    return [groups[key] for key in order]


def write_sentence_grouped_csv(
    path: Path,
    per_sentence: List[Dict[str, Any]],
    vendors: Sequence[Any],
) -> None:
    rows = _build_sentence_grouped_rows(per_sentence, vendors)
    fieldnames = _sentence_grouped_fieldnames(vendors)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _vendor_summary_lines(vendor_key: str, summary: Dict[str, Any]) -> List[str]:
    sp = summary.get("sentence_accuracy_percent")
    cp = summary.get("character_accuracy_percent")
    sc = summary.get("sentence_correct_count", 0)
    st = summary.get("sentence_total", 0)
    lines = [
        f"  [{vendor_key}]",
        f"    句子正确率: {sp}%  ({sc}/{st} 句完全匹配)",
        f"    文字正确率: {cp}%  (全语料金文加权，基于 Levenshtein)",
    ]
    mean_sent = summary.get("character_accuracy_mean_of_sentences_percent")
    if mean_sent is not None:
        lines.append(f"    文字正确率(逐句平均): {mean_sent}%")
    return lines


def format_timings_lines(timings: Dict[str, Any], indent: str = "  ") -> List[str]:
    if not timings:
        return []
    lines: List[str] = [
        f"{indent}读取文件: {timings.get('read_text_ms', '—')} ms",
        f"{indent}分句: {timings.get('split_ms', '—')} ms",
        f"{indent}预过滤: {timings.get('prepare_segments_ms', '—')} ms",
    ]
    for vendor_key, vendor_timings in sorted((timings.get("vendors") or {}).items()):
        if not isinstance(vendor_timings, dict):
            continue
        custom_parts = vendor_timings.get("display_parts")
        if isinstance(custom_parts, list) and custom_parts:
            lines.append(f"{indent}[{vendor_key}] " + ", ".join(str(part) for part in custom_parts))
            continue
        parts: List[str] = []
        if vendor_timings.get("input_ms") is not None:
            parts.append(f"输入串: {vendor_timings.get('input_ms', '—')} ms")
        if vendor_timings.get("load_ms") is not None:
            parts.append(f"librime 加载: {vendor_timings.get('load_ms', '—')} ms")
        if vendor_timings.get("session_open_ms") is not None:
            parts.append(f"开会话+选方案: {vendor_timings.get('session_open_ms', '—')} ms")
        if vendor_timings.get("launch_ms") is not None:
            parts.append(f"宿主启动: {vendor_timings.get('launch_ms', '—')} ms")
        if vendor_timings.get("self_check_ms") is not None:
            parts.append(f"环境自检: {vendor_timings.get('self_check_ms', '—')} ms")
        if vendor_timings.get("decode_ms") is not None:
            decode_label = vendor_timings.get("decode_label", "逐句解码")
            parts.append(f"{decode_label}: {vendor_timings.get('decode_ms', '—')} ms")
        if parts:
            lines.append(f"{indent}[{vendor_key}] " + ", ".join(parts))
    write_ms = timings.get("write_artifacts_ms")
    if write_ms is not None:
        lines.append(f"{indent}写出结果文件: {write_ms} ms")
    return lines


def write_report_txt(
    path: Path,
    *,
    generated_utc: str,
    title: str,
    engine_label: str,
    engine_value: str,
    corpus_files: Optional[Dict[str, str]],
    summary_by_corpus: Optional[Dict[str, Dict[str, Any]]],
    summary_overall: Dict[str, Any],
    vendors: Sequence[Any],
    mode: str,
    timings_one_corpus: Optional[Dict[str, Any]] = None,
    timings_by_corpus: Optional[Dict[str, Dict[str, Any]]] = None,
    timings_wall_total_ms: Optional[float] = None,
    eval_synonyms_summary: Optional[str] = None,
    footer_note: Optional[str] = None,
) -> None:
    lines: List[str] = [
        "=" * 72,
        title,
        "=" * 72,
        f"生成时间 (UTC): {generated_utc}",
        f"{engine_label}: {engine_value}",
        f"模式: {mode}",
        "",
    ]
    if corpus_files:
        lines.append("语料文件:")
        for stem, fp in sorted(corpus_files.items()):
            lines.append(f"  - {stem}: {fp}")
        lines.append("")

    lines.append("【总体】")
    for vendor in vendors:
        key = _vendor_key(vendor)
        lines.extend(_vendor_summary_lines(key, summary_overall.get(key) or {}))
        lines.append("")

    if summary_by_corpus:
        for stem in sorted(summary_by_corpus.keys()):
            lines.append("-" * 72)
            lines.append(f"【语料: {stem}】")
            block = summary_by_corpus[stem]
            for vendor in vendors:
                key = _vendor_key(vendor)
                lines.extend(_vendor_summary_lines(key, block.get(key) or {}))
                lines.append("")

    lines.append("=" * 72)
    if timings_one_corpus:
        lines.append("【耗时】")
        lines.extend(format_timings_lines(timings_one_corpus))
        lines.append("")
    if timings_wall_total_ms is not None:
        lines.append(f"【总耗时】全流程墙钟约 {timings_wall_total_ms} ms（多语料）")
        lines.append("")
    if timings_by_corpus:
        lines.append("【各语料耗时】")
        for stem in sorted(timings_by_corpus.keys()):
            lines.append(f"  · {stem}")
            lines.extend(format_timings_lines(timings_by_corpus[stem], indent='    '))
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
    )
    if footer_note:
        lines.append(footer_note)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_multi_summary_csv(
    path: Path,
    summary_by_corpus: Dict[str, Dict[str, Any]],
    summary_overall: Dict[str, Any],
    vendors: Sequence[Any],
) -> None:
    rows: List[Dict[str, Any]] = []
    for stem, block in sorted(summary_by_corpus.items()):
        rows.extend(summary_csv_rows_for_block(stem, block, vendors))
    rows.extend(summary_csv_rows_for_block("ALL", summary_overall, vendors))
    write_summary_csv(path, rows)
