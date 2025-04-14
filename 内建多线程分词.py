#这种方式太慢了，和直接读取文件处理没法比，如果是我写的调用的方式有问题麻烦帮助改改！
import os
import jieba
from opencc import OpenCC

# ======= 配置参数 =======
MAX_WORKERS = 16  # 并行线程数
cleaned_folder_or_file = 'autodl-tmp/语料清洗后'  # 输入路径，可以是文件夹也可以是文件
segmented_folder = 'autodl-tmp/语料分词后'  # 输出文件夹
CUSTOM_DICT_DIR = "autodl-tmp/自定义分词词典"
FILE_ENCODING = "utf-8"  # 默认文件编码
SEG_MODE = 'precise'  # 分词模式（'precise', 'full', 'search'）

# 启用 jieba 多线程分词
jieba.enable_parallel(MAX_WORKERS)

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
def process_file_stream(input_file, output_file, mode='precise'):
    try:
        print(f"正在处理文件：{input_file}")
        with open(input_file, 'r', encoding=FILE_ENCODING) as f_in, open(output_file, 'w', encoding='utf-8') as f_out:
            for line in f_in:
                try:
                    line = opencc.convert(line.strip())  # 繁体转简体
                    if line:
                        # 根据分词模式选择不同的分词方式
                        if mode == 'precise':
                            seg_list = jieba.cut(line, cut_all=False, HMM=False)  # 精确模式
                        elif mode == 'full':
                            seg_list = jieba.cut(line, cut_all=True)  # 全模式
                        elif mode == 'search':
                            seg_list = jieba.cut_for_search(line)  # 搜索引擎模式
                        else:
                            print(f"未知的分词模式: {mode}")
                            continue
                        segmented_line = " ".join(seg_list)
                        f_out.write(segmented_line + '\n')
                except Exception as line_error:
                    print(f"处理行失败：{line_error} (行内容：{line})")
        print(f"文件处理完成：{output_file}")
    except Exception as e:
        print(f"文件 {input_file} 处理出错：{e}")

# 递归处理文件夹
def process_folder_recursive(input_folder, output_folder, mode='precise'):
    if not os.path.exists(input_folder):
        print(f"输入路径 '{input_folder}' 不存在。")
        return

    if not os.path.isdir(input_folder):
        print(f"'{input_folder}' 不是一个有效的文件夹路径。")
        return

    os.makedirs(output_folder, exist_ok=True)

    # 遍历文件夹中的所有文件
    for root, dirs, files in os.walk(input_folder):
        for filename in files:
            input_path = os.path.join(root, filename)
            relative_path = os.path.relpath(input_path, input_folder)
            output_path = os.path.join(output_folder, relative_path)

            # 确保输出文件夹存在
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            process_file_stream(input_path, output_path, mode)

# 处理文件或文件夹
def process_input(input_path, output_folder, mode='precise'):
    if os.path.isfile(input_path):
        # 如果是文件，直接处理
        output_file = os.path.join(output_folder, os.path.basename(input_path) + '_segmented.txt')
        process_file_stream(input_path, output_file, mode)
    elif os.path.isdir(input_path):
        # 如果是文件夹，递归处理
        process_folder_recursive(input_path, output_folder, mode)
    else:
        print(f"输入路径 '{input_path}' 无效，请检查。")

if __name__ == '__main__':
    # 加载自定义词典
    load_custom_dict()

    # 处理文件或文件夹
    process_input(cleaned_folder_or_file, segmented_folder, mode=SEG_MODE)
