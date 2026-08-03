#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from advanced_settings import AdvancedSettingsMixin, deploy_rime_platform
import sys, os, re
import shutil
import time
import json
import hashlib
import fnmatch
import zipfile
import tempfile
import requests
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse
from typing import Dict, List, Tuple, Optional, Set, Callable
from dataclasses import dataclass
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLineEdit, 
                               QPushButton, QLabel)
from PySide6.QtCore import Signal, Qt
# pypinyin：优先从脚本同级加载（免安装）

def _base_dir() -> str:
    return getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))

def _ensure_pypinyin_on_path():
    base = _base_dir()
    local_pkg = os.path.join(base, 'pypinyin')
    vendor = os.path.join(base, 'vendor')
    if os.path.isdir(local_pkg):
        if base not in sys.path:
            sys.path.insert(0, base)
        if local_pkg not in sys.path:
            sys.path.insert(0, local_pkg)
    elif os.path.isdir(os.path.join(vendor, 'pypinyin')):
        if vendor not in sys.path:
            sys.path.insert(0, vendor)

try:
    from pypinyin import pinyin as pypinyin_func, Style, load_phrases_dict, load_single_dict
except Exception:
    _ensure_pypinyin_on_path()
    try:
        from pypinyin import pinyin as pypinyin_func, Style, load_phrases_dict, load_single_dict  # type: ignore
    except ImportError:
        pypinyin_func = None # 稍后处理

# --- PySide6 GUI ---
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QTranslator, QLibraryInfo, QTimer
from PySide6.QtGui  import QPalette, QColor, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QTabWidget, QCheckBox,
    QPlainTextEdit, QProgressBar, QLabel, QMessageBox, QGroupBox,
    QStyleFactory, QMenuBar, QDialog, QDialogButtonBox,
    QRadioButton, QButtonGroup, QComboBox, QGridLayout, QFrame, QSpinBox, QInputDialog, QMenu
)

# ============== 常量/工具 ==============
TOOL_VERSION = "v3.2.0beta"

AUX_SEP_REGEX = r'[;\[]'
YAML_HEADS = ('---', 'name:', 'version:', 'sort:', '...')
DEFAULT_SKIP_SET: Set[str] = {
    "duoyin.dict.yaml", "cuoyin.dict.yaml",
    "zi.dict.yaml", "renming.dict.yaml"
}
DEFAULT_WL_REGEX = [
    r"^custom_phrase\.txt$", 
    r".*userdb$", 
    r".*userdb\.txt", 
    r"sequence.*txt", 
    r"^(?!custom/).*\.custom\.yaml$", 
    r"^user\.yaml$", 
    r"^installation\.yaml$", 
    r"^sync/.*"
]





# =====================================================================
# 尝试导入 ruamel.yaml (用于安全修改 Rime 配置文件)
# =====================================================================
def _normalize_github_token(raw_token: str) -> str:
    """只保留 Token 本体，避免用户粘贴 Bearer/token 前缀后重复拼接。"""
    token = str(raw_token or "").strip()
    lowered = token.lower()

    for prefix in ("bearer ", "token "):
        if lowered.startswith(prefix):
            token = token[len(prefix):].strip()
            break

    return token


def _build_github_api_headers(raw_token: str) -> dict:
    """GitHub Token 只用于 api.github.com，不下发给代理或自定义地址。"""
    headers = {
        "User-Agent": "Rime-Wanxiang-Tool",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _normalize_github_token(raw_token)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _download_headers_for_url(
    url: str,
    *,
    using_github_proxy: bool,
    headers_cnb: dict,
    headers_github_download: dict,
    headers_github_proxy: dict,
    headers_external: dict,
) -> dict:
    """按最终请求主机选择请求头，确保 Token 不泄露到非 GitHub API 地址。"""
    host = (urlparse(str(url or "")).hostname or "").lower()

    if host == "cnb.cool" or host.endswith(".cnb.cool"):
        return headers_cnb

    if using_github_proxy:
        return headers_github_proxy

    # 官方 GitHub 文件下载不需要 API Token。公开 release 会继续跳转到
    # release-assets.githubusercontent.com；这里始终使用无 Authorization 请求头。
    if (
        host == "github.com"
        or host.endswith(".github.com")
        or host.endswith(".githubusercontent.com")
    ):
        return headers_github_download

    # 自定义 URL、其他镜像和未知主机一律不携带 GitHub Token。
    return headers_external


def _resolve_github_latest_tag(owner: str, repo: str) -> str:
    """通过 GitHub 网页 latest 跳转解析标签，不消耗 REST API 额度。"""
    latest_url = f"https://github.com/{owner}/{repo}/releases/latest"
    headers = {
        "User-Agent": "Rime-Wanxiang-Tool",
        "Accept-Encoding": "identity",
    }

    try:
        with requests.get(
            latest_url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(5, 12),
        ) as response:
            if response.status_code != 200:
                return ""

            path = urlparse(response.url).path
            marker = "/releases/tag/"
            if marker not in path:
                return ""

            return path.split(marker, 1)[1].split("/", 1)[0].strip()
    except Exception:
        return ""


# ============== 万象组件中文说明字典 ==============
# 方案高级配置 元数据模型 (定义界面怎么显示、对应 yaml 什么路径)

# =====================================================================
# 左侧菜单：文件分类与索引元数据
# =====================================================================
# ============== 键盘按键与 Rime 标识符映射表 ==============

# 辅助函数：安全读写嵌套字典 (全面支持 Rime 的 @0 数组语法)

# —— GitHub 链接 ——
GITHUB_LINKS = [
    ("万象拼音项目主页", "https://github.com/amzxyz/rime-wanxiang"),
    ("万象语法模型与词库工具", "https://github.com/amzxyz/RIME-LMDG"),
    ("CNB国内仓库",   "https://cnb.cool/amzxyz/rime-wanxiang"),
]

# —— 在线更新相关常量 ——
OWNER = "amzxyz"
REPO = "rime-wanxiang"
CNB_REPO = "rime-wanxiang"
MODEL_REPO = "RIME-LMDG"
DICT_TAG = "dict-nightly"
MODEL_FILE = "wanxiang-lts-zh-hans.gram"
MODEL_TAG = "LTS"
GITHUB_ROUTES = {
    0: {"name": "GitHub", "prefix": ""},
    1: {"name": "gh.b52m.cn", "prefix": "https://gh.b52m.cn/"},
    2: {"name": "gh-proxy.com", "prefix": "https://gh-proxy.com/"},
    3: {"name": "ghfast.top", "prefix": "https://ghfast.top/"},
    4: {"name": "xxlab", "prefix": "https://github.xxlab.tech/"},
    5: {"name": "xxooo", "prefix": "https://gh.xxooo.cf/"},
}

GITHUB_ROUTE_TEST_URL = (
    "https://github.com/amzxyz/rime-wanxiang/"
    "releases/download/dict-nightly/base-dicts.zip"
)
SCHEME_MAP = {
    'zrm': '自然码辅助 (Zrm)',
    'wx': '万象辅助 (WX)',
    'flypy': '小鹤辅助 (Flypy)',
    'moqi': '墨奇辅助 (Moqi)',
    'hanxin': '汉心辅助 (Hanxin)',
    'shouyou': '首右辅助 (Shouyou)',
    'shyplus': '首右+辅助 (Shyplus)',
    'tiger': '虎码辅助 (Tiger)',
    'wubi': '五笔辅助 (Wubi)'

}
# ======== 新增逻辑：双拼映射表 ========
# 为了方便你修改，我将所有方案的映射表集中定义在这里
# 目前除了【自然码】是完全按照你提供的填写的，其他方案暂时复制了自然码的作为占位
# 你可以在这里修改对应的 'initials', 'finals', 'zero' 字典

SP_ZRM_DATA = {
    "finals": {
        "iu": "q", "ua": "w", "ia": "w", "e": "e", "uan": "r", "ue": "t", "ve": "t", "uai": "y", "ing": "y",
        "i": "i", "u": "u", "uo": "o", "o": "o", "un": "p", "a": "a", "ong": "s", "iong": "s", "iang": "d",
        "uang": "d", "en": "f", "eng": "g", "ai": "l", "an": "j", "ang": "h", "ao": "k", "ei": "z", "ie": "x",
        "iao": "c", "ui": "v", "ian": "m", "ou": "b", "in": "n", "ü": "v"
    },
    "initials": {
        "b": "b", "c": "c", "d": "d", "f": "f", "g": "g", "h": "h", "j": "j", "k": "k", "l": "l", "m": "m",
        "n": "n", "p": "p", "q": "q", "r": "r", "s": "s", "t": "t", "w": "w", "x": "x", "y": "y", "z": "z",
        "ch": "i", "sh": "u", "zh": "v"
    },
    "zero": {
        "a": "aa", "o": "oo", "e": "ee", "er": "er", "en": "en", "eng": "eg",
        "ou": "ou", "ai": "ai", "ei": "ei", "an": "an", "ao": "ao"
    }
}
SP_FLYPY_DATA = {
    "finals": {
        "iu": "q", "ei": "w", "e": "e", "uan": "r", "ue": "t", "ve": "t", "un": "y",
        "i": "i", "u": "u", "uo": "o", "o": "o", "ie": "p", "a": "a", "ong": "s", "iong": "s", "ai": "d",
        "en": "f", "eng": "g", "iang": "l", "uang": "l", "an": "j", "ang": "h", "ing": "k", "uai": "k", "ou": "z", "ia": "x", "ua": "x",
        "ao": "c", "ui": "v", "ian": "m", "in": "b", "iao": "n", "ü": "v"
    },
    "initials": {
        "b": "b", "c": "c", "d": "d", "f": "f", "g": "g", "h": "h", "j": "j", "k": "k", "l": "l", "m": "m",
        "n": "n", "p": "p", "q": "q", "r": "r", "s": "s", "t": "t", "w": "w", "x": "x", "y": "y", "z": "z",
        "ch": "i", "sh": "u", "zh": "v"
    },
    "zero": {
        "a": "aa", "o": "oo", "e": "ee", "er": "er", "en": "en", "eng": "eg",
        "ou": "ou", "ai": "ai", "ei": "ei", "an": "an", "ao": "ao"
    }
}
SP_MSPY_DATA = {
    "finals": {
        "iu": "q", "ua": "w", "ia": "w", "e": "e", "uan": "r", "ue": "t", "uai": "y", "v": "y",
        "i": "i", "u": "u", "uo": "o", "o": "o", "un": "p", "a": "a", "ong": "s", "iong": "s", "iang": "d",
        "uang": "d", "en": "f", "eng": "g", "ai": "l", "an": "j", "ang": "h", "ao": "k", "ei": "z", "ie": "x",
        "iao": "c", "ui": "v", "ve": "v", "ian": "m", "ou": "b", "in": "n", "ü": "v", "ing": ";"
    },
    "initials": {
        "b": "b", "c": "c", "d": "d", "f": "f", "g": "g", "h": "h", "j": "j", "k": "k", "l": "l", "m": "m",
        "n": "n", "p": "p", "q": "q", "r": "r", "s": "s", "t": "t", "w": "w", "x": "x", "y": "y", "z": "z",
        "ch": "i", "sh": "u", "zh": "v"
    },
    "zero": {
        "a": "oa", "o": "oo", "e": "oe", "er": "er", "en": "en", "eng": "eg",
        "ou": "ou", "ai": "ai", "ei": "ei", "an": "an", "ao": "ao"
    }
}
SP_SOGOUPY_DATA = {
    "finals": {
        "iu": "q", "ua": "w", "ia": "w", "e": "e", "uan": "r", "ue": "t", "ve": "t", "uai": "y", "v": "y",
        "i": "i", "u": "u", "uo": "o", "o": "o", "un": "p", "a": "a", "ong": "s", "iong": "s", "iang": "d",
        "uang": "d", "en": "f", "eng": "g", "ai": "l", "an": "j", "ang": "h", "ao": "k", "ei": "z", "ie": "x",
        "iao": "c", "ui": "v", "ian": "m", "ou": "b", "in": "n", "ü": "v", "ing": ";"
    },
    "initials": {
        "b": "b", "c": "c", "d": "d", "f": "f", "g": "g", "h": "h", "j": "j", "k": "k", "l": "l", "m": "m",
        "n": "n", "p": "p", "q": "q", "r": "r", "s": "s", "t": "t", "w": "w", "x": "x", "y": "y", "z": "z",
        "ch": "i", "sh": "u", "zh": "v"
    },
    "zero": {
        "a": "oa", "o": "oo", "e": "oe", "er": "er", "en": "en", "eng": "eg",
        "ou": "ou", "ai": "ai", "ei": "ei", "an": "an", "ao": "ao"
    }
}
SP_PYJJ_DATA = {
    "finals": {
        "er": "q", "ing": "q","ei": "w", "e": "e", "en": "r", "eng": "t", "ong": "y", "iong": "y",
        "i": "i", "u": "u", "uo": "o", "o": "o", "ou": "p", "a": "a", "ai": "s", "ao": "d",
        "an": "f", "ang": "g", "in": "l", "ian": "j", "iang": "h", "uang": "h", "iao": "k", "un": "z", "ue": "x",
        "uai": "x","uan": "c", "v": "v", "ie": "m", "ia": "b", "ua": "b", "iu": "n", "ü": "v",
    },
    "initials": {
        "b": "b", "c": "c", "d": "d", "f": "f", "g": "g", "h": "h", "j": "j", "k": "k", "l": "l", "m": "m",
        "n": "n", "p": "p", "q": "q", "r": "r", "s": "s", "t": "t", "w": "w", "x": "x", "y": "y", "z": "z",
        "sh": "i", "ch": "u", "zh": "v"
    },
    "zero": {
        "a": "oa", "o": "oo", "e": "oe", "er": "eq", "en": "er", "eng": "et",
        "ou": "ou", "ai": "as", "ei": "ow", "an": "af", "ao": "ad"
    }
}
# 可以在此添加其他方案的真实映射
SHUANGPIN_SCHEMAS = {
    'zrm':    {'name': '自然码', 'data': SP_ZRM_DATA},
    'flypy':  {'name': '小鹤双拼', 'data': SP_FLYPY_DATA},
    'msp':    {'name': '微软双拼', 'data': SP_MSPY_DATA},
    'sogou':  {'name': '搜狗双拼', 'data': SP_SOGOUPY_DATA},
    'jj':     {'name': '拼音加加', 'data': SP_PYJJ_DATA},
    #'zg':     {'name': '紫光双拼', 'data': SP_ZRM_DATA}, # 待修改
    #'abc':    {'name': '智能ABC',  'data': SP_ZRM_DATA}, # 待修改
}

# 声调去除映射
TONE_MAP = str.maketrans("āáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ", "aaaaooooeeeeiiiiuuuuvvvv")

def is_userdb_head(line: str) -> bool:
    return ('#@/db_type\tuserdb' in line) or ('# Rime user dictionary' in line)

def is_dir_like(path: str) -> bool:
    return (path.endswith(('/', '\\')) or os.path.isdir(path) or not os.path.splitext(path)[1])

class CancelledError(Exception): pass

def system_check():
    """检查系统类型"""
    if sys.platform == 'win32':
        return 'windows'
    # iOS上a-shell、code app的Python环境sys.pltform也为'darwin'，因此取当前解释器路径进行判断
    elif sys.platform == 'darwin' and sys.executable.find('Code.app') >= 0:
        return 'ios'
    elif sys.platform == 'darwin' and sys.executable == 'python3':
        return 'ios'
    elif sys.platform == 'darwin':
        return 'macos'
    elif sys.platform == 'ios':
        return 'ios'
    else:
        return 'android/linux'

SYSTEM_TYPE = system_check()

# ============== 取消与强制中止支持 ==============
class CancelledError(Exception):
    """用于协作式中止"""
    pass

# ============== 逻辑 ①：刷拼音（严格对齐原脚本） ==============

def _load_from_files(file_paths: List[str], log) -> None:
    s_map, p_map = {}, {}
    for fpath in file_paths:
        try:
            with open(fpath, encoding='utf-8') as f:
                for line in f:
                    line = line.rstrip('\n')
                    if not line or line.startswith('#'): continue
                    parts = line.split('\t')
                    if len(parts) < 2: continue
                    word, pyline = parts[0], parts[1]
                    plist = pyline.split()
                    if len(word) == 1: s_map[ord(word)] = ','.join(plist)
                    else: p_map[word] = [[p] for p in plist]
        except Exception as e:
            log(f"[WARN] 读取 {fpath} 出错：{e}")
    if p_map:
        load_phrases_dict(p_map)
        log(f"✓ 词组拼音加载 {len(p_map)} 条")
    if s_map:
        load_single_dict(s_map)
        log(f"✓ 单字拼音加载 {len(s_map)} 条")

def load_custom_pinyin(custom_dir: Optional[str], log) -> None:
    if not custom_dir:
        log("使用默认拼音数据库。")
        return
    if not os.path.isdir(custom_dir):
        log(f"[WARN] 目录不存在：{custom_dir}（使用默认词库）")
        return
    file_list: List[str] = []
    cs = os.path.join(custom_dir, 'custom_single.txt')
    cp = os.path.join(custom_dir, 'custom_phrase.txt')
    if os.path.isfile(cs): file_list.append(cs)
    if os.path.isfile(cp): file_list.append(cp)
    if not file_list:
        for fn in os.listdir(custom_dir):
            if fn.endswith(('.txt', '.yaml')):
                file_list.append(os.path.join(custom_dir, fn))
    if not file_list:
        log("[WARN] 未找到 .txt/.yaml，自定义拼音跳过。")
        return
    log(f"使用自定义拼音目录：{custom_dir}")
    _load_from_files(file_list, log)

def tone_mark(seg: str) -> str:
    root = re.split(AUX_SEP_REGEX, seg)[0]
    suffix = seg[len(root):]
    py = pypinyin_func(root, style=Style.TONE, heteronym=False, errors='default')
    return (py[0][0] if py else root) + suffix
SP_PATTERN = re.compile(r"^(ch|sh|zh|[b-df-hj-np-tv-z]?)([a-zv]+)$")
CHINESE_PATTERN = re.compile(r'[^\u4E00-\u9FFF\u3400-\u4DBF\U00020000-\U0002A6DF]+')

def filter_non_chinese(word: str) -> str:
    return CHINESE_PATTERN.sub('', word)

def pinyin_normal_line(cols: List[str], ignore_non_chinese: bool, py_sep: str) -> Tuple[str, bool]:
    src = '\t'.join(cols)
    original_word = cols[0]
    word_for_pinyin = filter_non_chinese(original_word) if ignore_non_chinese else original_word
    char_py = [p[0] for p in pypinyin_func(word_for_pinyin, style=Style.TONE, heteronym=False, errors='default')]

    if len(cols) == 1:
        newline = '\t'.join([original_word, py_sep.join(char_py)])
        return newline, (newline != src)
    if len(cols) == 2 and cols[1].isdigit():
        newline = '\t'.join([original_word, py_sep.join(char_py), cols[1]])
        return newline, (newline != src)

    segs = cols[1].split()
    new_segs = []
    for i, py in enumerate(char_py):
        if i < len(segs):
            root = re.split(AUX_SEP_REGEX, segs[i])[0]
            suffix = segs[i][len(root):]
        else:
            suffix = ''
        new_segs.append(py + suffix)
    new_cols = list(cols); new_cols[1] = ' '.join(new_segs)
    newline = '\t'.join(new_cols)
    return newline, (newline != src)

def pinyin_userdb_line(cols: List[str], ignore_non_chinese: bool, py_sep: str) -> Tuple[str, bool]:
    src = '\t'.join(cols)
    segs = cols[0].split()
    original_word = cols[1]
    word_for_pinyin = filter_non_chinese(original_word) if ignore_non_chinese else original_word
    char_py = [p[0] for p in pypinyin_func(word_for_pinyin, style=Style.TONE, heteronym=False, errors='default')]

    new_segs = []
    for i, seg in enumerate(segs):
        base_py = char_py[i] if i < len(char_py) else tone_mark(seg)
        root    = re.split(AUX_SEP_REGEX, seg)[0]
        suffix  = seg[len(root):]
        new_segs.append(base_py + suffix)

    seg_join = py_sep.join(new_segs)
    if not seg_join.endswith(' '): seg_join += ' '
    newline = '\t'.join([seg_join, original_word] + cols[2:])
    return newline, (newline != src)

def pinyin_process_single_file(
    src: str, dst: str, skip_set: Set[str], ignore_non_chinese: bool, py_sep: str, 
    should_stop: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[int], None]] = None # [新增参数]
) -> Tuple[int, int]:
    if os.path.basename(src) in skip_set:
        with open(src, encoding='utf-8') as s, open(dst, 'w', encoding='utf-8') as d:
            txt = s.read(); d.write(txt)
            if progress_cb: progress_cb(txt.count('\n')) # 简单反馈
            return (txt.count('\n') + (1 if txt and not txt.endswith('\n') else 0), 0)

    total, changed = 0, 0
    userdb = False
    
    with open(src, encoding='utf-8') as s, open(dst, 'w', encoding='utf-8') as d:
        for raw in s:
            if should_stop and should_stop(): raise CancelledError()
            total += 1
            # [新增] 每1000行回调一次进度，避免频繁刷新卡死界面
            if progress_cb and total % 1000 == 0: progress_cb(total)

            line = raw.rstrip('\n')
            if line.startswith(YAML_HEADS) or line.startswith('#'):
                d.write(line + '\n')
                if is_userdb_head(line): userdb = True
                continue
            if not line.strip():
                d.write('\n'); continue

            cols = line.split('\t')
            if userdb and len(cols) >= 3:
                newline, ch = pinyin_userdb_line(cols, ignore_non_chinese, py_sep)
            else:
                newline, ch = pinyin_normal_line(cols, ignore_non_chinese, py_sep)
            if ch: changed += 1
            d.write(newline + '\n')
    return total, changed

# ============== 逻辑 ②：刷新辅助码（严格对齐原脚本） ==============

