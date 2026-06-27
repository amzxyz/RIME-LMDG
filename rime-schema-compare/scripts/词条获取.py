#!/usr/bin/env python3
"""
生成式纠错数据提取 (倒序精准借词 & 分组免疫版)
1. 倒序最大匹配 (RMM)：自错误位置向左倒序查词，完美避免正向切词导致的边界割裂（如"好数/学"）。
2. 强制向左借词：保证片段长度达到 4~5 字，凑够立刻停止。
3. 分组互换免疫：支持配置多组免疫词（如 他/她/它 一组，买/卖 一组），同组互换不输出。
4. 剔除单字：过滤掉长度 <= 2 的无意义短句。
5. 极简流式输出：只输出 [correct, wrong] 两列。
"""

from __future__ import annotations

import argparse
import csv
import difflib
import logging
import sys
from pathlib import Path
from typing import List, Tuple

if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

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
from rime_schema_compare.config import DEFAULT_VENDORS, VendorConfig, resolve_rime_dll, repo_root
from rime_schema_compare.rime_runner import RimeDistroRunner
from rime_schema_compare.text_pipeline import (
    MIN_EVAL_HANZI_CHARS, extract_hanzi, is_pure_hanzi_segment,
    segment_has_ascii_digit_or_letter, sentence_to_continuous_pinyin,
    sentence_to_shape_code_prefix_input, split_sentences,
)

try:
    import opencc
    t2s_converter = opencc.OpenCC('t2s')
except ImportError:
    t2s_converter = None

logger = logging.getLogger("extract_training_data")

def _setup_logging() -> None:
    if logger.handlers:
        return
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.propagate = False

def _pick_wanxiang_vendors() -> List[VendorConfig]:
    target_keys = {"rime_wanxiang_with_gram"} 
    out = [v for v in DEFAULT_VENDORS if v.key in target_keys]
    if not out:
        raise SystemExit("Error: 未找到万象相关方案！")
    return out

def _build_vendor_input(vendor: VendorConfig, text: str, root: Path) -> str:
    if vendor.input_mode == "pinyin":
        return sentence_to_continuous_pinyin(text)
    if vendor.input_mode == "shape_code_prefix":
        dict_path = vendor.input_dict_path(root)
        return sentence_to_shape_code_prefix_input(text, dict_path, vendor.input_code_prefix_len)
    raise ValueError(f"Unsupported input_mode: {vendor.input_mode}")

def scan_data_directory(target_dir: Path) -> Tuple[List[Path], Path]:
    corpora = []
    dict_path = None
    if not target_dir.is_dir():
        return corpora, dict_path
    for p in target_dir.iterdir():
        if p.is_file():
            if p.suffix.lower() in [".yaml", ".yml"]:
                dict_path = p
            elif p.suffix.lower() == ".txt":
                if "jichu" in p.name.lower():
                    dict_path = p
                else:
                    corpora.append(p)
    return sorted(corpora), dict_path

