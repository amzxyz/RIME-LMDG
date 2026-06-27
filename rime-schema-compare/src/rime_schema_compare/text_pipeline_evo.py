import re
import difflib
import jieba

# 预编译正则，提升流式处理切分速度
CJK_SPLIT_PATTERN = re.compile(r'[^\u4e00-\u9fff]+')

def process_corpus_to_lines(raw_text: str) -> list:
    """
    清洗语料，切割成纯汉字短句
    """
    raw_segments = CJK_SPLIT_PATTERN.split(raw_text)
    
    valid_lines = []
    for line in raw_segments:
        line = line.strip()
        if len(line) >= 3:
            valid_lines.append(line)
            
    return valid_lines

def extract_missed_segments(gold_text: str, output_text: str) -> list:
    """
    全量结巴词界吸附提取算法（解决生硬截断与错误集中问题）
    """
    bad_segments = set()
    
    # 1. 对【正确的原文】进行结巴分词，打下牢固的“物理词界地基”
    tokens = []
    idx = 0
    for word in jieba.cut(gold_text):
        tokens.append((word, idx, idx + len(word)))
        idx += len(word)
        
    # 2. 获取基于字的差异坐标
    matcher = difflib.SequenceMatcher(None, gold_text, output_text)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue
            
        # 防止插入错误（即漏打或多打，导致 i1 == i2）
        # 强制将搜索区间拉长 1 个字，以便精准锁定受影响的 Token
        search_start = i1
        search_end = max(i1 + 1, i2)
        
        # 3. 错误坐标吸附：寻找该错误波及了哪几个 Token
        start_tok_idx = -1
        end_tok_idx = -1
        
        for t_idx, (w, t_start, t_end) in enumerate(tokens):
            if t_end > search_start and start_tok_idx == -1:
                start_tok_idx = t_idx
            if t_start < search_end:
                end_tok_idx = t_idx
                
        if start_tok_idx == -1 or end_tok_idx == -1:
            continue
            
        # 4. 动态边界扩展：基于词的边界向外蔓延，补足上下文（左侧优先）
        left_ptr = start_tok_idx
        right_ptr = end_tok_idx
        
        # 设定我们的“完美上下文长度”为 4 到 6 个字
        TARGET_MIN_LEN = 4 
        
        while True:
            current_len = tokens[right_ptr][2] - tokens[left_ptr][1]
            if current_len >= TARGET_MIN_LEN:
                break
                
            expanded_this_round = False
            
            # 第一步：绝对优先向左侧扩展（历史状态对 N-gram 预测最重要）
            if left_ptr > 0:
                left_ptr -= 1
                expanded_this_round = True
                
            # 重新计算长度，如果左边借完还是不够长，再向右借
            current_len = tokens[right_ptr][2] - tokens[left_ptr][1]
            if current_len < TARGET_MIN_LEN and right_ptr < len(tokens) - 1:
                right_ptr += 1
                expanded_this_round = True
                
            # 已经顶到句子边缘，无法再借词了
            if not expanded_this_round:
                break
                
        # 5. 按照吸附后的 Token 边界进行切割
        final_start = tokens[left_ptr][1]
        final_end = tokens[right_ptr][2]
        fragment = gold_text[final_start:final_end]
        
        # 6. 保底品控：只产出 4 到 7 个字的精华片段（抛弃过短的 3 字词）
        if 4 <= len(fragment) <= 7:
            bad_segments.add(fragment)
            
    return list(bad_segments)