def load_aux_metadata(path: str, log) -> Dict[str, str]:
    if not os.path.isfile(path): raise FileNotFoundError("辅助码文件不存在")
    aux_map: Dict[str, str] = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            if not line.strip() or line.startswith('#'): continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) < 2 or len(parts[0]) != 1: continue
            char = parts[0]
            seg_full = parts[1]
            seg_parts = re.split(AUX_SEP_REGEX, seg_full, maxsplit=1)
            aux_map[char] = (seg_parts[1].strip() if len(seg_parts) > 1 else seg_full.strip())
            if aux_map[char] == ';': aux_map[char] = ''
    log(f"✓ 辅助码加载 {len(aux_map)} 条")
    return aux_map

def build_seg_by_aux(word: str, aux_map: Dict[str, str]) -> List[str]:
    return [aux_map.get(ch, '') for ch in word]

def refresh_aux(cols: List[str], word: str, aux_map: Dict[str, str], userdb: bool, ignore_non_chinese: bool) -> Tuple[List[str], bool]:
    before = '\t'.join(cols)
    if ignore_non_chinese: word = filter_non_chinese(word)
    if not userdb and len(cols) == 1: cols.insert(1, '')
    if userdb and len(cols) < 2: cols.append('')
    
    seg_idx = 0 if userdb else 1
    raw_segs = cols[seg_idx].strip().split() if seg_idx < len(cols) else []
    aux_segs = build_seg_by_aux(word, aux_map)
    
    merged = []
    for i, seg in enumerate(raw_segs):
        parts = seg.split(';')
        py_part = parts[0]
        aux = aux_segs[i] if i < len(aux_segs) else ''
        merged.append(f"{py_part};{aux}")
    
    if userdb:
        cols[0] = ' '.join(merged)
        if not cols[0].endswith(' '): cols[0] += ' '
    else:
        cols[seg_idx] = ' '.join(merged)
    
    after = '\t'.join(cols)
    return cols, (after != before)

def aux_process_single_file(
    src: str, dst: str, aux_map: Dict[str, str], ignore_non_chinese: bool, 
    should_stop: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[int], None]] = None # [新增参数]
) -> Tuple[int, int]:
    userdb = False
    total, changed = 0, 0
    with open(src, encoding='utf-8') as s, open(dst, 'w', encoding='utf-8') as d:
        for raw in s:
            if should_stop and should_stop(): raise CancelledError()
            total += 1
            if progress_cb and total % 1000 == 0: progress_cb(total) # [新增]

            line = raw.rstrip('\n')
            if line.startswith(YAML_HEADS) or line.startswith('#'):
                d.write(line + '\n')
                if is_userdb_head(line): userdb = True
                continue
            if not line.strip():
                d.write('\n'); continue

            cols = line.split('\t')
            word = cols[1] if userdb else cols[0]
            new_cols, ch = refresh_aux(cols, word, aux_map, userdb, ignore_non_chinese)
            if ch: changed += 1
            d.write('\t'.join(new_cols) + '\n')
    return total, changed
# ============== 逻辑 ③：双拼转换 (新增) ==============

def clean_pinyin(pinyin: str) -> str:
    """移除拼音中的声调，并转换 ü -> v"""
    return pinyin.translate(TONE_MAP).replace("ü", "v")

def convert_to_shuangpin(pinyin: str, schema_data: dict) -> str:
    """将单个拼音音节转换为双拼"""
    pinyin = clean_pinyin(pinyin)
    initials_map = schema_data.get('initials', {})
    finals_map = schema_data.get('finals', {})
    zero_map = schema_data.get('zero', {})
    match = SP_PATTERN.match(pinyin)
    if not match:
        return pinyin
    initial, final = match.groups()
    # 处理零声母
    if not initial and final in zero_map:
        return zero_map[final]
    
    sp_initial = initials_map.get(initial, "")
    sp_final = finals_map.get(final, final) 
    
    return sp_initial + sp_final
# ==================== 修改位置 1：逻辑处理函数 ====================

def shuangpin_process_line(cols: List[str], schema_data: dict, in_sep: str, out_sep: str, is_jianma: bool) -> Tuple[str, bool]:
    """处理单行双拼转换"""
    src = '\t'.join(cols)
    if len(cols) < 2: return src, False # 格式不对
    
    # cols[0]=汉字, cols[1]=拼音串, cols[2]=权重(可选)
    original_pinyin_str = cols[1]
    
    # 1. 使用 [输入分隔符] 切割原始拼音
    # 如果用户没填分隔符，split(None) 会自动按空白字符切割
    sep_char = in_sep if in_sep else None
    pinyin_list = original_pinyin_str.split(sep_char)
    
    # 2. 逐个转换
    sp_list = [convert_to_shuangpin(p, schema_data) for p in pinyin_list]
    # 2.5简码提取：取每个双拼音节的第一个字母，如果是空字符串则保持空
    if is_jianma:
        sp_list = [s[0] if s else "" for s in sp_list]
    # 3. 使用 [输出分隔符] 连接双拼
    # 如果用户没填，则默认为无缝连接，但用户现在要求默认空格
    out_join_char = out_sep if out_sep else "" 
    new_sp_str = out_join_char.join(sp_list)
    
    cols[1] = new_sp_str
    newline = '\t'.join(cols)
    return newline, (newline != src)

def shuangpin_process_single_file(
    src: str, dst: str, schema_key: str, in_sep: str, out_sep: str, is_jianma: bool, 
    should_stop: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[int], None]] = None # [新增参数]
) -> Tuple[int, int]:
    total, changed = 0, 0
    schema_info = SHUANGPIN_SCHEMAS.get(schema_key)
    if not schema_info: return 0, 0
    schema_data = schema_info['data']

    with open(src, encoding='utf-8') as s, open(dst, 'w', encoding='utf-8') as d:
        for raw in s:
            if should_stop and should_stop(): raise CancelledError()
            total += 1
            if progress_cb and total % 1000 == 0: progress_cb(total) # [新增]

            line = raw.rstrip('\n')
            if line.startswith(YAML_HEADS) or line.startswith('#'):
                d.write(line + '\n'); continue
            if not line.strip(): 
                d.write('\n'); continue
            
            cols = line.split('\t')
            newline, ch = shuangpin_process_line(cols, schema_data, in_sep, out_sep, is_jianma)
            
            if ch: changed += 1
            d.write(newline + '\n')
            
    return total, changed
# ============== 任务线程 (本地工具) ==============
@dataclass
class JobArgs:
    op: int  # 1=刷拼音, 2=刷辅助码， 3=双拼转换
    in_path: str
    out_path: str
    custom_dir: Optional[str] = None
    aux_file: Optional[str] = None
    skip_set: Optional[Set[str]] = None
    ignore_non_chinese: bool = True
    py_sep: Optional[str] = None
    sp_schema: Optional[str] = None # 双拼转换方案key
    sp_out_sep: Optional[str] = None #双拼转换输出分隔符
    sp_is_jianma: bool = False # 是否输出简码
# ==================== 修改位置：Worker 类 (支持多文件合并计算总行数进度) ====================
class Worker(QThread):
    log_sig = Signal(str)
    progress_sig = Signal(int, int)
    done_sig = Signal(bool, str, dict)

    def __init__(self, args: JobArgs):
        super().__init__()
        self.args = args
        self._stop = False
        self.aux_map: Optional[Dict[str, str]] = None

    def log(self, msg: str): self.log_sig.emit(msg)

    def collect_tasks(self, path_in: str) -> List[Tuple[str, str]]:
        tasks = []
        if os.path.isfile(path_in):
            tasks.append((path_in, ""))
        else:
            for root, _dirs, files in os.walk(path_in):
                for fn in files:
                    if not fn.endswith(('.txt', '.yaml')): continue
                    tasks.append((os.path.join(root, fn), ""))
        return tasks

    def should_stop(self) -> bool:
        return self._stop or self.isInterruptionRequested()

    def _count_lines(self, fpath: str) -> int:
        """快速统计单个文件行数"""
        count = 0
        try:
            with open(fpath, 'rb') as f:
                for _ in f: count += 1
        except: pass
        return count

    def run(self):
        try:
            op = self.args.op
            in_path = self.args.in_path
            out_path = self.args.out_path

            if not in_path: self.done_sig.emit(False, "请输入输入路径", {}); return
            if not out_path: self.done_sig.emit(False, "请输入输出路径", {}); return
            if op == 2 and not self.args.aux_file: self.done_sig.emit(False, "请选择辅助码文件", {}); return

            # 1. 构建任务列表
            if os.path.isfile(in_path):
                if is_dir_like(out_path):
                    dst = os.path.join(out_path, os.path.basename(in_path))
                else:
                    dst = out_path
                Path(dst).parent.mkdir(parents=True, exist_ok=True)
                tasks = [(in_path, dst)]
            else:
                tasks = []
                for src0, _ in self.collect_tasks(in_path):
                    rel = os.path.relpath(os.path.dirname(src0), in_path)
                    ddir = os.path.join(out_path, rel)
                    Path(ddir).mkdir(parents=True, exist_ok=True)
                    tasks.append((src0, os.path.join(ddir, os.path.basename(src0))))

            total_files = len(tasks)
            if total_files == 0: self.done_sig.emit(False, "未找到待处理的 .txt/.yaml 文件", {}); return

            # 2. 初始化资源
            if op == 1:
                load_custom_pinyin(self.args.custom_dir, self.log)
                skip_set = set(DEFAULT_SKIP_SET)
                if self.args.skip_set is not None: skip_set = {x for x in self.args.skip_set if x}
            elif op == 2:
                skip_set = set()
                self.aux_map = load_aux_metadata(self.args.aux_file or "", self.log)
            else: # op == 3 双拼
                skip_set = set()
                if not self.args.sp_schema or self.args.sp_schema not in SHUANGPIN_SCHEMAS:
                    self.done_sig.emit(False, "未知的双拼方案", {}); return

            # ==================== [新增逻辑] 预扫描总行数 ====================
            self.log("⏳ 正在预扫描所有文件行数，请稍候...")
            grand_total_lines = 0
            for src, _ in tasks:
                if self.should_stop(): return
                grand_total_lines += self._count_lines(src)
            
            if grand_total_lines == 0: grand_total_lines = 1 # 防止除以零
            self.log(f"📊 任务统计：共 {total_files} 个文件，合计约 {grand_total_lines} 行。")
            # ===============================================================

            files_changed = lines_total = lines_changed = 0
            lines_finished_previously = 0 # 记录之前已完成文件的总行数

            for i, (src, dst) in enumerate(tasks, 1):
                if self.should_stop():
                    self.done_sig.emit(False, "已中止", {"total_files": i - 1, "files_changed": files_changed, "lines_total": lines_total, "lines_changed": lines_changed}); return
                
                temp_dst = dst + ".tmp_processing"
                
                # 定义动态回调函数：当前总进度 = 之前文件的行数 + 当前文件正处理的行数
                def _global_progress_cb(curr_file_lines):
                    current_total = lines_finished_previously + curr_file_lines
                    self.progress_sig.emit(current_total, grand_total_lines)

                try:
                    # 传入回调函数
                    if op == 1:
                        t, c = pinyin_process_single_file(src, temp_dst, skip_set, self.args.ignore_non_chinese, self.args.py_sep, self.should_stop, progress_cb=_global_progress_cb)
                    elif op == 2:
                        t, c = aux_process_single_file(src, temp_dst, self.aux_map or {}, self.args.ignore_non_chinese, self.should_stop, progress_cb=_global_progress_cb)
                    elif op == 3:
                        t, c = shuangpin_process_single_file(src, temp_dst, self.args.sp_schema, self.args.py_sep, self.args.sp_out_sep, self.args.sp_is_jianma, self.should_stop, progress_cb=_global_progress_cb)
                    
                    if os.path.exists(dst):
                        os.remove(dst) 
                    os.rename(temp_dst, dst)

                except CancelledError:
                    if os.path.exists(temp_dst): os.remove(temp_dst)
                    self.done_sig.emit(False, "⚠️已中止", {"total_files": i - 1, "files_changed": files_changed, "lines_total": lines_total, "lines_changed": lines_changed}); return
                except Exception as e:
                    if os.path.exists(temp_dst): os.remove(temp_dst)
                    import traceback
                    traceback.print_exc()
                    self.done_sig.emit(False, f"出错：{e}", {})
                    return

                # 更新统计数据
                lines_total += t; lines_changed += c
                if c > 0: files_changed += 1
                
                # 关键：累加当前文件实际行数到全局计数器
                lines_finished_previously += t 

                if os.path.abspath(src) == os.path.abspath(dst):
                    display_info = f"{os.path.basename(src)} (覆盖)"
                else:
                    display_info = f"{os.path.basename(src)} → {os.path.relpath(dst, out_path)}"
                
                self.log(f"✓ 完成 {display_info}（改动 {c}/{t} 行）")

            # 强制进度条走满 (防止行数统计微小误差)
            self.progress_sig.emit(grand_total_lines, grand_total_lines)

            stats = dict(total_files=total_files, files_changed=files_changed, lines_total=lines_total, lines_changed=lines_changed)
            self.done_sig.emit(True, "全部处理完成", stats)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.done_sig.emit(False, f"出错：{e}", {})

    def stop(self):
        self._stop = True
        self.requestInterruption()
# ============== 新增逻辑：在线更新 (独立于原有 Worker) ==============
@dataclass
class UpdateConfig:
    scope: int  # 0=全量, 1=方案  2=仅词库, 3=仅模型
    scheme_type: str  # 'base' or 'pro'
    aux_scheme: str
    rime_dir: str
    github_token: str
    github_proxy: str
    use_mirror: bool
    whitelist: List[str]
    current_versions: Dict[str, str]
    clean_build: bool
    clean_before: bool
    custom_url: Optional[str] # 自定义下载源 URL
    server_path: str = ""   # 算法服务路径 (WeaselServer.exe)
    deployer_path: str = "" # 部署工具路径 (WeaselDeployer.exe)
    force_update: bool = False #强制更新
    proxy_slow_fallback: bool = True
    proxy_min_speed_kbps: int = 128
class PathDetector:
    """按平台检测 Rime 用户目录及部署程序。

    Windows 检测保持受控：
    1. 优先读取小狼毫原有注册表；
    2. 同时兼容 32/64 位注册表视图及 HKCU/HKLM；
    3. 注册表无结果时，仅检查明确的常见安装目录和 PATH；
    4. 不递归扫描整块磁盘。
    """

    @staticmethod
    def _clean_windows_path(value) -> str:
        if value is None:
            return ""
        value = os.path.expandvars(str(value).strip().strip('"'))
        return os.path.normpath(value) if value else ""

    @classmethod
    def _read_registry_value(cls, winreg, hive, key_path, value_name, view_flag=0) -> str:
        access = winreg.KEY_READ | view_flag
        try:
            with winreg.OpenKey(hive, key_path, 0, access) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                return cls._clean_windows_path(value)
        except OSError:
            return ""

    @classmethod
    def _registry_views(cls, winreg):
        views = [0]
        for attr in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
            flag = getattr(winreg, attr, 0)
            if flag and flag not in views:
                views.append(flag)
        return views

    @classmethod
    def _candidate_weasel_dirs(cls, registry_roots):
        candidates = []

        def add(path):
            path = cls._clean_windows_path(path)
            if not path:
                return
            p = Path(path)
            if p.suffix.lower() == ".exe":
                p = p.parent
            key = os.path.normcase(os.path.abspath(str(p)))
            if key not in seen:
                seen.add(key)
                candidates.append(p)

        seen = set()
        for root in registry_roots:
            add(root)

        env = os.environ
        for base_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = env.get(base_name, "")
            if not base:
                continue
            add(Path(base) / "Rime")
            add(Path(base) / "Programs" / "Rime")
            add(Path(base) / "Rime" / "Weasel")

        user_profile = env.get("USERPROFILE", "")
        if user_profile:
            add(Path(user_profile) / "scoop" / "apps" / "weasel" / "current")
            add(Path(user_profile) / "AppData" / "Local" / "Programs" / "Rime")

        # 只展开一层版本目录，例如 Rime/weasel-0.17.x。
        expanded = list(candidates)
        for parent in list(candidates):
            try:
                if parent.is_dir():
                    for child in sorted(parent.glob("weasel-*"), reverse=True):
                        add(child)
            except OSError:
                continue

        return candidates

    @classmethod
    def _find_weasel_executables(cls, registry_roots):
        server_path = ""
        deployer_path = ""

        # PATH 中存在时优先采用。
        path_server = shutil.which("WeaselServer.exe") or ""
        path_deployer = shutil.which("WeaselDeployer.exe") or ""
        if path_server and os.path.isfile(path_server):
            server_path = os.path.abspath(path_server)
        if path_deployer and os.path.isfile(path_deployer):
            deployer_path = os.path.abspath(path_deployer)

        for directory in cls._candidate_weasel_dirs(registry_roots):
            if not server_path:
                candidate = directory / "WeaselServer.exe"
                if candidate.is_file():
                    server_path = str(candidate.resolve())

            if not deployer_path:
                candidate = directory / "WeaselDeployer.exe"
                if candidate.is_file():
                    deployer_path = str(candidate.resolve())

            if server_path and deployer_path:
                break

        return server_path, deployer_path

    @classmethod
    def detect(cls) -> Dict[str, str]:
        detected = {
            "rime_user_dir": "",
            "weasel_server": "",
            "weasel_deployer": "",
        }

        if SYSTEM_TYPE == "windows":
            import winreg

            views = cls._registry_views(winreg)

            # 用户目录沿用原来的 HKCU\Software\Rime\Weasel。
            for view in views:
                detected["rime_user_dir"] = cls._read_registry_value(
                    winreg,
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Rime\Weasel",
                    "RimeUserDir",
                    view,
                )
                if detected["rime_user_dir"]:
                    break

            registry_roots = []
            registry_specs = (
                (winreg.HKEY_CURRENT_USER, r"Software\Rime\Weasel"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Rime\Weasel"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Rime\Weasel"),
            )
            root_value_names = ("WeaselRoot", "InstallDir", "InstallPath")

            for hive, key_path in registry_specs:
                for view in views:
                    for value_name in root_value_names:
                        root = cls._read_registry_value(
                            winreg,
                            hive,
                            key_path,
                            value_name,
                            view,
                        )
                        if root and root not in registry_roots:
                            registry_roots.append(root)

            server_path, deployer_path = cls._find_weasel_executables(
                registry_roots
            )
            detected["weasel_server"] = server_path
            detected["weasel_deployer"] = deployer_path

            if not detected["rime_user_dir"]:
                appdata = os.environ.get("APPDATA", "")
                if appdata:
                    detected["rime_user_dir"] = os.path.join(appdata, "Rime")

        elif SYSTEM_TYPE == "macos":
            detected["rime_user_dir"] = os.path.expanduser("~/Library/Rime")
        else:
            detected["rime_user_dir"] = os.path.expanduser(
                "~/.local/share/fcitx5/rime"
            )

        return detected

class GithubRouteTestWorker(QThread):
    """测试少量 GitHub 下载路线，避免阻塞主界面。"""

    done_sig = Signal(object)

    def __init__(self, test_url):
        super().__init__()
        self.test_url = test_url

    def _test_route(self, route):
        prefix = route["prefix"]
        test_url = f"{prefix}{self.test_url}" if prefix else self.test_url

        headers = {
            "User-Agent": "Rime-Wanxiang-Tool",
            "Range": "bytes=0-65535",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
        }

        started = time.perf_counter()
        received = 0
        signature = b""

        try:
            with requests.get(
                test_url,
                headers=headers,
                stream=True,
                allow_redirects=True,
                timeout=(4, 8),
            ) as response:
                if response.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {response.status_code}")

                content_type = response.headers.get("content-type", "").lower()

                if "text/html" in content_type:
                    raise RuntimeError("返回了网页")

                for chunk in response.iter_content(chunk_size=16384):
                    if not chunk: continue

                    if len(signature) < 4:
                        signature += chunk[:4 - len(signature)]

                    received += len(chunk)

                    if received >= 65536:
                        break

            if received == 0:
                raise RuntimeError("没有收到数据")

            zip_signatures = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

            if not signature.startswith(zip_signatures):
                raise RuntimeError(f"返回内容不是ZIP，文件头={signature!r}")

            elapsed = time.perf_counter() - started

            return {
                "ok": True,
                "ms": elapsed * 1000,
                "bytes": received,
            }

        except Exception as error:
            return {
                "ok": False,
                "ms": float("inf"),
                "error": str(error),
            }
    def run(self):
        results = {}

        for route_id, route in GITHUB_ROUTES.items():
            results[route_id] = self._test_route(route)

        self.done_sig.emit(results)
class ProxySpeedTooSlow(RuntimeError):
    """第三方代理持续低速，需要立即交给CNB兜底。"""


