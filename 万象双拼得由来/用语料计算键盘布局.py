import sys
from collections import defaultdict

# 1. 基础字典与常量
TONE_MAP = {
    'ā':'a', 'á':'a', 'ǎ':'a', 'à':'a', 'ō':'o', 'ó':'o', 'ǒ':'o', 'ò':'o',
    'ē':'e', 'é':'e', 'ě':'e', 'è':'e', 'ī':'i', 'í':'i', 'ǐ':'i', 'ì':'i',
    'ū':'u', 'ú':'u', 'ǔ':'u', 'ù':'u', 'ǖ':'v', 'ǘ':'v', 'ǚ':'v', 'ǜ':'v', 'ü':'v'
}

INITIAL_HAND = {
    'q':'L', 'w':'L', 'r':'L', 't':'L', 's':'L', 'd':'L', 'f':'L', 'g':'L', 'z':'L', 'x':'L', 'c':'L', 'v':'L', 'b':'L', 'zh':'L',
    'y':'R', 'p':'R', 'h':'R', 'j':'R', 'k':'R', 'l':'R', 'n':'R', 'm':'R', 'ch':'R', 'sh':'R'
}

# 【单韵母及特殊共键保护区 (按自然码标准锁死)】
# o/uo 锁在 O，v/ui 锁在 V
FIXED_ASSIGNMENTS = {
    'a': ['a'], 'e': ['e'], 'i': ['i'], 
    'o': ['o', 'uo'], 'u': ['u'], 'v': ['v', 'ui']
}

# 【自然码的 20 个绝不重码的“积木块”】
NATURAL_BLOCKS = [
    ('iu',), ('ia', 'ua'), ('uan', 'er'), ('ue',), ('ing', 'uai'), 
    ('un',), ('ong', 'iong'), ('iang', 'uang'), ('en',), ('eng',), 
    ('ang',), ('an',), ('ao',), ('ai',), ('ei',), 
    ('ie',), ('iao',), ('ou',), ('in',), ('ian',)
]

# 【20 个空余按键的黄金地段打分】
MOVABLE_KEYS = {
    'f':100, 'j':100, 'g':90, 'h':90, 'd':80, 'k':80, 'r':70, 'm':70, 
    't':60, 'y':60, 'n':60, 'c':50, 's':40, 'l':40, 'w':30, 'b':20, 
    'x':10, 'q':0, 'z':-10, 'p':-20
}

# 2. 清洗与解析引擎
def split_syllable(syl):
    if syl.startswith(('zh', 'ch', 'sh')): return syl[:2], syl[2:]
    if syl and syl[0] in 'bpmfdtnlgkhjqxrzcsyw': return syl[0], syl[1:]
    return '', syl

def remove_tones(syl):
    syl = syl.replace('ńg', 'eng').replace('ňg', 'eng').replace('ǹg', 'eng')
    syl = syl.replace('ń', 'en').replace('ň', 'en').replace('ǹ', 'en')
    syl = syl.replace('ūe', 've').replace('úe', 've').replace('ǔe', 've').replace('ùe', 've')
    for t, f in TONE_MAP.items(): syl = syl.replace(t, f)
    syl = syl.replace('ve', 'ue').replace('vn', 'un')
    if syl == 'n': return 'en'
    if syl == 'ng': return 'eng'
    if syl == 'm': return 'mu'
    return syl

def analyze_corpus(filepath):
    final_freq = defaultdict(int)
    final_initial_pairs = defaultdict(lambda: defaultdict(int))
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    weight = int(parts[2].strip()) if len(parts) >= 3 and parts[2].strip().isdigit() else 1
                    for syl in parts[1].lower().split(' '):
                        syl_clean = remove_tones(syl)
                        if not syl_clean: continue
                        initial, final = split_syllable(syl_clean)
                        if final:
                            final_freq[final] += weight
                            final_initial_pairs[final][initial] += weight
    except FileNotFoundError:
        return None, None
    return final_freq, final_initial_pairs

# 3. 核心分配算法：按频次抢地盘
def optimize_layout_with_blocks(final_freq, final_initial_pairs):

    block_stats = []
    # 统计每一个积木块的总词频和左右互击倾向
    for block in NATURAL_BLOCKS:
        total_freq, lh_count, rh_count = 0, 0, 0
        for f in block:
            total_freq += final_freq[f]
            for ini, count in final_initial_pairs[f].items():
                if ini == '': continue
                if INITIAL_HAND.get(ini) == 'L': lh_count += count
                elif INITIAL_HAND.get(ini) == 'R': rh_count += count
                
        target = 'R' if lh_count > rh_count else 'L' if rh_count > 0 else 'ANY'
        ratio = (lh_count / (lh_count + rh_count)) if (lh_count + rh_count) > 0 else 0.5
        
        block_stats.append({
            'block': block, 'freq': total_freq, 'target_hand': target, 'lh_ratio': ratio
        })

    # 【阶级特权】词频越高的积木，越早出来选位置！
    block_stats.sort(key=lambda x: x['freq'], reverse=True)
    
    assigned = {}
    available_keys = list(MOVABLE_KEYS.keys())
    
    # 按照频次顺序，给每个积木安排最爽的键
    for stat in block_stats:
        target_hand = stat['target_hand']
        best_key, best_score = None, -9999
        
        for k in available_keys:
            key_hand = 'L' if k in 'qwertasdfgzxcvb' else 'R'
            score = MOVABLE_KEYS[k]
            # 如果按键在哪边手，正好和它的互击期望匹配，加巨分！
            if target_hand != 'ANY' and key_hand == target_hand:
                score += 50 
            
            if score > best_score:
                best_score = score
                best_key = k
                
        # 抢占该键，并将其从空闲列表中移除
        assigned[best_key] = stat
        available_keys.remove(best_key)

    # 4. 融合打印结果
    print("=" * 75)
    left_keys = 'qwertasdfgzxcvb'
    
    for row in ['qwertyuiop', 'asdfghjkl', 'zxcvbnm']:
        for key in row:
            # 优先看是不是固定键 (如 A, O, E)
            if key in FIXED_ASSIGNMENTS:
                finals_str = " ".join(FIXED_ASSIGNMENTS[key])
                print(f"[{key.upper()}] : {finals_str} [固定位]")
            else:
                stat = assigned.get(key)
                if stat:
                    f_str = " ".join(stat['block'])
                    target = stat['target_hand']
                    actual_hand = 'L' if key in left_keys else 'R'
                    status = "✔" if target == 'ANY' or target == actual_hand else "❌"
                    ratio = stat['lh_ratio'] * 100
                    print(f"[{key.upper()}] : {f_str:<9} [应去{target}|实去{actual_hand}{status}|左呼叫率{ratio:.0f}%]")
                else:
                    print(f"[{key.upper()}] : [空]")
        print("-" * 75)

if __name__ == "__main__":
    import os
    if not os.path.exists("语料统计词频表.txt"):
        with open("语料统计词频表.txt", "w", encoding="utf-8") as f:
            f.write("双拼\tshuāng pīn\t1000\n测试\tcè shì\t500\n")
    freq, pairs = analyze_corpus("语料统计词频表.txt")
    if freq: optimize_layout_with_blocks(freq, pairs)