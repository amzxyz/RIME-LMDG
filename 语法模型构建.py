import os
import re
import regex
import tempfile
import shutil
import jieba
import math
import subprocess
from tqdm import tqdm
from collections import defaultdict

# ========== 配置文件路径 ==========
ARPA_FILE = 'log.arpa'
PROCESSED_CORPUS_FILE = '清理后.txt'
SEGMENTED_FILE = '分词后.txt'
merged_file = 'merge1_2_3.txt'
language = 'zh-hans'
RAW_CORPUS_DIR = '语料输入'
STOPWORDS_DIR = '停用词表'
SUPPORTED_FORMATS = ['.txt', '.yaml', '.csv', '.json', '.jsonl']

# n-gram 文件名模板
NGRAM_FILE_TEMPLATE = "ngram_{}_.txt"
NGRAM_FILES = [NGRAM_FILE_TEMPLATE.format(i) for i in range(1, 4)]

# ========== 分词和停用词配置 ==========
STOPWORDS_ENABLED = False    #开启或者关闭停用词表
SEGMENT_MODE = 'accurate'   #请选择 'accurate' / 'all' / 'search'

# ========== 停用词加载 ==========
def load_stopwords_from_directory(directory):
    """加载停用词文件夹中的所有停用词。"""
    stopwords = set()
    if not os.path.exists(directory):
        print(f"警告：停用词目录 {directory} 不存在，未加载任何停用词。")
        return stopwords

    for root, _, files in os.walk(directory):
        for file in files:
            file_path = os.path.join(root, file)
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stopwords.add(line.strip())
    print(f"已加载 {len(stopwords)} 个停用词。")
    return stopwords

STOPWORDS = load_stopwords_from_directory(STOPWORDS_DIR) if STOPWORDS_ENABLED else set()

# ========== 初始化结巴分词 ==========
def configure_jieba():
    """配置结巴分词模式。"""
    if SEGMENT_MODE == 'accurate':
        jieba.initialize()
    elif SEGMENT_MODE == 'all':
        jieba.enable_parallel()
    elif SEGMENT_MODE == 'search':
        jieba.enable_paddle()
    else:
        raise ValueError("未知的分词模式，请选择 'accurate' / 'all' / 'search'")

configure_jieba()

# ========== 语料预处理 ==========
def preprocess_corpus(input_dirs, output_file, max_length=30, chunk_size=10000):
    """处理多个输入目录中的文件，并按块写入磁盘，优化内存使用。"""
    pattern = r'[^\p{Script=Han}\n]'  # 匹配所有非汉字和非换行符
    with open(output_file, 'w', encoding='utf-8') as f_out:
        buffer = []
        for input_dir in input_dirs:
            for root, _, files in os.walk(input_dir):
                for file in files:
                    if any(file.endswith(ext) for ext in SUPPORTED_FORMATS):
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as f_in:
                            for line in tqdm(f_in, desc=f"处理 {file}"):
                                # 第一步：符号替换，逗号替换为空格
                                line = re.sub(r'[。.！!?？]', '\n', line)
                                #line = re.sub(r'，', ' ', line)
                                line = re.sub(r'来源": "zhihu', '', line)
                                # 第二步：特定关键词替换为换行符
                                line = re.sub(r'\b(title|category|})\b', '\n', line)
                                line = re.sub(r'"id":\s*".*?",\s*"问":\s*".*?"', '', line)
                                # 第三步：只保留 CJK 汉字和换行符
                                line = regex.sub(pattern, '', line) 
                                # 第四步：去掉所有空行
                                lines = [l for l in line.split('\n') if l.strip()]
                                # 第五步：将行长度超过30的部分截断
                                for l in lines:
                                    while len(l) > max_length:
                                        buffer.append(l[:max_length] + '\n')
                                        l = l[max_length:]
                                    if l:
                                        buffer.append(l + '\n')
                                if len(buffer) >= chunk_size:
                                    f_out.writelines(buffer)
                                    buffer.clear()
        if buffer:
            f_out.writelines(buffer)

