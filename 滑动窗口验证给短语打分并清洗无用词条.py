#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
功能：利用 2-4 字滑动窗口 + 同音首选权重 进行多维智能打分。
核心升维点：
1. 提取 jichu 词库中的拼音与权重，去除声调后进行同音词聚类。
2. 根据同音词组内的绝对打分（排行老几），赋予词条不同的“身价加成”。
3. 碎片命中及 VIP 拼接时，首选词条构成的组合分数将碾压备胎组合。
"""

import os
import re
from pathlib import Path
from collections import defaultdict

# ======================= 用户配置区 =======================
JICHU_FILE = "/home/amz/Documents/原始词库/jichu.dict.yaml"
INPUT_FILE = "/home/amz/5字.txt"
OUTPUT_FILE = "/home/amz/打分后5字.txt"

# 打分权重配置
SCORE_BASE_HIT = 1      # 普通碎片命中一次加 1 分
SCORE_PENALTY = -3      # 连续断层（如3个字连不起来）扣 3 分
SCORE_VIP = 20          # 完美拼接的 VIP 词条保底加 20 分

# 家族地位加成 (同音组内排行)
RANK_SCORE_1 = 4        # 首选 (老大) 额外加 4 分
RANK_SCORE_2 = 2        # 次选 (老二) 额外加 2 分
RANK_SCORE_3 = 1        # 三选 (老三) 额外加 1 分
RANK_SCORE_OTHER = 0    # 四选及以后无加成
# ==========================================================

def remove_tones(pinyin_str: str) -> str:
    replacements = {
        'ā':'a', 'á':'a', 'ǎ':'a', 'à':'a', 'ō':'o', 'ó':'o', 'ǒ':'o', 'ò':'o',
        'ē':'e', 'é':'e', 'ě':'e', 'è':'e', 'ī':'i', 'í':'i', 'ǐ':'i', 'ì':'i',
        'ū':'u', 'ú':'u', 'ǔ':'u', 'ù':'u', 'ǖ':'v', 'ǘ':'v', 'ǚ':'v', 'ǜ':'v', 'ü':'v'
    }
    res = pinyin_str.lower()
    for k, v in replacements.items():
        res = res.replace(k, v)
    # 顺手干掉 Rime 拼音里可能带的数字声调(如 a1)
    return re.sub(r'\d+', '', res).strip()

def load_base_dict(filepath: Path):
    """
    加载基础词库，构建双引擎：
    1. base_set: 极速存取集合
    2. word_rank_map: 词条身份牌（记录该词在它的同音家族里，最高混到了老几）
    """
    base_set = set()
    word_rank_map = {}
    pinyin_groups = defaultdict(list)
    
    if not filepath.exists():
        print(f"❌ 错误：基础词库不存在 -> {filepath}")
        return base_set, word_rank_map
        
    print(f"📖 正在加载基础词库 (jichu) 并计算家族地位...")
    line_num = 0
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line_num += 1
            clean_line = line.strip()
            if not clean_line or clean_line.startswith('#'):
                continue
            
            parts = clean_line.split('\t')
            if len(parts) >= 1:
                word = parts[0].strip()
                if not (2 <= len(word) <= 4):
                    continue
                
                base_set.add(word)
                
                # 如果有拼音和权重，参与家族内卷排位
                if len(parts) >= 3:
                    pinyin = parts[1].strip()
                    weight_str = parts[2].strip()
                    if weight_str.isdigit():
                        weight = int(weight_str)
                    else:
                        weight = 0
                        
                    py_no_tone = remove_tones(pinyin)
                    pinyin_groups[py_no_tone].append((word, weight))

    for py, items in pinyin_groups.items():
        # 按照权重从大到小排序
        items.sort(key=lambda x: x[1], reverse=True)
        
        for rank, (word, weight) in enumerate(items):
            if rank == 0:
                bonus = RANK_SCORE_1
            elif rank == 1:
                bonus = RANK_SCORE_2
            elif rank == 2:
                bonus = RANK_SCORE_3
            else:
                bonus = RANK_SCORE_OTHER
            
            if word not in word_rank_map or bonus > word_rank_map[word]:
                word_rank_map[word] = bonus
                
    print(f"✅ 词库处理完毕！共载入 {len(base_set):,} 个词元。")
    print(f"👑 其中 {len([w for w, s in word_rank_map.items() if s == RANK_SCORE_1]):,} 个词斩获同音首选殊荣。\n")
    return base_set, word_rank_map


def calculate_score(phrase: str, base_set: set, word_rank_map: dict) -> int:
    """三维融合打分：N-gram 匹配 + 家族地位加成 + VIP 拼接 + 断层斩杀"""
    score = 0
    phrase_len = len(phrase)
    
    if phrase_len < 2:
        return 0
        
    for window_size in (2, 3, 4):
        for i in range(phrase_len - window_size + 1):
            sub_word = phrase[i : i + window_size]
            if sub_word in base_set:
                score += SCORE_BASE_HIT
                score += word_rank_map.get(sub_word, 0)
    w2_hits = [phrase[i : i+2] in base_set for i in range(phrase_len - 1)]
    for i in range(len(w2_hits) - 1):
        if not w2_hits[i] and not w2_hits[i+1]:
            score += SCORE_PENALTY
    vip_multiplier = 0
    
    if phrase_len == 5:
        # A: 2+3
        if (phrase[0:2] in base_set) and (phrase[2:5] in base_set):
            vip_multiplier += 1
            score += word_rank_map.get(phrase[0:2], 0) + word_rank_map.get(phrase[2:5], 0)
        # B: 3+2
        if (phrase[0:3] in base_set) and (phrase[3:5] in base_set):
            vip_multiplier += 1
            score += word_rank_map.get(phrase[0:3], 0) + word_rank_map.get(phrase[3:5], 0)
        # C: 4+1
        if (phrase[0:4] in base_set):
            vip_multiplier += 1
            score += word_rank_map.get(phrase[0:4], 0)
        # D: 1+4
        if (phrase[1:5] in base_set):
            vip_multiplier += 1
            score += word_rank_map.get(phrase[1:5], 0)
        # E: 2+1+2
        if (phrase[0:2] in base_set) and (phrase[3:5] in base_set):
            vip_multiplier += 1
            score += word_rank_map.get(phrase[0:2], 0) + word_rank_map.get(phrase[3:5], 0)
            
    elif phrase_len == 4:
        if (phrase[0:2] in base_set) and (phrase[2:4] in base_set):
            vip_multiplier += 1
            score += word_rank_map.get(phrase[0:2], 0) + word_rank_map.get(phrase[2:4], 0)
        if (phrase[0:3] in base_set) or (phrase[1:4] in base_set):
            vip_multiplier += 1
            score += word_rank_map.get(phrase[0:3], 0) if (phrase[0:3] in base_set) else word_rank_map.get(phrase[1:4], 0)

    # 结算最终 VIP 保送分
    if vip_multiplier > 0:
        score += SCORE_VIP

    return score


def main():
    jichu_path = Path(JICHU_FILE)
    input_path = Path(INPUT_FILE)
    output_path = Path(OUTPUT_FILE)
    
    base_set, word_rank_map = load_base_dict(jichu_path)
    if not base_set:
        return
        
    if not input_path.exists():
        print(f"❌ 输入文件不存在 -> {input_path}")
        return
        
    print(f"🚀 开始执行滑窗特征扫描与 VIP 智能降维打分...")
    
    scored_results = []
    total_lines = 0
    
    with open(input_path, 'r', encoding='utf-8', errors='ignore') as fin:
        for line in fin:
            clean_line = line.rstrip('\n')
            if not clean_line or clean_line.startswith('#'):
                continue
                
            parts = clean_line.split('\t')
            if len(parts) >= 2:
                phrase = parts[0]
                weight = parts[1]
                
                score = calculate_score(phrase, base_set, word_rank_map)
                scored_results.append((phrase, weight, score))
                total_lines += 1
                
    print(f"📊 扫描完成，共处理 {total_lines:,} 行。正在按得分进行降序排列...")
    scored_results.sort(key=lambda x: x[2], reverse=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as fout:
        for phrase, weight, score in scored_results:
            fout.write(f"{phrase}\t{weight}\t{score}\n")
            
    print(f"🎉 完美提纯！带有排位压制特性的结果已保存至: {output_path.name}")

if __name__ == "__main__":
    main()