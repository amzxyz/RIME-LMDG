# fetch_any_dict.py
# encoding: utf-8
'''
# -------------------------------------------------------------------------
# 作用：
# 当前脚本用于拉取万象词库的最近更新，并进行「转换 ➭ 合并 ➭ 排序」处理，以
# 生成所需的五笔、虎码常规及整句词库、拼音词库
# 
# --- 其他说明 ---
# 其实稍微修改一下当前脚本，可以获得更多转换功能，有兴趣的朋友可以自行扩展
# -------------------------------------------------------------------------
'''
import os
import sys
import stat
import re
import shutil
import subprocess
import hashlib
from pathlib import Path
import threading
from timer import timer
from is_chinese_char import is_chinese_char
from progress import format_progress_bar
from pinyin2aux import load_metadata, process_input
from tiger_map import tiger_map
from wubi86_8105_map import wubi86_8105_map
from header import get_header_ext
from header import get_header_common
from collections import defaultdict
import zipfile
import urllib.request
from datetime import datetime, timedelta, timezone

def run_git_command(command, cwd=None):
    """执行git命令并返回是否成功"""
    try:
        result = subprocess.run(["git"] + command, cwd=cwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        return {
            "success": True,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip()
        }
    except subprocess.CalledProcessError:
        return False

def ask_yes_no(question, timeout=5):
    '''
    询问是否继续操作  
    question - 具体请求描述  
    timeout - 默认超过 5s 自动取消
    '''
    answer = [None]  # 使用列表以便在嵌套函数中修改
    def input_thread():
        answer[0] = input(f"{question} ? (y/n) y: ").strip().lower() or "y"

    print(f"\n--- 默认 {timeout} 秒后取消操作 ---")
    thread = threading.Thread(target=input_thread)
    thread.daemon = True
    thread.start()
    thread.join(timeout)
    if answer[0] in ("y", "yes"):
        print("🔜  » 继续操作 ¦ 即将开始执行...")
        return True
    else:
        print('\n🎉  » 取消操作 ¦ 祝你使用愉快')
        return False

def remove_readonly(func, path, exc):
    """
    清除只读属性并重新尝试删除。
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        print(f"Error removing {path}: {e}")

def force_delete(path):
    """
    强制删除文件或文件夹，忽略权限限制。
    """
    if not os.path.exists(path):
        return True
    try:
        if os.path.isfile(path) or os.path.islink(path):
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path, onexc=remove_readonly)
        return True
    except Exception as e:
        print(f"Error deleting {path}: {e}")
        return False


def sync_repository(repo_url, local_path):
    """同步Git仓库（克隆时只获取最新版本）"""
    git_dir = local_path / ".git"
    backup_path = local_path.with_suffix('.bak')
    sync_success = True

    if git_dir.exists():
        print(f"仓库已存在于 {local_path}")
        print(f"--- 拉取最新更新 ---")
        print(f"🔜  正在拉取最新更新...")
        pull_result = run_git_command(["pull", "--depth=10"], cwd=local_path)
        if pull_result and pull_result['success']:
            # print("输出信息:", pull_result["stdout"])
            if 'Already up to date' in pull_result["stdout"]:
                print("✅  » 无需转换 ¦ 仓库没有新的提交")
                # sync_success = False
                sync_success = ask_yes_no(f"🔔  是否继续执行转换操作")
                # if sync_success:
                #     print("🔜  » 继续转换 ¦ 即将开始转换...")
                # else:
                #     print("\n🎉  » 不再转换 ¦ 祝你使用愉快")
            else:
                print("✅  » 拉取更新成功")
        else:
            print("🚫  » 拉取更新失败")
            sync_success = False
            if local_path.exists():
                # if backup_path.exists():
                force_delete(backup_path)
                local_path.rename(backup_path)
                print(f"✅  » 当前仓库已备份为 { backup_path }")

                # 失败了之后回退版本后重试（避免源仓库强推导致错误）
                # run_git_command(["reset", "--hard HEAD~1"], cwd=local_path)
                run_git_command(["reset", "--hard", "HEAD~1"], cwd=local_path)

            print(f"--- 重新浅克隆 ---")
            sync_success = sync_repository(repo_url, local_path)
    else:
        print(f"🔜  正在浅克隆 {repo_url}...")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        
        if run_git_command(["clone", "--depth=10", repo_url, str(local_path)]):
            print(f"✅  » 仓库已浅克隆到 {local_path}")
            sync_success = True
        else:
            print("🚫  » 克隆仓库失败")
            if backup_path.exists():
                print(f"--- 开始恢复仓库 ---")
                # if local_path.exists():
                force_delete(local_path)
                backup_path.rename(local_path)
                print(f"✅  » 仓库恢复成功 {local_path}")
                sync_success = False
    return sync_success


def get_wubi_code(word: str) -> str:
    """将汉字转换为五笔编码"""
    if code_type.startswith("20"):
        # ^ 常规编码
        if len(word) == 1:
            return f'{wubi86_8105_map[word]}'
        elif len(word) == 2:
            return f'{wubi86_8105_map[word[0]][:2]}{wubi86_8105_map[word[1]][:2]}'
        elif len(word) == 3:
            return f'{wubi86_8105_map[word[0]][0]}{wubi86_8105_map[word[1]][0]}{wubi86_8105_map[word[2]][:2]}'
        elif len(word) >= 4:
            return f'{wubi86_8105_map[word[0]][0]}{wubi86_8105_map[word[1]][0]}{wubi86_8105_map[word[2]][0]}{wubi86_8105_map[word[len(word) - 1]][0]}'
    else:
        # ^ 整句编码
        code_parts = []
        for char in word:
            wubi_code = wubi86_8105_map[char]
            if len(wubi_code) == 3:
                code_parts.append(f"{wubi_code[:2]};{wubi_code[2:]}z")
            else:
                code_parts.append(f"{wubi_code[:2]};{wubi_code[2:]}")
        return ' '.join(code_parts)

def get_tiger_code(word: str) -> str:
    """将汉字转换为虎码编码"""
    if code_type.startswith("30"):
        # ^ 常规编码
        if len(word) == 1:
            return f'{tiger_map[word]}'
        elif len(word) == 2:
            return f'{tiger_map[word[0]][:2]}{tiger_map[word[1]][:2]}'
        elif len(word) == 3:
            return f'{tiger_map[word[0]][0]}{tiger_map[word[1]][0]}{tiger_map[word[2]][:2]}'
        elif len(word) >= 4:
            return f'{tiger_map[word[0]][0]}{tiger_map[word[1]][0]}{tiger_map[word[2]][0]}{tiger_map[word[len(word) - 1]][0]}'
    else:
        # ^ 整句编码
        code_parts = []
        for char in word:
            tiger_code = tiger_map[char]
            if len(tiger_code) == 3:
                code_parts.append(f"{tiger_code[:2]};{tiger_code[2:]}_")
            else:
                code_parts.append(f"{tiger_code[:2]};{tiger_code[2:]}")
        return ' '.join(code_parts)

def get_pinyin_code(code: str) -> str:
    """将汉字转换为拼音 + 辅助码编码（可选）"""
    code_parts = []
    for _code in code.split(' '):
        _cc = _code.split(';')
        fuzhuma = _cc[int(code_type[-1])] if not code_type.endswith('0') else ''
        code_parts.append(f'{_cc[0]}{";" if fuzhuma else ""}{fuzhuma}')

    return ' '.join(code_parts)


@timer
def convert(src_dir: Path, out_dir: Path, file_endswith_filter: str) -> None:
    """将拼音词库转换为五笔词库"""
    out_dir.mkdir(parents=True, exist_ok=True)
    tab_split_re = re.compile(r'\t+')

    list_with_tone = list('āáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜüńňǹ')
    list_without_tone = list('aaaaooooeeeeiiiiuuuuvvvvvnnn')

    res_dict_word_weight = {}
    valid_entries = set()
    _valid_entries = set()

    for file_num, file_path in enumerate(src_dir.glob(f'*{file_endswith_filter}'), 1):
        print(f'☑️  已加载第 {file_num} 份码表 » {file_path.name}')

        invalid_line_count = 0


        # 预处理，获取权重字的最大权重映射
        with open(file_path, 'r', encoding='utf-8') as fp:
            for line in fp:
                line = line.strip()
                if not line or not is_chinese_char(line[0]):
                    continue

                parts = tab_split_re.split(line)
                if len(parts) < 3:
                    continue
                word, _, weight = parts[0], parts[1], parts[2]

                # 避免 weight 中包含非数字的情况 
                if any(i not in '1234567890' for i in weight):
                    print(line)
                    weight = 1
                # 将权重转换为整数以便比较
                current_weight = int(weight)
                # 如果字不存在于字典中，或者当前权重更大，则更新字典
                # 拼音时由于存在多音字，不再根据 word 去重
                if code_type.startswith("1"):
                    res_dict_word_weight[word + get_md5(line)] = current_weight
                    continue

                if word not in res_dict_word_weight or current_weight > res_dict_word_weight[word]:
                    res_dict_word_weight[word] = current_weight


        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or not is_chinese_char(line[0]):
                    continue

                parts = tab_split_re.split(line)
                if len(parts) < 3:
                    continue

                word, code, weight = parts[0], parts[1], parts[2]
                # 不喜欢带调的（与其他可能使用的拼音词库同步后会冲突），转换成不带调的
                if is_clear_tone:
                    for idx, char in enumerate(list_with_tone):
                        code = code.replace(char, list_without_tone[idx])
                
                if word_length_limit > 0 and len(word) > word_length_limit:
                    # print(f"过滤掉长词语: {word} (长度: {len(word)})")
                    continue
                
                # 8105 过滤器开关 - is_filter_8105
                if is_filter_8105 and any(char not in wubi86_8105_map for char in word):
                    continue

                try:
                    if code_type.startswith("1"):
                        pinyin_code = get_pinyin_code(code)
                        valid_entries.add(f"{word}\t{pinyin_code}\t{res_dict_word_weight[word + get_md5(line)]}\n")
                    elif code_type.startswith("2"):
                        wubi_code = get_wubi_code(word)
                        # valid_entries.add(f"{word}\t{wubi_code}\t{res_dict_word_weight[word]}\n")
                        _valid_entries.add(f"{word}\t{wubi_code}")
                    elif code_type.startswith("3"):
                        tiger_code = get_tiger_code(word)
                        # valid_entries.add(f"{word}\t{tiger_code}\t{res_dict_word_weight[word]}\n")
                        _valid_entries.add(f"{word}\t{tiger_code}")
                except KeyError:
                    invalid_line_count += 1

    # 非拼音时去重多音字造成的重复词条
    if not code_type.startswith("1"):
        for wc in _valid_entries:
            # if wc == '从\tww;yz':
            #     print(wc)
            #     print(res_dict_word_weight[tab_split_re.split(wc)[0]])
            valid_entries.add(f"{wc}\t{res_dict_word_weight[tab_split_re.split(wc)[0]]}\n")

    if valid_entries:
        output_path = out_dir / f"{file_path.stem}.yaml"
        with open(output_path, 'w', encoding='utf-8') as o:
            o.writelines(get_header_common(f"{file_path.stem}.yaml"))
            o.writelines(sorted(valid_entries))

        # print(f"  成功转换 {len(valid_entries)} 条记录，跳过 {invalid_line_count} 条无效记录")


@timer
def filter_8105(src_dir: Path, out_file: Path):
    """过滤并合并五笔码表，保持按词长排序"""
    dict_num = 0
    res_dict = {}
    res_dict_code = defaultdict(set)
    tab_split_re = re.compile(r'\t+')
    word_len_groups = {}
    
    # 按词长分组处理
    for filepath in src_dir.iterdir():
        if filepath.is_file():
            dict_num += 1
            print(f'☑️  已加载第 {dict_num} 份码表 » {filepath.name}')
            
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line or not is_chinese_char(line[0]):
                        continue
                        
                    parts = tab_split_re.split(line.strip())
                    if len(parts) < 2:
                        continue
                        
                    word, code = parts[0], parts[1]
                    weight = parts[2] if len(parts) >= 3 else '0'
                    word_len = len(word)
                    
                    try:
                        if (word + get_md5(line)) not in res_dict or code not in res_dict_code[word]:
                            res_dict[word + get_md5(line)] = {code}
                            res_dict_code[word].add(code)
                            
                            if word_len not in word_len_groups:
                                word_len_groups[word_len] = []
                            word_len_groups[word_len].append(f"{word}\t{code}\t{weight}\n")
                    except KeyError:
                        continue
    
    print('\n🔜  --- 正在合并处理词库文件 ---')
    
    # 按词长排序并收集结果
    output_lines = []
    line_count_sum = 0
    for word_len in sorted(word_len_groups.keys()):
        group_lines = word_len_groups[word_len]
        output_lines.extend(group_lines)
        line_count_sum += len(group_lines)
        print(f'☑️  已合并处理生成 {word_len} 字词语，共计 {len(group_lines)} 行')
    
    print(f'✅ » 共生成 {line_count_sum} 行数据')
    
    # 写入输出文件
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists():
        out_file.unlink()
        
    with open(out_file, 'w', encoding='utf-8') as o:
        o.write(get_header_ext(out_file.name))
        o.writelines(output_lines)


def get_md5(text: str) -> str:
    """计算字符串的 MD5 哈希值"""
    md5 = hashlib.md5()  # 创建 MD5 对象
    md5.update(text.encode('utf-8'))  # 传入字节数据（必须 encode）
    return md5.hexdigest()  # 返回 32 位 16 进制字符串

@timer
def sort_dict(src_dir, out_dir, dict_start):
    """分组排序处理用户词典"""
    res_dict = {}
    lines_total = []

    # 加载所有词典文件
    for file_path in src_dir.iterdir():
        if file_path.is_file() and file_path.name.startswith(dict_start):
            with open(file_path, 'r', encoding='utf-8') as f:
                lines_total.extend(f.readlines())

    # 保留原有词典表头
    header_str = ''
    is_header_end = False
    for line in lines_total:
        if line.startswith('.'):
            is_header_end = True
        if not is_chinese_char(line[0]) and not is_header_end:
            header_str += line 


    # 去重并处理词条
    for line in set(lines_total):
        if is_chinese_char(line[0]):
            word, code, weight = line.strip().split('\t')
            weight = int(weight)
            
            # 唯一化
            # 拼音时由于存在多音字，不再根据 word 去重
            if code_type.startswith("1"):
                res_dict[word + get_md5(line)] = f'{code}\t{weight}'
                continue

            if word not in res_dict:
                res_dict[word + get_md5(line)] = f'{code}\t{weight}'


    # 多级分组排序（词长→编码长度→编码→汉字）
    with open(out_dir / f'{dict_start}.dict.yaml', 'w', encoding='utf-8') as o:
        o.write(header_str)
        # o.write(get_header_sort(out_file))
        o.write('...\n')
        
        # 第一级：按词长分组
        word_len_dict = defaultdict(list)
        for word, value in res_dict.items():
            word_len_dict[len(word)].append((word, value))

        # 处理每组词长
        for word_len in sorted(word_len_dict.keys()):
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
                    o.write(f'{word[:-32]}\t{value}\n')
            print(f'☑️  已排序处理生成 {word_len - 32} 字词语')
        print('✅ » 已排序生成用户词典 %s' % (out_dir / f'{dict_start}.dict.yaml'))


def get_remote_mtime(url):
    '''
    获取远程资源更新日期
    '''
    with urllib.request.urlopen(url) as response:
        last_modified = response.getheader('Last-Modified')
        if last_modified:
            # 转换GMT时间字符串为时间戳（需处理时区请自行调整）
            gmt_time = datetime.strptime(last_modified, '%a, %d %b %Y %H:%M:%S GMT')
            # 添加UTC时区标记
            utc_time = gmt_time.replace(tzinfo=timezone.utc)
            # 转换为北京时间（东八区）
            beijing_time = utc_time.astimezone(timezone(timedelta(hours=8)))
            
            return beijing_time.strftime('%Y-%m-%d %H:%M:%S')
    return None

def fetch_url_file(url, out_dir, is_download_gram = False):
    '''
    获取远程文件  
    url - 远程资源地址  
    out_dir - 存放目录  
    is_download_gram - 是否下载大模型  
    '''
    default_url = "https://github.com/amzxyz/rime_wanxiang.git"
    url = url or default_url

    filename = os.path.basename(url)
    filename = 'cn_dicts.zip' if not is_download_gram else 'wanxiang-lts-zh-hans.gram'
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with urllib.request.urlopen(url) as response:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            chunk_size = 8192  # 8KB

            with open(out_dir / filename, 'wb') as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    format_progress_bar(downloaded, total_size)
        print(f"\n✅ » 下载完成 {out_dir}")
    except Exception as e:
        print(f"\n下载失败：{e}")

@timer
def download_dict(url_dict, out_url_directory, is_download_gram = False):
    """
    url_dict - 如 https://github.com/amzxyz/rime_wanxiang/releases/download/dict-nightly/cn_dicts.zip
    out_url_directory - 如 C:\\Users\\jack\\AppData\\Roaming\\.temp_rime\\rime_url
    is_download_gram - False 默认不下载大模型
    """
    # 直接下载仓库词典文件
    url_dict = url_dict or url_dict_rime_wanxiang                                         # 远程资源地址
    out_url_directory = out_url_directory or (proj_dir / work_dir / 'rime_url').resolve() # 预设下载目录
    out_file = 'cn_dicts.zip'

    if is_download_gram:
        url_dict = url_dict or url_gram
        out_url_directory = out_url_directory or proj_dir
        out_file = 'wanxiang-lts-zh-hans.gram'

    print(f'🔜  远程资源： {url_dict}')
    print(f'🔜  目标路径： {out_url_directory}')
    
    # modified time
    # current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # print(f'当前时间：{current_datetime}')
    cur_remote_file_mtime = get_remote_mtime(url_dict)
    print(f'远程文件更新时间：{cur_remote_file_mtime}')

    if (out_url_directory / out_file).exists():
        pre_mtime = datetime.fromtimestamp(os.path.getmtime((out_url_directory / out_file))).strftime('%Y-%m-%d %H:%M:%S')
        # 文件上次下载时间 > 远程文件更新时间 ➭ 无需下载
        print(f'文件上次下载时间：{pre_mtime}')
        delta = datetime.strptime(pre_mtime, "%Y-%m-%d %H:%M:%S").timestamp() - datetime.strptime(cur_remote_file_mtime, "%Y-%m-%d %H:%M:%S").timestamp()
        # print(int(int(delta) / 60 / 60 / 24 ))
        if delta > 0:
            print('✅  » 无需下载 ¦ 仓库没有新的提交')
            return False
        else:
            fetch_url_file(url_dict, out_url_directory, is_download_gram)
    else:
        fetch_url_file(url_dict, out_url_directory, is_download_gram)
        # 解压整个ZIP文件到指定目录
        if not is_download_gram:
            with zipfile.ZipFile((out_url_directory / out_file), 'r') as zip_ref:
                zip_ref.extractall(out_url_directory)


def exec(proj_dir, work_dir, repository_url):
    exec_success = True

    # ① 同步仓库
    repository_url = repository_url or "https://cnb.cool/amzxyz/rime-wanxiang.git"
    repository_name = repository_url.split('/')[-1][:-4] # 如 rime_wanxiang
    local_directory = (proj_dir / work_dir / repository_name).resolve()
    out_dict = f'cn_dicts_{repository_name}'
    cn_dicts = 'cn_dicts' if repo_type != '1' else 'dicts' # 万象改字典名称了……

    # --- 仓库克隆 ---
    if int(dict_type) == 1:
        print('🔜  === 〔 仓库克隆 〕开始获取最新词库文件 ===')
        exec_success = sync_repository(repository_url, local_directory)
        if not exec_success:
            return False
    # --- 远程下载 ---
    if int(dict_type) == 2:
        print('🔜  === 〔 远程下载 〕开始获取最新词库文件 ===')
        # 直接下载仓库词典文件
        url_dict = url_dict_rime_wanxiang
        out_url_directory = (proj_dir / work_dir / 'rime_url').resolve()

        download_dict(url_dict, out_url_directory)
        exec_success = ask_yes_no("🔔  是否继续执行转换操作")
        if not exec_success:
            return False;
    
        # 更新工作文件目录 
        repository_name = 'rime_url'
        out_dict = 'cn_dicts_rime_url'

        print(f'☑️  已加载词典 {out_url_directory}/cn_dicts \n')                
    # --- 本地词典 ---
    if int(dict_type) == 3:
        print('🔜  === 〔 本地词典 〕开始转换本地词库文件 ===')
        if not local_directory.exists():
            print(f'''
🚫  请检查 .temp_rime/{repository_name}/cn_dicts 是否存在
--- Tips ---------------------------------------------------------------------
# ¹ 本地词库文件夹为 .temp_rime/rime_local/cn_dicts
# ² 其中 .temp_rime 与 scripts 父级目录同级
------------------------------------------------------------------------------
            ''')
            return False
        else:
            print(f'☑️  已加载词典 {local_directory}/cn_dicts \n')


    # '非万象Pro词库转换为带辅助码版本
    if code_type.startswith("1"):
        metadata_directory = Path(proj_dir / 'scripts').resolve()   # / 'auxiliary_code.yaml'
        input_path =  Path(proj_dir / work_dir / repository_name / cn_dicts).resolve()
        output_path = Path(proj_dir / work_dir / (repository_name + '_aux') / cn_dicts).resolve()
        # 如果存在输出文件，先删除
        if os.path.exists(output_path):
            shutil.rmtree(output_path)
        # os.mkdir(output_path)
        output_path.mkdir(parents=True, exist_ok=True)
        # 加载元数据
        metadata = load_metadata(metadata_directory)
        print(f'已加载 {len(metadata)} 个字符的元数据')
        # 处理输入路径
        process_input(input_path, metadata, output_path)

    # ② 转换拼音词库为目标词库
    src_dir = proj_dir / work_dir / repository_name / cn_dicts
    out_dir = proj_dir / work_dir / out_dict
    if code_type.startswith("1"):
        src_dir = proj_dir / work_dir / (repository_name + '_aux') / cn_dicts

    # 已存在，先删除，再转换
    if out_dir.exists():
        shutil.rmtree(out_dir)
    print('\n🔜  === 开始同步转换词库文件 ===')
    convert(src_dir, out_dir, '.dict.yaml')
    # return
    # 分包操作，以减小推送之后仓库快照体积
    if not is_merge:
        dist_dir = proj_dir / cn_dicts
        if dist_dir.exists():
            shutil.rmtree(dist_dir)
        shutil.copytree(out_dir, dist_dir)
        return

    # ③ 过滤合并五笔码表
    out_file_name = ''
    if code_type.startswith("1"):
        out_file_name = 'pinyin.dict.yaml'
    elif code_type.startswith("20"):
        out_file_name = 'wubi86_ext.dict.yaml'
    elif code_type.startswith("21"):
        out_file_name = 'wubi86_zj.dict.yaml'
    elif code_type.startswith("30"):
        out_file_name = 'tiger_ext.dict.yaml'
    elif code_type.startswith("31"):
        out_file_name = 'tiger_zj.dict.yaml'

    src_dir = proj_dir / work_dir / out_dict
    out_file = proj_dir / work_dir / out_file_name
    print('\n🔜  === 开始合并处理词库文件 ===')
    filter_8105(src_dir, out_file)
    
    # ④ 重新排序
    src_dir = proj_dir /  work_dir
    out_dir = proj_dir / 'dicts'
    dict_start = ''
    if code_type.startswith("1"):
        dict_start = 'pinyin'
    elif code_type.startswith("20"):
        dict_start = 'wubi86_ext'
    elif code_type.startswith("21"):
        dict_start = 'wubi86_zj'
    elif code_type.startswith("30"):
        dict_start = 'tiger_ext'
    elif code_type.startswith("31"):
        dict_start = 'tiger_zj'

    # 若不存在，创建
    if not out_dir.exists():
        out_dir.mkdir(parents=True, exist_ok=True)
    print('\n🔜  === 开始排序处理词库文件 ===')
    # 排序处理至用户词典
    sort_dict(src_dir, out_dir, dict_start)


    is_download_gram = ask_yes_no("🔔  是否继续下载语言大模型")
    if not is_download_gram:
        return False;
    download_dict(url_gram, proj_dir, is_download_gram)

if __name__ == "__main__":
    proj_dir = Path(__file__).resolve().parent.parent
    work_dir = "../.temp_rime"

    # ---------------------------------------------------------------------------------------
    # code_type         编码类型            → 详见下
    # dict_type         字典来源类型        → ¹仓库克隆  ²远程下载  ³本地词典
    # repo_type         仓库类型            → ¹万象拼音  ²白霜拼音  ³雾凇拼音  ⁰其它
    # is_download_gram  是否下载语言大模型  → ⁰否  ¹是
    # ---------------------------------------------------------------------------------------
    dict_type = 1
    code_type = 0
    repo_type = 0
    is_download_gram = 0
    for i, arg in enumerate(sys.argv):
        if arg == "-c":
            code_type = sys.argv[i + 1]
        elif arg == '-d':
            dict_type = sys.argv[i + 1]
        elif arg == '-r':
            repo_type = sys.argv[i + 1]
        elif arg == '-g':
            is_download_gram = sys.argv[i + 1]

    # === 可配置项 ===
    # ① --- 编码类型 ---
    # 目标转码类型：
    # ¹ 拼音：¹1 moqi 墨奇, ¹2 flypy 鹤形, ¹3 zrm 自然码, ¹4 jdh 简单鹤, ¹5 cj 仓颉,
    #         ¹6 tiger 虎码首末, ¹7 wubi 五笔前二, ¹8 hanxin 汉心，¹0 纯拼音
    # 
    # ² 五笔：²1 五笔整句，²0 五笔常规
    # ³ 虎码：³1 虎码整句，³0 虎码常规 
    code_dict = { 
        '10': '纯拼音', '11': '墨奇', '12': '鹤形', '13': '自然码', '14': '简单鹤', '15': '仓颉', '16': '虎码首末', '17': '五笔前二', '18': '汉心',  
        '20': '五笔常规','21': '五笔整句',
        '30': '虎码常规','31': '虎码整句' 
    }

    if code_type not in code_dict:
        print(f'''
🔔  请输入正确的词典标识码:
------------------------------------------------------------------------------
# 目标转码类型：
# ¹ 拼音：¹1 moqi 墨奇, ¹2 flypy 鹤形, ¹3 zrm 自然码, ¹4 jdh 简单鹤, ¹5 cj 仓颉,
#         ¹6 tiger 虎码首末, ¹7 wubi 五笔前二, ¹8 hanxin 汉心，¹0 纯拼音
# 
# ² 五笔：²1 五笔整句，²0 五笔常规
# ³ 虎码：³1 虎码整句，³0 虎码常规 

如：16 ➭ 拼音+虎码首末；20 ➭ 五笔常规；31 ➭ 虎码整句
------------------------------------------------------------------------------
        ''')
        code_type = input(f"🔔  默认「 鹤形 ¦ 辅助码 」? (12): ").strip().lower() or "12"
        # print(f'🔜  {code_type}   ➭ {code_dict[code_type]}\n')
    print(f'🔜  {code_type} {code_dict[code_type]} \n')

    # ② --- 字集过滤 ---
    # 是否开启 8105 通规字字符范围过滤「 🔥 强烈推荐开启 」
    # 该设置项仅供有扩展字符集需求的用户
    # 拼音、虎码已提供大字集映射，五笔默认提供 8105 通规字映射
    # !!! 再次强烈推荐开启
    is_filter_8105 = True

    # ③ --- 分包归并 ---
    # 分包还是归并「 合并后可提高 Rime 重新部署速度 」
    # - 归并 True （dicts/pinyin.dict.yaml、dicts/*_ext.dict.yaml、dicts/*_zj.dict.yaml）
    # - 分包 False （cn_dicts/*）
    is_merge = True

    # ④ --- 词长限制 ---
    # 是否限制词库最大词长，若为 0 ，则不限制
    word_length_limit = 0

    # ⑤ --- 仓库指定 ---
    # 字典来源类型 → ¹仓库克隆  ²远程下载  ³本地词典
    # ----------
    repository_url_wanxiang = "https://cnb.cool/amzxyz/rime-wanxiang.git"
    repository_url_frost = "https://github.com/gaboolic/rime-frost.git"
    repository_url_ice = "https://github.com/iDvel/rime-ice.git"
    # 
    repo_dict = { '1': '万象拼音', '2': '白霜拼音', '3': '雾凇拼音', '0': '其它' }
    repository_url = ''
    repository_url_str = ''
    # --- ¹仓库克隆 ---
    if int(dict_type) == 1:
        if repo_type not in repo_dict:
            print(f'''
🔔  请输入正确的仓库标识码:
------------------------------------------------------------------------------
# 目标候选仓库：
# ¹ 万象拼音 ² 白霜拼音  ³ 雾凇拼音  ⁰ 其它完整仓库地址 

如：0 ➭ https://github.com/amzxyz/rime_wanxiang.git
------------------------------------------------------------------------------
            ''')
            repo_type = input(f"🔔  默认「 万象拼音 」? (1): ").strip().lower() or "1"
        if repo_type == '1':
            repository_url = repository_url_wanxiang
        elif repo_type == '2':
            repository_url = repository_url_frost
        elif repo_type == '3':
            repository_url = repository_url_ice
        else:
            repository_url = input(f"🔔  请输入完整的仓库地址: ").strip()

        repo_type = str(repo_type)
        repository_url_str = (repo_dict[repo_type] + ' ➭ ' + repository_url) if repo_type != '0' else ('其它 ➭ ' + repository_url)
        print(f'🔜  {repository_url_str} \n')

    # --- ²远程下载 ---
    # 为了不增加脚本复杂性，我们固定本地词库文件夹为：
    # [ .temp_rime/rime_url/cn_dicts ]
    # 其中 .temp_rime 与 scripts 父级目录同级
    # ----------
    # url_dict_rime_ice = "https://github.com/iDvel/rime-ice/releases/download/2025.04.06/cn_dicts.zip"
    url_dict_rime_wanxiang = "https://github.com/amzxyz/rime_wanxiang/releases/download/dict-nightly/base-dicts.zip"
    # 
    # --- ³本地词典 ---
    # 为了不增加脚本复杂性，我们固定本地词库文件夹为 .temp_rime/rime_local/cn_dicts
    # 其中 .temp_rime 与 scripts 父级目录同级
    # [ rime_local/cn_dicts ]
    # ！仓库需要重命名为 rime_local ，字典置于 cn_dicts 中
    repository_url = 'rime_local.git' if int(dict_type) == 3 else repository_url
    # 
    # 是否需要下载语言大模型
    is_download_gram = bool(int(is_download_gram))
    url_gram = 'https://cnb.cool/amzxyz/rime-wanxiang/-/releases/download/model/wanxiang-lts-zh-hans.gram'

    # ⑥ --- 是否清除声调 ---
    # 万象拼音词库本身是带声调的
    # 清除←True  False→不清除
    is_clear_tone = True

    # 开始执行
    exec(proj_dir, work_dir, repository_url)