# ========== 分词处理 ==========
def segment_corpus(input_file, output_file, chunk_size=10000):
    """对语料进行分词，并保存为输出文件。"""
    with open(input_file, 'r', encoding='utf-8') as f_in, \
         open(output_file, 'w', encoding='utf-8') as f_out:
        buffer = []
        for line in tqdm(f_in, desc="分词处理中"):
            words = jieba.lcut(line.strip(), HMM=True)
            if STOPWORDS_ENABLED:
                words = [word for word in words if word not in STOPWORDS]
            buffer.append(' '.join(words) + '\n')
            if len(buffer) >= chunk_size:
                f_out.writelines(buffer)
                buffer.clear()
        if buffer:
            f_out.writelines(buffer)

# ========== 生成 ARPA 文件 ==========
def generate_arpa(segmented_file, arpa_file, ngram_order=3):
    """调用 KenLM 生成 ARPA 文件，并使用指定的用户临时缓存目录。"""
    # 使用 ~/ARPAtmp 目录，并确保它存在
    tmp_dir = os.path.expanduser("~/ARPAtmp")

    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
        print(f"已创建临时目录：{tmp_dir}")

    try:
        # 构建 lmplz 命令并指定缓存目录
        cmd = (
            f"lmplz -o {ngram_order} "
            f"--text {segmented_file} "
            f"--arpa {arpa_file} "
            f"-T {tmp_dir} "
            f"-S 4G "   # 分配 4G 内存用于排序（根据需要调整）
            f"--prune 0 75 300"    #枝剪系数，分别代表1-4级需要过滤调的低于多少得词频1级不过滤，所以2、3、4分别过滤到词频低于1、2、3的数据
        )

        print(f"执行命令：{cmd}")
        exit_code = os.system(cmd)

        if exit_code != 0:
            raise RuntimeError(f"生成 ARPA 文件失败，退出代码: {exit_code}")

        print(f"ARPA 文件生成完成：{arpa_file}")

    finally:
        # 在程序完成后删除临时目录及其内容
        clean_temp_directory(tmp_dir)

def clean_temp_directory(tmp_dir):
    """删除临时目录及其所有内容。"""
    if os.path.exists(tmp_dir):
        try:
            shutil.rmtree(tmp_dir)  # 使用 rmtree 递归删除目录及内容
            print(f"已删除临时目录：{tmp_dir}")
        except Exception as e:
            print(f"删除临时目录失败：{e}")


