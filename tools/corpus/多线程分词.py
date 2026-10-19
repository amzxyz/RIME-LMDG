import os
import jieba
from opencc import OpenCC
from concurrent.futures import ThreadPoolExecutor, as_completed

# ======= 配置参数 =======
MAX_WORKERS = 20  # 并行线程数
cleaned_folder = 'autodl-tmp/语料清洗后'
segmented_folder = 'autodl-tmp/语料分词后'
CUSTOM_DICT_DIR = "autodl-tmp/自定义分词词典"
FILE_ENCODING = "utf-8"  # 默认文件编码

# 启用 jieba内部 多线程分词，这个不要用，自定义词典也得重复加载加载才行
#jieba.enable_parallel(MAX_WORKERS)

# 初始化 OpenCC 转换器
opencc = OpenCC('t2s')

# 加载自定义词典
def load_custom_dict():
    if os.path.isdir(CUSTOM_DICT_DIR):
        for filename in os.listdir(CUSTOM_DICT_DIR):
            dict_path = os.path.join(CUSTOM_DICT_DIR, filename)
            if os.path.isfile(dict_path):
                jieba.load_userdict(dict_path)
                print(f"已加载自定义词典：{dict_path}")
    elif os.path.isfile(CUSTOM_DICT_DIR):
        jieba.load_userdict(CUSTOM_DICT_DIR)
        print(f"已加载单个自定义词典：{CUSTOM_DICT_DIR}")
    else:
        print(f"路径 '{CUSTOM_DICT_DIR}' 无效，请检查。")

# 逐行分词
def process_file_stream(input_file, output_file):
    try:
        print(f"正在处理文件：{input_file}")
        with open(input_file, 'r', encoding=FILE_ENCODING) as f_in, open(output_file, 'w', encoding='utf-8') as f_out:
            for line in f_in:
                try:
                    line = opencc.convert(line.strip())  # 繁体转简体
                    if line:
                        seg_list = jieba.cut(line, cut_all=False, HMM=False)
                        segmented_line = " ".join(seg_list)
                        f_out.write(segmented_line + '\n')
                except Exception as line_error:
                    print(f"处理行失败：{line_error} (行内容：{line})")
        print(f"文件处理完成：{output_file}")
    except Exception as e:
        print(f"文件 {input_file} 处理出错：{e}")

# 并行处理文件夹
def process_folder_parallel(input_folder, output_folder):
    if not os.path.exists(input_folder):
        print(f"输入文件夹 '{input_folder}' 不存在。")
        return

    os.makedirs(output_folder, exist_ok=True)

    files = [(os.path.join(input_folder, filename), os.path.join(output_folder, filename + '_segmented.txt'))
             for filename in os.listdir(input_folder) if os.path.isfile(os.path.join(input_folder, filename))]

    if not files:
        print(f"输入文件夹 '{input_folder}' 中没有可处理的文件。")
        return

    # 使用线程池并行处理多个文件
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_file_stream, input_path, output_path): (input_path, output_path)
                   for input_path, output_path in files}

        for future in as_completed(futures):
            input_path, output_path = futures[future]
            try:
                future.result()
            except Exception as e:
                print(f"文件 {input_path} 处理出错：{e}")

if __name__ == '__main__':
    # 加载自定义词典
    load_custom_dict()

    # 并行处理文件夹中的所有文件
    process_folder_parallel(cleaned_folder, segmented_folder)