class UpdateWorker(QThread):
    log_sig = Signal(str)
    progress_sig = Signal(str, int, int) # task, cur, total
    done_sig = Signal(bool, str)
    version_sig = Signal(str, str)
    
    def __init__(self, config: UpdateConfig):
        super().__init__()
        self.cfg = config
        self._stop = False
        self._api_cache = {}
        self.whitelist_patterns = []
        for p in self.cfg.whitelist:
            if p.strip():
                try:
                    self.whitelist_patterns.append(re.compile(p.strip(), re.IGNORECASE))
                except re.error:
                    self.log(f"[Warn] 无效的正则规则: {p}")

        self.headers_cnb = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/vnd.cnb.web+json",
        }

        # Token 仅用于 GitHub 官方 API。
        self.headers_gh_api = _build_github_api_headers(
            self.cfg.github_token
        )

        # GitHub 官方 release 下载不携带 Token。
        self.headers_gh_download = {
            "User-Agent": "Rime-Wanxiang-Tool",
            "Accept-Encoding": "identity",
        }

        # 第三方 GitHub 代理永远不添加 Authorization。
        self.headers_gh_proxy = {
            "User-Agent": "Rime-Wanxiang-Tool",
            "Accept-Encoding": "identity",
        }

        # 自定义 URL 与其他未知来源也永远不携带 GitHub Token。
        self.headers_external = {
            "User-Agent": "Rime-Wanxiang-Tool",
            "Accept-Encoding": "identity",
        }
    def log(self, msg): self.log_sig.emit(msg)
    def stop(self): self._stop = True
    def _finish_cancelled(self):
        self.done_sig.emit(False, "⏹ 更新已取消。")
    # --- SHA256 计算工具 ---
    def _calculate_sha256(self, file_path):
        """计算本地文件的 SHA256 (用于比对跳过下载)"""
        if not os.path.exists(file_path): return None
        sha256 = hashlib.sha256()
        try:
            with open(file_path, 'rb') as f:
                for block in iter(lambda: f.read(4096), b""):
                    sha256.update(block)
            return sha256.hexdigest()
        except Exception as e:
            self.log(f"[Warn] 计算哈希出错: {e}")
            return None

    def _kill_rime_process(self):
        """强制终止 Rime 进程以释放文件锁"""
        if SYSTEM_TYPE == 'windows':
            self.log("正在终止小狼毫算法服务 (解锁文件)...")
            try:
                subprocess.run(['taskkill', '/F', '/IM', 'WeaselServer.exe'], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=0x08000000)
                subprocess.run(['taskkill', '/F', '/IM', 'WeaselDeployer.exe'], 
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=0x08000000)
                time.sleep(1.5) 
            except Exception as e:
                self.log(f"[Warn] 终止进程操作异常: {e}")
        elif SYSTEM_TYPE == 'macos':
            self.log("macOS 无需终止 Squirrel，保持进程运行以接收重新部署指令。")


    def _start_and_deploy(self):
        """执行 Rime 部署/重载，并在实际部署前重新确认平台路径。"""
        if self.cfg.clean_build:
            build_dir = os.path.join(self.cfg.rime_dir, "build")
            if os.path.exists(build_dir):
                try:
                    shutil.rmtree(build_dir)
                    self.log("🧹 已强制删除 build 目录，触发全量重新编译。")
                except Exception as error:
                    self.log(f"⚠️ 删除 build 目录失败：{error}")

        server_path = str(getattr(self.cfg, "server_path", "") or "")
        deployer_path = str(getattr(self.cfg, "deployer_path", "") or "")

        if SYSTEM_TYPE == "windows":
            server_valid = bool(server_path and os.path.isfile(server_path))
            deployer_valid = bool(deployer_path and os.path.isfile(deployer_path))

            if not server_valid or not deployer_valid:
                self.log("🔎 正在重新检测小狼毫安装目录……")
                try:
                    detected = PathDetector.detect()
                except Exception as error:
                    detected = {}
                    self.log(f"⚠️ 小狼毫路径重新检测失败：{error}")

                detected_server = str(
                    detected.get("weasel_server", "") or ""
                )
                detected_deployer = str(
                    detected.get("weasel_deployer", "") or ""
                )

                if detected_server and os.path.isfile(detected_server):
                    server_path = detected_server
                    self.cfg.server_path = detected_server

                if detected_deployer and os.path.isfile(detected_deployer):
                    deployer_path = detected_deployer
                    self.cfg.deployer_path = detected_deployer

            if deployer_path and os.path.isfile(deployer_path):
                self.log(f"📍 小狼毫部署器：{deployer_path}")

        ok, message = deploy_rime_platform(
            SYSTEM_TYPE,
            log=self.log,
            server_path=server_path,
            deployer_path=deployer_path,
        )
        self.log(("✅ " if ok else "❌ ") + message)
        return ok

    def _is_whitelisted(self, filename, rel_path):
        """检查文件是否在白名单内 (优化路径匹配逻辑，完美解决 custom 目录问题)"""
        rel_path = rel_path.replace("\\", "/")
        if rel_path.startswith("./"): rel_path = rel_path[2:]
        
        for pat in self.whitelist_patterns:
            if pat.search(rel_path):
                return True
            if "/" not in pat.pattern and pat.search(filename):
                return True
        return False

    def _clean_dir_recursive(self, target_root):
        """递归清理目录 (支持文件夹白名单 - 修改版)"""
        if not os.path.exists(target_root): return
        self.log(f"正在清理目录 (保留白名单): {target_root}")
        for root, dirs, files in os.walk(target_root, topdown=True):
            if self._stop: break
            for d in list(dirs):
                abs_dir_path = os.path.join(root, d)
                rel_path = os.path.relpath(abs_dir_path, self.cfg.rime_dir)
                # 如果文件夹匹配白名单
                if self._is_whitelisted(d, rel_path):
                    self.log(f"[保留] 白名单目录: {rel_path} (及其所有内容)")
                    dirs.remove(d) 
            # [文件清理] 处理当前层级未被跳过的文件
            for file in files:
                if self._stop: break
                abs_file_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_file_path, self.cfg.rime_dir)
                
                if self._is_whitelisted(file, rel_path):
                    self.log(f"[保留] 白名单文件: {rel_path}")
                else:
                    try:
                        os.remove(abs_file_path)
                    except Exception as e:
                        self.log(f"[Err] 无法删除 {file}: {e}")

        #第二轮：清理空文件夹
        for root, dirs, files in os.walk(target_root, topdown=False):
            if self._stop: break
            if root == target_root: continue # 根目录不删
            try:
                rel_path = os.path.relpath(root, self.cfg.rime_dir)
                if self._is_whitelisted(os.path.basename(root), rel_path):
                    continue
                os.rmdir(root)
            except OSError:
                pass # 目录非空，跳过
            except Exception as e:
                pass

    def _get_api(self, url, is_cnb):
        """获取 API 数据；GitHub 凭据异常时允许无认证重试一次。"""
        if url in self._api_cache:
            return self._api_cache[url]

        headers = {"Accept": "application/json"} if is_cnb else self.headers_gh_api

        def request(current_headers):
            return requests.get(url, headers=current_headers, timeout=15)

        try:
            response = request(headers)

            if (
                not is_cnb
                and response.status_code in (401, 403)
                and "Authorization" in headers
            ):
                self.log(
                    f"[Warn] GitHub Token 请求返回 {response.status_code}，"
                    "不再降级为匿名 API；后续改用非 API 下载路径。"
                )

            if response.status_code == 200:
                data = response.json()
                self._api_cache[url] = data
                return data

            details = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    details = str(payload.get("message", "") or "").strip()
            except Exception:
                details = response.text.strip()[:200]

            remaining = response.headers.get("X-RateLimit-Remaining", "")
            reset_at = response.headers.get("X-RateLimit-Reset", "")
            rate_info = ""
            if remaining:
                rate_info = f"，剩余额度 {remaining}"
            if reset_at:
                try:
                    reset_text = time.strftime(
                        "%Y-%m-%d %H:%M:%S",
                        time.localtime(int(reset_at)),
                    )
                    rate_info += f"，重置时间 {reset_text}"
                except (TypeError, ValueError, OverflowError):
                    rate_info += f"，重置时间戳 {reset_at}"

            suffix = f"：{details}" if details else ""
            self.log(
                f"[Warn] API 请求失败 ({response.status_code}{rate_info}): "
                f"{url}{suffix}"
            )
            return None
        except Exception as error:
            self.log(f"[Warn] API 连接异常: {error}")
            return None

    def _get_github_latest_scheme(self, repo_gh, reason=""):
        """不依赖 GitHub API 获取方案包；能解析标签时仍可正常比较版本。"""
        real_fn = (
            f"rime-wanxiang-{self.cfg.aux_scheme}-fuzhu.zip"
            if self.cfg.scheme_type == "pro"
            else "rime-wanxiang-base.zip"
        )

        if reason:
            self.log(reason)

        latest_tag = _resolve_github_latest_tag(OWNER, repo_gh)
        if latest_tag:
            self.log(
                f">>> 方案组件: 通过 GitHub Latest 跳转识别版本 [{latest_tag}]"
            )
            return {
                "url": (
                    f"https://github.com/{OWNER}/{repo_gh}/"
                    f"releases/download/{latest_tag}/{real_fn}"
                ),
                "tag": latest_tag,
                "src": "GitHub (Latest Redirect)",
                "hash": "",
                "time": "",
                "name": real_fn,
            }

        self.log(
            ">>> 方案组件: 无法解析 Latest 标签，"
            "直接使用 releases/latest/download 下载。"
        )
        return {
            "url": (
                f"https://github.com/{OWNER}/{repo_gh}/"
                f"releases/latest/download/{real_fn}"
            ),
            "tag": "latest",
            "src": "GitHub (Latest Direct)",
            "hash": "",
            "time": "",
            "name": real_fn,
        }

    def _check_url(self, repo_cnb, repo_gh, pattern, specific_tag=None, task_type=None):
        # ==================== [核心修改：双通道硬编码直链 (同时支持 CNB 与 GitHub)] ====================
        if task_type in ['词库组件', '预览方案']:
            if task_type == '预览方案':
                # 方案包：rime-wanxiang-xxx-fuzhu.zip 或 rime-wanxiang-base.zip
                real_fn = f"rime-wanxiang-{self.cfg.aux_scheme}-fuzhu.zip" if self.cfg.scheme_type == 'pro' else "rime-wanxiang-base.zip"
            else:
                # 词库包：pro-xxx-fuzhu-dicts.zip 或 base-dicts.zip
                real_fn = f"pro-{self.cfg.aux_scheme}-fuzhu-dicts.zip" if self.cfg.scheme_type == 'pro' else "base-dicts.zip"
            
            if self.cfg.use_mirror:
                # CNB 源直链
                release_tag = "v1.0.0"
                direct_url = f"https://cnb.cool/{OWNER}/{repo_cnb}/-/releases/download/{release_tag}/{real_fn}"
                src_name = "CNB (Direct Link)"
            else:
                # GitHub 源直链
                release_tag = DICT_TAG 
                direct_url = f"https://github.com/{OWNER}/{repo_gh}/releases/download/{release_tag}/{real_fn}"
                src_name = "GitHub (Direct Link)"
            
            self.log(f">>> {task_type}: 使用直链下载")
            return {
                "url": direct_url, "tag": release_tag, "src": src_name,
                "hash": "", "time": "", "name": real_fn
            }
        # --- 以下是原有逻辑：方案组件尝试走 CNB API，模型走直链 ---
        cnb_info = None
        if self.cfg.use_mirror:
            cnb_url = f"https://cnb.cool/{OWNER}/{repo_cnb}/-/releases"
            headers = {"User-Agent": "curl/7.68.0", "Accept": "application/json"}
            cnb_data = None
            try:
                if cnb_url in self._api_cache:
                    cnb_data = self._api_cache[cnb_url]
                else:
                    r = requests.get(cnb_url, headers=headers, timeout=5) # 缩短超时
                    if r.status_code == 200:
                        cnb_data = r.json()
                        self._api_cache[cnb_url] = cnb_data
                
                target_releases = cnb_data.get('releases', []) if isinstance(cnb_data, dict) else cnb_data
                if target_releases:
                    for rel in target_releases:
                        raw_tag = rel.get('tag_name') or rel.get('tag_ref', '')
                        current_tag = raw_tag.split('/')[-1]
                        if not specific_tag and current_tag in ['v1.0.0', '1.0.0', 'dict-nightly', 'model']: 
                            continue
                        if specific_tag and specific_tag != current_tag: continue
                        for asset in rel.get('assets') or []:
                            if fnmatch.fnmatch(asset['name'], pattern):
                                url = "https://cnb.cool" + asset.get('path') if asset.get('path') else asset.get('browser_download_url')
                                cnb_info = {
                                    "url": url, "tag": current_tag, "src": "CNB (API)",
                                    "hash": asset.get('sha256') or "", "time": "", "name": asset['name']
                                }
                                break
                        if cnb_info: break
            except: pass

            # 语法模型直链 (model 标签) 保持原有逻辑
            if not cnb_info and pattern == MODEL_FILE:
                return {
                    "url": f"https://cnb.cool/{OWNER}/{repo_cnb}/-/releases/download/model/{pattern}",
                    "tag": "model", "src": "CNB (Direct)", "hash": "", "time": "", "name": pattern
                }

        if cnb_info: return cnb_info

        # 2. === 检查 GitHub ===
        if (
            task_type == "方案组件"
            and not self.cfg.use_mirror
            and not _normalize_github_token(self.cfg.github_token)
        ):
            return self._get_github_latest_scheme(
                repo_gh,
                ">>> 方案组件: 未填写 GitHub Token，跳过 API 检查。",
            )

        self.log(f">>> {task_type} 检查: 通过 API 获取")
        gh_urls = [
            f"https://api.github.com/repos/{OWNER}/{repo_gh}/releases/tags/{specific_tag}" if specific_tag else None,
            f"https://api.github.com/repos/{OWNER}/{repo_gh}/releases"
        ]

        for gh_url in [u for u in gh_urls if u]:
            gh_data = self._get_api(gh_url, False)
            if not gh_data: continue

            # 定义一个内部提取器，方便复用
            def extract_asset_info(asset, tag_name):
                # 【核心修复点】：GitHub 尝试读取多种可能的 Hash 字段
                raw_hash = ""
                if asset.get('sha256'): 
                    raw_hash = asset.get('sha256')
                elif asset.get('digest'):
                    raw_hash = asset.get('digest').split(':')[-1]
                
                return {
                    "url": asset.get('browser_download_url'),
                    "tag": tag_name, "src": "GitHub",
                    "hash": raw_hash, 
                    "time": asset.get('updated_at', ''),
                    "name": asset['name']
                }

            if isinstance(gh_data, dict) and 'assets' in gh_data:
                for asset in gh_data['assets']:
                    if fnmatch.fnmatch(asset['name'], pattern):
                        return extract_asset_info(asset, gh_data.get('tag_name', '0.0.0'))
            
            elif isinstance(gh_data, list):
                for rel in gh_data:
                    current_tag = rel.get('tag_name', '0.0.0')
                    if not specific_tag and (current_tag in ['v1.0.0', '1.0.0', 'dict-nightly', 'apk'] or 'model' in current_tag.lower()):
                        continue
                    for asset in rel.get('assets', []):
                        if fnmatch.fnmatch(asset['name'], pattern):
                            return extract_asset_info(asset, rel.get('tag_name', '0.0.0'))

        if task_type == "方案组件" and not self.cfg.use_mirror:
            return self._get_github_latest_scheme(
                repo_gh,
                "🛟 方案组件：GitHub Token/API 不可用，"
                "改用 GitHub Latest 非 API 路径。",
            )

        return None
    def _download(self, url, dest, allow_slow_cnb_fallback=True):
        """按用户选择依次尝试下载路线，并校验下载内容。"""
        max_retries = 2
        timeout_sec = 60
        proxy_grace_sec = 5.0
        proxy_speed_window_sec = 4.0
        proxy_no_data_timeout_sec = 10

        original_url = url
        clean_url = original_url.split("?", 1)[0].lower()
        expected_zip = clean_url.endswith(".zip") or str(dest).lower().endswith(".zip")

        if original_url.startswith("https://github.com/"):
            selected_prefix = self.cfg.github_proxy
            proxy_prefixes = [route["prefix"] for route in GITHUB_ROUTES.values() if route["prefix"]]

            if selected_prefix:
                # 用户选中代理：当前代理优先，再尝试其他代理，不尝试 GitHub 官方。
                route_prefixes = [selected_prefix]
                route_prefixes.extend(prefix for prefix in proxy_prefixes if prefix != selected_prefix)
            else:
                # 用户选中 GitHub 官方：先尝试官方，再尝试全部代理。
                route_prefixes = [""]
                route_prefixes.extend(proxy_prefixes)

            route_prefixes = list(dict.fromkeys(route_prefixes))
            sources = [(f"{prefix}{original_url}" if prefix else original_url, bool(prefix)) for prefix in route_prefixes]
        else:
            sources = [(original_url, False)]

        force_cnb_fallback = False

        for source_index, (download_url, using_github_proxy) in enumerate(sources, 1):
            source_name = download_url.split("/", 3)[2] if "://" in download_url else download_url
            monitor_proxy_speed = (
                using_github_proxy
                and allow_slow_cnb_fallback
                and self.cfg.proxy_slow_fallback
                and self.cfg.proxy_min_speed_kbps > 0
            )
            read_timeout = proxy_no_data_timeout_sec if monitor_proxy_speed else timeout_sec
            self.log(f"🌐 尝试下载路线 {source_index}/{len(sources)}：{source_name}")

            for attempt in range(1, max_retries + 1):
                bad_payload = False
                response_started = False

                try:
                    if attempt > 1:
                        self.log(f"🔄 当前路线第 {attempt}/{max_retries} 次重试。")

                    headers = _download_headers_for_url(
                        download_url,
                        using_github_proxy=using_github_proxy,
                        headers_cnb=self.headers_cnb,
                        headers_github_download=self.headers_gh_download,
                        headers_github_proxy=self.headers_gh_proxy,
                        headers_external=self.headers_external,
                    )

                    with requests.get(
                        download_url,
                        headers=headers,
                        stream=True,
                        allow_redirects=True,
                        timeout=(10, read_timeout),
                    ) as response:
                        response.raise_for_status()
                        response_started = True

                        content_type = response.headers.get("content-type", "").lower()
                        final_url = response.url

                        if "text/html" in content_type:
                            bad_payload = True
                            raise RuntimeError("代理返回了网页，不是下载文件")

                        total_size = int(response.headers.get("content-length", 0) or 0)
                        downloaded_size = 0
                        download_started = time.monotonic()
                        monitor_started = None
                        monitor_bytes = 0
                        last_progress_emit = 0.0

                        with open(dest, "wb") as file:
                            for chunk in response.iter_content(chunk_size=65536):
                                if self._stop:
                                    if os.path.exists(dest):
                                        try: os.remove(dest)
                                        except OSError: pass
                                    return False

                                if not chunk: continue

                                file.write(chunk)
                                chunk_size = len(chunk)
                                downloaded_size += chunk_size
                                now = time.monotonic()
                                elapsed = max(now - download_started, 0.001)
                                average_speed_kbps = downloaded_size / elapsed / 1024.0

                                if now - last_progress_emit >= 0.2:
                                    self.progress_sig.emit(f"下载中 {average_speed_kbps:.0f} KB/s", downloaded_size, total_size)
                                    last_progress_emit = now

                                if monitor_proxy_speed and elapsed >= proxy_grace_sec:
                                    if monitor_started is None:
                                        monitor_started = now
                                        monitor_bytes = chunk_size
                                    else:
                                        monitor_bytes += chunk_size
                                        window_elapsed = now - monitor_started

                                        if window_elapsed >= proxy_speed_window_sec:
                                            window_speed_kbps = monitor_bytes / window_elapsed / 1024.0

                                            if window_speed_kbps < self.cfg.proxy_min_speed_kbps:
                                                raise ProxySpeedTooSlow(
                                                    f"{source_name}连续{window_elapsed:.1f}秒仅"
                                                    f"{window_speed_kbps:.0f} KB/s，低于"
                                                    f"{self.cfg.proxy_min_speed_kbps} KB/s"
                                                )

                                            monitor_started = now
                                            monitor_bytes = 0

                    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
                        raise RuntimeError("下载文件为空")

                    local_size = os.path.getsize(dest)

                    if total_size > 0 and local_size != total_size:
                        raise RuntimeError(f"文件不完整：预期 {total_size} 字节，实际 {local_size} 字节")

                    if expected_zip and not zipfile.is_zipfile(dest):
                        bad_payload = True

                        try:
                            with open(dest, "rb") as file:
                                preview = file.read(160).decode("utf-8", errors="replace")
                            preview = " ".join(preview.split())
                        except Exception:
                            preview = ""

                        detail = f"，内容开头：{preview[:80]!r}" if preview else ""
                        raise RuntimeError(
                            f"返回内容不是 ZIP：{local_size} B，类型={content_type or '未知'}，最终地址={final_url}{detail}"
                        )

                    self.progress_sig.emit("下载完成", local_size, local_size)
                    self.log(f"✅ 下载路线可用：{source_name}，文件大小 {local_size} B")
                    return True

                except ProxySpeedTooSlow as error:
                    self.log(f"🐢 {error}，立即停止代理并切换CNB。")

                    if os.path.exists(dest):
                        try: os.remove(dest)
                        except OSError: pass

                    force_cnb_fallback = True
                    break

                except Exception as error:
                    error_text = str(error)
                    is_stream_timeout = monitor_proxy_speed and response_started and "timed out" in error_text.lower()

                    if is_stream_timeout:
                        self.log(f"🐢 {source_name}连续约{proxy_no_data_timeout_sec}秒无数据，立即停止代理并切换CNB。")
                        force_cnb_fallback = True
                    else:
                        self.log(f"⚠️ {source_name} 下载无效：{error}")

                    if os.path.exists(dest):
                        try: os.remove(dest)
                        except OSError: pass

                    if self._stop: return False
                    if force_cnb_fallback: break

                    # 返回网页或假文件通常重试也不会恢复，直接换下一条路线。
                    if bad_payload:
                        self.log(f"↪ {source_name} 返回内容错误，直接切换下一条路线。")
                        break

                    if attempt < max_retries:
                        time.sleep(1)

            if force_cnb_fallback:
                self.log("🛟 已放弃低速GitHub代理，准备使用CNB兜底。")
                break

            self.log(f"↪ 当前路线不可用：{source_name}")

        if force_cnb_fallback:
            return False

        self.log("⚠️ 当前下载路线均不可用。")
        return False

    def _detect_smart_root(self, extract_root: str, task_type: str) -> str:
        """智能解压根目录检测"""
        if task_type in ['dict', '词库组件']:
            for root, dirs, files in os.walk(extract_root):
                for f in files:
                    if f.endswith('.dict.yaml'):
                        return root
            return extract_root
        if task_type in ['CustomZip', 'scheme', '方案组件', '预览方案']: 
            for root, dirs, files in os.walk(extract_root):
                if 'lua' in dirs: return root
            for root, dirs, files in os.walk(extract_root):
                if 'default.yaml' in files or 'rime.lua' in files: return root
        return extract_root

    def _safe_merge_dir(self, src_root, dst_root):
        """安全合并目录 (保持原样)"""
        if not os.path.exists(src_root): return
        total_files = sum([len(files) for r, d, files in os.walk(src_root)])
        processed = 0
        for root, dirs, files in os.walk(src_root):
            if self._stop: break
            rel_path = os.path.relpath(root, src_root)
            target_dir = os.path.join(dst_root, rel_path)
            if not os.path.exists(target_dir): os.makedirs(target_dir, exist_ok=True)
            for file in files:
                if self._stop: break
                processed += 1
                self.progress_sig.emit("合并文件", processed, total_files)
                src_file = os.path.join(root, file)
                dst_file = os.path.join(target_dir, file)
                abs_dst_file = os.path.abspath(dst_file)
                rime_rel_path = os.path.relpath(abs_dst_file, self.cfg.rime_dir)
                if os.path.exists(dst_file):
                    if self._is_whitelisted(file, rime_rel_path):
                        self.log(f"[跳过] 白名单保护: {rime_rel_path}")
                        continue
                try:
                    shutil.copy2(src_file, dst_file)
                except Exception as e:
                    self.log(f"[Err] 写入失败 {file}: {e}")

    def run(self):
        pending_tasks = [] # 用于暂存已下载好的任务
        needs_deploy = False 

        with tempfile.TemporaryDirectory() as temp_root:
            try:
                if not os.path.isdir(self.cfg.rime_dir):
                    self.done_sig.emit(False, "❌ 错误: Rime用户目录无效"); return
                
                mode_dict = {0: '全量', 1: '仅方案', 2: '仅词库', 3: '仅模型', 4: '预览方案'}
                self.log(f">>> 开始更新任务: {mode_dict.get(self.cfg.scope, '未知')}")
                self.log(f">>> 目标目录: {self.cfg.rime_dir}")
                
                # --- 1. 任务分发---
                extract_temp = os.path.join(temp_root, "extract")
                tasks = [] 
                
                if self.cfg.custom_url:
                     tasks.append(('CustomZip', None, None, 'custom_mode', self.cfg.rime_dir, None))
                else:
                    scheme_key = self.cfg.aux_scheme if self.cfg.scheme_type == 'pro' else 'base'
                    # 方案组件
                    if self.cfg.scope in [0, 1]: 
                        pat = f"*{scheme_key}*fuzhu.zip" if self.cfg.scheme_type == 'pro' else "*base.zip"
                        tasks.append(('方案组件', REPO, CNB_REPO, pat, self.cfg.rime_dir, None))
                    if self.cfg.scope == 4:
                        pat = f"*{scheme_key}*fuzhu.zip" if self.cfg.scheme_type == 'pro' else "*base.zip"
                        # 核心：CNB 去 v1.0.0 找，GitHub 去 dict-nightly 找
                        preview_tag = "v1.0.0" if self.cfg.use_mirror else DICT_TAG
                        tasks.append(('预览方案', REPO, CNB_REPO, pat, self.cfg.rime_dir, preview_tag))
                    # 词库组件
                    if self.cfg.scope in [0, 2]:
                        pat = f"*{scheme_key}*dicts.zip" if self.cfg.scheme_type == 'pro' else "*base*dicts.zip"
                        tasks.append(('词库组件', REPO, CNB_REPO, pat, self.cfg.rime_dir, DICT_TAG))
                    # 语法模型
                    if self.cfg.scope in [0, 3]:
                        tasks.append(('语法模型', MODEL_REPO, CNB_REPO, MODEL_FILE, self.cfg.rime_dir, MODEL_TAG))

                # --- 2. 纯下载循环 (进程活跃中) ---
                for task_type, gh_repo, cnb_repo, pattern, final_dest, specific_tag in tasks:
                    if self._stop:
                        self._finish_cancelled()
                        return

                    if task_type == 'CustomZip':
                        remote_data = {"url": self.cfg.custom_url, "tag": "custom", "src": "Custom URL", "hash": "", "time": "", "name": "custom.zip"}
                    else:
                        # 传入 task_type 参数
                        remote_data = self._check_url(cnb_repo, gh_repo, pattern, specific_tag, task_type)
                    
                    if not remote_data and task_type != 'CustomZip':
                        self.log(f"🛟 {task_type}：GitHub资源信息获取失败，正在尝试CNB。")

                        old_use_mirror = self.cfg.use_mirror
                        self.cfg.use_mirror = True

                        try:
                            cnb_data = self._check_url(cnb_repo, gh_repo, pattern, specific_tag, task_type)
                        finally:
                            self.cfg.use_mirror = old_use_mirror

                        if cnb_data and cnb_data.get('url') and str(cnb_data.get('src', '')).startswith('CNB'):
                            remote_data = cnb_data
                            self.log(f"✓ {task_type}：已获取CNB兜底资源。")

                    if not remote_data:
                        self.done_sig.emit(False, f"❌ {task_type}：GitHub和CNB均未找到可用资源。")
                        return

                    url, tag, remote_hash = remote_data['url'], remote_data['tag'], remote_data.get('hash')
                    should_skip = False
                    if task_type == '预览方案':
                        self.log(f">>> {task_type}: 预览模式，跳过比对直接下载")
                        should_skip = False  # 永远不跳过
                        
                    elif task_type == '方案组件':
                        if tag.lower().startswith('v'): tag = tag[1:]
                        local_ver = self.cfg.current_versions.get('方案组件', "0.0.0")
                        if local_ver == "0.0.0": local_ver = "未记录"
                        
                        self.log(f">>> {task_type}: 本地[{local_ver}] 在线[{tag}]")
                        
                        if not self.cfg.force_update and tag == local_ver:
                            should_skip = True

                    elif task_type == 'CustomZip':
                        self.log(f">>> {task_type}: 自定义压缩包直连")
                        
                    else:
                        key_map = {'词库组件': 'dict_hash', '语法模型': 'model_hash'}
                        key = key_map.get(task_type, "")
                        local_ver_id = self.cfg.current_versions.get(key, "")
                        remote_ver_id = remote_data.get('time', '')
                        if remote_ver_id:
                            remote_ver_id = remote_ver_id[:16].replace('T', '_')
                        if not remote_ver_id:
                            remote_ver_id = remote_hash
                        
                        d_l = local_ver_id if local_ver_id else "无"
                        d_r = remote_ver_id if remote_ver_id else "无(无法校验)"
                        
                        self.log(f">>> {task_type}: 本地[{d_l}] 在线[{d_r}]")
                        
                        if not self.cfg.force_update:
                            if remote_ver_id and local_ver_id == remote_ver_id:
                                self.log(f"✓ 版本一致: 文件未改变，跳过")
                                should_skip = True

                    if should_skip: continue

                    self.log(f"✓ {task_type} 下载中...")
                    fname = os.path.basename(url.split('?')[0]) or f"update_{task_type}.tmp"
                    local_download_path = os.path.join(temp_root, fname)

                    # 先走用户选择的 GitHub 官方或代理路线。
                    download_ok = self._download(
                        url,
                        local_download_path,
                        allow_slow_cnb_fallback=(task_type != 'CustomZip'),
                    )

                    # 主动停止不能被当成下载失败，也不能继续回退 CNB。
                    if self._stop:
                        self._finish_cancelled()
                        return

                    # GitHub及代理全部失败后，才启用原有CNB逻辑兜底。
                    if not download_ok and task_type != 'CustomZip':
                        self.log(f"🛟 {task_type}：GitHub下载路线全部失败，正在回退CNB。")

                        old_use_mirror = self.cfg.use_mirror
                        self.cfg.use_mirror = True

                        try:
                            cnb_data = self._check_url(cnb_repo, gh_repo, pattern, specific_tag, task_type)
                        finally:
                            self.cfg.use_mirror = old_use_mirror

                        if self._stop:
                            self._finish_cancelled()
                            return

                        if cnb_data and cnb_data.get('url') and str(cnb_data.get('src', '')).startswith('CNB'):
                            cnb_url = cnb_data['url']
                            self.log(f"🌐 {task_type}：尝试CNB兜底地址。")
                            download_ok = self._download(cnb_url, local_download_path, allow_slow_cnb_fallback=False)

                            if self._stop:
                                self._finish_cancelled()
                                return

                            if download_ok:
                                remote_data = cnb_data
                                tag = str(cnb_data.get('tag', tag))

                                if task_type == '方案组件' and tag.lower().startswith('v'):
                                    tag = tag[1:]

                                remote_hash = cnb_data.get('hash', '')
                        else:
                            self.log(f"❌ {task_type}：未找到可用的CNB兜底资源。")

                    if self._stop:
                        self._finish_cancelled()
                        return

                    if not download_ok:
                        self.done_sig.emit(False, f"❌ {task_type}：GitHub路线和CNB均下载失败。")
                        return

                    if task_type == '语法模型' and remote_hash:
                        if self._calculate_sha256(local_download_path) != remote_hash:
                            self.done_sig.emit(False, "❌ 语法模型文件校验失败。")
                            return

                    # 只添加到列表，全部资源下载成功后再统一安装。
                    pending_tasks.append({
                        'type': task_type,
                        'path': local_download_path,
                        'dest': final_dest,
                        'ver': tag,
                        'hash': remote_hash,
                        'time': remote_data.get('time', '')
                    })

                    self.log(f"✓ {task_type} 下载完毕，进入安装队列。")

                # --- 3. 统一杀进程 ---
                if not pending_tasks and not self.cfg.clean_before:
                    self.log("✓ 版本一致，无需更新。")
                    self.done_sig.emit(True, "✓ 所有组件已是最新。"); return
                time.sleep(2)
                if self._stop:
                    self._finish_cancelled()
                    return

                self.log(">>> 开始安装任务")
                self._kill_rime_process() # 此时才杀进程

                if self.cfg.clean_before:
                    self.log("✓ 执行清理模式")
                    target = os.path.join(self.cfg.rime_dir, "dicts") if self.cfg.scope == 2 else self.cfg.rime_dir
                    self._clean_dir_recursive(target)

                # --- 4. 统一安装循环 ---
                for task in pending_tasks:
                    if self._stop:
                        self._finish_cancelled()
                        return
                    
                    t_type = task['type']
                    src_path = task['path']
                    dst_dir = task['dest']

                    try:
                        if t_type == '语法模型':
                            os.makedirs(dst_dir, exist_ok=True)
                            target_file = os.path.join(dst_dir, MODEL_FILE)
                            if os.path.exists(target_file): os.remove(target_file)
                            shutil.copy2(src_path, target_file)
                        else:
                            if os.path.exists(extract_temp): shutil.rmtree(extract_temp)
                            os.makedirs(extract_temp, exist_ok=True)
                            with zipfile.ZipFile(src_path, 'r') as zf: zf.extractall(extract_temp)
                            
                            real_source_dir = extract_temp
                            if t_type == '词库组件':
                                found_root = None
                                for r, d, f in os.walk(extract_temp):
                                    if any(filename.endswith('.dict.yaml') for filename in f):
                                        found_root = r; break
                                if found_root:
                                    # 【核心修复】如果结构是扁平的，严禁 parent_dir 逃逸到存放 zip 的外层目录
                                    if found_root == extract_temp:
                                        safe_wrap = os.path.join(temp_root, "safe_wrap")
                                        os.makedirs(safe_wrap, exist_ok=True)
                                        new_path = os.path.join(safe_wrap, 'dicts')
                                        os.rename(extract_temp, new_path)
                                        real_source_dir = safe_wrap
                                    else:
                                        parent_dir = os.path.dirname(found_root)
                                        if os.path.basename(found_root) != 'dicts':
                                            new_path = os.path.join(parent_dir, 'dicts')
                                            if os.path.exists(new_path): shutil.rmtree(new_path)
                                            os.rename(found_root, new_path)
                                        real_source_dir = parent_dir
                            else:
                                real_source_dir = self._detect_smart_root(extract_temp, t_type)

                            if t_type == '方案组件':
                                version_path = os.path.join(real_source_dir, "version.txt")
                                if os.path.isfile(version_path):
                                    try:
                                        package_version = Path(version_path).read_text(
                                            encoding="utf-8"
                                        ).strip()
                                        if package_version.lower().startswith("v"):
                                            package_version = package_version[1:]
                                        if package_version:
                                            task['ver'] = package_version
                                    except Exception as error:
                                        self.log(f"[Warn] 读取方案包版本失败：{error}")

                            self._safe_merge_dir(real_source_dir, dst_dir)

                        if not self.cfg.custom_url:
                            if t_type == '方案组件':
                                if task['ver'] != "latest":
                                    self.version_sig.emit("方案组件", task['ver'])
                                else:
                                    self.log(
                                        "[Warn] 方案包未提供可识别的 version.txt，"
                                        "不覆盖本地版本记录。"
                                    )
                            
                            # 【核心修改】：词库和模型：强行摒弃 Hash，强制使用时间作为版本标识！
                            elif t_type in ['词库组件', '语法模型']:
                                time_str = str(task.get('time', ''))
                                
                                # 如果走直链没有抓到时间，主动通过 API 抓取
                                if not time_str:
                                    try:
                                        api_url = ""
                                        if t_type == '词库组件':
                                            api_url = "https://api.github.com/repos/amzxyz/rime-wanxiang/releases/tags/dict-nightly"
                                        elif t_type == '语法模型':
                                            api_url = "https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/LTS"
                                        
                                        if api_url:
                                            api_data = self._get_api(api_url, False)
                                            if isinstance(api_data, dict):
                                                for a in api_data.get('assets', []):
                                                    if (t_type == '词库组件' and 'dicts.zip' in a['name']) or \
                                                       (t_type == '语法模型' and 'wanxiang-lts-zh-hans.gram' in a['name']):
                                                        time_str = a.get('updated_at', '')
                                                        break
                                    except Exception:
                                        pass
                                
                                # 如果成功获取到时间，就用时间；否则才退化使用 Hash
                                remote_ver_id = time_str[:16].replace('T', '_') if time_str else task.get('hash', '')
                                
                                # 发送信号保存
                                if remote_ver_id:
                                    if t_type == '词库组件': self.version_sig.emit("dict_hash", remote_ver_id)
                                    elif t_type == '语法模型': self.version_sig.emit("model_hash", remote_ver_id)
                        
                        needs_deploy = True
                        self.log(f"✓ {t_type} 安装完成")

                    except Exception as e:
                        self.log(f"❌ {t_type} 安装失败：{e}")
                        self.done_sig.emit(False, f"❌ {t_type} 安装失败：{e}")
                        return
                # --- 5. 部署 ---
                if needs_deploy or self.cfg.clean_build:
                    self.log(">>> 正在触发部署")
                    deploy_ok = self._start_and_deploy()
                    if deploy_ok:
                        self.done_sig.emit(True, "✓ 更新并部署完成。")
                    else:
                        self.done_sig.emit(
                            False,
                            "⚠️ 更新文件已安装，但自动部署未完成。"
                        )
                else:
                    self.done_sig.emit(True, "更新流程结束。")

            except Exception as e:
                import traceback
                self.log(f"❌ 严重错误: {e}")
                self.done_sig.emit(False, f"更新异常: {e}")
