import os
import re
from collections import defaultdict

# 引入本地 pypinyin 库 (根据你的需求，同文件夹下直接引用)
try:
    import sys
    sys.path.append(os.path.dirname(__file__))
    from pypinyin import pinyin, Style, lazy_pinyin
except ImportError:
    print("⚠️ 未检测到 pypinyin，请确保同文件夹下有该库。")

# ========== 配置文件路径 ==========
SINGLE_CHAR_DICT_FILE = "/home/amz/Documents/输入法方案/万象拼音/dicts/zi.dict.yaml" # 单字表
BASE_DICT_FILE = "/home/amz/Documents/输入法方案/万象拼音/dicts/jichu.dict.yaml"      # 基础词库

# 【改动】：变成列表形式，你可以往里面加任意多个 part 文件
MODEL_DATA_FILES = [
    "/home/amz/Desktop/模型训练/split_models/修正后声调3字_part1.txt",
    "/home/amz/Desktop/模型训练/split_models/3字_part2.txt",
    "/home/amz/Desktop/模型训练/split_models/3字_part3.txt",
    "/home/amz/Desktop/模型训练/split_models/3字_part4.txt",
]        
OUTPUT_FILE = "/home/amz/Desktop/模型训练/split_models/修正后声调3字合并版.txt"

def strip_tones(py_str):
    """去除拼音中的声调符号和数字"""
    tone_map = {
        'ā':'a', 'á':'a', 'ǎ':'a', 'à':'a',
        'ō':'o', 'ó':'o', 'ǒ':'o', 'ò':'o',
        'ē':'e', 'é':'e', 'ě':'e', 'è':'e',
        'ī':'i', 'í':'i', 'ǐ':'i', 'ì':'i',
        'ū':'u', 'ú':'u', 'ǔ':'u', 'ù':'u',
        'ǖ':'v', 'ǘ':'v', 'ǚ':'v', 'ǜ':'v', 'ü':'v',
        'ń':'n', 'ň':'n', 'ǹ':'n'
    }
    res = py_str.lower()
    for k, v in tone_map.items():
        res = res.replace(k, v)
    res = re.sub(r'\d', '', res)  
    return res.strip()

