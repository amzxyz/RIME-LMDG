#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量修正词库拼音（普通词表 + Rime userdb）
支持区分用户词典和固定词典执行不通的逻辑（格式固定）
支持保留辅助码刷新拼音
支持的固定词典格式：
单列汉字>单列汉字\t拼音
单列汉字\t数字>单列汉字\t拼音\t数字
单列汉字\t旧编码\t数字>单列汉字\t拼音\t数字
"""

import os, re
from tqdm import tqdm
from pypinyin import pinyin, Style, load_phrases_dict, load_single_dict

# ─────────────────────────────────────────────────────────
# 你的词典用什么分隔辅助码？
# ─────────────────────────────────────────────────────────
AUX_SEP_REGEX = r'[;\[]'           # 定义“拼音后缀”分隔符；默认匹配 `;` 与 `[`


# ─────────────────────────────────────────────────────────
# 自定义拼音加载
# ─────────────────────────────────────────────────────────
def load_custom_pinyin_from_directory(directory: str):
    s_map, p_map = {}, {}
    if not os.path.isdir(directory):
        print(f"[WARN] 自定义拼音目录不存在: {directory}")
        return
    for fn in os.listdir(directory):
        if not fn.endswith(('.txt', '.yaml')):
            continue
        with open(os.path.join(directory, fn), encoding='utf-8') as f:
            for line in f:
                word, *py = line.rstrip('\n').split('\t')
                if not py:
                    continue
                plist = py[0].split()
                if len(word) == 1:
                    s_map[ord(word)] = ','.join(plist)
                else:
                    p_map[word] = [[p] for p in plist]
    if p_map:
        load_phrases_dict(p_map)
        print(f"✓ 词组拼音加载 {len(p_map)} 条")
    if s_map:
        load_single_dict(s_map)
        print(f"✓ 单字拼音加载 {len(s_map)} 条")


# ─────────────────────────────────────────────────────────
# 表头和类型识别
# ─────────────────────────────────────────────────────────
yaml_heads = ('---', 'name:', 'version:', 'sort:', '...')

def is_userdb_head(line: str) -> bool:
    return '#@/db_type\tuserdb' in line or '# Rime user dictionary' in line

def tone_mark(seg: str) -> str:
    """seg = 'bin;sc' → 'bīn;sc'（仅根拼音加调）"""
    root   = re.split(AUX_SEP_REGEX, seg)[0]
    suffix = seg[len(root):]
    py = pinyin(root, style=Style.TONE, heteronym=False, errors='ignore')
    return (py[0][0] if py else root) + suffix


# ─────────────────────────────────────────────────────────
# 按行处理
# ─────────────────────────────────────────────────────────
def normal_line(cols: list[str]) -> str:
    """普通词表行拼音修正；保留后缀 (;xx / [xx])"""
    word = cols[0]
    char_py = [p[0] for p in pinyin(word, style=Style.TONE, heteronym=False)]

    if len(cols) == 1:                      # 仅汉字
        cols.append(' '.join(char_py))
        return '\t'.join(cols)

    if len(cols) == 2 and cols[1].isdigit():   # 词 + 词频
        cols = [word, ' '.join(char_py), cols[1]]
        return '\t'.join(cols)

    # 有原拼音列，需要保留后缀
    segs = cols[1].split()
    new_segs = []
    for i, py in enumerate(char_py):
        if i < len(segs):
            root = re.split(AUX_SEP_REGEX, segs[i])[0]
            suffix = segs[i][len(root):]
        else:
            suffix = ''
        new_segs.append(py + suffix)
    cols[1] = ' '.join(new_segs)
    return '\t'.join(cols)


def userdb_line(cols: list[str]) -> str:
    """
    第1列: 拼音段(含后缀) | 第2列: 汉字
    eg: 'bin;sc ma;um' + '编码' → 'biān;sc mǎ;um'
    """
    segs = cols[0].split()
    word = cols[1]
    char_py = [p[0] for p in pinyin(word, style=Style.TONE, heteronym=False)]

    new_segs = []
    for i, seg in enumerate(segs):
        base_py = char_py[i] if i < len(char_py) else tone_mark(seg)
        root    = re.split(AUX_SEP_REGEX, seg)[0]
        suffix  = seg[len(root):]
        new_segs.append(base_py + suffix)

    cols[0] = ' '.join(new_segs)
    return '\t'.join(cols)


# ─────────────────────────────────────────────────────────
# 单文件处理
# ─────────────────────────────────────────────────────────
skip_set = {
    "compatible.dict.yaml", "corrections.dict.yaml",
    "chars.dict.yaml", "people.dict.yaml", "encnnum.dict.yaml"
}

def process_single_file(src: str, dst: str):
    if os.path.basename(src) in skip_set:
        with open(src, encoding='utf-8') as s, open(dst, 'w', encoding='utf-8') as d:
            d.writelines(s)
        return

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
                d.write('\n'); continue

            cols = line.split('\t')
            newline = userdb_line(cols) if userdb and len(cols) >= 3 else normal_line(cols)

            # ─── 如果是 userdb 行且首列没空格，就补 1 个空格 ───
            if userdb:
                seg, *rest = newline.split('\t', 1)
                if not seg.endswith(' '):
                    seg += ' '
                    newline = '\t'.join([seg] + rest)

            d.write(newline + '\n')  


# ─────────────────────────────────────────────────────────
# 目录 / 单文件 处理 + tqdm
# ─────────────────────────────────────────────────────────
def process_files(path_in: str, path_out: str):
    # ————————————————— 单文件 —————————————————
    if os.path.isfile(path_in):
        # 判断 path_out 是目录还是文件
        if os.path.isdir(path_out) or path_out.endswith(('/', '\\')):
            # 当成目录
            os.makedirs(path_out, exist_ok=True)
            dst = os.path.join(path_out, os.path.basename(path_in))
        else:
            # 当成文件
            os.makedirs(os.path.dirname(path_out) or '.', exist_ok=True)
            dst = path_out

        process_single_file(path_in, dst)
        print(f"✓ 完成 {os.path.basename(path_in)} → {dst}")
        return

    # ————————————————— 目录递归 —————————————————
    tasks = []
    for root, _dirs, files in os.walk(path_in):
        for fn in files:
            if not fn.endswith(('.txt', '.yaml')):
                continue
            rel  = os.path.relpath(root, path_in)
            ddir = os.path.join(path_out, rel)
            os.makedirs(ddir, exist_ok=True)
            tasks.append((os.path.join(root, fn),
                          os.path.join(ddir, fn)))

    bar = tqdm(tasks, desc="处理文件", unit="file", ncols=90)
    for src, dst in bar:
        bar.set_postfix(file=os.path.basename(src))
        process_single_file(src, dst)
        tqdm.write(f"✓ 完成 {os.path.basename(src)} → {os.path.relpath(dst, path_out)}")


# ─────────────────────────────────────────────────────────
# 固定路径调用
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    #输入输出可以为目录或者单文件
    input_dir  = "/home/amz/Documents/输入法方案/原始词库"
    output_dir = "/home/amz/Documents/输入法方案/万象拼音/dicts"
    custom_dir = "pinyin_data"

    load_custom_pinyin_from_directory(custom_dir)
    process_files(input_dir, output_dir)
    print("✓ 全部文件处理完成")