# ============== 检查更新机制 ==============
class CheckUpdateWorker(QThread):
    result_sig = Signal(dict)

    def __init__(self, github_token=""):
        super().__init__()
        self.headers = _build_github_api_headers(github_token)

    def run(self):
        results = {}
        headers = self.headers
        
        # 1. 检查软件自身版本
        try:
            r = requests.get("https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/tool", headers=headers, timeout=8)
            if r.status_code == 200:
                full_name = r.json().get('name', '未知')
                # 解析诸如 "万象词库-刷拼音-辅助码工具 - v2.8.0" 中的版本号
                if " - " in full_name:
                    results['tool'] = full_name.split(" - ")[-1].strip()
                else:
                    results['tool'] = full_name
            else:
                results['tool'] = '获取失败'
        except:
            results['tool'] = '网络错误'
            
        # 2. 检查方案组件版本 (修复 Latest 被自动构建 Tag 顶替的 Bug)
        try:
            r = requests.get("https://api.github.com/repos/amzxyz/rime-wanxiang/releases", headers=headers, timeout=8)
            if r.status_code == 200:
                releases = r.json()
                schema_tag = '未知'
                for rel in releases:
                    t_name = rel.get('tag_name', '')
                    # 过滤掉词库和模型这类自动化 Tag，寻找真正的版本号 (如 v14.7.3)
                    if t_name and t_name not in [DICT_TAG, 'v1.0.0', '1.0.0', 'apk'] and 'model' not in t_name.lower():
                        schema_tag = t_name
                        break
                results['schema'] = schema_tag
            else:
                results['schema'] = '获取失败'
        except:
            results['schema'] = '网络错误'
        # 3. 检查词库与模型 (纯 GitHub 模式)
        try:
            r = requests.get(f"https://api.github.com/repos/amzxyz/rime-wanxiang/releases/tags/{DICT_TAG}", headers=headers, timeout=8)
            if r.status_code == 200:
                # 【千万别漏了这一行】先把网络请求的结果解析成 assets 列表！
                assets = r.json().get('assets', []) 
                
                asset = next((a for a in assets if 'dicts.zip' in a['name']), None)
                if asset:
                    # 提取 GitHub 的更新时间，例如 "2024-05-22T10:00:00Z"，截取年月日时分作为版本号
                    updated_time = asset.get('updated_at', '')[:16].replace('T', '_')
                    results['dict'] = updated_time if updated_time else DICT_TAG
                else:
                    results['dict'] = DICT_TAG
            else: 
                results['dict'] = DICT_TAG
        except: 
            results['dict'] = '网络错误'

        try:
            r = requests.get(f"https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/{MODEL_TAG}", headers=headers, timeout=8)
            if r.status_code == 200:
                assets = r.json().get('assets', [])
                asset = next((a for a in assets if a['name'] == MODEL_FILE), None)
                if asset:
                    updated_time = asset.get('updated_at', '')[:16].replace('T', '_')
                    results['model'] = updated_time if updated_time else 'model'
                else: 
                    results['model'] = 'model'
            else: 
                results['model'] = 'model'
        except: 
            results['model'] = '网络错误'
        
        self.result_sig.emit(results)

class UpdateCheckDialog(QDialog):
    def __init__(self, parent, local_vers, remote_vers):
        super().__init__(parent)
        self.setWindowTitle("检查更新")
        self.setMinimumWidth(500)
        self.parent_win = parent
        
        lay = QVBoxLayout(self)
        lay.setSpacing(15)
        
        # 标题区域
        lbl_title = QLabel("<b>万象拼音组件与工具箱版本状态</b>")
        lbl_title.setAlignment(Qt.AlignCenter)
        lbl_title.setStyleSheet("font-size: 16px; margin-bottom: 5px;")
        lay.addWidget(lbl_title)
        
        # 表格布局
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(15)
        
        headers = ["组件名称", "当前版本", "最新版本", "操作"]
        for col, text in enumerate(headers):
            lbl = QLabel(f"<b>{text}</b>")
            lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(lbl, 0, col)
            
        # 数据映射 (scope_id: -1=工具本身, 0=全量, 1=方案, 2=词库, 3=模型)
        items = [
            ("工具箱本身", local_vers['tool'], remote_vers.get('tool', '未知'), -1),
            ("全量更新", local_vers['schema'], remote_vers.get('schema', '未知'), 0),
            ("方案组件", local_vers['schema'], remote_vers.get('schema', '未知'), 1),
            ("词库组件", local_vers['dict'], remote_vers.get('dict', DICT_TAG), 2),
            ("语法模型", local_vers['model'], remote_vers.get('model', 'model'), 3),
        ]
        
        for i, (name, loc, rem, scope_id) in enumerate(items, 1):
            # 判别是否有新版本（对于未记录的，也视为有更新）
            has_update = (loc != rem and rem not in ['获取失败', '网络错误', '未知', 'CNB无在线校验'])
            
            lbl_name = QLabel(name)
            lbl_loc = QLabel(loc)
            lbl_loc.setAlignment(Qt.AlignCenter)
            
            lbl_rem = QLabel(rem)
            lbl_rem.setAlignment(Qt.AlignCenter)
            if has_update:
                lbl_rem.setStyleSheet("color: #d9534f; font-weight: bold;") # 红色高亮新版本
            else:
                lbl_rem.setStyleSheet("color: #5cb85c;") # 绿色代表已最新
                
            btn = QPushButton("下载更新" if has_update else "重新下载")
            btn.setCursor(Qt.PointingHandCursor)
            if has_update:
                # 绿色显眼按钮
                btn.setStyleSheet("background-color: #5cb85c; color: white; border: none; border-radius: 4px; padding: 6px 12px; font-weight: bold;")
            else:
                # 默认次级按钮
                btn.setStyleSheet("padding: 6px 12px;")
                
            btn.clicked.connect(lambda checked, s=scope_id, u=has_update: self.do_action(s, u))
            
            grid.addWidget(lbl_name, i, 0)
            grid.addWidget(lbl_loc, i, 1)
            grid.addWidget(lbl_rem, i, 2)
            grid.addWidget(btn, i, 3)
            
        lay.addLayout(grid)
        
        # 底部关闭按钮
        btn_close = QPushButton("关闭")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        lay.addWidget(btn_close, alignment=Qt.AlignCenter)
        
    def do_action(self, scope_id, is_update):
        if scope_id == -1:
            webbrowser.open("https://github.com/amzxyz/RIME-LMDG/releases/tag/tool")
        else:
            # 触发主界面的更新逻辑，如果没有更新(重新下载)，则传递 force=True
            self.parent_win.trigger_update_from_dialog(scope_id, not is_update)
            self.accept()
# ============== 可拖拽路径输入 ==============
class PathEdit(QLineEdit):
    def __init__(self, placeholder: str = ""):
        super().__init__()
        self.setAcceptDrops(True)
        if placeholder: self.setPlaceholderText(placeholder)
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
        else: super().dragEnterEvent(e)
    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            urls = e.mimeData().urls()
            if urls:
                local = urls[0].toLocalFile()
                if local: self.setText(local)
            e.acceptProposedAction()
        else: super().dropEvent(e)
