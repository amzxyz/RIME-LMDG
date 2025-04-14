"""
已获取1454000篇文章: : 4579025it [2:30:45, 506.24it/s]  截止2024年12月数据量
下载链接
https://dumps.wikimedia.org/zhwiki/latest/zhwiki-latest-pages-articles.xml.bz2  
需要安装的库：pip install opencc-python-reimplemented tqdm bz2file gensim
"""
from gensim.corpora.wikicorpus import extract_pages, filter_wiki
import bz2file
import re
from opencc import OpenCC
from tqdm import tqdm
import codecs

def wiki_replace(d, openCC):
    """
    对wiki文章的内容进行替换和清理
    :param d: 文章数据
    :param openCC: OpenCC 实例，用于简体转换
    :return: 处理后的文章内容
    """
    s = d[1]  # 获取文章内容
    # 清理wikicode标记
    s = re.sub(r':*{\|[\s\S]*?\|}', '', s)  # 清除表格
    s = re.sub(r'<gallery>[\s\S]*?</gallery>', '', s)  # 清除图集
    s = re.sub(r'(.){{([^{}\n]*?\|[^{}\n]*?)}}', r'\1[[\2]]', s)  # 修复wikilinks
    s = filter_wiki(s)  # 过滤wiki标记

    # 清理多余的标点符号和换行符
    s = re.sub(r'\* *\n|\'{2,}', '', s)
    s = re.sub(r'\n+', '\n', s)
    s = re.sub(r'\n[:;]|\n +', '\n', s)
    s = re.sub(r'\n==', '\n\n==', s)

    # 添加标题
    s = u'【' + d[0] + u'】\n' + s

    # 转换为简体中文
    s = openCC.convert(s)
    
    return s

def wiki_process(input_file, save_path):
    """
    处理wiki文件并保存
    :param input_file: 输入文件路径
    :param save_path: 保存文件路径
    """
    # 创建OpenCC实例，转换为简体
    openCC = OpenCC('t2s')

    # 解析wikicorpus
    wiki = extract_pages(bz2file.open(input_file))

    # 使用with语句确保文件关闭
    with codecs.open(save_path, 'w', encoding='utf-8') as f:
        i = 0
        w = tqdm(wiki, desc=u'已获取0篇文章')
        
        for d in w:
            # 排除标题和特殊内容
            if not re.findall('^[a-zA-Z]+:', d[0]) and d[0] and not re.findall(u'^#', d[1]):
                # 替换内容并写入文件
                s = wiki_replace(d, openCC)
                f.write(s + '\n\n\n')
                
                # 更新已处理文章数
                i += 1
                if i % 100 == 0:
                    w.set_description(u'已获取%s篇文章' % i)

if __name__ == '__main__':
    # bz2文件路径
    input_file = "/home/amz/Downloads/zhwiki-latest-pages-articles.xml.bz2"
    # 输出文件路径
    save_path = '/home/amz/Downloads/zhwiki-latest-pages-articles.txt'

    # 处理并保存
    wiki_process(input_file, save_path)