def process_alignment():
    # ================= 1. 加载单字表，确立“单字首选” =================
    print("🚀 [1/4] 正在加载单字表，建立【单字首选】锚点...")
    single_char_groups = defaultdict(list)
    with open(SINGLE_CHAR_DICT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 3: continue
            word, py_raw, weight_str = parts[0], parts[1], parts[2]
            clean_word = word.replace('$', '')
            
            # 单字表严格过滤只要1个字的
            if len(clean_word) != 1: continue 
            try: weight = int(weight_str)
            except ValueError: continue
                
            tl_py = strip_tones(py_raw)
            single_char_groups[tl_py].append({'word': clean_word, 'weight': weight})

    best_single_char = {}
    for tl_py, items in single_char_groups.items():
        # 按权重降序，取第一个字作为该拼音的绝对首选
        items.sort(key=lambda x: x['weight'], reverse=True)
        best_single_char[tl_py] = items[0]['word']

    # ================= 2. 加载基础词库，确立“组内排名” =================
    print("🚀 [2/4] 正在加载基础词库，建立【基准排名】锚点...")
    base_dict_groups = defaultdict(list)
    with open(BASE_DICT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 3: continue
            word, py_raw, weight_str = parts[0], parts[1], parts[2]
            clean_word = word.replace('$', '')
            
            # 去除了字数限制，加载所有长度的基准词！
            try: weight = int(weight_str)
            except ValueError: continue
                
            tl_py = strip_tones(py_raw)
            base_dict_groups[tl_py].append({'word': clean_word, 'weight': weight})

    base_ranks = {} 
    for tl_py, items in base_dict_groups.items():
        items.sort(key=lambda x: x['weight'], reverse=True)
        # Rank 为 0 代表这是该拼音下的首选词！
        base_ranks[tl_py] = {item['word']: rank for rank, item in enumerate(items)}

    # ================= 3. 加载模型数据并分组 (支持多文件合并) =================
    print(f"📊 [3/4] 正在读取 {len(MODEL_DATA_FILES)} 个模型数据文件，执行合并、去重与分组...")
    
    # 临时聚合字典，防止多个文件出现完全相同的词条导致重复
    # 结构: tl_py -> { (word, clean_word, py_raw): total_weight }
    temp_model_dict = defaultdict(lambda: defaultdict(int))
    
    for file_path in MODEL_DATA_FILES:
        if not os.path.exists(file_path):
            print(f"   ⚠️ 警告：文件不存在，跳过 -> {file_path}")
            continue
            
        print(f"   📁 正在读取: {file_path}")
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) < 3: continue
                word, py_raw, weight_str = parts[0], parts[1], parts[2]
                clean_word = word.replace('$', '')
                
                try: weight = int(weight_str)
                except ValueError: continue
                    
                tl_py = strip_tones(py_raw)
                
                # $ 占位分离
                if word.endswith('$') and not tl_py.endswith('$'):
                    tl_py = tl_py + " $"
                
                # 安全累加：跨文件如果遇到同样的词、同样的拼音，权重相加
                temp_model_dict[tl_py][(word, clean_word, py_raw)] += weight

    # 将临时字典转换回 model_groups 列表结构
    model_groups = defaultdict(list)
    for tl_py, items_dict in temp_model_dict.items():
        for (word, clean_word, py_raw), total_weight in items_dict.items():
            model_groups[tl_py].append({
                'word': word, 
                'clean_word': clean_word,
                'orig_py': py_raw, 
                'weight': total_weight
            })

    # ================= 4. 核心拆骨验证与重排 =================
    print("⚙️ [4/4] 正在执行【三级优先级】验证与权重置换...")
    final_grouped_results = {}
    
    # 拆骨验证函数：判定 2+1 或 1+2 是否全部命中“首选”
    def check_decomposition(clean_word, tl_py_no_dollar):
        if len(clean_word) != 3: return False
        
        py_parts = tl_py_no_dollar.split()
        if len(py_parts) != 3: return False 
        
        c1, c2, c3 = clean_word[0], clean_word[1], clean_word[2]
        p1, p2, p3 = py_parts[0], py_parts[1], py_parts[2]
        
        w12, p12 = c1 + c2, p1 + " " + p2
        w23, p23 = c2 + c3, p2 + " " + p3
        
        # 条件 A (2+1)
        is_w12_top = (base_ranks.get(p12, {}).get(w12) == 0)
        is_c3_top = (best_single_char.get(p3) == c3)
        cond_A = is_w12_top and is_c3_top
        
        # 条件 B (1+2)
        is_c1_top = (best_single_char.get(p1) == c1)
        is_w23_top = (base_ranks.get(p23, {}).get(w23) == 0)
        cond_B = is_c1_top and is_w23_top
        
        return cond_A or cond_B

    for tl_py, items in model_groups.items():
        # 奖金池提取
        available_weights = sorted([x['weight'] for x in items], reverse=True)
        
        base_py = tl_py.replace(' $', '').strip()
        group_base_ranks = base_ranks.get(base_py, {})
        
        # 三级火箭排序规则
        def sort_key(item):
            cw = item['clean_word']
            
            # 【T0 梯队】
            if cw in group_base_ranks:
                return (0, group_base_ranks[cw]) 
                
            # 【T1 梯队】
            if check_decomposition(cw, base_py):
                return (1, -item['weight']) 
                
            # 【T2 梯队】
            return (2, -item['weight'])
                
        # 执行重排
        sorted_items = sorted(items, key=sort_key)
        
        # 重新颁发奖金池权重
        for idx, item in enumerate(sorted_items):
            item['new_weight'] = available_weights[idx]
            
        final_grouped_results[tl_py] = sorted_items

    # ================= 5. 输出保存 =================
    print("💾 正在按拼音首字母排布组块，并合并输出为单个文件...")
    sorted_pinyin_keys = sorted(final_grouped_results.keys())
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for tl_py in sorted_pinyin_keys:
            for item in final_grouped_results[tl_py]:
                f.write(f"{item['word']}\t{item['orig_py']}\t{item['new_weight']}\n")
            
    print(f"🎉 任务完美结束！所有输入文件已整合并保存至：{OUTPUT_FILE}")

if __name__ == "__main__":
    process_alignment()