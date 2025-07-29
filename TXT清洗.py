import os
import re

# 清洗每行文本
def clean_text(text):
    # 第一步：将标点符号替换为换行符
    text = re.sub(r'[。；,?.!?！：：]', '\n', text)  # 常见标点替换为换行符，意味着语句的头尾得到了保留
    
    # 第二步：去除非汉字字符（保留汉字和换行符）
    text = re.sub(r'[^\u4e00-\u9fff\n]', '', text)
    
    # 返回清洗后的文本，去除多余的空白字符
    return text.strip()

# 处理文件夹中的txt文件
def clean_data(input_folder, output_folder):
    # 遍历输入文件夹中的所有文件
    for filename in os.listdir(input_folder):
        input_file = os.path.join(input_folder, filename)
        
        if os.path.isfile(input_file) and filename.endswith(".txt"):  # 只处理 .txt 文件
            # 定义输出文件路径
            output_file = os.path.join(output_folder, f"{os.path.splitext(filename)[0]}.txt")
            
            # 检查文件是否为空
            if os.path.getsize(input_file) == 0:
                print(f"文件 {input_file} 是空的，跳过处理")
                continue  # 跳过空文件

            print(f"正在处理文件: {input_file}")
            
            try:
                # 打开并处理每个 .txt 文件
                with open(input_file, 'r', encoding='utf-8') as infile:
                    with open(output_file, 'w', encoding='utf-8') as outfile:
                        for line in infile:
                            # 清洗每一行
                            cleaned_line = clean_text(line.strip())
                            
                            if cleaned_line:  # 如果该行不是空行，则写入输出文件
                                outfile.write(cleaned_line + '\n')  # 添加换行符
                    
                    print(f"处理完成，结果已保存至: {output_file}")
            except Exception as e:
                print(f"处理文件 {input_file} 时出错: {e}")

if __name__ == "__main__":
    input_folder = "语料输入"  # 请替换为输入文件夹的实际路径
    output_folder = "语料清洗后"  # 请替换为输出文件夹的实际路径
    
    # 创建输出文件夹（如果不存在）
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    clean_data(input_folder, output_folder)

    print("所有文件处理完成")
