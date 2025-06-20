from datetime import datetime

# --- 用户词典同步表头 ---
# 
def get_header_common(file_name):
    header = f'''
# Rime dictionary - {file_name}
# encoding: utf-8
# 
# Created by:
# - https://github.com/loveminimal/rime-jk
# - Jack Liu <https://aituyaa.com>
# 
---
name: {'.'.join(file_name.split('.')[:-2])}
version: {datetime.now().date().strftime("%Y.%m")}
sort: by_weight
use_preset_vocabulary: false
...
'''
    return header.strip() + '\n'


# --- 用户词典同步表头 ---
# 
def get_header_sync(file_name):
    header = f'''
# Rime dictionary - {file_name}
# encoding: utf-8
# 
# --- 说明 ---
# 该字典是基于官方自动同步的用户词典合并排序生成 - 越来越懂你的「养成系」词库
# - https://github.com/loveminimal/rime-jk
# - Jack Liu <https://aituyaa.com>
# 
# 运行脚本：
# - https://github.com/loveminimal/rime-jk/blob/master/scripts/sync_user_dict.py
# - py scripts/sync_user_dict.py
# 
---
name: {'.'.join(file_name.split('.')[:-2])}
version: {datetime.now().date().strftime("%Y.%m")}
sort: by_weight
use_preset_vocabulary: false
...
'''
    return header.strip() + '\n'


# --- 用户词典排序表头 ---
# 
def get_header_sort(file_name):
    header = f'''
# 
# --- 说明 ---------------------------------------------
# 该字典是按照「词长→编码长度→编码→汉字」多级分组排序
# 运行脚本：
# - https://github.com/loveminimal/rime-jk/blob/master/scripts/sort_dict.py
# 
'''
    return header.strip() + '\n'


# --- 扩展词典同步表头 ---
# 
def get_header_ext(file_name):
    header = f'''
# Rime dictionary - {file_name}
# encoding: utf-8
# 
# --- 说明 ---
# 该字典是基于拼音词库及自定义形码单字库处理合并排序生成
# - https://github.com/loveminimal/rime-jk
# - Jack Liu <https://aituyaa.com>
# 
# 参考码表：
# - 知心 」https://github.com/loveminimal/rime-jk
# - 万象 」https://github.com/amzxyz/rime_wanxiang
# - 白霜 」https://github.com/gaboolic/rime-frost
# - 雾凇 」https://github.com/iDvel/rime-ice
# - ……
# 
---
name: {'.'.join(file_name.split('.')[:-2])}
version: {datetime.now().date().strftime("%Y.%m")}
sort: by_weight
use_preset_vocabulary: false
...
'''
    return header.strip() + '\n'


# --- 自定义脚本指令 ---
# 
def get_en_aliases_header(file_name):
    header = f'''
# Rime dictionary - {file_name}
# encoding: utf-8
# 
# --- 说明 ---
# 该字典是对既有英文词典的个人扩充
# 用于自定义字符串、命令的快捷输入
# 转化自个人使用的 .bash_aliases 脚本别名文件
# - https://github.com/loveminimal/rime-jk
# - Jack Liu <https://aituyaa.com>
# 
# 运行脚本：
# - https://github.com/loveminimal/rime-jk/blob/master/scripts/sync_en_aliases_dict.py
# - py scripts/sync_en_aliases_dict.py
#
---
name: {'.'.join(file_name.split('.')[:-2])}
version: {datetime.now().date().strftime("%Y.%m")}
sort: by_weight
use_preset_vocabulary: false
...

'''
    return header.strip() + '\n'