# ========== 提取 n-gram 计数 ==========
def extract_ngram_counts(arpa_file):
    """从 ARPA 文件中提取 n-gram 计数。"""
    ngrams_counts = {}
    try:
        with open(arpa_file, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                # 匹配 n-gram 计数行，如 "ngram 1=1000"
                if line.startswith("ngram"):
                    parts = line.split('=')
                    if len(parts) == 2:
                        order = int(parts[0].split()[1])
                        count = int(parts[1])
                        ngrams_counts[order] = count
                elif line.startswith("\\1-grams:"):
                    break  # 遇到 1-grams 部分时停止解析
    except FileNotFoundError:
        print(f"错误：找不到 ARPA 文件 {arpa_file}")
    return ngrams_counts

# ========== 提取 n-grams ==========
def extract_ngrams(arpa_file):
    """从 ARPA 文件中提取 n-grams。"""
    ngram_line_pattern = re.compile(r"^(-?\d+\.\d+)\t(.+?)(?:\t-?\d+\.\d+)?$")
    with open(arpa_file, 'r', encoding='utf-8') as file:
        current_order = 0
        for line in file:
            line = line.strip()
            if line.startswith("\\") and "-grams:" in line:
                current_order = int(line.split('-')[0][1:])
                continue
            
            ngram_line_match = ngram_line_pattern.match(line)
            if ngram_line_match:
                logprob, ngram = ngram_line_match.groups()
                prob = math.exp(float(logprob))
                yield current_order, ngram.strip(), prob  # 确保生成器返回三个值


# ========== 写入频率文件 ==========
def write_frequencies_to_file(ngrams_counts, arpa_file, filename_template):
    """将 n-gram 数据块写入文件。"""
    ngrams_generator = extract_ngrams(arpa_file)
    current_order = 0
    file = None

    for order, ngram, prob in ngrams_generator:
        if order != current_order:
            if file:
                file.close()
            current_order = order
            filename = filename_template.format(order)
            file = open(filename, 'w', encoding='utf-8')
            print(f"Writing {current_order}-grams to {filename}")

        total_count = ngrams_counts.get(order, 1)
        freq = round(prob * total_count)

        if not ngram or freq is None:
            print(f"跳过无效频率行：{ngram} {freq}")
            continue

        file.write(f"{ngram}\t{freq}\n")

    if file:
        file.close()
# ========== 合并 n-gram 文件 ==========
def merge_ngram_files(file_list, output_file, batch_size=20000):
    """合并多个 n-gram 文件，并将结果写入一个输出文件，支持流式处理降低内存占用。"""
    word_map = defaultdict(int)  # 词频计数
    contains_keywords = ['<unk>']  # 需要过滤的关键词

    def write_batch_to_file(f_out, batch):
        """将一个批次的词频数据写入文件。"""
        for word, freq in sorted(batch.items()):
            f_out.write(f"{word}\t{freq}\n")

    total_files = len(file_list)
    
    # 打开输出文件
    with open(output_file, 'w', encoding='utf-8') as f_out:
        # 遍历所有 n-gram 文件
        for file_index, file_name in enumerate(file_list, 1):
            if not os.path.exists(file_name):
                print(f"错误：文件 {file_name} 不存在，跳过...")
                continue

            print(f"[{file_index}/{total_files}] 正在处理文件：{file_name}")

            # 获取文件行数以显示进度条
            total_lines = sum(1 for _ in open(file_name, 'r', encoding='utf-8'))

            # 逐行读取文件，显示进度条
            with open(file_name, 'r', encoding='utf-8') as file:
                for line in tqdm(file, total=total_lines, desc=f"读取 {file_name}"):
                    line = line.strip()

                    # 跳过包含指定关键词或无效的行
                    if any(keyword in line for keyword in contains_keywords):
                        continue
                    if not line or line.startswith('#') or '\t' not in line:
                        continue

                    # 解析行数据
                    try:
                        parts = line.split('\t')
                        if len(parts) < 2:
                            continue

                        word = parts[0].replace(" ", "").replace("<s>", "").replace("</s>", "$")
                        freq = int(parts[-1])

                        # 过滤掉长度不符合条件的词
                        if not (1 < len(word) <= 8):
                            continue

                        # 累加词频
                        word_map[word] += freq

                    except ValueError as e:
                        print(f"跳过解析错误的行：{line} - {e}")
                        continue

                    # 达到批次大小时，写入文件并清空缓冲区
                    if len(word_map) >= batch_size:
                        write_batch_to_file(f_out, word_map)
                        word_map.clear()

        # 写入剩余数据
        if word_map:
            write_batch_to_file(f_out, word_map)

    print(f"合并完成：{output_file}")
# ========== 生成 .gram 文件 ==========
def generate_gram_file(merged_file, language):
    # 生成带语言和自定义名称的 .gram 文件
    cmd = f"./build_grammar {language} < {merged_file}"
    exit_code = os.system(cmd)
    if exit_code != 0:
        raise RuntimeError(f"生成 .gram 文件失败，退出代码: {exit_code}")
    
    # 重命名文件，标记为完成
    final_name = f"wanxiang-lts-{language}.gram"
    os.rename(f"{language}.gram", final_name)
    print(f".gram 文件已生成并重命名为：{final_name}")


# ========== 主函数 ==========
def main(use_existing_segmentation=False, ngram_order=3):
    """主程序：处理语料和 n-gram 数据。    """      
    print("开始预处理语料...")
    preprocess_corpus([RAW_CORPUS_DIR], PROCESSED_CORPUS_FILE)

    if not use_existing_segmentation:
        print("开始分词处理...")
        segment_corpus(PROCESSED_CORPUS_FILE, SEGMENTED_FILE)


    print("生成 ARPA 文件...")
    generate_arpa(SEGMENTED_FILE, ARPA_FILE, ngram_order)

    print("提取 n-gram 计数...")
    # 确保这里的函数名称与定义的函数名称一致
    ngrams_counts = extract_ngram_counts(ARPA_FILE)

    print("写入频率文件...")
    write_frequencies_to_file(ngrams_counts, ARPA_FILE, NGRAM_FILE_TEMPLATE)

    print("合并 n-gram 文件...")
    merge_ngram_files(NGRAM_FILES, merged_file)

    print("生成 .gram 文件...")
    generate_gram_file(merged_file, language)

    print("所有任务完成。")


# ========== 入口 ==========
if __name__ == '__main__':
    main()
