import json

def clean_data(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as infile:
        with open(output_file, 'w', encoding='utf-8') as outfile:
            for line in infile:
                try:
                    data = json.loads(line)  # 逐行解析
                    category = data.get("category", "")
                    title = data.get("title", "")
                    desc = data.get("desc", "")
                    answer = data.get("answer", "")
                    content = data.get("content", "")    
                    内容 = data.get("内容", "")   
                    
                    # 写入数据到输出文件，每个字段的内容一行
                    outfile.write(f"{category}\n")
                    outfile.write(f"{title}\n")
                    outfile.write(f"{desc}\n")
                    outfile.write(f"{answer}\n")
                    outfile.write(f"{content}\n")
                    outfile.write(f"{内容}\n")                    
                    outfile.write("\n")  # 每个记录之间加一空行

                except json.JSONDecodeError as e:
                    print(f"JSONDecodeError: {e} - in line: {line}")
                except Exception as e:
                    print(f"Error: {e}")
if __name__ == "__main__":
    input_file = "语料输入/news.json"  # 输入文件路径
    output_file = "语料输入/news.txt"     # 输出文件路径
    clean_data(input_file, output_file)

    print("清理后的文件已保存至", output_file)