# 用户词整理 (Userdb Sort)
class UserDbWorker(QThread):
    log_sig = Signal(str)
    done_sig = Signal(bool, str)

    def __init__(self, rime_dir, min_len, max_len, use_dedup, out_path):
        super().__init__()
        self.rime_dir = rime_dir
        self.min_len = min_len
        self.max_len = max_len
        self.use_dedup = use_dedup
        self.out_path = out_path

    def run(self):
        try:
            self.log_sig.emit(">>> 开始解析 installation.yaml 查找 sync 目录...")
            sync_dir = ""
            install_yaml = os.path.join(self.rime_dir, "installation.yaml")
            if os.path.exists(install_yaml):
                try:
                    with open(install_yaml, 'r', encoding='utf-8') as f:
                        for line in f:
                            if "sync_dir:" in line:
                                val = line.split(":", 1)[1].strip()
                                val = val.strip("'\"")  # 去除首尾引号
                                val = val.replace('\\\\', '\\')  # 处理双斜杠
                                sync_dir = os.path.normpath(val) # 规范化斜杠
                                break
                except Exception as e:
                    self.log_sig.emit(f"[Warn] 读取 installation.yaml 出错: {e}")
            
            if not sync_dir:
                sync_dir = os.path.join(self.rime_dir, "sync")
                self.log_sig.emit("未找到自定义 sync_dir，使用默认路径。")

            self.log_sig.emit(f"📂 正在扫描目录: {sync_dir}")
            if not os.path.exists(sync_dir):
                self.done_sig.emit(False, f"同步目录不存在: {sync_dir}")
                return

            # 1. 提取新增词
            new_words = set()
            file_count = 0
            for root, _, files in os.walk(sync_dir):
                for file in files:
                    if file.endswith('.userdb.txt'):
                        file_count += 1
                        try:
                            with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                                for line in f:
                                    if line.startswith('#'): continue
                                    parts = line.split('\t')
                                    if len(parts) >= 2:
                                        word = parts[1].strip()
                                        if re.search(r'[a-zA-Z]', word):
                                            continue
                                        if self.min_len <= len(word) <= self.max_len:
                                            new_words.add(word)
                        except Exception as e:
                            self.log_sig.emit(f"[Warn] 读取文件失败 {file}: {e}")
            
            self.log_sig.emit(f"✅ 扫描了 {file_count} 个 userdb 文件，初步提取了 {len(new_words)} 个符合长度的词组。")

            # 2. 词库去重
            if self.use_dedup:
                dicts_dir = os.path.join(self.rime_dir, "dicts")
                self.log_sig.emit(f"🔎 正在扫描固定词库进行去重: {dicts_dir}")
                dict_words = set()
                dict_count = 0
                if os.path.exists(dicts_dir):
                    for root, _, files in os.walk(dicts_dir):
                        for file in files:
                            if file.endswith('.dict.yaml'):
                                dict_count += 1
                                try:
                                    with open(os.path.join(root, file), 'r', encoding='utf-8') as f:
                                        for line in f:
                                            if line.startswith('#') or line.startswith(YAML_HEADS): continue
                                            parts = line.split('\t')
                                            if parts and parts[0].strip():
                                                dict_words.add(parts[0].strip())
                                except Exception as e:
                                    pass
                
                original_len = len(new_words)
                new_words = new_words - dict_words
                self.log_sig.emit(f"✅ 扫描了 {dict_count} 个词库文件。去重后剩余: {len(new_words)} 个（过滤了 {original_len - len(new_words)} 个已有词）。")

            # 3. 写入输出文件
            if not new_words:
                self.done_sig.emit(True, "没有找到符合条件的新增词。")
                return

            with open(self.out_path, 'w', encoding='utf-8') as f:
                for w in sorted(new_words, key=lambda x: (len(x), x)):
                    f.write(w + '\n')

            self.done_sig.emit(True, f"🎉 整理完成！共保存 {len(new_words)} 个词到：\n{self.out_path}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.done_sig.emit(False, f"发生异常: {e}")

class UserDbSortDialog(QDialog):
    def __init__(self, parent=None, rime_dir=""):
        super().__init__(parent)
        self.setWindowTitle("用户新增词整理")
        self.setMinimumWidth(500)
        self.rime_dir = rime_dir
        self.settings = QSettings("amzxyz", "WanXiangSettings")

        lay = QVBoxLayout(self)
        
        # 长度设置
        h_len = QHBoxLayout()
        self.spin_min = QSpinBox()
        self.spin_min.setRange(1, 20)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 50)
        
        # 读取设置记忆
        self.spin_min.setValue(int(self.settings.value("userdb/min_len", 3)))
        self.spin_max.setValue(int(self.settings.value("userdb/max_len", 6)))

        h_len.addWidget(QLabel("字数长度限制：最小"))
        h_len.addWidget(self.spin_min)
        h_len.addWidget(QLabel("最大"))
        h_len.addWidget(self.spin_max)
        h_len.addStretch()
        lay.addLayout(h_len)

        # 去重选项
        self.chk_dedup = QCheckBox("使用固定词库去重 (自动扫描 Rime/dicts 目录)")
        self.chk_dedup.setChecked(self.settings.value("userdb/dedup", True, type=bool))
        lay.addWidget(self.chk_dedup)

        # 输出路径
        h_out = QHBoxLayout()
        self.out_edit = PathEdit("拖拽或选择：输出的 txt 文件路径")
        self.out_edit.setText(self.settings.value("userdb/out_path", ""))
        btn_out = QPushButton("选择...")
        btn_out.clicked.connect(self.pick_output)
        h_out.addWidget(self.out_edit)
        h_out.addWidget(btn_out)
        lay.addLayout(h_out)

        # 按钮与日志
        self.btn_run = QPushButton("开始整理")
        self.btn_run.setStyleSheet("background-color: #61A165; color: white; padding: 6px; font-weight: bold; border-radius: 4px;")
        self.btn_run.clicked.connect(self.run_sort)
        lay.addWidget(self.btn_run)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        lay.addWidget(self.log_view)

    def pick_output(self):
        dlg = QFileDialog(self, "选择输出文件")
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.selectFile("万象新增词提取.txt")
        dlg.setNameFilter("Text Files (*.txt);;All Files (*)")
        if dlg.exec():
            files = dlg.selectedFiles()
            if files: self.out_edit.setText(files[0])

    def run_sort(self):
        out_path = self.out_edit.text().strip()
        if not out_path:
            QMessageBox.warning(self, "错误", "请选择输出路径！")
            return
        if not self.rime_dir or not os.path.exists(self.rime_dir):
            QMessageBox.warning(self, "错误", "主界面的 Rime 目录无效，请先返回配置！")
            return

        # 记忆当前配置
        self.settings.setValue("userdb/min_len", self.spin_min.value())
        self.settings.setValue("userdb/max_len", self.spin_max.value())
        self.settings.setValue("userdb/dedup", self.chk_dedup.isChecked())
        self.settings.setValue("userdb/out_path", out_path)

        self.btn_run.setEnabled(False)
        self.log_view.clear()
        
        self.worker = UserDbWorker(self.rime_dir, self.spin_min.value(), self.spin_max.value(), self.chk_dedup.isChecked(), out_path)
        self.worker.log_sig.connect(self.log_view.appendPlainText)
        self.worker.done_sig.connect(self.on_done)
        self.worker.start()

    def on_done(self, ok, msg):
        self.btn_run.setEnabled(True)
        self.log_view.appendPlainText("-" * 30)
        self.log_view.appendPlainText(msg)
        if ok: QMessageBox.information(self, "完成", msg)
