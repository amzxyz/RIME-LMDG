#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rime固定词典或者用户词典刷新为带辅助码的格式.py
────────────────────────────────────────────────────────
功能：给第一列是汉字的词典批量添加“拼音+辅助码”。
⚠ 仅保证辅助码正确；拼音可能多音字错误，需后续“刷拼音”脚本修正。
包含了中英混排（如 AI绘画、AB型血）的智能对齐逻辑。
"""

from __future__ import annotations
import os, re, shutil
from pathlib import Path
from typing import Dict, List, Optional

# ─────────────── 配 置 区 ────────────────
INPUT_PATH  = "/home/amz/Documents/输入法方案/万象拼音/dicts/jichu.dict.yaml"          # 目录或单文件
OUTPUT_PATH = "/home/amz/Documents/输入法方案/万象拼音/dicts/outjichu.dict.yaml"       # 目录或文件；智能判断
AUX_FILE    = "/home/amz/Documents/输入法方案/转换目录/merged_dict.txt"  # 格式 你\tni;re  你\t;re  你\tre 三种格式都支持
# ──────────────────────────────────────

AUX_SEP_REGEX = r'[;\[]'
yaml_heads = ('---', 'name:', 'version:', 'sort:', '...')

# 极广的汉字正则匹配：涵盖基础汉字、扩展区 A-H 以及 "〇"
CJK_PATTERN = re.compile(r'[〇\u3400-\u4DBF\u4E00-\u9FFF\U00020000-\U000323AF]')

# ---------- 判断输出路径像目录 ----------
def is_dir_like(p: str) -> bool:
    return (p.endswith(('/', '\\'))       
            or os.path.isdir(p)           
            or not os.path.splitext(p)[1])

# ---------- 加载辅助码映射 ----------
def load_aux_metadata(path: str) -> Dict[str, str]:
    aux_map: Dict[str, str] = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            if not line.strip() or line.startswith('#'):
                continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 2 or len(parts[0]) != 1:
                continue
            char = parts[0]
            seg_full = parts[1]
            seg_parts = re.split(AUX_SEP_REGEX, seg_full, maxsplit=1)
            if len(seg_parts) > 1:
                aux_map[char] = seg_parts[1].strip()
            else:
                aux_map[char] = seg_full.strip()
            if aux_map[char] == ';':
                aux_map[char] = ''
    print(f"✓ 辅助码加载 {len(aux_map)} 条")
    return aux_map

# ---------- 核心：中英文本边界解析与智能对齐 ----------
def tokenize_word(word: str) -> List[Dict[str, str]]:
    """将词组按照汉字和非汉字块进行拆分"""
    units = []
    buf = []
    for char in word:
        if char.isspace(): # 忽略词组中可能出现的空格
            continue
        if CJK_PATTERN.match(char):
            if buf:
                units.append({'type': 'en', 'text': ''.join(buf)})
                buf = []
            units.append({'type': 'cn', 'text': char})
        else:
            buf.append(char)
    if buf:
        units.append({'type': 'en', 'text': ''.join(buf)})
    return units

def get_alignment(units: List[Dict[str, str]], segs: List[str], u_idx: int, s_idx: int, aux_map: Dict[str, str]) -> Optional[List[str]]:
    """
    递归匹配：将汉字和非汉字块对齐到拼音分段。
    返回每个拼音分段对应的辅助码（无辅码则为空字符串），若无法对齐返回 None。
    """
    if u_idx == len(units) and s_idx == len(segs):
        return []
    if u_idx == len(units) or s_idx == len(segs):
        return None
    
    unit = units[u_idx]
    if unit['type'] == 'cn':
        # 汉字：严格消耗 1 个拼音段
        res = get_alignment(units, segs, u_idx + 1, s_idx + 1, aux_map)
        if res is not None:
            return [aux_map.get(unit['text'], '')] + res
        return None
    else:
        # 非汉字（如 AI，C++）：可能消耗 1 个或多个拼音段
        en_text = unit['text'].lower()
        current_seg_text = ""
        
        # 策略 1：优先尝试拼音字符串完全匹配（如 "AI" 匹配拼音段 "ai" 或 "a", "i"）
        for k in range(s_idx, len(segs)):
            current_seg_text += segs[k].lower()
            if current_seg_text == en_text:
                res = get_alignment(units, segs, u_idx + 1, k + 1, aux_map)
                if res is not None:
                    return [''] * (k - s_idx + 1) + res
        
        # 策略 2：如果字符串无法完全匹配（如有声调、或者C++对应c jia jia），根据剩余汉字数量进行容错组合
        remaining_cn = sum(1 for u in units[u_idx+1:] if u['type'] == 'cn')
        max_consume = len(segs) - s_idx - remaining_cn
        
        # 优先贪婪匹配更多的拼音段给非汉字块
        for consume_len in range(max_consume, 0, -1):
            res = get_alignment(units, segs, u_idx + 1, s_idx + consume_len, aux_map)
            if res is not None:
                return [''] * consume_len + res
        
        return None

def build_seg_by_aux_aligned(word: str, raw_segs: List[str], aux_map: Dict[str, str]) -> List[str]:
    """
    生成与拼音段一一对应的辅助码列表。

    规则：
    1. 非汉字不参与辅助码索引。
    2. 若拼音段数量等于汉字数量，则直接按：
       第 i 个拼音段 <-> 第 i 个汉字
       应用对应辅助码。
    3. 若是旧词库，拼音列仍含英文等非汉字段，则继续使用原智能对齐。
    """
    if not raw_segs:
        return []

    # 只取汉字；β、英文、数字、符号全部忽略，不占索引。
    han_chars = [ch for ch in word if CJK_PATTERN.fullmatch(ch)]

    # 新格式：拼音列已经忽略非汉字。
    # 例如 阿β受体 -> ā shòu tǐ
    # 对应关系就是 阿->0、受->1、体->2。
    if len(raw_segs) == len(han_chars):
        return [aux_map.get(ch, '') for ch in han_chars]

    # 兼容旧格式：拼音列中仍可能存在 AI / β / 数字等非汉字段。
    units = tokenize_word(word)
    aligned_aux = get_alignment(units, raw_segs, 0, 0, aux_map)

    if aligned_aux is not None:
        return aligned_aux

    # 最后兜底：始终只按汉字顺序套辅助码。
    # 多出来的拼音段留空辅助码，非汉字绝不占用汉字索引。
    return [
        aux_map.get(han_chars[i], '') if i < len(han_chars) else ''
        for i in range(len(raw_segs))
    ]

def refresh_aux(cols: List[str], word: str, aux_map: Dict[str, str], userdb: bool):
    seg_idx = 0 if userdb else 1
    if not userdb and len(cols) == 1:
        cols.insert(1, '')
    if userdb and len(cols) < 2:
        cols.append('')

    # 获取拼音分段（默认以空格分割）
    raw_segs = cols[seg_idx].strip().split() if seg_idx < len(cols) else []
    
    # 获取智能对齐的辅助码
    aux_segs = build_seg_by_aux_aligned(word, raw_segs, aux_map)

    # 合并 拼音;辅码
    merged = []
    for i, py in enumerate(raw_segs):
        aux = aux_segs[i] if i < len(aux_segs) else ''
        merged.append(f"{py};{aux}")
        
    if userdb:
        cols[0] = ' '.join(merged)
    else:
        cols[seg_idx] = ' '.join(merged)

    return cols

def is_userdb_head(line: str) -> bool:
    return '#@/db_type\tuserdb' in line or '# Rime user dictionary' in line

# ---------- 单文件 ----------
def process_single_file(src: str, dst: str, aux_map: Dict[str, str]):
    userdb = False
    with open(src, encoding='utf-8') as s, open(dst, 'w', encoding='utf-8') as d:
        for raw in s:
            line = raw.rstrip('\n')

            if line.startswith(yaml_heads) or line.startswith('#'):
                d.write(line + '\n')
                if is_userdb_head(line):
                    userdb = True
                continue
            if not line.strip():
                d.write('\n')
                continue

            cols = line.split('\t')
            word = cols[1] if userdb else cols[0]
            cols = refresh_aux(cols, word, aux_map, userdb)

            if userdb and not cols[0].endswith(' '):
                cols[0] += ' '

            d.write('\t'.join(cols) + '\n')

# ---------- 目录递归 ----------
def process_files(path_in: str, path_out: str, aux_map: Dict[str, str]):
    if os.path.isfile(path_in):
        dst = (os.path.join(path_out, os.path.basename(path_in))
               if is_dir_like(path_out) else path_out)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        process_single_file(path_in, dst, aux_map)
        print(f"✓ 完成 {os.path.basename(path_in)} → {dst}")
        return

    tasks = []
    for root, _dirs, files in os.walk(path_in):
        for fn in files:
            if not fn.endswith(('.txt', '.yaml')):
                continue
            rel  = os.path.relpath(root, path_in)
            ddir = os.path.join(path_out, rel)
            Path(ddir).mkdir(parents=True, exist_ok=True)
            tasks.append((os.path.join(root, fn),
                          os.path.join(ddir, fn)))

    total = len(tasks)
    bar_length = 30  # 进度条长度

    for i, (src, dst) in enumerate(tasks, 1):
        process_single_file(src, dst, aux_map)
        
        # 模仿 tqdm.write，先清除当前行，打印文件处理完成日志，然后再重绘进度条
        print(f"\r{' ' * 100}\r✓ 完成 {os.path.basename(src)} → {os.path.relpath(dst, path_out)}")
        
        # 计算进度条参数
        percent = i / total
        filled_len = int(bar_length * percent)
        bar = '█' * filled_len + '-' * (bar_length - filled_len)
        
        # 截断过长的文件名以防进度条被挤得太长
        file_name = os.path.basename(src)
        if len(file_name) > 18:
            file_name = file_name[:15] + "..."
            
        # 在末尾同行输出动态进度条，使用 flush=True 强制立即刷新
        print(f"\r刷辅助码: {int(percent * 100):3d}%|{bar}| {i}/{total} [file={file_name}]", end="", flush=True)

    if tasks:
        print()  # 跑完换行防遮挡

# ---------- 主入口 ----------
if __name__ == "__main__":
    if not os.path.isfile(AUX_FILE):
        raise FileNotFoundError(f"辅助码文件不存在: {AUX_FILE}")
    aux_map = load_aux_metadata(AUX_FILE)
    process_files(INPUT_PATH, OUTPUT_PATH, aux_map)
    print("✓ 辅助码刷新完成")