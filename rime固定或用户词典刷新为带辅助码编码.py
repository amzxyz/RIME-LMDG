#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rime固定词典或者用户词典刷新为带辅助码的格式.py
────────────────────────────────────────────────────────
功能：给第一列是汉字的词典批量添加“拼音+辅助码”。
⚠ 仅保证辅助码正确；拼音可能多音字错误，需后续“刷拼音”脚本修正。
"""

from __future__ import annotations
import os, re, shutil
from pathlib import Path
from typing import Dict, List
from tqdm import tqdm

# ─────────────── 配 置 区 ────────────────
INPUT_PATH  = "/home/amz/Documents/输入法方案/万象拼音/base.dict.yaml"          # 目录或单文件
OUTPUT_PATH = "/home/amz/Documents/输入法方案/万象拼音/outbase.dict.yaml"       # 目录或文件；智能判断
AUX_FILE    = "/home/amz/Documents/辅助码.txt"  # 这里使用你选择的辅助码词库中的单字表作为数据源 格式  你\tni;re  你\t;re  你\tre三种格式都是支持的
# ──────────────────────────────────────

AUX_SEP_REGEX = r'[;\[]'
yaml_heads = ('---', 'name:', 'version:', 'sort:', '...')

# ---------- 判断输出路径像目录 ----------
def is_dir_like(p: str) -> bool:
    return (p.endswith(('/', '\\'))       # 末尾分隔符
            or os.path.isdir(p)           # 已存在目录
            or not os.path.splitext(p)[1])# 无扩展名

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
            # 修正：如果辅助码仅为 ; 或为空，设为空
            if aux_map[char] == ';':
                aux_map[char] = ''
    print(f"✓ 辅助码加载 {len(aux_map)} 条")
    return aux_map


# ---------- 行级处理 ----------
def build_seg_by_aux(word: str, aux_map: Dict[str, str]) -> List[str]:
    return [aux_map.get(ch, '') for ch in word]

def refresh_aux(cols: List[str], word: str, aux_map: Dict[str, str], userdb: bool):
    seg_idx = 0 if userdb else 1
    if not userdb and len(cols) == 1:
        cols.insert(1, '')
    if userdb and len(cols) < 2:
        cols.append('')

    raw_segs = cols[seg_idx].strip().split() if seg_idx < len(cols) else []
    aux_segs = build_seg_by_aux(word, aux_map)

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

            # 透传 YAML/注释
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

            # --- 若是 userdb 行且首列未以空格结尾，就补 1 个空格 ---
            if userdb and not cols[0].endswith(' '):
                cols[0] += ' '

            d.write('\t'.join(cols) + '\n')   # 直接写出，不再 rstrip('\t')


# ---------- 目录递归 ----------
def process_files(path_in: str, path_out: str, aux_map: Dict[str, str]):
    # —— 输入是单文件 ——
    if os.path.isfile(path_in):
        dst = (os.path.join(path_out, os.path.basename(path_in))
               if is_dir_like(path_out) else path_out)
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        process_single_file(path_in, dst, aux_map)
        print(f"✓ 完成 {os.path.basename(path_in)} → {dst}")
        return

    # —— 输入是目录，递归处理 ——
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

    bar = tqdm(tasks, desc="刷辅助码", unit="file", ncols=90)
    for src, dst in bar:
        bar.set_postfix(file=os.path.basename(src))
        process_single_file(src, dst, aux_map)
        tqdm.write(f"✓ 完成 {os.path.basename(src)} → {os.path.relpath(dst, path_out)}")

# ---------- 主入口 ----------
if __name__ == "__main__":
    if not os.path.isfile(AUX_FILE):
        raise FileNotFoundError(f"辅助码文件不存在: {AUX_FILE}")
    aux_map = load_aux_metadata(AUX_FILE)
    process_files(INPUT_PATH, OUTPUT_PATH, aux_map)
    print("✓ 辅助码刷新完成")