# 智能异步缓存预读线程
# 专为 schema_list 定制的特制复选框工厂
# ============== GUI ==============
class MainWin(AdvancedSettingsMixin, QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Rime万象拼音工具箱 {TOOL_VERSION}")
        self.setMinimumWidth(1000)
        self.resize(980, 750)
        self.settings = QSettings("amzxyz", "WanXiangSettings")
        self.worker: Optional[Worker] = None
        self.upd_worker: Optional[UpdateWorker] = None
        self._yaml_cache = {}  # 缓存池
        self.cache_worker = None
        # 初始化检测结果变量
        self.detected_deployer = ""
        self.detected_server = ""

        self.ignore_non_chinese_cb_py = QCheckBox("忽略词组中的非汉字字符（如连字符、空格等）")
        self.ignore_non_chinese_cb_aux = QCheckBox("忽略词组中的非汉字字符（如连字符、空格等）")
        
        self.menubar = QMenuBar(self)
        menu_app = self.menubar.addMenu("应用")
        act_export_log = QAction("导出日志…", self); act_export_log.triggered.connect(self.export_log)
        act_clear_log = QAction("清空日志", self); act_clear_log.triggered.connect(lambda: self.log.clear())
        act_reset = QAction("恢复默认配置", self)
        act_reset.triggered.connect(self.reset_settings)
        act_quit = QAction("退出", self); act_quit.triggered.connect(QApplication.instance().quit)
        menu_app.addActions([act_export_log, act_clear_log, act_reset]) 
        menu_app.addSeparator(); menu_app.addAction(act_quit)

        menu_view = self.menubar.addMenu("视图")
        self.act_dark = QAction("暗色主题", self, checkable=True)
        self.act_dark.setChecked(self.settings.value('ui/dark', False, bool))
        self.act_dark.toggled.connect(self.apply_palette)
        menu_view.addAction(self.act_dark)

        act_about = QAction("关于", self)
        act_about.triggered.connect(self.show_about)
        self.menubar.addAction(act_about)


        self.tabs = QTabWidget()
        self.tab_py = self._build_tab_pinyin()
        self.tab_aux = self._build_tab_aux()
        self.tab_upd = self._build_tab_update()
        self.tab_sp = self._build_tab_shuangpin()
        self.tab_yaml = self._build_tab_schema_config()
        self.tab_more = self._build_tab_more()
        # 1. 在线更新 (现在的 Index 0)
        self.tabs.addTab(self.tab_upd, "在线更新与部署")
        # 2. 刷拼音 (现在的 Index 1)
        self.tabs.addTab(self.tab_py, "刷新拼音（保留辅助码）")
        # 3. 刷辅助码 (现在的 Index 2)
        self.tabs.addTab(self.tab_aux, "刷新辅助码（拼音;辅助码）")
        self.tabs.addTab(self.tab_sp, "双拼编码转换")
        self.tabs.addTab(self.tab_yaml, "高级设置")
        self.tabs.addTab(self.tab_more, "更多功能")
        self.btn_run = QPushButton("运行")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setStyleSheet("""
            QPushButton {
                background-color: #61A165; 
                color: white; 
                border: none; 
                border-radius: 4px; 
                padding: 6px 25px; /* 让主按钮稍微长一点，更显眼 */
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #559159; }
            QPushButton:pressed { background-color: #49814D; }
            /* 运行中被禁用时的颜色：浅灰绿 */
            QPushButton:disabled { background-color: #A8C7AA; color: #F0F5F1; }
        """)
        self.btn_run.clicked.connect(self.run_job)
        
        self.btn_stop = QPushButton("停止"); self.btn_stop.setEnabled(False); self.btn_stop.clicked.connect(self.stop_job)

        self.chk_force = QCheckBox("强制更新")
        self.chk_force.setToolTip("勾选后将忽略版本号和Hash校验，强制重新下载并覆盖文件。")
        self.chk_force.hide() # 默认隐藏，只有切到Tab 3才显示
        ctrl = QHBoxLayout(); ctrl.addWidget(self.btn_run); ctrl.addWidget(self.chk_force); ctrl.addWidget(self.btn_stop); ctrl.addStretch(1)
        self.progress = QProgressBar(); self.progress.setRange(0, 100)
        self.status = QLabel("就绪")
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(20000)
        self.log.setMinimumHeight(150)
        root = QVBoxLayout(self)
        root.setMenuBar(self.menubar)
        root.addWidget(self.tabs)
        root.addLayout(ctrl)
        root.addWidget(self.progress)
        root.addWidget(self.status)
        root.addWidget(self.log)

        self.restore_settings()
        self.apply_palette(self.act_dark.isChecked())
        self.tabs.currentChanged.connect(self.on_tab_change)
        self.on_tab_change(0)  #初始化是运行，手动刷新为更新
    # ====================检查更新调度函数 ====================
    def check_update(self):
        # 【关键交互】点击检查更新时，自动帮用户切换到 GitHub 下载源
        self.rb_src_gh.setChecked(True)
        self.bg_src.idClicked.emit(0) 

        self.status.setText("正在获取最新版本信息，请稍候...")
        self.log.appendPlainText(">>> 正在连接 API 获取最新版本...")
        
        self.check_worker = CheckUpdateWorker(
            self.upd_token.text()
        )
        self.check_worker.result_sig.connect(self.on_check_update_result)
        self.check_worker.start()
        
    def on_check_update_result(self, remote_vers):
        self.status.setText("就绪")
        
        local_dict = self.settings.value("installed_versions/dict_hash", "0.0.0")
        local_dict_display = local_dict[:8] if len(local_dict) > 20 else local_dict
        local_model = self.settings.value("installed_versions/model_hash", "0.0.0")
        local_model_display = local_model[:8] if len(local_model) > 20 else local_model
        schema_ver = ""
        rime_dir = self.upd_rime.text().strip()
        version_file = os.path.join(rime_dir, "version.txt")
        if os.path.isfile(version_file):
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        # 去除开头的 v 或 V
                        if content.lower().startswith('v'):
                            content = content[1:]
                        schema_ver = content
            except Exception as e:
                self.log.appendPlainText(f"[Warn] 读取 version.txt 出错: {e}")
                
        # 如果文件不存在或为空，则回退到设置记录
        if not schema_ver:
            schema_ver = self.settings.value("installed_versions/方案组件", "0.0.0")
            if schema_ver and schema_ver.lower().startswith('v'):
                schema_ver = schema_ver[1:]
                
        # 同步处理远程方案版本（去除 v/V），防止本地无 v 远程有 v 导致一直提示更新
        rem_schema = remote_vers.get('schema', '未知')
        if rem_schema not in ['获取失败', '网络错误', '未知'] and rem_schema.lower().startswith('v'):
            remote_vers['schema'] = rem_schema[1:]
        local_vers = {
            'tool': TOOL_VERSION,
            'schema': schema_ver,
            'dict': local_dict_display,
            'model': local_model_display
        }
        for k in local_vers:
            if local_vers[k] == "0.0.0" or not local_vers[k]: local_vers[k] = "未记录"
            
        dlg = UpdateCheckDialog(self, local_vers, remote_vers)
        dlg.exec()
    def trigger_update_from_dialog(self, scope_id, force):
        """由弹窗调用的自动更新触发器"""
        self.tabs.setCurrentIndex(0) # 自动切到在线更新 Tab
        # 强制将顶部的大分类切回“万象更新”官方源，防止被自定义链接拦截
        if self.bg_source_type.checkedId() != 0:
            self.bg_source_type.button(0).setChecked(True)
            self.bg_source_type.idClicked.emit(0)
        # 选中对应的更新范围
        if self.bg_scope.button(scope_id):
            self.bg_scope.button(scope_id).setChecked(True)
            self.bg_scope.idClicked.emit(scope_id) # 触发布局联动
            
        # 根据是否是 "重新下载" 决定是否开启强制更新机制
        self.chk_force.setChecked(force)
        
        if force:
            self.log.appendPlainText("💡 [提示] 触发重新下载，已自动开启【强制更新】模式。")
            
        # 直接运行
        self.run_update()
            
        # 直接运行
        self.run_update()
    def _build_tab_update(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setSpacing(5) 
        l.setContentsMargins(5, 5, 5, 5)
        
        # --- 顶部提示 ---
        lbl_info = QLabel("【提示】请先选择更新源。GitHub源可能需要配置Token。\n CNB源为国内镜像。词库、模型选项因没有版本差异，所以不具备检测校验后下载的能力。")
        lbl_info.setStyleSheet("font-size: 14px; margin-bottom: 2px;")
        lbl_info.setWordWrap(True)
        l.addWidget(lbl_info)

        h_main = QHBoxLayout()
        l_left = QVBoxLayout()
        l_right = QVBoxLayout()
        l_left.setSpacing(8) 
        
        # === 1. 来源选择 ===
        gb_source = QGroupBox("来源选择")
        hb_source = QHBoxLayout(gb_source)
        hb_source.setContentsMargins(5, 5, 5, 5)
        self.bg_source_type = QButtonGroup(self)
        rb_official = QRadioButton("万象更新")
        rb_custom = QRadioButton("使用我的仓库(ZIP直链)")
        self.bg_source_type.addButton(rb_official, 0)
        self.bg_source_type.addButton(rb_custom, 1)
        rb_official.setChecked(True)
        hb_source.addWidget(rb_official)
        hb_source.addWidget(rb_custom)
        hb_source.addStretch()
        
        self.custom_url_input = QLineEdit()
        self.custom_url_input.setPlaceholderText("请输入 ZIP 下载直链地址")
        
        # === 2 & 3. 范围与版本 (合并显示) ===
        row_mid = QHBoxLayout()
        
        # Scope (范围)
        self.gb_scope = QGroupBox("更新范围")
        hb_scope = QHBoxLayout(self.gb_scope)
        hb_scope.setContentsMargins(5, 5, 5, 5)
        self.bg_scope = QButtonGroup(self)
        rb_full = QRadioButton("全量"); rb_full.setChecked(True)
        rb_schema = QRadioButton("仅方案")
        rb_preview = QRadioButton("预览方案")
        rb_dict = QRadioButton("仅词库")
        rb_mod = QRadioButton("仅模型")

        self.bg_scope.addButton(rb_full, 0)
        self.bg_scope.addButton(rb_schema, 1)
        self.bg_scope.addButton(rb_dict, 2)
        self.bg_scope.addButton(rb_mod, 3)
        self.bg_scope.addButton(rb_preview, 4)
        hb_scope.addWidget(rb_full); hb_scope.addWidget(rb_schema); hb_scope.addWidget(rb_preview); hb_scope.addWidget(rb_dict); hb_scope.addWidget(rb_mod); hb_scope.addStretch()
        
        # Version & Aux (版本 & 辅助码下拉框)
        self.gb_ver = QGroupBox("方案版本")
        hb_ver = QHBoxLayout(self.gb_ver)
        hb_ver.setContentsMargins(5, 5, 5, 5)
        self.bg_ver = QButtonGroup(self)
        
        self.rb_pro = QRadioButton("Pro")
        self.rb_pro.setChecked(True)
        self.rb_base = QRadioButton("Base")
        self.bg_ver.addButton(self.rb_pro, 0)
        self.bg_ver.addButton(self.rb_base, 1)
        
        # 【核心修改】新增下拉框用于选择辅助码方案
        self.combo_aux = QComboBox()
        self.combo_aux.setToolTip("选择 Pro 版对应的辅助码方案")
        # 填充数据 (显示名字，内部存储 key)
        for k, v in SCHEME_MAP.items():
            self.combo_aux.addItem(v, k)
        # 默认选中第一个 (自然码)
        self.combo_aux.setCurrentIndex(0)

        hb_ver.addWidget(self.rb_pro)
        hb_ver.addWidget(self.combo_aux) # 放在 Pro 按钮旁边
        hb_ver.addWidget(self.rb_base)
        hb_ver.addStretch()

        row_mid.addWidget(self.gb_scope, 3) 
        row_mid.addWidget(self.gb_ver, 3)   

        # 联动逻辑
        def on_source_changed(id):
            is_custom = (id == 1)
            self.gb_scope.setVisible(not is_custom)
            self.gb_ver.setVisible(not is_custom)
            self.custom_url_input.setVisible(is_custom)
            form.setRowVisible(self.row_src_widget, not is_custom)
        self.bg_source_type.idClicked.connect(on_source_changed)

        def update_states(id):
            # id 是范围 ID (0=全量, 1=词库, 2=方案 3=模型)
            is_mod_only = (id == 3)
            self.gb_ver.setEnabled(not is_mod_only)
            # 如果禁用了版本选择，辅助码下拉框也要禁用
            if is_mod_only:
                self.combo_aux.setEnabled(False)
            else:
                # 只有选 Pro 版才启用下拉框
                self.combo_aux.setEnabled(self.rb_pro.isChecked())

        self.bg_scope.idClicked.connect(update_states)
        
        # 只有选中 Pro 版时，辅助码下拉框才可用
        self.rb_pro.toggled.connect(lambda checked: self.combo_aux.setEnabled(checked and self.bg_scope.checkedId() != 3))

        # === 5. 配置 ===
        gb_cfg = QGroupBox("配置") # 序号变为4
        form = QFormLayout(gb_cfg)
        form.setContentsMargins(5, 5, 5, 5)
        form.setVerticalSpacing(5)
        
        self.upd_rime = PathEdit(); self.upd_rime.setPlaceholderText("Rime用户目录")
        def do_auto_detect():
            det = PathDetector.detect()
            if det['rime_user_dir']: 
                self.upd_rime.setText(det['rime_user_dir'])
                self.upd_rime.setStyleSheet("")
                self.detected_server = det.get('weasel_server', '')
                self.detected_deployer = det.get('weasel_deployer', '')
            else:
                self.upd_rime.setPlaceholderText("未能自动检测到路径")
        
        b_rime = QPushButton("选择"); b_rime.setFixedWidth(50); b_rime.clicked.connect(lambda: self.pick_dir(self.upd_rime))
        b_reset = QPushButton("重置"); b_reset.setFixedWidth(50); b_reset.clicked.connect(do_auto_detect)
        do_auto_detect()
        
        r_rime = QHBoxLayout(); r_rime.setContentsMargins(0,0,0,0)
        r_rime.addWidget(self.upd_rime); r_rime.addWidget(b_rime); r_rime.addWidget(b_reset)
        
        self.row_src_widget = QWidget()
        row_src = QHBoxLayout(self.row_src_widget)
        row_src.setContentsMargins(0,0,0,0)
        self.bg_src = QButtonGroup(self)

        # 保留内部对象兼容旧设置，但不再向用户显示。
        self.rb_src_auto = QRadioButton()
        self.rb_src_auto.hide()
        self.bg_src.addButton(self.rb_src_auto, 1)
        # [视觉容器] GitHub + 检查更新
        self.gh_frame = QFrame()
        self.gh_frame.setObjectName("ghBox")
        # 样式已移交 apply_palette 统一管理，支持暗黑模式切换
        gh_lay = QHBoxLayout(self.gh_frame)
        gh_lay.setContentsMargins(8, 2, 8, 2)
        
        self.rb_src_gh = QRadioButton("GitHub")
        self.bg_src.addButton(self.rb_src_gh, 0)
        self.rb_src_gh.setChecked(True)
        self.btn_check_update = QPushButton("检查更新")
        self.btn_check_update.setCursor(Qt.PointingHandCursor)
        # 换成护眼的莫兰迪灰绿 (Sage Green)
        self.btn_check_update.setStyleSheet("""
            QPushButton {
                background-color: #61A165; 
                color: white; 
                border: none; 
                border-radius: 4px; 
                padding: 3px 12px; 
                font-weight: bold;
            }
            QPushButton:hover { background-color: #559159; }
            QPushButton:pressed { background-color: #49814D; }
        """)
        self.btn_check_update.clicked.connect(self.check_update)

        self.btn_route_test = QPushButton("测速最优路线")
        self.btn_route_test.setCursor(Qt.PointingHandCursor)
        self.btn_route_test.setStyleSheet(self.btn_check_update.styleSheet())
        self.btn_route_test.clicked.connect(self.start_github_route_test)
        self.btn_add_proxy = QPushButton("添加代理连接")
        self.btn_add_proxy.setCursor(Qt.PointingHandCursor)
        self.btn_add_proxy.setStyleSheet(self.btn_check_update.styleSheet())
        self.btn_add_proxy.clicked.connect(self.add_github_proxy)
        gh_lay.addWidget(self.rb_src_gh)
        gh_lay.addSpacing(10)
        gh_lay.addWidget(self.btn_check_update)
        gh_lay.addSpacing(6)
        gh_lay.addWidget(self.btn_route_test)
        gh_lay.addSpacing(6)
        gh_lay.addWidget(self.btn_add_proxy)
        row_src.addWidget(self.gh_frame)
        row_src.addStretch()
        # === GitHub 下载路线：两行排列 ===
        self.row_route_widget = QWidget()
        self.route_grid = QGridLayout(self.row_route_widget)
        self.route_grid.setContentsMargins(0, 0, 0, 0)
        self.route_grid.setHorizontalSpacing(6)
        self.route_grid.setVerticalSpacing(5)
        self._load_custom_github_routes()
        self.bg_gh_route = QButtonGroup(self)
        self.route_buttons = {}

        for index, (route_id, route) in enumerate(GITHUB_ROUTES.items()):
            button = QRadioButton(route["name"])
            button.setProperty("route_name", route["name"])
            button.setMinimumHeight(28)
            self._set_route_button_style(button, "#747A76")
            self._bind_github_route_menu(button, route_id)

            self.bg_gh_route.addButton(button, route_id)
            self.route_buttons[route_id] = button

            row, column = divmod(index, 3)
            self.route_grid.addWidget(button, row, column)

        self.route_buttons[0].setChecked(True)
        self.route_grid.setColumnStretch(3, 1)

        self.route_test_worker = None

        self.row_slow_fallback_widget = QWidget()
        slow_fallback_lay = QHBoxLayout(self.row_slow_fallback_widget)
        slow_fallback_lay.setContentsMargins(0, 0, 0, 0)
        slow_fallback_lay.setSpacing(8)

        self.chk_proxy_slow_fallback = QCheckBox("代理低速时直接切换CNB")
        self.chk_proxy_slow_fallback.setChecked(True)

        self.combo_proxy_min_speed = QComboBox()
        for speed in (64, 128, 256, 512):
            self.combo_proxy_min_speed.addItem(f"{speed} KB/s", speed)
        self.combo_proxy_min_speed.setCurrentIndex(1)
        self.combo_proxy_min_speed.setFixedWidth(105)
        self.combo_proxy_min_speed.setToolTip("代理经过5秒预热后，连续约4秒低于此速度便停止并改用CNB。")
        self.chk_proxy_slow_fallback.toggled.connect(self.combo_proxy_min_speed.setEnabled)

        slow_fallback_lay.addWidget(self.chk_proxy_slow_fallback)
        slow_fallback_lay.addWidget(QLabel("最低速度:"))
        slow_fallback_lay.addWidget(self.combo_proxy_min_speed)
        slow_fallback_lay.addStretch()

        self.upd_token = QLineEdit(); self.upd_token.setPlaceholderText("GitHub Token (可选)")
        self.upd_token.setEchoMode(QLineEdit.Password)
        
        form.addRow("Rime目录:", r_rime)
        form.addRow("下载源:", self.row_src_widget)
        form.addRow("GitHub路线:", self.row_route_widget)
        form.addRow("低速回退:", self.row_slow_fallback_widget)
        form.addRow("Token:", self.upd_token)

        l_left.addWidget(gb_source)
        l_left.addWidget(self.custom_url_input)
        self.custom_url_input.hide()
        l_left.addLayout(row_mid)
        l_left.addWidget(gb_cfg)
        l_left.addStretch()
        # ==================== 右侧：白名单与安全 ====================
        gb_wl = QGroupBox("白名单与安全")
        l_wl = QVBoxLayout(gb_wl)
        l_wl.setContentsMargins(5, 5, 5, 5)
        
        self.chk_clean_build = QCheckBox("部署前清空 build 目录")
        l_wl.addWidget(self.chk_clean_build)

        self.chk_clean = QCheckBox("更新前清理非白名单文件 (慎用!)")
        self.chk_clean.setStyleSheet("color: red; font-weight: bold;")
        l_wl.addWidget(self.chk_clean)
        def on_clean_toggled(checked):
            if checked:
                # 勾选清理时 -> 自动勾选强制更新
                self.chk_force.setChecked(True)
                # 可选：如果你想强制用户不能取消，可以解开下面这行
                self.chk_force.setEnabled(False) 
                self.chk_force.setToolTip("安全保护：清理模式下必须强制下载，防止文件缺失。")
                self.log.appendPlainText("⚠️ [提示] 已开启清理模式，系统自动开启【强制更新】以确保文件完整。")
            else:
                # 取消清理时 -> 恢复强制更新可选状态 (不自动取消，由用户决定)
                self.chk_force.setEnabled(True)
                self.chk_force.setToolTip("勾选后将忽略版本号和Hash校验，强制重新下载并覆盖文件。")

        self.chk_clean.toggled.connect(on_clean_toggled)
        self.upd_wl_edit = QPlainTextEdit()
        self.upd_wl_edit.setPlainText("\n".join(DEFAULT_WL_REGEX))
        self.upd_wl_edit.setPlaceholderText("正则规则，一行一个")
        
        tip = QLabel("说明：\n白名单文件绝不会被删除或覆盖。\n只需要定义文件名规则，不用管路径深度。")
        tip.setStyleSheet("color: gray; font-size: 11px;")
        tip.setWordWrap(True)
        
        l_wl.addWidget(self.upd_wl_edit)
        l_wl.addWidget(tip)
        
        l_right.addWidget(gb_wl)

        h_main.addLayout(l_left, stretch=5)
        h_main.addLayout(l_right, stretch=3)
        l.addLayout(h_main)
        return w
    def _load_custom_github_routes(self):
        """读取当前保存的全部代理路线，同时兼容旧版自定义代理设置。"""
        raw = self.settings.value("upd/github_routes", "")

        if raw:
            try:
                routes = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                routes = []

            if isinstance(routes, list):
                for route_id in [rid for rid in list(GITHUB_ROUTES) if rid != 0]:
                    del GITHUB_ROUTES[route_id]

                for item in routes:
                    if not isinstance(item, dict): continue

                    try:
                        route_id = int(item.get("id"))
                    except Exception:
                        continue

                    name = str(item.get("name", "")).strip()
                    prefix = str(item.get("prefix", "")).strip()

                    if route_id == 0 or not name: continue
                    if not prefix.startswith(("http://", "https://")): continue

                    GITHUB_ROUTES[route_id] = {
                        "name": name,
                        "prefix": prefix.rstrip("/") + "/",
                    }

            return

        # 兼容之前只保存自定义代理的格式。
        raw = self.settings.value("upd/custom_github_routes", "[]")

        try:
            routes = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            routes = []

        if not isinstance(routes, list): return

        for item in routes:
            if not isinstance(item, dict): continue

            name = str(item.get("name", "")).strip()
            prefix = str(item.get("prefix", "")).strip()

            if not name or not prefix.startswith(("http://", "https://")): continue

            prefix = prefix.rstrip("/") + "/"

            if any(route["prefix"] == prefix for route in GITHUB_ROUTES.values()):
                continue

            route_id = max([99, *GITHUB_ROUTES.keys()]) + 1
            GITHUB_ROUTES[route_id] = {"name": name, "prefix": prefix}

    def _save_custom_github_routes(self):
        """保存当前全部代理路线，GitHub官方除外。"""
        routes = [
            {"id": route_id, "name": route["name"], "prefix": route["prefix"]}
            for route_id, route in GITHUB_ROUTES.items()
            if route_id != 0
        ]

        self.settings.setValue("upd/github_routes", json.dumps(routes, ensure_ascii=False))
        self.settings.remove("upd/custom_github_routes")
        self.settings.sync()

    def add_github_proxy(self):
        """添加一个“代理前缀 + GitHub原始地址”类型的代理。"""
        if self.route_test_worker and self.route_test_worker.isRunning():
            QMessageBox.information(self, "提示", "请等待当前测速完成后再添加代理。")
            return

        name, ok = QInputDialog.getText(
            self,
            "添加代理连接",
            "显示名称：",
            QLineEdit.Normal,
            "自定义代理",
        )

        if not ok: return

        name = name.strip()

        if not name:
            QMessageBox.warning(self, "输入错误", "代理名称不能为空。")
            return

        prefix, ok = QInputDialog.getText(
            self,
            "添加代理连接",
            "代理前缀：\n例如：https://proxy.example/",
        )

        if not ok: return

        prefix = prefix.strip()

        if not prefix.startswith(("http://", "https://")):
            QMessageBox.warning(self, "输入错误", "代理地址必须以 http:// 或 https:// 开头。")
            return

        prefix = prefix.rstrip("/") + "/"

        for route in GITHUB_ROUTES.values():
            if route["prefix"] == prefix:
                QMessageBox.information(self, "提示", "这个代理地址已经存在。")
                return

        route_id = max([99, *GITHUB_ROUTES.keys()]) + 1
        GITHUB_ROUTES[route_id] = {"name": name, "prefix": prefix}

        button = QRadioButton(name)
        button.setProperty("route_name", name)
        button.setMinimumHeight(28)
        self._set_route_button_style(button, "#747A76")
        self._bind_github_route_menu(button, route_id)

        self.bg_gh_route.addButton(button, route_id)
        self.route_buttons[route_id] = button

        index = len(self.route_buttons) - 1
        row, column = divmod(index, 3)
        self._reflow_github_route_grid()

        button.setChecked(True)

        self._save_custom_github_routes()
        self.settings.setValue("upd/github_route", route_id)
        self.settings.sync()

        self.log.appendPlainText(f"➕ 已添加GitHub代理：{name} → {prefix}")

        QTimer.singleShot(0, self.start_github_route_test)
    def _bind_github_route_menu(self, button, route_id):
        """为路线按钮绑定右键菜单。"""
        button.setContextMenuPolicy(Qt.CustomContextMenu)
        button.customContextMenuRequested.connect(
            lambda pos, rid=route_id, btn=button: self._show_github_route_menu(rid, btn, pos)
        )

    def _show_github_route_menu(self, route_id, button, pos):
        """显示代理路线右键菜单。"""
        menu = QMenu(button)

        if route_id == 0:
            action = menu.addAction("GitHub 官方路线不可删除")
            action.setEnabled(False)
        else:
            action = menu.addAction("删除此路线")
            action.triggered.connect(lambda: self.delete_github_route(route_id))

        menu.exec(button.mapToGlobal(pos))

    def _reflow_github_route_grid(self):
        """添加或删除后，重新按每行3个排列。"""
        while self.route_grid.count():
            self.route_grid.takeAt(0)

        for index, button in enumerate(self.route_buttons.values()):
            row, column = divmod(index, 3)
            self.route_grid.addWidget(button, row, column)

        self.route_grid.setColumnStretch(3, 1)

    def delete_github_route(self, route_id):
        """删除右键选中的代理，GitHub官方路线不可删除。"""
        if self.route_test_worker and self.route_test_worker.isRunning():
            QMessageBox.information(self, "提示", "请等待当前测速完成后再删除代理。")
            return

        if route_id == 0:
            QMessageBox.information(self, "无法删除", "GitHub官方路线必须保留。")
            return

        if route_id not in GITHUB_ROUTES:
            return

        route = GITHUB_ROUTES[route_id]
        name = route["name"]
        prefix = route["prefix"]

        result = QMessageBox.question(
            self,
            "删除代理路线",
            f"确定删除这个代理吗？\n\n名称：{name}\n地址：{prefix}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if result != QMessageBox.Yes:
            return

        was_selected = self.bg_gh_route.checkedId() == route_id
        button = self.route_buttons.pop(route_id, None)

        if button:
            self.bg_gh_route.removeButton(button)
            self.route_grid.removeWidget(button)
            button.deleteLater()

        del GITHUB_ROUTES[route_id]

        if was_selected:
            self.route_buttons[0].setChecked(True)
            self.settings.setValue("upd/github_route", 0)

        self._save_custom_github_routes()
        self._reflow_github_route_grid()

        self.log.appendPlainText(f"➖ 已删除GitHub代理：{name} → {prefix}")

    def _set_route_button_style(self, button, color):
        button.setStyleSheet(f"""
            QRadioButton {{
                color: {color};
                background-color: transparent;
                border: 1px solid {color};
                border-radius: 11px;
                padding: 3px 10px;
                font-size: 12px;
                font-weight: bold;
            }}
            QRadioButton:checked {{
                color: white;
                background-color: {color};
                border-color: {color};
            }}
        """)
    def start_github_route_test(self):
        if self.route_test_worker and self.route_test_worker.isRunning(): return

        self.btn_route_test.setEnabled(False)
        self.btn_route_test.setText("测速中...")

        for route_id, button in self.route_buttons.items():
            button.setText(GITHUB_ROUTES[route_id]["name"])
            self._set_route_button_style(button, "#8A8A8A")

        self.route_test_worker = GithubRouteTestWorker(GITHUB_ROUTE_TEST_URL)
        self.route_test_worker.done_sig.connect(self.finish_github_route_test)
        self.route_test_worker.start()
    def finish_github_route_test(self, results):
        self.btn_route_test.setEnabled(True)
        self.btn_route_test.setText("测速最优路线")

        available = []

        for route_id, result in results.items():
            route = GITHUB_ROUTES[route_id]
            button = self.route_buttons[route_id]

            if result["ok"]:
                ms = result["ms"]
                button.setText(f"{route['name']}  {ms:.0f} ms")
                available.append((ms, route_id))
            else:
                button.setText(f"{route['name']}  不可用")
                self._set_route_button_style(button, "#747A76")

        if not available:
            self.log.appendPlainText("⚠️ GitHub 路线测速均失败，请检查网络。")
            return

        available.sort()

        for rank, (_, route_id) in enumerate(available):
            if rank == 0:
                color = "#61A165"
            elif rank == 1:
                color = "#C9A44C"
            else:
                color = "#C46A6A"

            self._set_route_button_style(self.route_buttons[route_id], color)

        best_ms, best_route_id = available[0]
        best_name = GITHUB_ROUTES[best_route_id]["name"]

        self.route_buttons[best_route_id].setChecked(True)
        self.log.appendPlainText(f"🚀 已选择最优路线：{best_name}，延迟约 {best_ms:.0f} ms")
    def on_tab_change(self, idx):
        is_yaml_tab = (self.tabs.widget(idx) == self.tab_yaml)

        # 动态隐藏/显示底部控件
        self.btn_run.setVisible(not is_yaml_tab)
        self.btn_stop.setVisible(not is_yaml_tab)
        self.chk_force.setVisible(not is_yaml_tab and idx == 0)
        self.progress.setVisible(not is_yaml_tab)
        self.status.setVisible(not is_yaml_tab)
        self.log.setVisible(not is_yaml_tab)

        if is_yaml_tab:
            current_dir = self.upd_rime.text().strip()
            #只有当目录变更，或者第一次进入时，才触发全量加载！切标签绝不重载！
            if getattr(self, '_loaded_rime_dir', "") != current_dir:
                self.scan_rime_directory()
            return

        if idx == 0:
            self.btn_run.setText("开始更新")
            try: self.btn_run.clicked.disconnect()
            except: pass
            self.btn_run.clicked.connect(self.run_update)
            
            try: self.btn_stop.clicked.disconnect()
            except: pass
            self.btn_stop.clicked.connect(self.stop_update)
            
            det = PathDetector.detect()
            if det['rime_user_dir']:
                self.upd_rime.setText(det['rime_user_dir'])
                self.upd_rime.setStyleSheet("")
                self.detected_server = det.get('weasel_server', '')
                self.detected_deployer = det.get('weasel_deployer', '')
        else:
            if idx == 3: self.btn_run.setText("开始转换")
            else: self.btn_run.setText("运行")

            try: self.btn_run.clicked.disconnect()
            except: pass
            self.btn_run.clicked.connect(self.run_job)
            
            try: self.btn_stop.clicked.disconnect()
            except: pass
            self.btn_stop.clicked.connect(self.stop_job)
    def run_update(self):
        if self.upd_worker and self.upd_worker.isRunning(): return
        rime_dir = self.upd_rime.text()
        if not rime_dir or not os.path.exists(rime_dir):
            QMessageBox.warning(self, "错误", "Rime目录无效"); return

        is_custom_source = (self.bg_source_type.checkedId() == 1)
        custom_url = None
        
        if is_custom_source:
            custom_url = self.custom_url_input.text().strip()
            if not custom_url:
                QMessageBox.warning(self, "错误", "请输入 ZIP 下载链接"); return
            if not (custom_url.startswith("http://") or custom_url.startswith("https://")):
                QMessageBox.warning(self, "错误", "下载链接必须以 http 或 https 开头"); return

        aux_key = self.combo_aux.currentData() 
        if not aux_key: aux_key = "zrm"
        whitelist_lines = self.upd_wl_edit.toPlainText().splitlines()

        versions = {}
        self.settings.beginGroup("installed_versions")
        for key in self.settings.childKeys(): versions[key] = self.settings.value(key, "0.0.0")
        self.settings.endGroup()
        # 更新执行前：方案版本优先读取 version.txt
        version_file = os.path.join(rime_dir, "version.txt")
        schema_ver_from_file = ""
        if os.path.isfile(version_file):
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    v_content = f.read().strip()
                    if v_content:
                        if v_content.lower().startswith('v'):
                            v_content = v_content[1:]
                        schema_ver_from_file = v_content
            except: pass
            
        if schema_ver_from_file:
            versions["方案组件"] = schema_ver_from_file
        else:
            old_sch = versions.get("方案组件", "")
            if old_sch.lower().startswith('v'):
                versions["方案组件"] = old_sch[1:]
        
        clean_mode = self.chk_clean.isChecked()
        if clean_mode:
            ret = QMessageBox.warning(self, "高风险操作", "您勾选了【更新前清理】。\n\n这将删除 Rime 目录下所有【不在白名单中】的文件！\n\n是否继续？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret == QMessageBox.No: return
            if not self.chk_force.isChecked():
                self.chk_force.setChecked(True)
                self.log.appendPlainText("🛡️ 安全覆写：检测到清理模式，已自动修正为【强制更新】。")
        is_auto_mirror = False
        route_id = self.bg_gh_route.checkedId()
        route_info = GITHUB_ROUTES.get(
            route_id,
            GITHUB_ROUTES[0],
        )
        github_proxy = route_info["prefix"]
        # 获取部署路径。Windows 在每次开始更新时重新确认一次，
        # 避免只恢复了 Rime 用户目录、却沿用空的部署器缓存。
        srv_path = str(getattr(self, "detected_server", "") or "")
        dep_path = str(getattr(self, "detected_deployer", "") or "")

        if SYSTEM_TYPE == "windows":
            if not (dep_path and os.path.isfile(dep_path)):
                try:
                    detected = PathDetector.detect()
                except Exception as error:
                    detected = {}
                    self.log.appendPlainText(
                        f"⚠️ 更新前重新检测小狼毫路径失败：{error}"
                    )

                detected_server = str(
                    detected.get("weasel_server", "") or ""
                )
                detected_deployer = str(
                    detected.get("weasel_deployer", "") or ""
                )

                if detected_server and os.path.isfile(detected_server):
                    self.detected_server = detected_server
                    srv_path = detected_server

                if detected_deployer and os.path.isfile(detected_deployer):
                    self.detected_deployer = detected_deployer
                    dep_path = detected_deployer

        cfg = UpdateConfig(
            scope=self.bg_scope.checkedId(),
            scheme_type='base' if self.bg_ver.button(1).isChecked() else 'pro',
            aux_scheme=aux_key,
            rime_dir=rime_dir,
            github_token=_normalize_github_token(self.upd_token.text()),
            github_proxy=github_proxy,
            use_mirror=is_auto_mirror,
            whitelist=whitelist_lines,
            current_versions=versions,
            clean_before=clean_mode,
            clean_build=self.chk_clean_build.isChecked(),
            custom_url=custom_url,
            server_path=srv_path,
            deployer_path=dep_path,
            force_update=self.chk_force.isChecked(),
            proxy_slow_fallback=self.chk_proxy_slow_fallback.isChecked(),
            proxy_min_speed_kbps=int(self.combo_proxy_min_speed.currentData() or 128)
        )
        
        self.log.clear()
        self.save_settings()
        
        self.upd_worker = UpdateWorker(cfg)
        self.upd_worker.log_sig.connect(self.log.appendPlainText)
        self.upd_worker.progress_sig.connect(lambda t, c, tot: (self.status.setText(f"{t}: {c}/{tot}"), self.progress.setValue(int(c/tot*100) if tot else 0)))
        self.upd_worker.version_sig.connect(self.on_version_updated)
        self.upd_worker.done_sig.connect(self.on_update_done)
        
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.tabs.setEnabled(False)
        self.upd_worker.start()

    def on_version_updated(self, comp, ver):
        self.settings.setValue(f"installed_versions/{comp}", ver)

    def stop_update(self):
        if not self.upd_worker or not self.upd_worker.isRunning(): return

        self.btn_stop.setEnabled(False)
        self.status.setText("正在停止...")
        self.log.appendPlainText("⏹ 已请求停止，正在安全结束当前操作...")
        self.upd_worker.stop()

    def on_update_done(self, ok, msg):
        cancelled = (msg == "⏹ 更新已取消。")

        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.tabs.setEnabled(True)

        if cancelled:
            self.status.setText("已取消")
        else:
            self.status.setText("完成" if ok else "失败")

        self.log.appendPlainText(msg)
        self.settings.sync()
        self.save_settings()

        if cancelled:
            return

        if ok:
            QMessageBox.information(self, "完成", msg)
        else:
            QMessageBox.warning(self, "错误", msg)
    def do_import_switches(self, text_field):
        """一键从 wanxiang.schema.yaml 提取有用开关"""
        main_schema = os.path.join(self.upd_rime.text().strip(), "wanxiang.schema.yaml")
        if not os.path.exists(main_schema):
            QMessageBox.warning(self, "未找到主方案", "未能找到 wanxiang.schema.yaml")
            return
        try:
            from ruamel.yaml import YAML
            y = YAML()
            with open(main_schema, 'r', encoding='utf-8') as f: data = y.load(f)
            switches = data.get('switches', [])
            res = []
            for sw in switches:
                if 'name' in sw:
                    if 'reset' not in sw: res.append(sw['name'])
                elif 'options' in sw:
                    opts = sw['options']
                    if len(opts) > 1:
                        res.extend(opts[1:]) # 取后面有用的，丢弃第一个(通常是 off)
            text_field.setPlainText("\n".join(res))
            QMessageBox.information(self, "导入成功", f"成功提取了 {len(res)} 个开关，请保存生效！")
        except Exception as e:
            QMessageBox.critical(self, "解析出错", str(e))
    # —— 通用中文文件选择对话框 ——
    def get_open_file(self, title: str, name_filter: str) -> str:
        dlg = QFileDialog(self, title)
        dlg.setFileMode(QFileDialog.ExistingFile)
        dlg.setNameFilter(name_filter)
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        dlg.setLabelText(QFileDialog.Accept, "确定")
        dlg.setLabelText(QFileDialog.Reject, "取消")
        if dlg.exec():
            files = dlg.selectedFiles()
            if files: return files[0]
        return ""

    def get_existing_directory(self, title: str) -> str:
        dlg = QFileDialog(self, title)
        dlg.setFileMode(QFileDialog.Directory)
        dlg.setOption(QFileDialog.ShowDirsOnly, True)
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        dlg.setLabelText(QFileDialog.Accept, "确定")
        dlg.setLabelText(QFileDialog.Reject, "取消")
        if dlg.exec():
            files = dlg.selectedFiles()
            if files: return files[0]
        return ""

    def get_save_file(self, title: str, default_name: str, name_filter: str) -> str:
        dlg = QFileDialog(self, title)
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.selectFile(default_name)
        dlg.setNameFilter(name_filter)
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        dlg.setLabelText(QFileDialog.Accept, "确定")
        dlg.setLabelText(QFileDialog.Reject, "取消")
        if dlg.exec():
            files = dlg.selectedFiles()
            if files: return files[0]
        return ""

    # —— 构建各标签页 (Tab 1 & 2) ——
    def _build_tab_pinyin(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hbox1 = QHBoxLayout()
        hbox1.addWidget(self.ignore_non_chinese_cb_py)
        hbox1.addStretch(1)
        lay.addLayout(hbox1)
        self.ignore_non_chinese_cb_py.setChecked(True)

        hbox2 = QHBoxLayout()
        sep_lbl = QLabel("拼音分隔符：")
        self.py_sep_edit = QLineEdit(" ")
        self.py_sep_edit.setFixedWidth(50)
        self.py_sep_edit.setPlaceholderText("空格")
        hbox2.addWidget(sep_lbl)
        hbox2.addWidget(self.py_sep_edit)
        hbox2.addStretch(1)
        lay.addLayout(hbox2)

        g = QGroupBox("刷拼音参数（可选自定义拼音目录，目录内txt文本格式为：词组\\t拼音）")
        f = QFormLayout(g)
        self.in_edit_py = PathEdit("拖拽或选择：词表文件/目录（.txt/.yaml）")
        self.out_edit_py = PathEdit("拖拽或选择：输出文件/目录")
        self.custom_dir_edit = PathEdit("可放 custom_single.txt / custom_phrase.txt，或混放 .txt/.yaml；\n格式：词组\\t拼音（单字同理）")

        b_in = QPushButton("选择…");  b_in.clicked.connect(lambda: self.pick_any(self.in_edit_py, True))
        b_out = QPushButton("选择…"); b_out.clicked.connect(lambda: self.pick_output(self.out_edit_py))
        b_custom = QPushButton("选择…"); b_custom.clicked.connect(lambda: self.pick_dir(self.custom_dir_edit))
        row_in = QHBoxLayout(); row_in.addWidget(self.in_edit_py); row_in.addWidget(b_in)
        row_out = QHBoxLayout(); row_out.addWidget(self.out_edit_py); row_out.addWidget(b_out)
        row_c = QHBoxLayout(); row_c.addWidget(self.custom_dir_edit); row_c.addWidget(b_custom)
        f.addRow("输入路径：", self._wrap(row_in))
        f.addRow("输出路径：", self._wrap(row_out))
        f.addRow("自定义拼音目录（可选）：", self._wrap(row_c))

        self.skip_group = QGroupBox("排除文件名（仅在输入路径为目录时生效）")
        skip_lay = QVBoxLayout(self.skip_group)
        self.skip_edit = QPlainTextEdit()
        self.skip_edit.setPlaceholderText("每行一个文件名")
        self.skip_edit.setPlainText("\n".join(sorted(DEFAULT_SKIP_SET)))
        tip = QLabel("说明：当输入为目录时，这些文件将被原样复制，不做拼音处理。")
        tip.setStyleSheet("color:gray;")
        skip_lay.addWidget(self.skip_edit)
        skip_lay.addWidget(tip)

        self.in_edit_py.textChanged.connect(self._toggle_skip_box)
        self._toggle_skip_box()
        lay.addWidget(g)
        lay.addWidget(self.skip_group)
        return w

    def _toggle_skip_box(self):
        p = (self.in_edit_py.text() or "").strip()
        show = os.path.isdir(p)
        self.skip_group.setVisible(show)

    def _build_tab_aux(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self.ignore_non_chinese_cb_aux)
        self.ignore_non_chinese_cb_aux.setChecked(True)
        
        g = QGroupBox("刷新辅助码参数（辅助码文件必选，格式：字\\t辅助码 或 字\\t拼音;辅助码）")
        f = QFormLayout(g)
        self.in_edit_aux = PathEdit("拖拽或选择：词表文件/目录（.txt/.yaml）")
        self.out_edit_aux = PathEdit("拖拽或选择：输出文件/目录")
        self.aux_file_edit = PathEdit("拖拽或选择：辅助码单字表（可直接用 zi 表）")
        b_in = QPushButton("选择…");  b_in.clicked.connect(lambda: self.pick_any(self.in_edit_aux, True))
        b_out = QPushButton("选择…"); b_out.clicked.connect(lambda: self.pick_output(self.out_edit_aux))
        b_aux = QPushButton("选择…");  b_aux.clicked.connect(lambda: self.pick_file(self.aux_file_edit))
        row_in = QHBoxLayout(); row_in.addWidget(self.in_edit_aux); row_in.addWidget(b_in)
        row_out = QHBoxLayout(); row_out.addWidget(self.out_edit_aux); row_out.addWidget(b_out)
        row_a = QHBoxLayout(); row_a.addWidget(self.aux_file_edit); row_a.addWidget(b_aux)
        f.addRow("输入路径：", self._wrap(row_in))
        f.addRow("输出路径：", self._wrap(row_out))
        f.addRow("辅助码文件（必选）：", self._wrap(row_a))
        lay.addWidget(g)
        return w
        # 双拼标签页构建
    # ==================== 修改位置 4：GUI构建 ====================
    def _build_tab_shuangpin(self) -> QWidget:
        w = QWidget(); lay = QVBoxLayout(w)
        
        # 1. 方案选择
        gb_sch = QGroupBox("双拼方案选择 (单选)")
        gl = QGridLayout(gb_sch)
        self.bg_sp = QButtonGroup(self)
        
        keys = list(SHUANGPIN_SCHEMAS.keys())
        for i, key in enumerate(keys):
            info = SHUANGPIN_SCHEMAS[key]
            rb = QRadioButton(info['name'])
            self.bg_sp.addButton(rb, i)
            gl.addWidget(rb, i // 4, i % 4)
            if key == 'zrm': rb.setChecked(True)
            
        lay.addWidget(gb_sch)
        
        # 2. 输出配置
        gb_sep = QGroupBox("输入输出配置")
        h_sep = QHBoxLayout(gb_sep)
        
        self.sp_in_sep_edit = QLineEdit(" "); self.sp_in_sep_edit.setFixedWidth(40); self.sp_in_sep_edit.setAlignment(Qt.AlignCenter)
        self.sp_out_sep_edit = QLineEdit(" "); self.sp_out_sep_edit.setFixedWidth(40); self.sp_out_sep_edit.setAlignment(Qt.AlignCenter)
        
        # 简码复选框
        self.sp_jianma_cb = QCheckBox("输出为简码 (取转换后的首字母)")
        self.sp_jianma_cb.setToolTip("转换双拼后只保留每个音节的第一个字母")
        h_sep.addWidget(QLabel("输入分隔符:"))
        h_sep.addWidget(self.sp_in_sep_edit)
        h_sep.addWidget(QLabel("  →  "))
        h_sep.addWidget(QLabel("输出分隔符:"))
        h_sep.addWidget(self.sp_out_sep_edit)
        h_sep.addWidget(QLabel(" (默认为空格，留空则紧凑输出)"))
        h_sep.addSpacing(20)
        h_sep.addWidget(self.sp_jianma_cb) # 加入布局
        h_sep.addStretch()
        lay.addWidget(gb_sep)
        
        # 3. 路径选择
        gb_io = QGroupBox("文件路径")
        f = QFormLayout(gb_io)
        
        self.in_edit_sp = PathEdit(); self.in_edit_sp.setPlaceholderText("词表文件 或 文件夹")
        self.out_edit_sp = PathEdit(); self.out_edit_sp.setPlaceholderText("转换后的输出位置")
        
        b_in = QPushButton("…"); b_in.setFixedWidth(30); b_in.clicked.connect(lambda: self.pick_any(self.in_edit_sp, True))
        b_out = QPushButton("…"); b_out.setFixedWidth(30); b_out.clicked.connect(lambda: self.pick_output(self.out_edit_sp))
        
        r_in = QHBoxLayout(); r_in.addWidget(self.in_edit_sp); r_in.addWidget(b_in)
        r_out = QHBoxLayout(); r_out.addWidget(self.out_edit_sp); r_out.addWidget(b_out)
        
        f.addRow("输入路径:", r_in)
        f.addRow("输出路径:", r_out)
        
        lay.addWidget(gb_io)
        lay.addStretch()
        
        return w
    # YAML 高级配置页 (风格布局 & 内容自适应宽度 & UI 极速堆叠缓存)
    # 模块化全局中控台









        



    def _start_and_deploy_from_main(self):
        """高级设置保存后的统一部署入口，按原程序的平台逻辑执行。"""
        server_path = str(getattr(self, "detected_server", "") or "")
        deployer_path = str(getattr(self, "detected_deployer", "") or "")

        # 部署器路径只与 Windows 有关；Linux/macOS 不做无关检测。
        if SYSTEM_TYPE == "windows":
            try:
                detected = PathDetector.detect()
            except Exception as error:
                detected = {}
                self.log.appendPlainText(f"⚠️ 重新检测小狼毫部署器失败：{error}")

            new_server = str(detected.get("weasel_server", "") or "")
            new_deployer = str(detected.get("weasel_deployer", "") or "")
            if new_server:
                self.detected_server = new_server
                server_path = new_server
            if new_deployer:
                self.detected_deployer = new_deployer
                deployer_path = new_deployer

        return deploy_rime_platform(
            SYSTEM_TYPE,
            log=self.log.appendPlainText,
            server_path=server_path,
            deployer_path=deployer_path,
        )

    def _build_tab_more(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(15, 15, 15, 15)
        btn_userdb = QPushButton("用户新增词整理")
        btn_userdb.setCursor(Qt.PointingHandCursor)
        btn_userdb.setStyleSheet("""
            QPushButton {
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
                color: #61A165; /* <--- 字体颜色也改为莫兰迪绿 */
                border: 1px solid #A8C7AA; /* 静态时的浅绿边框 */
                border-radius: 6px;
                background-color: transparent; 
            }
            QPushButton:hover {
                border: 1px solid #61A165; /* 悬浮时边框加深 */
                background-color: rgba(97, 161, 101, 0.1); /* 悬浮时的淡绿底色底纹 */
            }
            QPushButton:pressed {
                background-color: rgba(97, 161, 101, 0.2);
            }
        """)
        btn_userdb.setToolTip(
            "自动读取 installation.yaml 获取同步路径。\n"
            "扫描 userdb 提取您输入的新词，\n"
            "支持按字数过滤，以及在 dicts 目录中进行去重验证。"
        )
        
        def open_userdb_dialog():
            rime_dir = self.upd_rime.text().strip()
            dlg = UserDbSortDialog(self, rime_dir)
            dlg.exec()
            
        btn_userdb.clicked.connect(open_userdb_dialog)
        grid = QGridLayout()
        grid.addWidget(btn_userdb, 0, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)
        lay.addStretch()
        
        return w
    def _wrap(self, inner: QHBoxLayout) -> QWidget:
        w = QWidget(); w.setLayout(inner); return w

    def apply_palette(self, dark: bool):
        # 【性能优化】：冻结界面刷新，切主题时绝不卡顿
        self.setUpdatesEnabled(False)
        
        try:
            from PySide6.QtWidgets import QApplication, QStyleFactory
            from PySide6.QtGui import QPalette, QColor
            from PySide6.QtCore import Qt
            
            # 统一跨平台基底风格
            QApplication.setStyle(QStyleFactory.create("Fusion"))
            pal = QPalette()
            
            # ==========================================
            #   共用：高级定制滚动条与 SVG 矢量勾选框
            # ==========================================
            common_scrollbar_and_checkbox_css = """
                /* 强行接管勾选框和单选框的绘制，彻底解决无边界隐形问题 */
                QCheckBox::indicator, QRadioButton::indicator {
                    width: 16px; height: 16px; border-radius: 4px; 
                    border: 1px solid #A8C7AA; /* <--- 削薄到 1px 极简细线 */
                    background-color: transparent;
                }
                QRadioButton::indicator { border-radius: 8px; }
                QCheckBox::indicator:hover, QRadioButton::indicator:hover { 
                    border: 1px solid #61A165; /* <--- 悬浮框也保持 1px */
                    background-color: rgba(97, 161, 101, 0.1); 
                }
                QCheckBox::indicator:checked {
                    background-color: #61A165; border: 1px solid #61A165;
                    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIzIiBzdHJva2UtbGluZWNhcD0icm91bmQiIHN0cm9rZS1saW5lam9pbj0icm91bmQiPjxwb2x5bGluZSBwb2ludHM9IjIwIDYgOSAxNyA0IDEyIj48L3BvbHlsaW5lPjwvc3ZnPg==);
                }
                QRadioButton::indicator:checked {
                    background-color: #61A165; border: 1px solid #61A165;
                    image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PGNpcmNsZSBjeD0iMTIiIGN5PSIxMiIgcj0iNiIgZmlsbD0id2hpdGUiLz48L3N2Zz4=);
                }
                QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { 
                    border: 1px solid #666; background-color: rgba(100, 100, 100, 0.2);
                }
                
                /* 高级定制滚动条 (隐形轨道 + 莫兰迪绿悬浮) */
                QScrollBar:vertical { border: none; background: transparent; width: 12px; margin: 0px; }
                QScrollBar::handle:vertical { background: rgba(150, 150, 150, 0.4); border-radius: 6px; min-height: 30px; margin: 2px; }
                QScrollBar::handle:vertical:hover { background: #61A165; }
                QScrollBar::handle:vertical:pressed { background: #49814D; }
                QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical { border: none; background: none; height: 0px; }
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
                
                QScrollBar:horizontal { border: none; background: transparent; height: 12px; margin: 0px; }
                QScrollBar::handle:horizontal { background: rgba(150, 150, 150, 0.4); border-radius: 6px; min-width: 30px; margin: 2px; }
                QScrollBar::handle:horizontal:hover { background: #61A165; }
                QScrollBar::handle:horizontal:pressed { background: #49814D; }
                QScrollBar::sub-line:horizontal, QScrollBar::add-line:horizontal { border: none; background: none; width: 0px; }
                QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }
            """

            if dark:
                # ==========================================
                #   暗色模式：引入专业的护眼莫兰迪灰白
                # ==========================================
                off_white = QColor(210, 210, 210) # #D2D2D2，专业暗色阅读灰度
                bg_dark = QColor(45, 45, 45)      # 柔和底色
                
                pal.setColor(QPalette.Window, bg_dark)
                pal.setColor(QPalette.WindowText, off_white)
                pal.setColor(QPalette.Base, QColor(30, 30, 30))
                pal.setColor(QPalette.AlternateBase, bg_dark)
                pal.setColor(QPalette.Text, off_white)
                pal.setColor(QPalette.Button, QColor(60, 60, 60))
                pal.setColor(QPalette.ButtonText, off_white)
                pal.setColor(QPalette.Highlight, QColor(97, 161, 101))
                pal.setColor(QPalette.HighlightedText, Qt.white)
                QApplication.setPalette(pal)
                
                self.tabs.setStyleSheet("""
                    QTabWidget::pane { border: 1px solid #444; top: -1px; border-radius: 4px; }
                    QTabBar::tab { background-color: #353535; color: #D4D4D4; border: 1px solid #444; padding: 6px 16px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
                    QTabBar::tab:selected { background-color: #49814D; color: white; border: 1px solid #61A165; font-weight: bold; }
                    QTabBar::tab:hover:!selected { background-color: #444; }
                """)
                self.progress.setStyleSheet("""
                    QProgressBar { border: 1px solid #444; border-radius: 4px; text-align: center; background-color: #353535; color: #D4D4D4; font-weight: bold; }
                    QProgressBar::chunk { background-color: #49814D; border-radius: 3px; }
                """)
                self.gh_frame.setStyleSheet("#ghBox { background-color: #2b302b; border: 1px solid #445044; border-radius: 5px; }")
                
                yaml_theme_css = """
                    MainWin { background-color: #2D2D2D; } 
                    QLabel, QCheckBox, QRadioButton { color: #D4D4D4; background-color: transparent; }
                    
                    QTreeWidget { font-size: 14px; border: 1px solid #444; border-radius: 8px; background-color: #262626; outline: none; color: #D4D4D4; }
                    QTreeWidget::item { min-height: 42px; border-bottom: 1px solid #444; }
                    QTreeWidget::item:selected, QTreeWidget::item:focus { background-color: transparent; color: #fff; border: none; border-bottom: 1px solid #444; }
                    QHeaderView::section { background-color: #353535; color: #D4D4D4; font-size: 14px; font-weight: bold; padding: 10px; border: none; border-bottom: 1px solid #444; }
                    
                    QLineEdit, QComboBox, QPlainTextEdit {
                        background-color: transparent; border: 1px solid #49814D; border-radius: 4px; padding: 4px 8px;
                        color: #D4D4D4; selection-background-color: #61A165; selection-color: white;
                    }
                    QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover { border: 1px solid #61A165; }
                    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #61A165; background-color: rgba(97, 161, 101, 0.05); }
                    QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled { border: 1px solid #444; color: #777; }
                    
                    QComboBox::drop-down { border: none; width: 24px; }
                    QComboBox QAbstractItemView { background-color: #353535; color: #D4D4D4; selection-background-color: #61A165; selection-color: white; border: 1px solid #49814D; }
                    
                    QGroupBox { border: 1px solid #49814D; border-radius: 5px; margin-top: 15px; padding-top: 10px; background-color: transparent; }
                    QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 5px; color: #D4D4D4; font-weight: bold; }
                    
                    #leftNavFrame { border: 1px solid #444; border-radius: 6px; background-color: #2b2b2b; }
                    #leftNavTree { background-color: transparent; font-size: 13px; outline: none; selection-background-color: transparent; color: #D4D4D4; }
                    #leftNavTree::branch { background-color: transparent; }
                    #leftNavTree::item { padding: 8px 6px; border-radius: 4px; margin: 2px 4px; }
                    #leftNavTree::item:hover { background-color: rgba(97, 161, 101, 0.3); }
                    #leftNavTree::item:selected { background-color: #49814D; color: white; font-weight: bold; }
                    
                    #loadingPage { background-color: rgba(43, 43, 43, 0.95); border-radius: 8px; border: 1px solid #444; }
                """ + common_scrollbar_and_checkbox_css
                
                self.setStyleSheet(yaml_theme_css)

                # 联动 Windows 暗色标题栏
                import sys
                if sys.platform == 'win32':
                    try:
                        import ctypes
                        hwnd = int(self.winId())
                        rendering_mode = ctypes.c_int(1)
                        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(rendering_mode), ctypes.sizeof(rendering_mode))
                        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(rendering_mode), ctypes.sizeof(rendering_mode))
                    except Exception: pass

            else:
                # ==========================================
                #   亮色模式：手动锁死深灰字，防止系统白字干扰
                # ==========================================
                dark_gray = QColor(51, 51, 51)    # 高级深灰 #333
                bg_light = QColor(245, 245, 245)
                
                pal.setColor(QPalette.Window, bg_light)
                pal.setColor(QPalette.WindowText, dark_gray)
                pal.setColor(QPalette.Base, Qt.white)
                pal.setColor(QPalette.AlternateBase, bg_light)
                pal.setColor(QPalette.Text, dark_gray)
                pal.setColor(QPalette.Button, QColor(240, 240, 240))
                pal.setColor(QPalette.ButtonText, dark_gray)
                pal.setColor(QPalette.Highlight, QColor(97, 161, 101))
                pal.setColor(QPalette.HighlightedText, Qt.white)
                QApplication.setPalette(pal)
                
                self.tabs.setStyleSheet("""
                    QTabWidget::pane { border: 1px solid #A8C7AA; top: -1px; border-radius: 4px; }
                    QTabBar::tab { background-color: #F0F5F1; color: #333; border: 1px solid #A8C7AA; padding: 6px 16px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
                    QTabBar::tab:selected { background-color: #61A165; color: white; border: 1px solid #61A165; font-weight: bold; }
                    QTabBar::tab:hover:!selected { background-color: #E2ECE3; }
                """)
                self.progress.setStyleSheet("""
                    QProgressBar { border: 1px solid #A8C7AA; border-radius: 4px; text-align: center; background-color: #F0F5F1; color: #333; font-weight: bold; }
                    QProgressBar::chunk { background-color: #61A165; border-radius: 3px; }
                """)
                self.gh_frame.setStyleSheet("#ghBox { background-color: #F0F5F1; border: 1px solid #A8C7AA; border-radius: 5px; }")
                
                yaml_theme_css = """
                    MainWin { background-color: #F5F5F5; }
                    QLabel, QCheckBox, QRadioButton { color: #333; background-color: transparent; }
                    
                    QTreeWidget { font-size: 14px; border: 1px solid #E0E0E0; border-radius: 8px; background-color: white; outline: none; color: #333; }
                    QTreeWidget::item { min-height: 42px; border-bottom: 1px solid #F5F5F5; }
                    QTreeWidget::item:selected, QTreeWidget::item:focus { background-color: transparent; color: #333; border: none; border-bottom: 1px solid #F5F5F5; }
                    QHeaderView::section { background-color: #F0F5F1; color: #333; font-size: 14px; font-weight: bold; padding: 10px; border: none; border-bottom: 1px solid #C1D4C3; }
                    
                    QLineEdit, QComboBox, QPlainTextEdit {
                        background-color: transparent; border: 1px solid #A8C7AA; border-radius: 4px; padding: 4px 8px;
                        color: #333; selection-background-color: #61A165; selection-color: white;
                    }
                    QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover { border: 1px solid #61A165; }
                    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border: 1px solid #61A165; background-color: rgba(97, 161, 101, 0.05); }
                    QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled { border: 1px solid #ddd; color: #aaa; }
                    
                    QComboBox::drop-down { border: none; width: 24px; }
                    QComboBox QAbstractItemView { background-color: #FFFFFF; color: #333; selection-background-color: #E2ECE3; selection-color: #333; border: 1px solid #A8C7AA; }
                    
                    QGroupBox { border: 1px solid #61A165; border-radius: 5px; margin-top: 15px; padding-top: 10px; background-color: transparent; }
                    QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 5px; color: #333; font-weight: bold; }
                    
                    #leftNavFrame { border: 1px solid #61A165; border-radius: 6px; background-color: #F8FAF8; }
                    #leftNavTree { background-color: transparent; font-size: 13px; outline: none; selection-background-color: transparent; color: #333; }
                    #leftNavTree::branch { background-color: transparent; }
                    #leftNavTree::item { padding: 8px 6px; border-radius: 4px; margin: 2px 4px; }
                    #leftNavTree::item:hover { background-color: rgba(97, 161, 101, 0.1); }
                    #leftNavTree::item:selected { background-color: #61A165; color: white; font-weight: bold; }
                    
                    #loadingPage { background-color: rgba(240, 245, 241, 0.95); border-radius: 8px; border: 1px solid #C1D4C3; }
                """ + common_scrollbar_and_checkbox_css
                
                self.setStyleSheet(yaml_theme_css)

                # 联动 Windows 亮色标题栏
                import sys
                if sys.platform == 'win32':
                    try:
                        import ctypes
                        hwnd = int(self.winId())
                        rendering_mode = ctypes.c_int(0)
                        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(rendering_mode), ctypes.sizeof(rendering_mode))
                        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(rendering_mode), ctypes.sizeof(rendering_mode))
                    except Exception: pass

            self.settings.setValue('ui/dark', dark)

        finally:
            # 【收尾】：切完主题后恢复屏幕刷新，瞬间出图！
            self.setUpdatesEnabled(True)
    def show_about(self):
        links_html = "<br>".join([f'• <a href="{u}">{t}</a>' for t, u in GITHUB_LINKS]) or "（未配置链接）"
        dlg = QDialog(self)
        dlg.setWindowTitle("关于")
        lay = QVBoxLayout(dlg)
        title = QLabel("<b>Rime万象拼音词库工具</b>")
        title.setTextFormat(Qt.RichText)
        links = QLabel(f"开源地址：<br>{links_html}")
        links.setTextFormat(Qt.RichText)
        links.setOpenExternalLinks(True)
        lay.addWidget(title)
        lay.addWidget(links)
        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        lay.addWidget(btns)
        dlg.exec()

    def pick_any(self, target: QLineEdit, allow_dir: bool, is_output: bool = False):
        if allow_dir:
            box = QMessageBox(self)
            box.setWindowTitle("选择类型")
            box.setText("请选择类型：")
            btn_file = box.addButton("选文件…", QMessageBox.AcceptRole)
            btn_dir  = box.addButton("选目录…", QMessageBox.AcceptRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is btn_file:
                if is_output:
                    default = os.path.basename(target.text()) if target.text() else "output.txt"
                    f = self.get_save_file("选择输出文件", default, "词表 (*.txt *.yaml *.yml);;全部 (*)")
                else:
                    f = self.get_open_file("选择文件", "词表 (*.txt *.yaml *.yml);;全部 (*)")
                if f: target.setText(f)
            elif clicked is btn_dir:
                d = self.get_existing_directory("选择目录")
                if d: target.setText(d)
            return
        
        if is_output:
            default = os.path.basename(target.text()) if target.text() else "output.txt"
            f = self.get_save_file("选择输出文件", default, "词表 (*.txt *.yaml *.yml);;全部 (*)")
        else:
            f = self.get_open_file("选择文件", "词表 (*.txt *.yaml *.yml);;全部 (*)")
        if f: target.setText(f)

    def pick_output(self, target: QLineEdit):
        self.pick_any(target, allow_dir=True, is_output=True)

    def pick_dir(self, target: QLineEdit):
        d = self.get_existing_directory("选择目录")
        if d: target.setText(d)

    def pick_file(self, target: QLineEdit):
        f = self.get_open_file("选择辅助码文件", "Text/YAML (*.txt *.yaml *.yml);;全部 (*)")
        if f: target.setText(f)

    def export_log(self):
        fn = self.get_save_file("导出日志", "log.txt", "Text (*.txt);;All files (*)")
        if not fn: return
        try:
            with open(fn, 'w', encoding='utf-8') as f: f.write(self.log.toPlainText())
            QMessageBox.information(self, "成功", f"已导出到：{fn}")
        except Exception as e:
            QMessageBox.critical(self, "失败", f"导出失败：{e}")

    def run_job(self):
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning(): return
        cur = self.tabs.currentIndex()
        args = None
        
        # 1. 收集参数
        if cur == 1: # 刷拼音
            args = JobArgs(op=1, in_path=self.in_edit_py.text().strip(), out_path=self.out_edit_py.text().strip(),
                           custom_dir=self.custom_dir_edit.text().strip() or None,
                           skip_set={x.strip() for x in self.skip_edit.toPlainText().splitlines() if x.strip()} if os.path.isdir(self.in_edit_py.text()) else set(DEFAULT_SKIP_SET),
                           ignore_non_chinese=self.ignore_non_chinese_cb_py.isChecked(), py_sep=self.py_sep_edit.text() or " ")
        elif cur == 2: # 刷辅助码
            if not self.aux_file_edit.text(): QMessageBox.warning(self, "提示", "请选择辅助码文件"); return
            args = JobArgs(op=2, in_path=self.in_edit_aux.text().strip(), out_path=self.out_edit_aux.text().strip(),
                           aux_file=self.aux_file_edit.text().strip(), ignore_non_chinese=self.ignore_non_chinese_cb_aux.isChecked())
        elif cur == 3: # 双拼转换
            sp_keys = list(SHUANGPIN_SCHEMAS.keys())
            sel_id = self.bg_sp.checkedId()
            if sel_id < 0 or sel_id >= len(sp_keys): return
            sp_key = sp_keys[sel_id]
            
            in_p = self.in_edit_sp.text().strip()
            out_p = self.out_edit_sp.text().strip()
            
            in_s = self.sp_in_sep_edit.text()
            out_s = self.sp_out_sep_edit.text()
            is_jianma = self.sp_jianma_cb.isChecked()
            
            args = JobArgs(op=3, in_path=in_p, out_path=out_p, py_sep=in_s, sp_out_sep=out_s, sp_schema=sp_key, sp_is_jianma=is_jianma)

        if not args: return
        try:
            abs_in = os.path.abspath(args.in_path)
            abs_out = os.path.abspath(args.out_path)
            if os.path.isfile(abs_in) and os.path.isdir(abs_out):
                abs_out = os.path.join(abs_out, os.path.basename(abs_in))
            if abs_in == abs_out:
                box = QMessageBox(self)
                box.setWindowTitle("⚠️ 覆盖警告")
                box.setText(f"输入路径与输出路径相同：\n{abs_in}\n\n该操作将直接覆盖源文件。\n是否继续？")
                box.setIcon(QMessageBox.Warning)
                yes_btn = box.addButton("是(Y)", QMessageBox.AcceptRole)
                box.addButton("否(N)", QMessageBox.RejectRole)
                box.setDefaultButton(yes_btn)
                box.exec()
                if box.clickedButton() != yes_btn:
                    return
        except Exception:
            pass 
        self.worker = Worker(args)
        self.worker.log_sig.connect(self.log.appendPlainText)
        self.worker.progress_sig.connect(lambda c, t: (self.progress.setValue(int(c*100/max(t,1))), self.status.setText(f"进度: {c}/{t}")))
        self.worker.done_sig.connect(lambda ok, msg, s: (self.btn_run.setEnabled(True), self.btn_stop.setEnabled(False), self.log.appendPlainText(msg)))
        
        self.btn_run.setEnabled(False); self.btn_stop.setEnabled(True)
        self.log.appendPlainText(f"开始任务: {'双拼编码转换' if cur==3 else '处理'}")
        self.log.appendPlainText(f"输入：{args.in_path}")
        self.log.appendPlainText(f"输出：{args.out_path}")
        self.save_settings()
        self.worker.start()
    def stop_job(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log.appendPlainText("正在请求停止…"); self.status.setText("正在停止…"); self.btn_stop.setEnabled(False)

    def on_progress(self, cur: int, total: int):
        pct = int(cur * 100 / max(total, 1))
        self.progress.setValue(pct); self.status.setText(f"进度：{cur}/{total}（{pct}%）")

    def on_done(self, ok: bool, msg: str, stats: dict):
        self.btn_run.setEnabled(True); self.btn_stop.setEnabled(False)
        self.status.setText("完成" if ok else "失败")
        if stats:
            self.log.appendPlainText("—" * 40 + "\n统计摘要：")
            self.log.appendPlainText(f"  文件总数：{stats.get('total_files', 0)}\n  发生改动：{stats.get('files_changed', 0)}")
            self.log.appendPlainText("—" * 40)
        self.log.appendPlainText(msg)

    def save_settings(self):
        s = self.settings
        s.setValue('py/ignore_non_chinese', self.ignore_non_chinese_cb_py.isChecked())
        s.setValue('aux/ignore_non_chinese', self.ignore_non_chinese_cb_aux.isChecked())
        s.setValue('py/in', self.in_edit_py.text().strip())
        s.setValue('py/out', self.out_edit_py.text().strip())
        s.setValue('py/custom', self.custom_dir_edit.text().strip())
        s.setValue('py/skip', self.skip_edit.toPlainText())
        s.setValue('aux/in', self.in_edit_aux.text().strip())
        s.setValue('aux/out', self.out_edit_aux.text().strip())
        s.setValue('aux/file', self.aux_file_edit.text().strip())
        s.setValue('ui/dark', self.act_dark.isChecked())
        s.setValue('sp/in_sep', self.sp_in_sep_edit.text())
        s.setValue('sp/out_sep', self.sp_out_sep_edit.text())
        s.setValue('sp/schema', self.bg_sp.checkedId())
        s.setValue('sp/in', self.in_edit_sp.text().strip())
        s.setValue('sp/out', self.out_edit_sp.text().strip())
        s.setValue('sp/is_jianma', self.sp_jianma_cb.isChecked())
        try:
            s.setValue('upd/source_type', self.bg_source_type.checkedId()) # 保存源类型
            s.setValue('upd/custom_url', self.custom_url_input.text())     # 保存自定义URL
            s.setValue('upd/scope', self.bg_scope.checkedId())
            s.setValue('upd/ver', self.bg_ver.checkedId())
            s.setValue('upd/aux_index', self.combo_aux.currentIndex())
            s.setValue('upd/rime', self.upd_rime.text())
            s.setValue('upd/token', self.upd_token.text())
            s.setValue('upd/github_route', self.bg_gh_route.checkedId())
            s.setValue('upd/proxy_slow_fallback', self.chk_proxy_slow_fallback.isChecked())
            s.setValue('upd/proxy_min_speed_kbps', int(self.combo_proxy_min_speed.currentData() or 128))
            s.setValue('upd/whitelist', self.upd_wl_edit.toPlainText()) 
            s.setValue('upd/clean', self.chk_clean.isChecked())
            s.setValue('upd/clean_build', self.chk_clean_build.isChecked()) # 保存清理build选项
        except Exception as e: print(f"保存配置出错: {e}")

    def restore_settings(self):
        s = self.settings
        self.ignore_non_chinese_cb_py.setChecked(s.value('py/ignore_non_chinese', True, bool))
        self.ignore_non_chinese_cb_aux.setChecked(s.value('aux/ignore_non_chinese', True, bool))
        self.in_edit_py.setText(s.value('py/in', ''))
        self.out_edit_py.setText(s.value('py/out', ''))
        self.custom_dir_edit.setText(s.value('py/custom', ''))
        default_skip = "\n".join(sorted(DEFAULT_SKIP_SET))
        self.skip_edit.setPlainText(s.value('py/skip', default_skip))
        self.in_edit_aux.setText(s.value('aux/in', ''))
        self.out_edit_aux.setText(s.value('aux/out', ''))
        self.aux_file_edit.setText(s.value('aux/file', ''))
        self.sp_in_sep_edit.setText(s.value('sp/in_sep', ' '))
        self.sp_out_sep_edit.setText(s.value('sp/out_sep', ' '))
        self.in_edit_sp.setText(s.value('sp/in', ''))
        self.out_edit_sp.setText(s.value('sp/out', ''))
        self.sp_jianma_cb.setChecked(s.value('sp/is_jianma', False, bool))
        sp_id = int(s.value('sp/schema', 0))
        if self.bg_sp.button(sp_id):
            self.bg_sp.button(sp_id).setChecked(True)
        try:
            src_type = int(s.value('upd/source_type', 0))
            if self.bg_source_type.button(src_type):
                self.bg_source_type.button(src_type).setChecked(True)
            self.custom_url_input.setText(s.value('upd/custom_url', ''))
            scope_id = int(s.value('upd/scope', 0))
            self.bg_scope.button(scope_id).setChecked(True)
            ver_id = int(s.value('upd/ver', 0))
            self.bg_ver.button(ver_id).setChecked(True)
            aux_idx = int(s.value('upd/aux_index', 0)) 
            if aux_idx >= 0 and aux_idx < self.combo_aux.count():
                self.combo_aux.setCurrentIndex(aux_idx)
            saved_rime = s.value('upd/rime', '').strip()
            if saved_rime:
                self.upd_rime.setText(saved_rime)
            else:
                det = PathDetector.detect()
                if det['rime_user_dir']:
                    self.upd_rime.setText(det['rime_user_dir'])
                    self.detected_server = det.get('weasel_server', '')
                    self.detected_deployer = det.get('weasel_deployer', '')
            self.upd_token.setText(s.value('upd/token', ''))
            route_id = int(s.value('upd/github_route', 0))
            if self.bg_gh_route.button(route_id): self.bg_gh_route.button(route_id).setChecked(True)

            self.chk_proxy_slow_fallback.setChecked(s.value('upd/proxy_slow_fallback', True, bool))
            saved_min_speed = int(s.value('upd/proxy_min_speed_kbps', 128))
            speed_index = self.combo_proxy_min_speed.findData(saved_min_speed)
            self.combo_proxy_min_speed.setCurrentIndex(speed_index if speed_index >= 0 else 1)
            self.combo_proxy_min_speed.setEnabled(self.chk_proxy_slow_fallback.isChecked())

            self.rb_src_gh.setChecked(True)
            wl = s.value('upd/whitelist', "")
            if wl: self.upd_wl_edit.setPlainText(wl)
            self.chk_clean.setChecked(s.value('upd/clean', False, bool))
            self.chk_clean_build.setChecked(s.value('upd/clean_build', False, bool))
            self.bg_source_type.idClicked.emit(src_type)
            self.bg_source_type.idClicked.emit(src_type)
            self.bg_scope.idClicked.emit(scope_id)
            is_pro = (self.bg_ver.checkedId() == 0)
            is_mod_only = (scope_id == 3) 
            self.combo_aux.setEnabled(is_pro and not is_mod_only)

        except Exception as e: print(f"恢复配置出错: {e}")

    def reset_settings(self):
        """全面恢复默认配置 (最终版)"""
        # 1. 确认操作
        ret = QMessageBox.question(self, "确认重置", 
                                   "确定要恢复默认配置吗？\n\n这将清空所有保存的路径、选项、Token和自定义规则，并重新检测Rime目录。", 
                                   QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes: return
        self.settings.clear()
        for route_id in [rid for rid in list(GITHUB_ROUTES) if rid >= 100]:
            button = self.route_buttons.pop(route_id, None)

            if button:
                self.bg_gh_route.removeButton(button)
                self.route_grid.removeWidget(button)
                button.deleteLater()

            del GITHUB_ROUTES[route_id]
        # UI复位
        self.ignore_non_chinese_cb_py.setChecked(True)
        self.in_edit_py.clear()
        self.out_edit_py.clear()
        self.custom_dir_edit.clear()
        self.py_sep_edit.setText(" ")
        self.skip_edit.setPlainText("\n".join(sorted(DEFAULT_SKIP_SET)))
        self._toggle_skip_box()
        self.ignore_non_chinese_cb_aux.setChecked(True)
        self.in_edit_aux.clear()
        self.out_edit_aux.clear()
        self.aux_file_edit.clear()
        if self.bg_sp.button(0): self.bg_sp.button(0).setChecked(True) 
        self.sp_in_sep_edit.setText(" ")
        self.sp_out_sep_edit.setText(" ")
        self.sp_jianma_cb.setChecked(False)
        self.in_edit_sp.clear()
        self.out_edit_sp.clear()
        self.bg_source_type.button(0).setChecked(True) 
        self.custom_url_input.clear()
        self.bg_scope.button(0).setChecked(True) 
        self.bg_ver.button(0).setChecked(True) 
        self.combo_aux.setCurrentIndex(0) 
        self.rb_src_gh.setChecked(True)
        self.upd_token.clear()
        self.bg_gh_route.button(0).setChecked(True)
        self.chk_proxy_slow_fallback.setChecked(True)
        self.combo_proxy_min_speed.setCurrentIndex(1)
        self.combo_proxy_min_speed.setEnabled(True)
        for route_id, button in self.route_buttons.items():
            button.setText(GITHUB_ROUTES[route_id]["name"])
            self._set_route_button_style(button, "#8A8A8A")
        self.upd_wl_edit.setPlainText("\n".join(DEFAULT_WL_REGEX))
        # 复位勾选框
        self.chk_clean_build.setChecked(False)
        self.chk_clean.setChecked(False)
        self.chk_force.setChecked(False) # 即使隐藏了也要复位
        self.chk_force.setEnabled(True) 
        self.chk_force.setChecked(False)
        self.bg_source_type.idClicked.emit(0) # 触发隐藏自定义URL输入框
        self.bg_scope.idClicked.emit(0)       # 触发全量模式逻辑
        self.bg_ver.idClicked.emit(0)         # 触发Pro版逻辑(启用辅助码选择)

        # ==================== 全局状态复位 ====================
        if self.act_dark.isChecked():
            self.act_dark.setChecked(False)
        det = PathDetector.detect()
        if det['rime_user_dir']:
            self.upd_rime.setText(det['rime_user_dir'])
            self.upd_rime.setStyleSheet("")
            self.detected_server = det.get('weasel_server', '')
            self.detected_deployer = det.get('weasel_deployer', '')
        else:
            self.upd_rime.clear()
            self.upd_rime.setPlaceholderText("未能自动检测到路径")

        # 3. 完成提示
        self.log.clear()
        self.log.appendPlainText(">>> ✅ 已成功恢复默认配置")
        QMessageBox.information(self, "成功", "所有设置已恢复默认，路径已尝试重新检测。")
    def closeEvent(self, event):
        """窗口关闭事件：拦截退出，保存配置，并执行极速强退"""
        self.status.setText("正在保存配置并退出...")
        # 1. 保存用户配置
        try:
            self.save_settings()
        except:
            pass

        # 2. 通知所有正在运行的后台线程立刻停止
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(500)  # 最多等0.5秒
            
        if self.upd_worker and self.upd_worker.isRunning():
            self.upd_worker.stop()
            self.upd_worker.wait(500)
            
        if self.cache_worker and self.cache_worker.isRunning():
            self.cache_worker._stop = True
            self.cache_worker.wait(500)
        event.accept()
        import os
        os._exit(0)
def main():
    app = QApplication(sys.argv)
    trans = QTranslator()
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)

    if trans.load("qt_zh_CN", path):
        app.installTranslator(trans)
    elif trans.load("qtbase_zh_CN", path):
        app.installTranslator(trans)

    w = MainWin()
    w.show()

    QTimer.singleShot(800, w.start_github_route_test)

    sys.exit(app.exec())
if __name__ == '__main__':
    main()