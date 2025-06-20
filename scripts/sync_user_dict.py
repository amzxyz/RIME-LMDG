# 基于官方自动同步的用户词典合并排序生成用户词典
# - https://github.com/loveminimal/rime-jk
# - Jack Liu <https://aituyaa.com>
# 
'''
---------------------------------- 使用方法 -------------------------------------------
# 用户词典类型 1 拼音；20 五笔常规；21 五笔整句；30 虎码常规；31 虎码整句
# ¹ python sync_user_dict.py			默认交互式「 需要交互输入用户词典类型 」
# ² python sync_user_dict.py 31         直接指定用户词典类型(31)

$ ➭ python sync_user_dict.py

# 默认目录：
# src - C:\\Users\\jack\\Nutstore\\1\\我的坚果云\\RimeSync\\jk-jack\\jk_wubi.userdb.txt
# out - C:\\Users\\jack\\AppData\\Roaming\\Rime\\dicts\\wubi86_user.dict.yaml
---------------------------------------------------------------------------------------
'''
import re
from pathlib import Path
from collections import defaultdict
import sys
from header import get_header_sync
from timer import timer
from progress import progress
from is_chinese_char import is_chinese_char


@timer
def convert(src_dir, out_dir, src_file, out_file):
    """
    将用户同步的词典文件合并、排序并生成适用于 Rime 输入法的用户词典文件。

    :param src_dir: 源文件目录
    :param out_dir: 输出文件目录
    """
    # 遍历源文件夹文件，处理
    res_dict = defaultdict(set)  # 使用 defaultdict 提高效率
    lines_total = []

    src_file_path = src_dir / src_file

    print('☑️  已加载用户词库文件 » %s' % src_file_path)
    with open(src_file_path, 'r', encoding='utf-8') as f:
        lines_total = f.readlines()

    with open(out_dir / f'{out_file + '.temp'}', 'w', encoding='utf-8') as o:
        res = ''
        # 以下几行为原始同步词典格式
        # ---------------------------------------------------
        # yywg 	方便	c=3 d=0.187308 t=1959
        # yywr 	文件	c=1 d=0.826959 t=1959
        # encabb 	萍聊了	c=0 d=0.0201897 t=1959
        # encabbk 	萍聊了吗	c=0 d=0.0202909 t=1959
        # encabbn 	萍聊了	c=0 d=0.0201897 t=1959
        # ---------------------------------------------------
        for line in lines_total:
            if not line[0] in '# ':  # 忽略注释和特殊行
                line_list = re.split(r'\t+', line.strip())
                code = line_list[0].strip()
                word = line_list[1]
                weight = line_list[2].split(' ')[0].split('=')[1]

                # 删除权重为负数的字词（废词）
                if int(weight) <= 0:
                    continue

                # 处理特殊编码
                if '' in code:
                    code = code.split('')[1]

                # 过滤掉过长、过短(如 1)的词条
                if len(word) == 1 or (word_length_limit > 0 and len(word) > word_length_limit):
                    continue

                # 此外不再过滤非 8105 字词（源码表已做过滤 & 加载超范字词）
                # 仅处理已合成词典中 不存在 或 已存在但编码不同的字词
                if word not in res_dict or code not in res_dict[word]:
                    res += f'{word}\t{code}\t{weight}\n'
                    res_dict[word].add(code)

        if len(res.strip()) > 0:
            progress('正在转换')
            print('\n✅  » 已生成用户词库临时文件 %s' % (out_dir / f'{out_file + '.temp'}'))
            o.write(res)

@timer
def combine(out_dir, out_file):
    res_dict = {}
    res_dict_weight = defaultdict(set)
    lines_total = []

    # 加载所有词典文件
    for file_path in out_dir.iterdir():
        if file_path.is_file() and file_path.name.startswith(f'{out_file.split('.')[0] + '.'}'):
            with open(file_path, 'r', encoding='utf-8') as f:
                lines_total.extend(f.readlines())

    # 加载定频时添加的自造词词典
    # 修改为直接从 user_words.lua 中解析，不再依赖其生成的 user_words.dict.yaml
    type = ""   # tiger | wubi
    lines_users = []
    # user_words_path = out_dir / 'user_words.dict.yaml'
    user_words_path = Path(out_dir / '../lua/user_words.lua').resolve()
    # print(user_words_path)
    if user_words_path.exists():
        with open(user_words_path, 'r', encoding='utf-8') as f:
            print('☑️  已加载用户自造词文件 » %s' % user_words_path)
            for l in f.readlines():
                l = l.strip()
                if l.startswith('-- type'):
                    type = l.split(': ')[1]   # tiger | wubi
                if l.startswith('["'):
                    _arr = l.split('"] = "')
                    word = _arr[0][2:]
                    code = _arr[1][:-2]
                    weight = '100000000' if is_keep_user_dict_first else '1'
                    # print(f'{word}\t{code}\t{weight}')
                    lines_users.append(f'{word}\t{code}\t{weight}\n')
        # print(type)
        # ^ 虎码常规
        if type == 'tiger' and code_type == '30':
            lines_total.extend(lines_users)
        # ^ 五笔常规
        if type == 'wubi' and code_type == '20':
            lines_total.extend(lines_users)
        # ^ 小鹤音形
        if type == 'flyyx' and code_type == '40':
            lines_total.extend(lines_users)


    # 去重并处理词条
    for line in set(lines_total):
        if is_chinese_char(line[0]):
            word, code, weight = line.strip().split('\t')

            # 增加用户词语的权重，放大亿点点 100,000,000
            if is_keep_user_dict_first:
                weight = int(weight)  * 100000000 if not weight.endswith('00000000') else int(weight)
            else:
                weight = int(weight) if not weight.endswith('00000000') else int(weight[:-8])

            if word not in res_dict or weight > max(res_dict_weight[word]):
                res_dict[word] = f'{code}\t{weight}'
                res_dict_weight[word].add(weight)

    # 多级分组排序（词长→编码长度→编码→汉字）
    with open(out_dir / out_file, 'w', encoding='utf-8') as o:
        o.write(get_header_sync(out_file))
        
        # 第一级：按词长分组
        word_len_dict = defaultdict(list)
        for word, value in res_dict.items():
            word_len_dict[len(word)].append((word, value))

        # 处理每组词长
        for word_len in sorted(word_len_dict.keys()):
            # 过滤掉过长、过短(如 1)的词条
            if word_len == 1 or (word_length_limit > 0 and word_len > word_length_limit):
                continue

            # 第二级：按编码长度分组
            code_len_dict = defaultdict(list)
            for word, value in word_len_dict[word_len]:
                code = value.split('\t')[0]
                code_len_dict[len(code)].append((word, code, value))

            # 按编码长度处理
            for code_len in sorted(code_len_dict.keys()):
                # 关键修改：当编码相同时，按汉字unicode排序
                group = sorted(code_len_dict[code_len], 
                             key=lambda x: (x[1], x[0]))  # 先按编码排序，再按汉字排序
                for word, _, value in group:
                    o.write(f'{word}\t{value}\n')
            print(f'☑️  已合并处理生成 {word_len} 字词语')
        print('✅  » 已合并生成用户词典 %s' % (out_dir / out_file))


