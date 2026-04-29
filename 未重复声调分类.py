import os
import sys
import glob
import re
from collections import defaultdict

# 将脚本所在目录加入系统路径，优先调用当前目录下的自定义 pypinyin
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

import pypinyin

def get_toneless_pinyin(word):
    """
    获取词组的无声调拼音，作为唯一性判断标准。
    """
    raw_pinyin = pypinyin.pinyin(word, style=pypinyin.Style.NORMAL)
    py_str = "".join([item[0] for item in raw_pinyin])
    
    # 针对极端特殊字符（如 ń ǹ ň）做额外替换过滤
    py_str = re.sub(r'[ńňǹ]', 'n', py_str)
    py_str = re.sub(r'[ḿm̀]', 'm', py_str)
    py_str = re.sub(r'[êếềểễệ]', 'e', py_str)
    return py_str

def process_txt_files(folder_path):
    """
    边读边写：单文件处理后立刻覆盖原文件，并直接追加输出未重复项
    """
    # 1. 运行前先清理旧的输出文件，避免追加模式下重复写入历史数据
    old_output_files = glob.glob(os.path.join(folder_path, '*字未重复.txt'))
    for old_file in old_output_files:
        try:
            os.remove(old_file)
        except OSError:
            pass

    # 2. 获取所有的 txt 文件
    txt_files = glob.glob(os.path.join(folder_path, '*.txt'))
    
    for file_path in txt_files:
        lines_data = []
        pinyin_counts = defaultdict(int)
        
        # 读取并统计当前文件
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split('\t')
                if len(parts) >= 2:
                    word = parts[0]
                    weight = parts[1]
                    
                    py_str = get_toneless_pinyin(word)
                    pinyin_counts[py_str] += 1
                    lines_data.append((word, weight, py_str))
        
        # 用于暂存当前文件的未重复项，按字数分类
        current_file_uniques = defaultdict(list)
        repeated_lines = []
        
        # 分流数据
        for word, weight, py_str in lines_data:
            if pinyin_counts[py_str] == 1:
                # 拼音未重复，归入追加队列
                current_file_uniques[len(word)].append(f"{word}\t{weight}")
            else:
                # 拼音有重复，归入覆写队列
                repeated_lines.append(f"{word}\t{weight}")
                
        # 3. 立刻覆写原文件（剥离了未重复的数据）
        with open(file_path, 'w', encoding='utf-8') as f:
            if repeated_lines:
                f.write('\n'.join(repeated_lines) + '\n')
            else:
                f.write('') 

        # 4. 立刻将未重复的数据追加到分类文件中
        for length, lines in current_file_uniques.items():
            output_filename = os.path.join(folder_path, f"{length}字未重复.txt")
            # 采用追加模式('a')，不同文件的不重复数据直接汇聚到这里
            with open(output_filename, 'a', encoding='utf-8') as f:
                f.write('\n'.join(lines) + '\n')

    print("处理完成！采用边读边写、直接追加模式。")


if __name__ == "__main__":
    # 你可以在这里指定你的目标文件夹路径，默认处理当前文件夹下所有的 txt
    target_folder = "/home/amz/Desktop/模型训练/全新尝试2" 
    process_txt_files(target_folder)