def load_dictionary(dict_path: Path) -> set:
    vocab = set()
    if not dict_path or not dict_path.is_file():
        logger.warning("⚠️ 未找到词库，降级为单字模式。")
        return vocab
    logger.info(f"📚 正在加载词库文件: {dict_path.name} ...")
    with open(dict_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('-') or ':' in line:
                continue
            parts = line.split('\t')
            if parts:
                word = parts[0].strip()
                if word:
                    vocab.add(word)
    logger.info(f"✅ 基础词库加载完毕: {len(vocab)} 条")
    return vocab


# =========================================================
# 🌟 核心重构区：倒序最大匹配 (RMM) 与 免疫分组
# =========================================================

# 免疫词分组（同一括号内的字互换直接视为正确）
IMMUNITY_SETS = [
    {'他', '她', '它'},
    {'买', '卖'}
]

def extract_error_pairs_with_rmm(gold: str, pred: str, vocab: set, target_min: int = 4) -> list[tuple[str, str]]:
    pairs = []
    matcher = difflib.SequenceMatcher(None, gold, pred)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('replace', 'insert', 'delete'):
            err_gold = gold[i1:i2]
            err_pred = pred[j1:j2]
            
            # 🌟 1. 同组字互换免疫机制 (如 他/她/它 错乱，直接无视)
            if tag == 'replace' and len(err_gold) == len(err_pred):
                is_immune = True
                for g_char, p_char in zip(err_gold, err_pred):
                    if not any((g_char in immune_group and p_char in immune_group) for immune_group in IMMUNITY_SETS):
                        is_immune = False
                        break
                if is_immune:
                    continue 

            # 🌟 2. 从错误边界 (i1) 开启倒序最大匹配 (RMM) 借词
            prefix_gold = gold[:i1] # 截取错误位置之前的所有字符串
            added_context_gold = ""
            idx = len(prefix_gold)  # 游标放在紧贴错误字的前方
            
            # 只要总长度不够目标 (4~5字)，就继续向左借词
            while idx > 0 and (len(added_context_gold) + len(err_gold) < target_min):
                matched = False
                # 从最大词长 5 开始倒序尝试匹配
                for length in range(min(5, idx), 0, -1):
                    cand = prefix_gold[idx - length : idx]
                    if cand in vocab or length == 1:
                        added_context_gold = cand + added_context_gold
                        idx -= length
                        matched = True
                        break

            final_gold = added_context_gold + err_gold
            
            # 🌟 3. 在预测结果中截取等量的前置上下文
            pred_context_start = max(0, j1 - len(added_context_gold))
            final_pred = pred[pred_context_start:j1] + err_pred
            
            # 🌟 4. 极致过滤（过滤 <= 2字的无效短片）
            if len(final_gold) <= 2:
                continue
                
            if final_gold != final_pred:
                pairs.append((final_gold, final_pred))
                
    return pairs

# =========================================================

def main() -> None:
    _setup_logging()
    p = argparse.ArgumentParser(description="语料纠错片段提取 - 倒序借词版")
    p.add_argument("--data-dir", type=Path, default=Path("data/corpus"), help="目录")
    p.add_argument("--out", type=Path, default=Path("artifacts/training_pairs.csv"), help="输出")
    p.add_argument("--rime-dll", type=str, default="", help="DLL路径")
    args = p.parse_args()

    if not t2s_converter:
        logger.error("未安装 OpenCC！请先 pip install opencc")
        sys.exit(1)

    root = repo_root()
    dll = resolve_rime_dll(args.rime_dll or None)
    vendors = _pick_wanxiang_vendors()
    
    target_dir = args.data_dir if args.data_dir.is_absolute() else root / args.data_dir
    corpora, dict_path = scan_data_directory(target_dir)
    
    if not corpora:
        logger.error(f"❌ 未找到txt语料")
        sys.exit(1)

    jichu_vocab = load_dictionary(dict_path)
    runner = RimeDistroRunner(dll)
    extracted_count = 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    
    with args.out.open("w", encoding="utf-8", newline="") as out_file:
        writer = csv.writer(out_file)
        writer.writerow(["correct", "wrong"])

        try:
            for v in vendors:
                ud_prep = v.data_dir(root)
                if ud_prep.is_dir():
                    prepare_vendor_for_benchmark(ud_prep, v.schema_id)
                    
                runner.switch_distro(v)
                for corpus_path in corpora:
                    text = corpus_path.read_text(encoding="utf-8")
                    raw_sents = split_sentences(text)
                    
                    prepared = []
                    for seg in raw_sents:
                        piece = seg.strip()
                        if not piece or segment_has_ascii_digit_or_letter(piece) or not is_pure_hanzi_segment(piece):
                            continue
                        if len(piece) < MIN_EVAL_HANZI_CHARS:
                            continue
                        gold = extract_hanzi(piece)
                        if gold:
                            raw_input = _build_vendor_input(v, piece, root)
                            if raw_input:
                                prepared.append({"gold": gold, "input": raw_input})

                    runner.begin_decode_batch()
                    try:
                        for slot in prepared:
                            res = runner.decode_input_in_batch(slot["input"])
                            pred = res.prediction if res.ok else ""
                            gold = slot["gold"]

                            if not pred:
                                continue

                            pred_simp = t2s_converter.convert(pred)
                            gold_simp = t2s_converter.convert(gold)

                            if pred_simp != gold_simp:
                                # target_min=4 保证片段最小长度，不够就触发倒序借词
                                pairs = extract_error_pairs_with_rmm(gold_simp, pred_simp, vocab=jichu_vocab, target_min=4)
                                
                                for c_frag, w_frag in pairs:
                                    if c_frag.strip() or w_frag.strip():
                                        writer.writerow([c_frag, w_frag])
                                        out_file.flush()
                                        extracted_count += 1
                    finally:
                        runner.end_decode_batch()
        finally:
            runner.close()

    logger.info(f"✅ 完美提取！共流式写入 {extracted_count} 对纠错数据至 {args.out.resolve()}")

if __name__ == "__main__":
    main()