def exec(code_type = ''):
    # print(type(code_type), code_type)

    src_dir = Path('C:\\Users\\jack\\Nutstore\\1\\我的坚果云\\RimeSync\\jk-jack')
    out_dir = Path('C:\\Users\\jack\\AppData\\Roaming\\Rime\\dicts')

    src_file = 'jk_wubi.userdb.txt'
    out_file = 'wubi86_user.dict.yaml'

    code_dict = { '1': '拼音', '20': '五笔常规','21': '五笔整句','30': '虎码常规','31': '虎码整句', '40': '小鹤音形' }

    if code_type not in code_dict:
        print(f'''
🔔  请输入正确的用户词典标识码:
--------------------------------------------------------------------------------------
1 ➭ 拼音；20 ➭ 五笔常规；21 ➭ 五笔整句；30 ➭ 虎码常规；31 ➭ 虎码整句；40 ➭ 小鹤音形
--------------------------------------------------------------------------------------
        ''')
        code_type = input(f"🔔  默认「 虎码常规 」? (30): ").strip().lower() or "30"
        print(f'🔜  {code_type}   ➭ {code_dict[code_type]}\n')

    if code_type.startswith("1"):
        src_file = 'jk_pinyin_u.userdb.txt'
        out_file = 'pinyin_user.dict.yaml'
    elif code_type.startswith("20"):
        src_file = 'jk_wubi.userdb.txt'
        out_file = 'wubi86_user.dict.yaml'
    elif code_type.startswith("21"):
        src_file = 'jk_wubi_u.userdb.txt'
        out_file = 'wubi86_user_zj.dict.yaml'
    elif code_type.startswith("30"):
        src_file = 'jk_tiger.userdb.txt'
        out_file = 'tiger_user.dict.yaml'
    elif code_type.startswith("31"):
        src_file = 'jk_tiger_u.userdb.txt'
        out_file = 'tiger_user_zj.dict.yaml'
    elif code_type.startswith("40"):
        src_file = 'jk_flyyx.userdb.txt'
        out_file = 'flyyx_user.dict.yaml'

    # 如果存在输出文件，先删除
    current_out_file_temp = out_dir / f'{out_file + '.temp'}'
    if current_out_file_temp.exists():
        current_out_file_temp.unlink()
        
    print(f'🔜  === 开始同步转换「 {code_dict[code_type]} 」用户词库文件 ===')

    convert(src_dir, out_dir, src_file, out_file)
    # 合并至用户文件
    combine(out_dir, out_file)
    # 清理掉临时文件 *.temp
    current_out_file_temp.unlink()
    

if __name__ == '__main__':
    current_dir = Path.cwd()

    # --- ① 是否让用户词库排在最前 ---
    # 权重放大亿点点
    is_keep_user_dict_first = True

    # --- ② 编码类型 ---
    # 目标转码类型：
    # ¹ 拼音：¹1 moqi 墨奇, ¹2 flypy 鹤形, ¹3 zrm 自然码, ¹4 jdh 简单鹤, ¹5 cj 仓颉,
    #         ¹6 tiger 虎码首末, ¹7 wubi 五笔前二, ¹8 hanxin 汉心，¹0 纯拼音
    # 
    # ² 五笔：²1 五笔整句，²0 五笔常规
    # ³ 虎码：³1 虎码整句，³0 虎码常规 

    # ③ --- 词长限制 ---
    # 是否限制词库最大词长，若为 0 ，则不限制
    # - 主要是为了过滤掉包含已添加词汇的较长词条
    # - 默认删除了单字（因为积累单字毫无意义）
    word_length_limit = 7

    code_type = sys.argv[1] if len(sys.argv) > 1 else ''

    # 词长限制 -- 只限制拼音、整句，常规形码不限制
    if not (code_type.startswith("1") or code_type in ['21', '31']):
        word_length_limit = 0
    
    exec(code_type)
    
