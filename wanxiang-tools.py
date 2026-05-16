#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
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
from PySide6.QtCore import Qt, QThread, Signal, QSettings, QTranslator, QLibraryInfo
from PySide6.QtGui  import QPalette, QColor, QAction
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QTabWidget, QCheckBox,
    QPlainTextEdit, QProgressBar, QLabel, QMessageBox, QGroupBox,
    QStyleFactory, QMenuBar, QDialog, QDialogButtonBox,
    QRadioButton, QButtonGroup, QComboBox, QGridLayout, QFrame, QSpinBox
)

# ============== 常量/工具 ==============
TOOL_VERSION = "v3.0.3beta"

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
class DynamicInputWidget(QWidget):
    """跨列协同：输入框部分 - 视觉大一统版"""
    hover_in = Signal()
    hover_out = Signal()
    value_changed = Signal(str)

    def __init__(self, initial_value="", placeholder=""):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 4, 0)
        self.layout.setAlignment(Qt.AlignVCenter) # 垂直居中，不乱跑
        
        self.input_field = QLineEdit(initial_value)
        self.input_field.setPlaceholderText(placeholder)
        
        self._hover_active = False 
        self._is_updating = False 
        
        # 【视觉核心】：全局统一标准
        self.normal_style = ""
        self.hover_style = ""
        
        self.input_field.setStyleSheet(self.normal_style)
        self.input_field.setFixedHeight(34) # 锁死单行高度
        self.input_field.textChanged.connect(self.value_changed.emit)
        
        self.layout.addWidget(self.input_field)

    def set_hover_state(self, hovered):
        if self._hover_active == hovered: return
        self._is_updating = True
        self._hover_active = hovered
        if hovered:
            self.input_field.setStyleSheet(self.hover_style)
        else:
            if not self.input_field.hasFocus():
                self.input_field.setStyleSheet(self.normal_style)
        self._is_updating = False

    def enterEvent(self, event):
        if not getattr(self, '_is_updating', False):
            self.hover_in.emit()
            self.set_hover_state(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not getattr(self, '_is_updating', False):
            self.hover_out.emit()
            self.set_hover_state(False)
        super().leaveEvent(event)
        
    def get_value(self):
        return self.input_field.text().strip()


class DynamicActionWidget(QWidget):
    """跨列协同：操作按钮部分 - 对齐抗抖版"""
    add_requested = Signal()
    move_up_requested = Signal()
    move_down_requested = Signal()
    delete_requested = Signal()
    hover_in = Signal()
    hover_out = Signal()

    def __init__(self, desc_text=""):
        super().__init__()
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 5, 8, 0) 
        self.layout.setSpacing(4)
        self.layout.setAlignment(Qt.AlignTop) 
        
        self.btn_add = QPushButton("➕")
        self.btn_up = QPushButton("⬆️")
        self.btn_down = QPushButton("⬇️")
        self.btn_del = QPushButton("❌")
        
        from PySide6.QtWidgets import QSizePolicy
        
        for btn in [self.btn_add, self.btn_up, self.btn_down, self.btn_del]:
            btn.setFixedSize(24, 24)
            btn.setCursor(Qt.PointingHandCursor)
            sp = btn.sizePolicy()
            sp.setRetainSizeWhenHidden(True) 
            btn.setSizePolicy(sp)
            self.layout.addWidget(btn)
            btn.hide() 
            
        self.btn_add.clicked.connect(lambda *args: self.add_requested.emit())
        self.btn_up.clicked.connect(lambda *args: self.move_up_requested.emit())
        self.btn_down.clicked.connect(lambda *args: self.move_down_requested.emit())
        self.btn_del.clicked.connect(lambda *args: self.delete_requested.emit())
        
        self.desc_label = QLabel(desc_text)
        self.desc_label.setStyleSheet("font-size: 13px; padding-top: 3px;")
        self.layout.addWidget(self.desc_label, stretch=1)
        
        self._buttons_visible = False
        self._is_updating = False 
        
    def show_buttons(self):
        if self._buttons_visible: return
        self._is_updating = True
        self._buttons_visible = True
        self.btn_add.show(); self.btn_up.show(); self.btn_down.show(); self.btn_del.show()
        self._is_updating = False
        
    def hide_buttons(self):
        if not self._buttons_visible: return
        self._is_updating = True
        self._buttons_visible = False
        self.btn_add.hide(); self.btn_up.hide(); self.btn_down.hide(); self.btn_del.hide()
        self._is_updating = False

    def enterEvent(self, event):
        if not getattr(self, '_is_updating', False):
            self.hover_in.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not getattr(self, '_is_updating', False):
            self.hover_out.emit()
        super().leaveEvent(event)


class DynamicKeyValueWidget(QWidget):
    """跨列协同：字典组件 - 动态行高 + 包裹式对齐 + 视觉一统版 + 智能下拉解析"""
    hover_in = Signal()
    hover_out = Signal()
    value_changed = Signal(str)
    key_changed = Signal(str)
    needs_resize = Signal(int)

    def __init__(self, initial_key="", initial_val="", preset_keys=None):
        super().__init__()
        self.preset_keys = preset_keys or {}
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 4, 0)
        self.layout.setSpacing(6)
        self.layout.setAlignment(Qt.AlignTop) 
        
        from PySide6.QtWidgets import QComboBox, QLineEdit, QLabel, QSizePolicy, QStackedWidget, QPlainTextEdit, QVBoxLayout
        
        self.key_box = QComboBox()
        self.key_box.setEditable(False) 
        self.key_box.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.key_box.setMinimumWidth(150)
        self.key_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.key_box.setFixedHeight(34) 
        
        self.key_box.addItem("--- 请选择参数 ---", "")
        for k, desc in self.preset_keys.items():
            self.key_box.addItem(f"{k} ({desc})", k)
        
        self.val_stack = QStackedWidget()
        self.val_stack.setMinimumWidth(120)
        
        self.val_line = QLineEdit()
        self.val_line.setFixedHeight(34)
        
        self.val_bool = QComboBox()
        self.val_bool.addItems(["", "true", "false"])
        self.val_bool.setFixedHeight(34)
        
        self.val_text = QPlainTextEdit() 
        self.val_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff) 
        
        self.val_select = QComboBox()
        self.val_select.setFixedHeight(34)

        self.val_stack.addWidget(self.val_line)   # index 0
        self.val_stack.addWidget(self.val_bool)   # index 1
        self.val_stack.addWidget(self.val_text)   # index 2
        self.val_stack.addWidget(self.val_select) # index 3
        
        self._hover_active = False
        self._is_updating = False 
        
        self.style_single = ""
        self.style_single_hover = ""
        
        self.style_multi = ""
        self.style_multi_hover = ""
        
        self.key_box.setStyleSheet(self.style_single)
        self.val_line.setStyleSheet(self.style_single)
        self.val_bool.setStyleSheet(self.style_single)
        self.val_text.setStyleSheet(self.style_multi)
        self.val_select.setStyleSheet(self.style_single) 
        
        self.layout.addWidget(self.key_box, stretch=5)
        lbl = QLabel(":")
        lbl.setStyleSheet("padding-top: 8px;") 
        self.layout.addWidget(lbl)
        self.layout.addWidget(self.val_stack, stretch=6)

        def adjust_text_height():
            if self.val_stack.currentIndex() == 2:
                text = self.val_text.toPlainText()
                lines = text.count('\n') + 1 
                fm = self.val_text.fontMetrics()
                line_height = fm.lineSpacing()
                
                new_h = (lines * line_height) + 24
                new_h = max(38, min(new_h, 400)) 
                
                if self.val_text.height() != new_h:
                    self.val_text.setFixedHeight(new_h)
                    self.val_stack.setFixedHeight(new_h)
                    self.setFixedHeight(new_h)
                    self.needs_resize.emit(new_h) 

        self.val_text.textChanged.connect(adjust_text_height)

        self._temp_key = initial_key
        self._is_loading = True
        self.set_key_value(initial_key, initial_val)
        self._is_loading = False
        
        self.val_line.textChanged.connect(self.value_changed.emit)
        self.val_bool.currentTextChanged.connect(self.value_changed.emit)
        self.val_text.textChanged.connect(lambda: self.value_changed.emit(""))
        self.val_select.currentTextChanged.connect(self.value_changed.emit)
        self.key_box.currentIndexChanged.connect(self._on_index_changed)

    def _on_index_changed(self, idx):
        k = self.get_key()
        desc = self.preset_keys.get(k, "")
        
        is_bool = "(true/false)" in desc.lower()
        is_list = "填列表" in desc or "数组" in desc
        is_num = "数字" in desc
        
        import re
        m = re.search(r'\(([a-zA-Z0-9_]+(?:/[a-zA-Z0-9_]+)+)\)', desc)
        select_opts = m.group(1).split('/') if m else []
        
        if is_bool: new_idx = 1
        elif is_list: new_idx = 2
        elif select_opts: 
            new_idx = 3
            self.val_select.blockSignals(True)
            self.val_select.clear()
            self.val_select.addItems(select_opts)
            self.val_select.blockSignals(False)
        else: new_idx = 0
        
        self.val_stack.setCurrentIndex(new_idx)
        
        from PySide6.QtWidgets import QSizePolicy
        for i in range(self.val_stack.count()):
            w = self.val_stack.widget(i)
            if i == new_idx:
                w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                w.show()
            else:
                w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
                w.hide()
                
        if new_idx in [0, 1, 3]:
            self.val_stack.setFixedHeight(34)
            self.val_line.setFixedHeight(34)
            self.val_bool.setFixedHeight(34)
            self.val_select.setFixedHeight(34)
            self.setFixedHeight(34)
            self.needs_resize.emit(34) 
        else:
            text = self.val_text.toPlainText()
            lines = text.count('\n') + 1 
            fm = self.val_text.fontMetrics()
            new_h = max(38, (lines * fm.lineSpacing()) + 24)
            self.val_stack.setFixedHeight(new_h)
            self.val_text.setFixedHeight(new_h)
            self.setFixedHeight(new_h)
            self.needs_resize.emit(new_h)
        
        if not self._is_loading:
            self.val_line.clear()
            self.val_bool.setCurrentIndex(0)
            self.val_text.clear()
            if select_opts: self.val_select.setCurrentIndex(0)
        
        if new_idx == 0:
            if is_num: self.val_line.setPlaceholderText("填入纯数字...")
            else: self.val_line.setPlaceholderText("填入值...")
        elif new_idx == 2:
            self.val_text.setPlaceholderText("无需写 '-'，回车换行即可\n如: user")
            
        self.key_changed.emit(k)

    def set_key_value(self, k, v):
        self.key_box.blockSignals(True)
        if k:
            idx = self.key_box.findData(k)
            if idx >= 0: self.key_box.setCurrentIndex(idx)
        else:
            self.key_box.setCurrentIndex(0)
        self.key_box.blockSignals(False)
        
        self._on_index_changed(self.key_box.currentIndex())
        
        if isinstance(v, dict) and len(v) == 1 and list(v.values())[0] is None:
            v = f"{{{list(v.keys())[0]}}}"
            
        if isinstance(v, bool):
            v_str = "true" if v else "false"
        else:
            v_str = str(v) if v is not None else ""
        
        if self.val_stack.currentIndex() == 1:
            if v_str in ["true", "false"]:
                self.val_bool.setCurrentText(v_str)
        elif self.val_stack.currentIndex() == 2:
            if isinstance(v, list):
                clean_list = ["true" if isinstance(x, bool) and x else "false" if isinstance(x, bool) else str(x) for x in v]
                self.val_text.setPlainText("\n".join(clean_list))
            else:
                self.val_text.setPlainText(v_str)
        elif self.val_stack.currentIndex() == 3:
            self.val_select.setCurrentText(v_str)
        else:
            self.val_line.setText(v_str)

    def get_key(self):
        return self.key_box.currentData()

    def get_key_value(self):
        k = self.get_key()
        if self.val_stack.currentIndex() == 1:
            v = self.val_bool.currentText().strip()
        elif self.val_stack.currentIndex() == 2:
            v = self.val_text.toPlainText().strip()
        elif self.val_stack.currentIndex() == 3:
            v = self.val_select.currentText().strip()
        else:
            v = self.val_line.text().strip()
        return k, v

    def set_hover_state(self, hovered):
        if self._hover_active == hovered: return
        self._is_updating = True
        self._hover_active = hovered
        if hovered:
            self.key_box.setStyleSheet(self.style_single_hover)
            self.val_line.setStyleSheet(self.style_single_hover)
            self.val_bool.setStyleSheet(self.style_single_hover)
            self.val_text.setStyleSheet(self.style_multi_hover)
            self.val_select.setStyleSheet(self.style_single_hover)
        else:
            if not self.key_box.hasFocus() and not self.key_box.view().isVisible(): 
                self.key_box.setStyleSheet(self.style_single)
            if not self.val_line.hasFocus(): 
                self.val_line.setStyleSheet(self.style_single)
            if not self.val_bool.hasFocus() and not self.val_bool.view().isVisible():
                self.val_bool.setStyleSheet(self.style_single)
            if not self.val_select.hasFocus() and not self.val_select.view().isVisible():
                self.val_select.setStyleSheet(self.style_single)
            if not self.val_text.hasFocus():
                self.val_text.setStyleSheet(self.style_multi)
        self._is_updating = False

    def enterEvent(self, event):
        if not getattr(self, '_is_updating', False):
            self.hover_in.emit()
            self.set_hover_state(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not getattr(self, '_is_updating', False):
            self.hover_out.emit()
            self.set_hover_state(False)
        super().leaveEvent(event)
class AlgebraPatchWidget(QWidget):
    """专为 Rime speller/algebra/__patch 打造的智能挂载器 (支持细分模糊音与只读冻结)"""
    needs_resize = Signal(int)
    
    def __init__(self, initial_val=None, is_pro=False, is_direct=False):
        super().__init__()
        self.is_pro = is_pro
        self.is_direct = is_direct
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 2, 0, 2)
        self.layout.setSpacing(6)
        
        # ⚠️ 直写警告标签 (默认创建，通过 set_direct_mode 控制显隐)
        self.warn_lbl = QLabel("⚠️ 保护机制：核心规则仅允许在【补丁模式】下编辑。")
        self.warn_lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 12px;")
        self.layout.addWidget(self.warn_lbl)
            
        # --- 1. 方案 & 辅助 ---
        h1 = QHBoxLayout()
        self.cb_scheme = QComboBox()
        self.cb_scheme.addItems(["全拼", "自然码", "小鹤双拼", "搜狗双拼", "微软双拼", "智能ABC", "紫光双拼", "国标双拼"])
        self.cb_scheme.setFixedHeight(34)
        
        self.cb_aux = QComboBox()
        self.cb_aux.addItems(["直接辅助", "间接辅助"])
        self.cb_aux.setFixedHeight(34)
        
        h1.addWidget(QLabel("🔤 拼写方案:"), 0); h1.addWidget(self.cb_scheme, 1)
        h1.addWidget(QLabel("  ⌨️ 辅助模式:"), 0); h1.addWidget(self.cb_aux, 1)
        self.layout.addLayout(h1)
        
        # --- 2. 提权 ---
        self.chk_tiquan = QCheckBox("🚀 四码唯一字提权 (限自然/小鹤)")
        self.layout.addWidget(self.chk_tiquan)
        
        # --- 3. 细分模糊音 (网格紧凑布局) ---
        gb_mohu = QGroupBox("☁️ 模糊音")
        gl = QGridLayout(gb_mohu)
        gl.setContentsMargins(10, 15, 10, 5)
        gl.setVerticalSpacing(2)
        
        self.fuzzy_map = {
            "n / l": "wanxiang_algebra:/模糊音_nl",
            "r / y": "wanxiang_algebra:/模糊音_ry",
            "h / f": "wanxiang_algebra:/模糊音_hf",
            "r / l": "wanxiang_algebra:/模糊音_rl",
            "k / g": "wanxiang_algebra:/模糊音_kg",
            "en / eng": "wanxiang_algebra:/模糊音_en_eng",
            "in / ing": "wanxiang_algebra:/模糊音_in_ing",
            "c / ch": "wanxiang_algebra:/模糊音_c_ch",
            "z / zh": "wanxiang_algebra:/模糊音_z_zh",
            "s / sh": "wanxiang_algebra:/模糊音_s_sh"
        }
        self.fuzzy_checks = {}
        for i, (name, path) in enumerate(self.fuzzy_map.items()):
            cb = QCheckBox(name)
            self.fuzzy_checks[path] = cb
            gl.addWidget(cb, i // 5, i % 5)
        self.layout.addWidget(gb_mohu)
        
        # --- 4. 附加挂载项 ---
        h3 = QHBoxLayout()
        lbl3 = QLabel("🧩 附加补丁:")
        lbl3.setAlignment(Qt.AlignTop)
        self.ext_edit = QPlainTextEdit()
        self.ext_edit.setFixedHeight(50)
        h3.addWidget(lbl3)
        h3.addWidget(self.ext_edit, 1)
        self.layout.addLayout(h3)
        
        # 信号连接
        self.cb_scheme.currentTextChanged.connect(self._on_scheme_changed)
        self.cb_scheme.currentTextChanged.connect(self._emit_resize)
        self.cb_aux.currentTextChanged.connect(self._emit_resize)
        self.ext_edit.textChanged.connect(self._emit_resize)
        
        # 核心：先应用冻结状态及样式，再填入初值！
        self.set_direct_mode(is_direct)
        self.set_value(initial_val)

    def set_direct_mode(self, is_direct):
        """核心控制：动态切换直写/补丁模式下的禁用与置灰状态"""
        self.is_direct = is_direct
        self.warn_lbl.setVisible(is_direct)
        
        style_cb = ""
        style_cb_disabled = ""
        
        # 拼写方案：如果在直写模式则置灰不可用
        self.cb_scheme.setEnabled(not is_direct)
        self.cb_scheme.setStyleSheet(style_cb if not is_direct else style_cb_disabled)
        is_aux_enabled = self.is_pro and not is_direct
        self.cb_aux.setEnabled(is_aux_enabled)
        self.cb_aux.setStyleSheet(style_cb if is_aux_enabled else style_cb_disabled)
        
        if not self.is_pro:
            self.cb_aux.setToolTip("⚠️ Base 基础版固定默认模式，无间接辅助")
        else:
            self.cb_aux.setToolTip("")
            
        # 其他控件跟随 is_direct 状态
        self.chk_tiquan.setStyleSheet("font-weight: bold;")
        if is_direct:
            self.chk_tiquan.setEnabled(False)
        else:
            self._on_scheme_changed(self.cb_scheme.currentText()) 
            
        for cb in self.fuzzy_checks.values():
            cb.setEnabled(not is_direct)
            cb.setStyleSheet("")
            
        self.ext_edit.setReadOnly(is_direct)
        self.ext_edit.setPlaceholderText("自定义扩展，回车换行，无需写 -" if not is_direct else "只读展示")

    def _on_scheme_changed(self, text):
        if self.is_direct: 
            return # 直写模式下，强制锁定，无视方案变更
            
        if text in ["自然码", "小鹤双拼"]:
            self.chk_tiquan.setEnabled(True)
        else:
            self.chk_tiquan.setEnabled(False)
            self.chk_tiquan.setChecked(False)

    def _emit_resize(self):
        lines = self.ext_edit.toPlainText().count('\n') + 1
        fm = self.ext_edit.fontMetrics()
        ext_h = max(50, lines * fm.lineSpacing() + 16)
        if self.ext_edit.height() != ext_h:
            self.ext_edit.setFixedHeight(ext_h)
            self.needs_resize.emit(220 + ext_h)
            
    def set_value(self, val_list):
        if not val_list or not isinstance(val_list, list): val_list = []
        other_patches = []
        scheme_found = aux_found = tiquan_found = False
        
        for item in val_list:
            item_str = str(item).strip()
            if item_str in self.fuzzy_checks:
                self.fuzzy_checks[item_str].setChecked(True)
                continue
                
            if "wanxiang_algebra:/" in item_str:
                name = item_str.split("/")[-1].strip()
                if name in ["直接辅助", "间接辅助"]:
                    self.cb_aux.setCurrentText(name); aux_found = True; continue
                elif name in ["全拼", "自然码", "小鹤双拼", "搜狗双拼", "微软双拼", "智能ABC", "紫光双拼", "国标双拼"]:
                    self.cb_scheme.setCurrentText(name); scheme_found = True; continue
                elif name in ["自然码提权", "小鹤双拼提权"]:
                    tiquan_found = True; continue
                elif name == "模糊音": # 兼容旧版单一模糊音
                    for cb in self.fuzzy_checks.values(): cb.setChecked(True)
                    continue
            other_patches.append(item_str)
            
        self.ext_edit.setPlainText("\n".join(other_patches))
        if not scheme_found: self.cb_scheme.setCurrentText("全拼")
        if not aux_found: self.cb_aux.setCurrentText("直接辅助")
        self.chk_tiquan.setChecked(tiquan_found)
        self._on_scheme_changed(self.cb_scheme.currentText())
        
    def get_value(self):
        res = []
        scheme = self.cb_scheme.currentText()
        prefix = "wanxiang_algebra:/pro/" if self.is_pro else "wanxiang_algebra:/base/"
        
        res.append(prefix + scheme)
        if self.is_pro: res.append("wanxiang_algebra:/pro/" + self.cb_aux.currentText())
        if self.chk_tiquan.isChecked(): res.append(f"wanxiang_algebra:/{scheme}提权")
            
        for path, cb in self.fuzzy_checks.items():
            if cb.isChecked(): res.append(path)
            
        for line in self.ext_edit.toPlainText().splitlines():
            if line.strip(): res.append(line.strip())
        return res
class ReverseAlgebraWidget(QWidget):
    """专为 wanxiang_reverse.schema.yaml 定制的反查拼音与笔画挂载器"""
    def __init__(self, initial_val=None, is_direct=False):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 2, 0, 2)
        self.layout.setSpacing(6)
        
        # ⚠️ 直写警告标签
        self.warn_lbl = QLabel("⚠️ 保护机制：核心规则仅允许在【补丁模式】下编辑。")
        self.warn_lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 12px;")
        self.layout.addWidget(self.warn_lbl)
            
        # --- 下拉框 ---
        h1 = QHBoxLayout()
        h2 = QHBoxLayout()
        
        self.cb_pinyin = QComboBox()
        self.cb_pinyin.addItems(["全拼", "自然码", "小鹤双拼", "微软双拼", "搜狗双拼", "智能ABC", "紫光双拼", "拼音加加"])
        self.cb_pinyin.setFixedHeight(34)
        
        self.cb_stroke = QComboBox()
        self.cb_stroke.addItem("hspzn (横竖撇捺折默认)", "hspzn")
        self.cb_stroke.addItem("hupvd (双拼专用)", "hupvd")
        self.cb_stroke.addItem("hslzy (乱序17)", "hslzy")
        self.cb_stroke.setFixedHeight(34)
        
        h1.addWidget(QLabel("🔤 拼音解析方案:"), 0); h1.addWidget(self.cb_pinyin, 1)
        h2.addWidget(QLabel("🖌️ 笔画挂接方案:"), 0); h2.addWidget(self.cb_stroke, 1)
        self.layout.addLayout(h1)
        self.layout.addLayout(h2)
        
        self.set_direct_mode(is_direct)
        self.set_value(initial_val)

    def set_direct_mode(self, is_direct):
        self.warn_lbl.setVisible(is_direct)
        
        style_cb = ""
        style_cb_disabled = ""
        
        self.cb_pinyin.setEnabled(not is_direct)
        self.cb_pinyin.setStyleSheet(style_cb if not is_direct else style_cb_disabled)
        self.cb_stroke.setEnabled(not is_direct)
        self.cb_stroke.setStyleSheet(style_cb if not is_direct else style_cb_disabled)

    def set_value(self, val_dict):
        # 兼容 librime 补丁语法产生的列表嵌套字典
        if isinstance(val_dict, list):
            dict_item = next((item for item in val_dict if isinstance(item, dict) and ("__patch" in item or "__include" in item)), None)
            val_dict = dict_item if dict_item else {}
            
        if not isinstance(val_dict, dict): val_dict = {}
        
        # 提取 __include (拼音方案)
        inc_val = val_dict.get("__include", "")
        if isinstance(inc_val, list) and inc_val: inc_val = inc_val[0]
        inc_str = str(inc_val)
        
        if "wanxiang_algebra:/reverse/" in inc_str:
            py_scheme = inc_str.split("/")[-1].strip(" '\"[]")
            self.cb_pinyin.setCurrentText(py_scheme)
        else:
            self.cb_pinyin.setCurrentText("自然码")
            
        patch_val = val_dict.get("__patch", "")
        if isinstance(patch_val, list) and patch_val: patch_val = patch_val[0]
        patch_str = str(patch_val)
        
        if "wanxiang_algebra:/reverse/" in patch_str:
            stroke_scheme = patch_str.split("/")[-1].strip(" '\"[]")
            idx = self.cb_stroke.findData(stroke_scheme)
            if idx >= 0: self.cb_stroke.setCurrentIndex(idx)
        else:
            self.cb_stroke.setCurrentIndex(0)
        
    def get_value(self):
        from ruamel.yaml.comments import CommentedMap
        res = CommentedMap()
        res["__include"] = f"wanxiang_algebra:/reverse/{self.cb_pinyin.currentText()}"
        res["__patch"] = f"wanxiang_algebra:/reverse/{self.cb_stroke.currentData()}"
        return res
class EnglishAlgebraWidget(QWidget):
    """专为 wanxiang_english.schema.yaml 定制的英文拼写挂载器"""
    def __init__(self, initial_val=None, is_direct=False):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 2, 0, 2)
        self.layout.setSpacing(6)
        
        # ⚠️ 直写警告标签
        self.warn_lbl = QLabel("⚠️ 保护机制：核心规则仅允许在【补丁模式】下编辑。")
        self.warn_lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 12px;")
        self.layout.addWidget(self.warn_lbl)
            
        # --- 1. 基础规则 (固定不可修改) ---
        h1 = QHBoxLayout()
        self.txt_include = QLineEdit("通用规则 (自动强制挂载)")
        self.txt_include.setFixedHeight(34)
        self.txt_include.setReadOnly(True)
        self.txt_include.setStyleSheet("background: rgba(128, 128, 128, 0.1); border-radius: 4px; padding: 4px 8px; color: #888; font-weight: bold;")
        h1.addWidget(QLabel("📚 基础规则:"), 0); h1.addWidget(self.txt_include, 1)
        self.layout.addLayout(h1)

        # --- 2. 英文按键映射方案 ---
        h2 = QHBoxLayout()
        self.cb_schema = QComboBox()
        self.cb_schema.addItems(["全拼", "自然码", "小鹤双拼", "微软双拼", "搜狗双拼", "智能ABC", "紫光双拼", "拼音加加", "自然龙", "汉心龙"])
        self.cb_schema.setFixedHeight(34)
        h2.addWidget(QLabel("🔤 按键映射:"), 0); h2.addWidget(self.cb_schema, 1)
        self.layout.addLayout(h2)
        
        self.set_direct_mode(is_direct)
        self.set_value(initial_val)

    def set_direct_mode(self, is_direct):
        self.warn_lbl.setVisible(is_direct)
        style_cb = ""
        style_cb_disabled = ""
        
        self.cb_schema.setEnabled(not is_direct)
        self.cb_schema.setStyleSheet(style_cb if not is_direct else style_cb_disabled)

    def set_value(self, val_dict):
        # 兼容 librime 补丁语法产生的列表嵌套字典
        if isinstance(val_dict, list):
            dict_item = next((item for item in val_dict if isinstance(item, dict) and ("__patch" in item or "__include" in item)), None)
            val_dict = dict_item if dict_item else {}
            
        if not isinstance(val_dict, dict): val_dict = {}
        
        patch_val = val_dict.get("__patch", "")
        if isinstance(patch_val, list) and patch_val: patch_val = patch_val[0]
        patch_str = str(patch_val)
        if "wanxiang_algebra:/english/" in patch_str:
            scheme = patch_str.split("/")[-1].strip(" '\"[]")
            self.cb_schema.setCurrentText(scheme)
        else:
            self.cb_schema.setCurrentText("自然码")
        
    def get_value(self):
        from ruamel.yaml.comments import CommentedMap
        res = CommentedMap()
        res["__include"] = "wanxiang_algebra:/english/通用规则"
        res["__patch"] = f"wanxiang_algebra:/english/{self.cb_schema.currentText()}"
        return res
class MixedAlgebraWidget(QWidget):
    """专为 wanxiang_mixedcode.schema.yaml 定制的混合编码拼写挂载器"""
    def __init__(self, initial_val=None, is_direct=False):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 2, 0, 2)
        self.layout.setSpacing(6)
        
        # ⚠️ 直写警告标签
        self.warn_lbl = QLabel("⚠️ 保护机制：核心规则仅允许在【补丁模式】下编辑。")
        self.warn_lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 12px;")
        self.layout.addWidget(self.warn_lbl)
            
        # --- 1. 基础规则 (固定不可修改) ---
        h1 = QHBoxLayout()
        self.txt_include = QLineEdit("通用派生规则 (自动强制挂载)")
        self.txt_include.setFixedHeight(34)
        self.txt_include.setReadOnly(True)
        self.txt_include.setStyleSheet("background: rgba(128, 128, 128, 0.1); border-radius: 4px; padding: 4px 8px; color: #888; font-weight: bold;")
        h1.addWidget(QLabel("📚 基础规则:"), 0); h1.addWidget(self.txt_include, 1)
        self.layout.addLayout(h1)

        # --- 2. 混合按键映射方案 ---
        h2 = QHBoxLayout()
        self.cb_schema = QComboBox()
        self.cb_schema.addItems(["全拼", "自然码", "小鹤双拼", "微软双拼", "搜狗双拼", "智能ABC", "紫光双拼", "拼音加加", "自然龙", "汉心龙"])
        self.cb_schema.setFixedHeight(34)
        h2.addWidget(QLabel("🔤 按键映射:"), 0); h2.addWidget(self.cb_schema, 1)
        self.layout.addLayout(h2)
        
        self.set_direct_mode(is_direct)
        self.set_value(initial_val)

    def set_direct_mode(self, is_direct):
        self.warn_lbl.setVisible(is_direct)
        style_cb = ""
        style_cb_disabled = ""
        
        self.cb_schema.setEnabled(not is_direct)
        self.cb_schema.setStyleSheet(style_cb if not is_direct else style_cb_disabled)

    def set_value(self, val_dict):
        # 兼容 librime 补丁语法产生的列表嵌套字典
        if isinstance(val_dict, list):
            dict_item = next((item for item in val_dict if isinstance(item, dict) and ("__patch" in item or "__include" in item)), None)
            val_dict = dict_item if dict_item else {}
            
        if not isinstance(val_dict, dict): val_dict = {}
        
        patch_val = val_dict.get("__patch", "")
        if isinstance(patch_val, list) and patch_val: patch_val = patch_val[0]
        patch_str = str(patch_val)
        if "wanxiang_algebra:/mixed/" in patch_str:
            scheme = patch_str.split("/")[-1].strip(" '\"[]")
            self.cb_schema.setCurrentText(scheme)
        else:
            self.cb_schema.setCurrentText("全拼")
        
    def get_value(self):
        from ruamel.yaml.comments import CommentedMap
        res = CommentedMap()
        res["__include"] = "wanxiang_algebra:/mixed/通用派生规则"
        res["__patch"] = f"wanxiang_algebra:/mixed/{self.cb_schema.currentText()}"
        return res
class DynamicMultiLineWidget(QWidget):
    """多行文本列表组件 - 莫兰迪绿 + 自动拉伸版"""
    hover_in = Signal()
    hover_out = Signal()
    value_changed = Signal(str)
    needs_resize = Signal(int)

    def __init__(self, initial_value=None, placeholder=""):
        super().__init__()
        from PySide6.QtWidgets import QPlainTextEdit
        from PySide6.QtCore import QTimer
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 4, 0)
        self.layout.setAlignment(Qt.AlignVCenter)
        
        self.text_field = QPlainTextEdit()
        self.text_field.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_field.setPlaceholderText(placeholder)
        
        if isinstance(initial_value, list):
            self.text_field.setPlainText("\n".join(str(x) for x in initial_value))
        elif initial_value:
            self.text_field.setPlainText(str(initial_value))
            
        self._hover_active = False 
        self._is_updating = False 
        
        # 纯白底色 + 莫兰迪绿边框
        self.style_normal = ""
        self.style_hover = ""
        
        self.text_field.setStyleSheet(self.style_normal)
        self.layout.addWidget(self.text_field)

        def adjust_text_height():
            lines = self.text_field.toPlainText().count('\n') + 1
            fm = self.text_field.fontMetrics()
            new_h = (lines * fm.lineSpacing()) + 26
            new_h = max(40, min(new_h, 450))
            if self.text_field.height() != new_h:
                self.text_field.setFixedHeight(new_h)
                self.setFixedHeight(new_h)
                self.needs_resize.emit(new_h)
                
        self.text_field.textChanged.connect(adjust_text_height)
        self.text_field.textChanged.connect(lambda: self.value_changed.emit(self.text_field.toPlainText()))
        
        # 初始触发高度计算
        QTimer.singleShot(0, adjust_text_height)

    def set_hover_state(self, hovered):
        if self._hover_active == hovered: return
        self._is_updating = True; self._hover_active = hovered
        self.text_field.setStyleSheet(self.style_hover if hovered else self.style_normal)
        self._is_updating = False

    def enterEvent(self, event): self.hover_in.emit(); self.set_hover_state(True); super().enterEvent(event)
    def leaveEvent(self, event): self.hover_out.emit(); self.set_hover_state(False); super().leaveEvent(event)

# =====================================================================
# 尝试导入 ruamel.yaml (用于安全修改 Rime 配置文件)
# =====================================================================
try:
    from ruamel.yaml import YAML
    HAS_RUAMEL = True
except ImportError:
    HAS_RUAMEL = False
# ============== 万象组件中文说明字典 ==============
KNOWN_COMPONENTS_DESC = {
    "lua_processor@*wanxiang.force_upper_aux": "强制大写辅码(固定分词)",
    "lua_processor@*wanxiang.super_processor": "核心(小键盘/退格限制/声调回退)",
    "lua_processor@*wanxiang.partial_commit": "局部提交(Ctrl+1~0)",
    "lua_processor@*wanxiang.super_sequence*P": "手动排序控制(左/右/置顶)",
    "lua_processor@*wanxiang.super_tips": "超级提示(表情/翻译/简码等)",
    "ascii_composer": "处理英文模式及中英切换",
    "recognizer": "特定规则码识别(如网址/反查)",
    "key_binder": "按键绑定(标点翻页等)",
    "lua_processor@*wanxiang.key_binder": "正则按键绑定扩展",
    "speller": "拼写处理器(接受按键,编辑输入)",
    "punctuator": "符号处理器",
    "selector": "选字处理器(数字选字/翻页)",
    "navigator": "光标导航移动",
    "express_editor": "编辑器(空格/回车/退格)",
    
    "ascii_segmentor": "标识英文段落(直接上屏)",
    "matcher": "标识符合recognizer的段落",
    "abc_segmentor": "常规汉字拼音段落",
    "affix_segmentor@wanxiang_reverse": "反查分段器",
    "affix_segmentor@add_user_dict": "自造词分段器",
    "punct_segmentor": "符号段落分段",
    "fallback_segmentor": "兜底分段(必须在最后)",

    "punct_translator": "转换标点符号",
    "script_translator": "主拼音/音节翻译器",
    "lua_translator@*wanxiang.version_display": "输入 /wx 显示版本",
    "lua_translator@*wanxiang.set_schema": "输入 /zrm 等切换方案",
    "lua_translator@*wanxiang.shijian": "农历/日期/时间/节日",
    "lua_translator@*wanxiang.unicode": "大写U引导Unicode",
    "lua_translator@*wanxiang.number_translator": "大写R引导数字大写",
    "lua_translator@*wanxiang.super_calculator": "超级计算器",
    "lua_translator@*wanxiang.input_statistics": "打字统计(日/周/月)",
    "table_translator@custom_phrase": "自定义短语(短语置顶)",
    "table_translator@wanxiang_english": "英文词汇表",
    "table_translator@wanxiang_mixedcode": "混合编码词汇表",
    "reverse_lookup_translator@wanxiang_reverse": "反查/辅码翻译",
    "script_translator@user_dict_set": "使用自造词",
    "script_translator@add_user_dict": "生成自造词",

    "lua_filter@*wanxiang.auto_phrase": "无感造词/英文造词",
    "lua_filter@*wanxiang.super_lookup": "反查辅助筛选",
    "lua_filter@*wanxiang.super_english": "英文单词格式化/加空格",
    "lua_filter@*wanxiang.charset_filter": "字符集过滤",
    "lua_filter@*wanxiang.super_replacer": "OpenCC(简繁/Emoji/简码等)",
    "lua_filter@*wanxiang.super_filter": "综合前置过滤",
    "lua_filter@*wanxiang.super_comment_preedit": "超级注释(辅码/拆分显示)",
    "lua_filter@*wanxiang.super_sequence*F": "手动调序固化过滤",
    "uniquifier": "全局去重(必须在最后)",
    # ===== 追加：符号包裹说明 =====
    "a": "方括号 []",
    "b": "黑方头括号 【】",
    "c": "双大括号 ❲❳",
    "d": "方头括号 〔〕",
    "e": "小圆括号 ⟮⟯",
    "f": "双方括号 ⟦⟧",
    "g": "直角引号 「」",
    "i": "双直角引号 『』",
    "j": "尖括号 <>",
    "k": "书名号(双) 《》",
    "l": "书名号(单) 〈〉",
    "q": "圆括号 ()",
    "z": "花括号 {}",
    "dy": "英文单引号 ''",
    "sy": "英文双引号 \"\"",
    "zs": "中文双引号 “”",
    "zd": "中文单引号 ‘’",
    "fy": "反引号 ``",
    "md": "Markdown 粗体 **|**",
    "jc": "加粗 **|**",
    "it": "斜体 __|__",
    "st": "删除线 ~~|~~",
    "eq": "高亮 ==|==",
    "ln": "行内代码 `|`",
    "cb": "代码块 ```|```",
    "qt": "引用 > |",
    "ul": "无序列表项 - |",
    "ol": "有序列表项 1. |",
    "lk": "链接 [|](url)",
    "im": "图片 ![|](img)",
    "h": "一级标题 # |",
    "hh": "二级标题 ## |",
    "hhh": "三级标题 ### |",
    "hhhh": "四级标题 #### |",
    "br": "换行 |  ",
    # ===== 追加：数字声调映射说明 =====
    "1": "数字键 1 映射",
    "2": "数字键 2 映射",
    "3": "数字键 3 映射",
    "4": "数字键 4 映射",
    "5": "数字键 5 映射",
    "6": "数字键 6 映射",
    "7": "数字键 7 映射",
    "8": "数字键 8 映射",
    "9": "数字键 9 映射",
    "0": "数字键 0 映射"
}
# 方案高级配置 元数据模型 (定义界面怎么显示、对应 yaml 什么路径)
SCHEMA_META_CONFIG = {
    "schema_info_base": {
        "_root_key": "schema",
        "_match_file": "wanxiang.schema.yaml",
        "_title": "🏷️ 方案信息与扩展挂接 (Base版)",
        "_desc": "自定义在输入法菜单中显示的名称，以及挂接的附属方案。",
        "nodes": {
            "name": {"title": "方案显示名称", "type": "str", "desc": "默认：万象拼音"},
            "version": {"title": "方案版本号", "type": "str", "desc": "默认：LTS"},
            "dependencies": {"title": "扩展方案挂接", "type": "list_text", "desc": "支持多行，直接回车换行，无需写 -\n默认:\nwanxiang_mixedcode\nwanxiang_reverse\nwanxiang_english"},
        }
    },
    "schema_info_pro": {
        "_root_key": "schema",
        "_match_file": "wanxiang_pro.schema.yaml",
        "_title": "🏷️ 方案信息与扩展挂接 (Pro增强版)",
        "_desc": "自定义在输入法菜单中显示的名称，以及挂接的附属方案。",
        "nodes": {
            "name": {"title": "方案显示名称", "type": "str", "desc": "默认：万象拼音·Pro"},
            "version": {"title": "方案版本号", "type": "str", "desc": "默认：LTS"},
            "dependencies": {"title": "扩展方案挂接", "type": "list_text", "desc": "支持多行，直接回车换行，无需写 -\n默认:\nwanxiang_mixedcode\nwanxiang_reverse\nwanxiang_english"},
        }
    },
    "schema_info_mixedcode": {
        "_root_key": "schema",
        "_match_file": "wanxiang_mixedcode.schema.yaml",  # 👈 核心：精准匹配文件名
        "_title": "🏷️ 方案信息 (混合编码 Mixedcode)",
        "_desc": "定义混合编码方案的基础属性与元数据。",
        "nodes": {
            "schema_id": {"title": "方案标识 (schema_id)", "type": "str", "desc": "不可随意更改，须与文件名对齐"},
            "name": {"title": "方案名称 (name)", "type": "str", "desc": "如: 万象：英文与混合编码"},
            "version": {"title": "版本号 (version)", "type": "str"},
            "author": {"title": "作者 (author)", "type": "str"},
            "description": {"title": "方案描述 (description)", "type": "str", "desc": "简要描述该方案的作用"}
        }
    },
    "schema_info_reverse": {
        "_root_key": "schema",
        "_match_file": "wanxiang_reverse.schema.yaml",  # 👈 仅在反查方案中显示
        "_title": "🏷️ 方案信息 (拆分与笔画反查 Reverse)",
        "_desc": "定义反查方案的基础属性与元数据。",
        "nodes": {
            "schema_id": {"title": "方案标识 (schema_id)", "type": "str", "desc": "不可随意更改，须与文件名对齐"},
            "name": {"title": "方案名称 (name)", "type": "str", "desc": "如: 万象：拆分与笔画反查"},
            "version": {"title": "版本号 (version)", "type": "str"},
            "author": {"title": "作者 (author)", "type": "str"},
            "description": {"title": "方案描述 (description)", "type": "str", "desc": "简要描述该方案的作用"}
        }
    },
    "schema_info_english": {
        "_root_key": "schema",
        "_match_file": "wanxiang_english.schema.yaml",  # 👈 仅在英文方案中显示
        "_title": "🏷️ 方案信息 (英文 English)",
        "_desc": "定义英文语句流方案的基础属性与元数据。",
        "nodes": {
            "schema_id": {"title": "方案标识 (schema_id)", "type": "str", "desc": "不可随意更改，须与文件名对齐"},
            "name": {"title": "方案名称 (name)", "type": "str", "desc": "如: 万象英文"},
            "version": {"title": "版本号 (version)", "type": "str"},
            "author": {"title": "作者 (author)", "type": "str"},
            "description": {"title": "方案描述 (description)", "type": "str", "desc": "支持整句输入及格式化..."}
        }
    },
    "schema_info_t9": {
        "_root_key": "schema",
        "_match_file": "wanxiang_t9.schema.yaml",  # 👈 仅在九宫格方案中显示
        "_title": "🏷️ 方案信息 (九宫格 T9)",
        "_desc": "定义九宫格(仓输入法)方案的基础属性与元数据。",
        "nodes": {
            "schema_id": {"title": "方案标识 (schema_id)", "type": "str", "desc": "不可随意更改，须与文件名对齐"},
            "name": {"title": "方案名称 (name)", "type": "str", "desc": "如: 万象・九宫格"},
            "version": {"title": "版本号 (version)", "type": "str"},
            
            # 【重点】：这里使用 list_text 完美兼容多个作者的数组格式！
            "author": {"title": "作者 (author)", "type": "list_text", "desc": "支持多作者，直接回车换行，无需写减号 -"},
            
            "description": {"title": "方案描述 (description)", "type": "str", "desc": "简要描述该方案的作用"}
        }
    },
    "speller": {
        "_root_key": "speller",
        "_title": "🔤 拼写与运算设定 (speller)",
        "_desc": "定义允许输入的字符、分隔符以及核心的拼写运算规则 (algebra)。",
        "nodes": {
            "auto_select": {"title": "候选自动上屏", "type": "bool", "desc": "配合正则使用，如 zmhu 自动上屏"},
            "auto_select_pattern": {"title": "自动上屏正则", "type": "str", "desc": "如 ^[a-z]+/ 等"},
            "alphabet": {"title": "有效输入字符", "type": "str", "desc": "定义哪些按键会被输入法接管"},
            "initials": {"title": "起始首字母", "type": "str"},
            "delimiter": {"title": "系统分隔符", "type": "str", "desc": "如 \" '\""},
            "visual_delimiter": {"title": "视觉分隔符", "type": "str", "desc": "界面显示的假装分隔符"},
            "tone_isolate": {"title": "声调隔离", "type": "bool", "desc": "数字声调是否免于参与拼写转换运算"},
            "algebra/__patch": {
                "title": "🧩 拼写方案与辅助码", 
                "type": "algebra_patch", 
                "desc": "智能配置拼写输入方案、辅助码模式与细分模糊音"
            }
        }
    },
    "speller_reverse": {
        "_root_key": "speller",
        "_match_file": "wanxiang_reverse.schema.yaml",
        "_title": "🔤 反查拼写与运算 (speller)",
        "_desc": "配置反查方案独有的拼音解析与笔画规则。",
        "nodes": {
            "algebra": {
                "title": "🧩 反查拼音与笔画方案", 
                "type": "reverse_algebra", 
                "desc": "智能配置反查拼音解析类型与笔画打法"
            }
        }
    },
    "speller_english": {
        "_root_key": "speller",
        "_match_file": "wanxiang_english.schema.yaml",
        "_title": "🔤 英文拼写与运算 (speller)",
        "_desc": "配置英文方案独有的通用规则与按键映射。",
        "nodes": {
            "algebra": {
                "title": "🧩 英文按键映射方案", 
                "type": "english_algebra", 
                "desc": "智能配置英文状态下的按键映射打法"
            }
        }
    },
    "speller_mixed": {
        "_root_key": "speller",
        "_match_file": "wanxiang_mixedcode.schema.yaml",  # 👈 锁定混合方案专属
        "_title": "🔤 混合拼写与运算 (speller)",
        "_desc": "配置混合编码方案独有的通用派生规则与按键映射。",
        "nodes": {
            "algebra": {
                "title": "🧩 混合按键映射方案", 
                "type": "mixed_algebra", 
                "desc": "智能配置混合状态下的按键映射打法"
            }
        }
    },
    "switches": {
        "_root_key": "switches",
        "_title": "🎛️ 状态开关 (switches)",
        "_desc": "定义输入法的状态切换开关（如中英文、繁简、标点等）。支持拖拽排序。",
        "nodes": {
            "__self__": {
                "title": "开关配置块",
                "type": "dynamic_block_list",
                "desc": "添加或修改开关。【注意】：单开关填 name，多开关组填 options，二选一即可！",
                "template": {
                    "name": {"title": "单开关标识 (name)", "type": "str", "desc": "如: ascii_mode (与 options 二选一)"},
                    "options": {"title": "多开关组 (options)", "type": "list_text", "desc": "如: [s2s, s2t, s2hk]"},
                    "states": {"title": "菜单显示名称 (states)", "type": "list_text", "desc": "如: [简体, 通繁, 港繁]"},
                    "reset": {"title": "默认状态索引 (reset)", "type": "str", "desc": "重置到的默认项(从 0 开始)。留空则不重置"},
                    "abbrev": {"title": "状态栏缩写 (abbrev)", "type": "list_text", "desc": "（可选）如: [简, 通, 港]"}
                }
            }
        }
    },
    "engine": {
        "_root_key": "engine",
        "_title": "🚀 引擎组件树 (engine)",
        "_desc": "动态管理底层处理单元，悬浮行支持自由添加、移动、删除组件。",
        "nodes": {
            "processors": {
                "title": "处理器 (Processors)",
                "type": "dynamic_list",
                "desc": "打字按键拦截与基础逻辑处理"
            },
            "segmentors": {
                "title": "分段器 (Segmentors)",
                "type": "dynamic_list",
                "desc": "对输入的编码段落进行标签化"
            },
            "translators": {
                "title": "翻译器 (Translators)",
                "type": "dynamic_list",
                "desc": "将不同标签的编码翻译为候选文字"
            },
            "filters": {
                "title": "过滤器 (Filters)",
                "type": "dynamic_list",
                "desc": "对最终的候选词进行修饰、去重与调序"
            }
        }
    },
    "translator": {
        "_root_key": "translator",
        "_title": "🔤 主翻译器配置 (translator)",
        "_desc": "自由增减核心参数。点击 ➕ 号添加，在左侧下拉框中选择要启用的功能，右侧填写对应值。\n【提示】true/false直接填。不需要的参数直接点 ❌ 删除即可！",
        "nodes": {
            "__self__": {
                "title": "已启用的参数",
                "type": "dynamic_kv_list",  
                "preset_keys": {  
                    "dictionary": "挂载主词库名 (填字符串)",
                    "packs": "额外扩展词典 (填列表,如 [user])",
                    "prism": "独立缓存名 (填字符串)",
                    "user_dict": "用户词典名 (填字符串)",
                    "db_class": "词典格式 (tabledb 或 userdb)",
                    "enable_completion": "启用候选词补全 (true/false)",
                    "enable_user_dict": "启用自动调频 (true/false)",
                    "enable_sentence": "启用自动造句 (true/false)",
                    "enable_encoder": "启用自动造词 (true/false)",
                    "enable_correction": "启用自动纠错 (true/false)",
                    "encode_commit_history": "历史上屏自动成词 (true/false)",
                    "contextual_suggestions": "智能上下文预测 (true/false)",
                    "core_word_length": "核心词组长度 (数字)",
                    "max_word_length": "最大词组长度 (数字)",
                    "max_homophones": "最大同音词数 (数字)",
                    "max_homographs": "最大同形词数 (数字)",
                    "initial_quality": "初始质量权重 (数字)",
                    "spelling_hints": "拼写提示最大长度 (数字)",
                    "always_show_comments": "强制始终显示注释 (true/false)",
                    "preedit_format": "编码提示格式化规则 (填列表, 一行一条)", 
                    "comment_format": "注释格式化规则 (填列表, 一行一条)", 
                    "disable_user_dict_for_patterns": "不记录调频的正则 (填列表)"
                }
            }
        }
    },
    "user_predict": {
        "_root_key": "user_predict",
        "_title": "🔮 用户长句预测 (user_predict)",
        "_desc": "控制上屏后自动预测与输入时上下文调频的高级行为。",
        "nodes": {
            "db_name": {"title": "数据库名称", "type": "str", "desc": "默认: lua/predict (将生成 predict.userdb)"},
            "enable_post_predict": {"title": "上屏后预测", "type": "bool", "desc": "开启后，上屏词汇后会自动给出后续词联想"},
            "enable_context_reorder": {"title": "输入时调频", "type": "bool", "desc": "开启后，会根据前文动态调整当前候选词的权重"},
            "max_candidates": {"title": "最大联想词数", "type": "int", "desc": "屏幕最多显示的联想词数量"},
            "max_predictions": {"title": "连续预测限制", "type": "int", "desc": "连续触发预测的最高次数限制"},
            "expiry_days": {"title": "绝对寿命(天)", "type": "int", "desc": "不命中则物理销毁"},
            "activation_days": {"title": "激活期限(天)", "type": "int", "desc": "冷冻期内输入第2次转正"},
            "max_memory_branches": {"title": "记忆分支上限", "type": "int", "desc": "单前缀最多保留后续预测的数量"},
            "decay_rate": {"title": "记忆衰减率", "type": "str", "desc": "如 0.85 (单日时间权重打85折)"},
            "enable_predict_space": {"title": "联想时空格上屏空格", "type": "bool", "desc": "true: 联想时按空格上屏空格\nfalse: 默认行为（一般手机开电脑关）"},
            "context_timeout": {"title": "上文超时(毫秒)", "type": "int", "desc": "超过该时间未输入，视为上下文断裂 (默认: 5000)"}
        }
    },
    "custom_phrase": {
        "_root_key": "custom_phrase",
        "_title": "📝 自定义短语 (custom_phrase)",
        "_desc": "定义打字时优先上屏的快捷短语与权重。",
        "nodes": {
            "dictionary": {"title": "挂载词库", "type": "str", "desc": "通常留空"},
            "user_dict": {"title": "用户词典名", "type": "str", "desc": "默认: custom_phrase"},
            "db_class": {"title": "数据库类型", "type": "select", "options": ["stabledb", "tabledb", "userdb"], "desc": "默认: stabledb"},
            "enable_completion": {"title": "开启补全提示", "type": "bool"},
            "enable_sentence": {"title": "开启自动造句", "type": "bool"},
            "initial_quality": {"title": "初始权重值", "type": "str", "desc": "设为 99 可让短语置顶"}
        }
    },
    "wanxiang_english": {
        "_root_key": "wanxiang_english",
        "_title": "🔤 英文混输与造词 (wanxiang_english)",
        "_desc": "处理英文模式、中英混输空格策略及英文自动造词。",
        "nodes": {
            "dictionary": {"title": "挂载英文词库", "type": "str"},
            "user_dict": {"title": "英文用户词典", "type": "str", "desc": "默认: en"},
            "enable_completion": {"title": "开启补全提示", "type": "bool"},
            "enable_sentence": {"title": "开启自动造句", "type": "bool"},
            "initial_quality": {"title": "初始权重值", "type": "str", "desc": "如: 2.1"},
            "comment_format": {"title": "注释格式化规则", "type": "list_text", "desc": "去除带声调字母防崩溃"},
            "english_spacing": {"title": "自动加空格模式", "type": "select", "options": ["smart", "off", "before", "after"], "desc": "smart: 智能加空格"},
            "spacing_timeout": {"title": "空格状态超时(秒)", "type": "int", "desc": "0为不超时"},
            "max_candidates": {"title": "最大候选数", "type": "int", "desc": "英文候选输出最大数量"},
            "trigger": {"title": "英文造词触发符", "type": "str", "desc": "默认: \\ (双击生效)"}
        }
    },
    "wanxiang_mixedcode": {
        "_root_key": "wanxiang_mixedcode",
        "_title": "🔣 混合编码表 (wanxiang_mixedcode)",
        "_desc": "处理中文、英文、数字、符号等混合词汇上屏。",
        "nodes": {
            "dictionary": {"title": "挂载混合词库", "type": "str"},
            "db_class": {"title": "数据库类型", "type": "select", "options": ["stabledb", "tabledb", "userdb"]},
            "enable_completion": {"title": "开启补全提示", "type": "bool"},
            "enable_sentence": {"title": "开启自动造句", "type": "bool"},
            "initial_quality": {"title": "初始权重值", "type": "str"},
            "comment_format": {"title": "注释格式化规则", "type": "list_text", "desc": "去除带声调字母防崩溃"}
        }
    },
    "wanxiang_reverse": {
        "_root_key": "wanxiang_reverse",
        "_title": "🔍 部件拆字反查 (wanxiang_reverse)",
        "_desc": "提供拼音反查部件、笔画等的入口配置。",
        "nodes": {
            "tag": {"title": "反查生效标签", "type": "str"},
            "dictionary": {"title": "挂载反查词库", "type": "str"},
            "enable_completion": {"title": "开启补全提示", "type": "bool"},
            "prefix": {"title": "反查触发前缀", "type": "str", "desc": "默认: ` (反引号)"},
            "tips": {"title": "反查提示语", "type": "str", "desc": "如: 〔反查：拆分|笔画〕"}
        }
    },
    "default_schema_list": {
        "_root_key": "schema_list",
        "_match_file": "default.yaml",
        "_title": "📜 启用方案列表 (schema_list)",
        "_desc": "勾选需要在输入法菜单中切换的方案 (自动扫描目录下所有方案)。",
        "nodes": {
            "__self__": {
                "title": "全局可选方案",
                "type": "schema_checkboxes",
                "desc": "智能解析本地方案名称，取消勾选即视为停用"
            }
        }
    },
    "default_menu": {
        "_root_key": "menu",
        "_match_file": "default.yaml",
        "_title": "🪟 候选菜单条数 (menu)",
        "_desc": "全局生效的候选词数量与选词标签设定。",
        "nodes": {
            "page_size": {"title": "候选词个数", "type": "int", "desc": "建议: 6"},
            "alternative_select_labels": {"title": "候选项标签", "type": "list_text", "desc": "如: [1, 2, 3] 或者 [⒈, ⒉, ⒊]"},
            "alternative_select_keys": {"title": "选字按键", "type": "str", "desc": "如: ASDFGHJKL"}
        }
    },
    "default_switcher": {
        "_root_key": "switcher",
        "_match_file": "default.yaml",
        "_title": "🔁 状态面板设置 (switcher)",
        "_desc": "控制由快捷键唤出的状态切换面板（记忆开关、标题等）。",
        "nodes": {
            "caption": {"title": "面板标题", "type": "str", "desc": "如: 「万象状态面板」"},
            "fold_options": {"title": "呼出时自动折叠", "type": "bool"},
            "abbreviate_options": {"title": "折叠时缩写显示", "type": "bool"},
            "option_list_separator": {"title": "折叠选项分隔符", "type": "str", "desc": "如: ' / '"},
            "hotkeys": {"title": "面板呼出快捷键", "type": "list_text", "desc": "如: Control+grave"},
            "save_options": {
                "title": "状态记忆开关", 
                "type": "list_text", 
                "action_btn": "📥 从主方案自动提取",  # 👈 核心：触发一键导入魔法
                "desc": "自动提取无 reset 状态的有用开关变量，一行一个"
            }
        }
    },
    "default_ascii_composer": {
        "_root_key": "ascii_composer",
        "_match_file": "default.yaml",
        "_title": "🔠 中英切换逻辑 (ascii_composer)",
        "_desc": "定义 Shift / CapsLock 等修饰键的中英文切换行为。",
        "nodes": {
            "good_old_caps_lock": {"title": "传统 CapsLock 行为", "type": "bool", "desc": "true: 切换大写, false: 切换中英"},
            "switch_key/Caps_Lock": {"title": "[ Caps Lock 键 ]", "type": "select", "options": ["clear", "commit_code", "commit_text", "noop"]},
            "switch_key/Shift_L": {"title": "[ 左 Shift 键 ]", "type": "select", "options": ["commit_code", "commit_text", "inline_ascii", "clear", "noop"]},
            "switch_key/Shift_R": {"title": "[ 右 Shift 键 ]", "type": "select", "options": ["commit_code", "commit_text", "inline_ascii", "clear", "noop"]},
            "switch_key/Control_L": {"title": "[ 左 Ctrl 键 ]", "type": "select", "options": ["noop", "commit_code", "commit_text", "inline_ascii", "clear"]},
            "switch_key/Control_R": {"title": "[ 右 Ctrl 键 ]", "type": "select", "options": ["noop", "commit_code", "commit_text", "inline_ascii", "clear"]}
        }
    },
    "super_replacer": {
        "_root_key": "super_replacer",
        "_title": "🔄 超级替代器 (super_replacer)",
        "_desc": "深度定制过滤与替换逻辑。区块支持任意添加、移动、删除。",
        "nodes": {
            "db_name": {"title": "数据库路径", "type": "str", "desc": "默认: lua/replacer"},
            "delimiter": {"title": "候选分隔符", "type": "str", "desc": "默认: |"},
            "comment_format": {"title": "注释格式", "type": "str", "desc": "默认: 〔%s〕"},
            "chain": {"title": "流水线模式", "type": "bool", "desc": "开启后上一个结果会传给下一个"},
            "rules": {
                "title": "📑 规则链条 (Rules)",
                "type": "dynamic_block_list",
                "desc": "按自上而下的顺序执行的替换/滤镜规则块",
                "template": {
                    "option": {"title": "绑定开关", "type": "list_text", "desc": "单开关、true，或数组 [s2t, s2hk]"},
                    "cand_type": {"title": "候选类型", "type": "str", "desc": "如: emoji, abbrev"},
                    "mode": {"title": "处理模式", "type": "select", "options": ["append", "replace", "comment", "abbrev"]},
                    "comment_mode": {"title": "注释模式", "type": "select", "options": ["none", "append", "text"], "visible_if": {"mode": ["append", "replace"]}},
                    "sentence": {"title": "整句转换", "type": "bool", "visible_if": {"mode": ["append", "replace"]}},
                    "tags": {"title": "生效标签", "type": "list_text", "desc": "如: [abc]"},
                    "prefix": {"title": "数据前缀", "type": "str", "desc": "如: _em_"},
                    
                    # ====== 新增的 abbrev 模式专属参数 ======
                    "abbrev_rule": {"title": "简码置顶规则", "type": "str", "desc": "如: 1,6 或 2,3", "visible_if": {"mode": ["abbrev"]}},
                    "t9_optimization": {"title": "T9编码优化", "type": "bool", "desc": "将字母转为数字编码", "visible_if": {"mode": ["abbrev"]}},
                    
                    "files": {"title": "字典文件", "type": "list_text", "desc": "每行一个文件路径"}
                }
            }
        }
    },
    "grammar": {
        "_root_key": "grammar",
        "_title": "🧠 语法模型权重 (grammar)",
        "_desc": "控制 LMDG 语法模型的联想行为与惩罚权重（非专业人士建议保持默认）。",
        "nodes": {
            "collocation_max_length": {"title": "最大搭配长度", "type": "int", "desc": "默认: 7"},
            "collocation_min_length": {"title": "最小搭配长度", "type": "int", "desc": "默认: 3"},
            "collocation_penalty": {"title": "搭配惩罚项", "type": "int", "desc": "默认: -10"},
            "non_collocation_penalty": {"title": "非搭配惩罚", "type": "int", "desc": "默认: 3"},
            "rear_penalty": {"title": "尾部惩罚", "type": "int", "desc": "默认: -12"},
        }
    },
    "super_comment": {
        "_root_key": "super_comment",
        "_title": "📝 超级注释样式 (super_comment)",
        "_desc": "控制候选词后面的提示信息样式（辅助码、拆分、词类标识）。",
        "nodes": {
            "candidate_length": {"title": "辅码提醒生效长度", "type": "int", "desc": "多长的词显示辅码提示？0为关闭"},
            "corrector_type": {"title": "普通注释括号", "type": "str", "desc": "占位符 comment 必须保留，如: 〔comment〕"},
            "chaifen": {"title": "拆分提醒括号", "type": "str", "desc": "占位符 chaifen 必须保留，如: 〔chaifen〕"},
            "cand_type/sentence": {"title": "【整句】标识符", "type": "str", "desc": "默认: ∞"},
            "cand_type/user_phrase": {"title": "【用户词】标识符", "type": "str", "desc": "留空则不显示"},
        }
    },
    "super_processor": {
        "_root_key": "super_processor",
        "_title": "⚙️ 核心处理器 (super_processor)",
        "_desc": "控制拼音、选词、退格等高级逻辑行为。",
        "nodes": {
            "enable_backspace_limit": {"title": "开启退格限制", "type": "bool", "desc": "限制退格键越界删除（防止删错上屏词）"},
            "enable_seg_loop": {"title": "分词符循环", "type": "bool", "desc": "开启后单引号分词符可循环切换"},
            "enable_tone_fallback": {"title": "声调回退", "type": "bool", "desc": "启用声调输入时的逻辑回退"},
            "enable_predict_space": {"title": "联想空格打断", "type": "bool", "desc": "对齐大厂：空格直接上屏并清空联想"},
            "kp_number_mode": {"title": "小键盘模式", "type": "select", "options": ["auto", "compose"], "desc": "auto: 自动识别 | compose: 强制组字"},
            "limit_repeated": {"title": "重复声母限制", "type": "str", "desc": "格式：最大重复声母,最大候选字数 (如 8,40)"},
            "select_character": {"title": "以词定字按键", "type": "str", "desc": "默认: [,] (支持括号名或全拼名)"},
        }
    },
    "super_tips": {
        "_root_key": "super_tips",
        "_title": "💡 超级提示模块 (super_tips)",
        "_desc": "控制实时提示数据的路径与触发按键。",
        "nodes": {
            "db_name": {"title": "数据库路径", "type": "str", "desc": "默认: lua/tips"},
            "tips_key": {"title": "提示上屏按键", "type": "str", "desc": "用于上屏提示内容的按键（默认 comma 逗号）"},
            "disabled_types": {
                "title": "🚫 屏蔽的提示类型", 
                "type": "list_text", 
                "desc": "一行填一个。\n可选类型：偏旁，符号，化学式，时间，组字，翻译，表情，货币，车牌，单位"
            }
        }
    },
    "input_stats": {
        "_root_key": "input_stats",
        "_title": "📊 打字效率统计 (input_stats)",
        "_desc": "日、周、月、年生涯打字统计看板",
        "nodes": {
            "db_name": {"title": "数据库路径", "type": "str", "desc": "统计数据存放位置 (如 lua/stats)"},
            "triggers/today": {"title": "今日统计触发码", "type": "str", "desc": "默认：/rtj"},
            "triggers/history": {"title": "时光机触发码", "type": "str", "desc": "默认：/htj"},
            "triggers/clear": {"title": "清空数据触发码", "type": "str", "desc": "默认：/qctj"}
        }
    },
    "charset": {
        "_root_key": "charset",
        "_title": "🔤 字符集过滤 (charset)",
        "_desc": "按字区进行精准过滤，支持多个开启状态的开关求并集。",
        "nodes": {
            "__self__": {  
                "title": "过滤规则组",
                "type": "dynamic_block_list",
                "desc": "增减字符集过滤块，悬浮可拖拽",
                "template": {
                    "option": {"title": "绑定开关", "type": "str", "desc": "如 charset_filter, s2hk 等"},
                    "base": {"title": "基础字符集", "type": "str", "desc": "填入代号，如: a"},
                    "addlist": {"title": "白名单 (增补)", "type": "list_text", "desc": "突破限制强行显示的字"},
                    "blacklist": {"title": "黑名单 (剔除)", "type": "list_text", "desc": "强行隐藏的字"}
                }
            }
        }
    },
    "date_formats": {
        "_root_key": "date_formats",
        "_title": "📅 日期格式化 (date_formats)",
        "_desc": "触发码: orq, /rq, N日期 等。\n【占位符】 Y:四位年 | y:两位年 | m:月(带零) | n:月(无零) | d:日(带零) | j:日(无零)",
        "nodes": {
            "__self__": {
                "title": "可选格式列表",
                "type": "dynamic_list",
                "desc": "向下排序对应打字时的候选 1, 2, 3..."
            }
        }
    },
    "time_formats": {
        "_root_key": "time_formats",
        "_title": "🕒 时间格式化 (time_formats)",
        "_desc": "触发码: osj, /sj 等。\n【占位符】 H:24时(带零) | G:24时(无零) | I:12时(带零) | l:12时(无零) | M:分 | S:秒\n【标识符】 p:am/pm | P:AM/PM | A:凌晨/上午/中午/下午/晚上",
        "nodes": {
            "__self__": {
                "title": "可选格式列表",
                "type": "dynamic_list",
                "desc": "向下排序对应打字时的候选 1, 2, 3..."
            }
        }
    },
    "datetime_formats": {
        "_root_key": "datetime_formats",
        "_title": "🕙 完整日期时间组合 (datetime_formats)",
        "_desc": "触发码: odt, /dt, /tt 等。\n【时区占位】 O:带冒号(+08:00) | o:无冒号(+0800)\n【高级语法】 支持 \\X 转义单个字符，或 [[...]] 整体原样输出",
        "nodes": {
            "__self__": {
                "title": "可选格式列表",
                "type": "dynamic_list",
                "desc": "向下排序对应打字时的候选 1, 2, 3..."
            }
        }
    },
    "super_sequence": {
        "_root_key": "super_sequence",
        "_title": "↕️ 手动排序 (super_sequence)",
        "_desc": "控制候选项的手动调序与置顶按键",
        "nodes": {
            "db_name": {"title": "数据库路径", "type": "str", "desc": "默认为 lua/sequence"},
            "up": {"title": "向前移动快捷键", "type": "str", "desc": "默认：Control+j"},
            "down": {"title": "向后移动快捷键", "type": "str", "desc": "默认：Control+k"},
            "reset": {"title": "重置位移快捷键", "type": "str", "desc": "默认：Control+l"},
            "pin": {"title": "置顶候选快捷键", "type": "str", "desc": "默认：Control+p"},
        }
    },
    "quick_symbol_text": {
        "_root_key": "quick_symbol_text",
        "_title": "⚡ 单字母快符 (quick_symbol_text)",
        "_desc": "单字母结合引导符(如 a/)触发符号快捷上屏。将值设为 'repeat' 可实现对应按键连续上屏。\n【提示】留空输入框即可自动删除该快捷按键的绑定。",
        "nodes": {
            "trigger": {"title": "触发正则表达式", "type": "str", "desc": "默认: ^([a-z])/$ (即字母加斜杠)"},
            
            # --- 键盘第一排 ---
            "symkey/q": {"title": "[ q ] 键符号", "type": "str", "desc": "默认: repeat"},
            "symkey/w": {"title": "[ w ] 键符号", "type": "str", "desc": "默认: ？"},
            "symkey/e": {"title": "[ e ] 键符号", "type": "str", "desc": "默认: （"},
            "symkey/r": {"title": "[ r ] 键符号", "type": "str", "desc": "默认: ）"},
            "symkey/t": {"title": "[ t ] 键符号", "type": "str", "desc": "默认: ~"},
            "symkey/y": {"title": "[ y ] 键符号", "type": "str", "desc": "默认: ·"},
            "symkey/u": {"title": "[ u ] 键符号", "type": "str", "desc": "默认: 『"},
            "symkey/i": {"title": "[ i ] 键符号", "type": "str", "desc": "默认: 』"},
            "symkey/o": {"title": "[ o ] 键符号", "type": "str", "desc": "默认: 〖"},
            "symkey/p": {"title": "[ p ] 键符号", "type": "str", "desc": "默认: 〗"},

            # --- 键盘第二排 ---
            "symkey/a": {"title": "[ a ] 键符号", "type": "str", "desc": "默认: ！"},
            "symkey/s": {"title": "[ s ] 键符号", "type": "str", "desc": "默认: ……"},
            "symkey/d": {"title": "[ d ] 键符号", "type": "str", "desc": "默认: 、"},
            "symkey/f": {"title": "[ f ] 键符号", "type": "str", "desc": "默认: “"},
            "symkey/g": {"title": "[ g ] 键符号", "type": "str", "desc": "默认: ”"},
            "symkey/h": {"title": "[ h ] 键符号", "type": "str", "desc": "默认: ‘"},
            "symkey/j": {"title": "[ j ] 键符号", "type": "str", "desc": "默认: ’"},
            "symkey/k": {"title": "[ k ] 键符号", "type": "str", "desc": "默认: 【"},
            "symkey/l": {"title": "[ l ] 键符号", "type": "str", "desc": "默认: 】"},

            # --- 键盘第三排 ---
            "symkey/z": {"title": "[ z ] 键符号", "type": "str", "desc": "默认: 。”"},
            "symkey/x": {"title": "[ x ] 键符号", "type": "str", "desc": "默认: ？”"},
            "symkey/c": {"title": "[ c ] 键符号", "type": "str", "desc": "默认: ！”"},
            "symkey/v": {"title": "[ v ] 键符号", "type": "str", "desc": "默认: ——"},
            "symkey/b": {"title": "[ b ] 键符号", "type": "str", "desc": "默认: %"},
            "symkey/n": {"title": "[ n ] 键符号", "type": "str", "desc": "默认: 《"},
            "symkey/m": {"title": "[ m ] 键符号", "type": "str", "desc": "默认: 》"},
        }
    },
    "paired_symbols": {
        "_root_key": "paired_symbols",
        "_title": "🔠 成对符号包裹 (paired_symbols)",
        "_desc": "输入引导键(默认为 \\)触发包裹，如输入 nihao\\c 将候选[你好]变为 ❲你好❳。\n【语法】支持使用 | 明确区分前后(如 **|**)，没有 | 则默认各分一半。",
        "nodes": {
            "trigger": {"title": "触发引导符", "type": "str", "desc": "默认: \\ (提示: 填单反斜杠即可)"},
            "symkey": {
                "title": "包裹规则映射表",
                "type": "dynamic_map",
                "desc": "格式必须为【键: 值】(如 md: **|**)。支持任意修改Key和Value！"
            }
        }
    },
    "wanxiang_lookup": {
        "_root_key": "wanxiang_lookup",
        "_title": "🔎 反查辅助筛选 (wanxiang_lookup)",
        "_desc": "控制 super_lookup.lua 反查滤镜的行为、引导符及声调支持。",
        "nodes": {
            "tags": {"title": "生效标签 (tags)", "type": "list_text", "desc": "检索当前tag的候选\n一行填一个，如: abc"},
            "key": {"title": "反查引导符 (key)", "type": "str", "desc": "默认: ` (需添加到 speller/alphabet 中)"},
            "lookup": {"title": "反查数据库 (lookup)", "type": "list_text", "desc": "反查滤镜数据库\n一行填一个，如: wanxiang_reverse"},
            "data_source": {"title": "数据来源 (data_source)", "type": "list_text", "desc": "基础版填 db，Pro版可加 comment"},
            "enable_tone": {"title": "启用声调反查 (enable_tone)", "type": "bool", "desc": "勾选开启声调反查支持"}
        }
    },
    "recognizer": {
        "_root_key": "recognizer",
        "_title": "🎯 正则识别器 (recognizer)",
        "_desc": "处理符合特定规则的输入码，如网址、反查、特定前缀引导等。",
        "nodes": {
            "import_preset": {"title": "继承预设", "type": "str", "desc": "默认: default"},
            "patterns": {
                "title": "触发规则表 (patterns)",
                "type": "dynamic_map",
                "desc": "格式必须为【键: 值】。值为正则表达式，支持任意增减和修改键名。"
            }
        }
    },
    "key_binder": {
        "_root_key": "key_binder",
        "_title": "⌨️ 快捷键与宏绑定 (key_binder)",
        "_desc": "自定义快捷键，支持翻页、方案切换、功能开关及按键宏(宏序列)。",
        "nodes": {
            "import_preset": {"title": "继承预设", "type": "str", "desc": "默认: default"},
            "shijian_keys": {"title": "时间引导符", "type": "list_text", "desc": "如 / 或 o，每行一个"},
            "bindings": {
                "title": "按键映射表 (bindings)",
                "type": "dynamic_block_list",
                "desc": "添加或修改快捷键绑定。【注意】：条件和动作在各自的下拉框选一个即可！",
                "template": {
                    "accept": {"title": "触发按键 (accept)", "type": "str", "desc": "如 Control+a 或 minus"},

                    "_condition": {
                        "title": "触发条件",
                        "type": "action_kv",
                        "preset_keys": {
                            "when": "状态条件 (always/has_menu/composing/paging)",
                            "match": "正则匹配 (如 ^/$)"
                        }
                    },

                    "_action": {
                        "title": "执行动作",
                        "type": "action_kv",
                        "preset_keys": {
                            "send": "映射按键 (send)",
                            "toggle": "切换开关 (toggle)",
                            "send_sequence": "发送宏串 (send_sequence)",
                            "select": "切换方案 (select)"
                        }
                    }
                }
            }
        }
    },
    "editor": {
        "_root_key": "editor",
        "_title": "📝 编辑器行为 (editor)",
        "_desc": "定义打字过程中各种快捷键的系统级处理逻辑（上屏、撤销、删除等）。",
        "nodes": {
            "bindings/space": {
                "title": "[ 空格键 ] space", 
                "type": "select", 
                "options": ["confirm", "commit_raw_input", "commit_script_text", "commit_comment"]
            },
            "bindings/Return": {
                "title": "[ 回车键 ] Return", 
                "type": "select", 
                "options": ["commit_raw_input", "confirm", "commit_script_text", "commit_comment"]
            },
            "bindings/Control+Return": {
                "title": "[ Ctrl+回车 ] Control+Return", 
                "type": "select", 
                "options": ["commit_script_text", "commit_raw_input", "confirm", "commit_comment"]
            },
            "bindings/Control+Shift+Return": {
                "title": "[ Ctrl+Shift+回车 ]", 
                "type": "select", 
                "options": ["commit_comment", "commit_script_text", "commit_raw_input", "confirm"]
            },
            "bindings/BackSpace": {
                "title": "[ 退格键 ] BackSpace", 
                "type": "select", 
                "options": ["revert", "back_syllable", "delete_candidate", "delete"]
            },
            "bindings/Delete": {
                "title": "[ 删除键 ] Delete", 
                "type": "select", 
                "options": ["delete", "revert", "back_syllable", "delete_candidate"]
            },
            "bindings/Control+BackSpace": {
                "title": "[ Ctrl+退格 ]", 
                "type": "select", 
                "options": ["back_syllable", "revert", "delete", "delete_candidate"]
            },
            "bindings/Control+Delete": {
                "title": "[ Ctrl+Delete ]", 
                "type": "select", 
                "options": ["delete_candidate", "delete", "revert", "back_syllable"]
            },
            "bindings/Escape": {
                "title": "[ Esc键 ] Escape", 
                "type": "select", 
                "options": ["cancel"]
            }
        }
    },
    "navigator": {
        "_root_key": "navigator",
        "_title": "🧭 光标导航器 (navigator)",
        "_desc": "控制光标在拼音编码串中的左右移动与跳转规则。",
        "nodes": {
            "bindings/Left": {
                "title": "[ 左方向键 ] Left", 
                "type": "select", 
                "options": ["left_by_char_no_loop", "left_by_char", "left_by_syllable", "left_by_syllable_no_loop", "rewind"]
            },
            "bindings/Right": {
                "title": "[ 右方向键 ] Right", 
                "type": "select", 
                "options": ["right_by_char_no_loop", "right_by_char", "right_by_syllable", "right_by_syllable_no_loop", "forward"]
            },
            "bindings/Shift+Left": {
                "title": "[ Shift+左 ] Shift+Left", 
                "type": "select", 
                "options": ["left_by_syllable", "left_by_syllable_no_loop", "left_by_char", "left_by_char_no_loop", "rewind"]
            },
            "bindings/Shift+Right": {
                "title": "[ Shift+右 ] Shift+Right", 
                "type": "select", 
                "options": ["right_by_syllable", "right_by_syllable_no_loop", "right_by_char", "right_by_char_no_loop", "forward"]
            }
        }
    },
    "user_dict_set": {
        "_root_key": "user_dict_set",
        "_title": "📕 自造词读取 (user_dict_set)",
        "_desc": "独立挂载的自定义词典引擎，用于读取和输出你造过的词。",
        "nodes": {
            "dictionary": {"title": "挂载主词库 (dictionary)", "type": "str", "desc": "如: wanxiang"},
            "user_dict": {"title": "自造词库名 (user_dict)", "type": "str", "desc": "默认: zc (对应 zc.userdb)"},
            "initial_quality": {"title": "初始权重 (initial_quality)", "type": "str", "desc": "默认: 0"},
            "enable_completion": {"title": "开启补全提示 (completion)", "type": "bool"},
            "enable_sentence": {"title": "开启自动造句 (sentence)", "type": "bool"},
            "enable_user_dict": {"title": "开启自动调频 (user_dict)", "type": "bool"},
            "contextual_suggestions": {"title": "智能上下文预测", "type": "bool", "desc": "若开启预测可能与连续长句冲突，导致组合不如预期"},
            "spelling_hints": {"title": "拼写提示长度", "type": "int"},
            "max_homophones": {"title": "最大同音词数", "type": "int"},
            "max_homographs": {"title": "最大同形词数", "type": "int"},
            "comment_format": {"title": "注释格式化规则", "type": "list_text", "desc": "留空即可"}
        }
    },
    "add_user_dict": {
        "_root_key": "add_user_dict",
        "_title": "✍️ 动态造词引擎 (add_user_dict)",
        "_desc": "负责写入自造词。双击前缀进入造词模式，或通过 Lua 脚本实现无感造词。",
        "nodes": {
            "tag": {"title": "生效标签 (tag)", "type": "str", "desc": "默认: add_user_dict"},
            "dictionary": {"title": "挂载主词库 (dictionary)", "type": "str", "desc": "如: wanxiang"},
            "user_dict": {"title": "目标词库名 (user_dict)", "type": "str", "desc": "默认: zc (生成的词会存入此处)"},
            "prefix": {"title": "手动造词引导符 (prefix)", "type": "str", "desc": "默认: `` (双击反引号)"},
            "tips": {"title": "造词提示语 (tips)", "type": "str", "desc": "如: 〔开始造词〕"},
            "initial_quality": {"title": "初始权重 (initial_quality)", "type": "str", "desc": "默认: -1"},
            "enable_completion": {"title": "开启补全提示 (completion)", "type": "bool", "desc": "提前显示尚未输入完整码的字"},
            "enable_user_dict": {"title": "开启自动调频 (user_dict)", "type": "bool"},
            "enable_auto_phrase": {"title": "启用 Lua 无感造词", "type": "bool", "desc": "模型已有词不造，只造未收录词，需配合 lua"},
            "spelling_hints": {"title": "拼写提示长度", "type": "int"},
            "comment_format": {"title": "注释格式化规则", "type": "list_text", "desc": "留空即可"}
        }
    },
    "tone_preedit": {
        "_root_key": "tone_preedit",
        "_title": "🎵 编码区声调转换 (tone_preedit)",
        "_desc": "常规状态下输入数字时，自动将其转换为对应的声调字符（由超级 preedit 接管）。\n【语法】格式为【键: 值】(如 7: ¹)。支持通过右侧按钮任意添加、移动、删除！",
        "nodes": {
            "__self__": {
                "title": "声调转换映射表",
                "type": "dynamic_map",
                "desc": "输入如 7: ¹，保存后自动生效。"
            }
        }
    },
    "force_upper_aux": {
        "_root_key": "force_upper_aux",
        "_title": "🅰️ 强制大写辅码(句中固定) (force_upper_aux)",
        "_desc": "控制强制大写辅码（固定候选）的快捷键与视觉替代符号。",
        "nodes": {
            "hotkey": {
                "title": "固定候选快捷键 (hotkey)", 
                "type": "str", 
                "desc": "默认: period (可用组合键或符号，如 Tab)"
            },
            "symbol": {
                "title": "视觉替代符号 (symbol)", 
                "type": "str", 
                "desc": "默认: › (用于避免双大写辅码导致输入提示被拉长)"
            }
        }
    }
}

# =====================================================================
# 左侧菜单：文件分类与索引元数据
# =====================================================================
FILE_INDEX_META = {
    "🌍 全局与通用配置": [
        {"file": "default.yaml", "name": "全局默认配置 (default)"},
        {"file": "wanxiang_algebra.yaml", "name": "拼写运算规则 (algebra)"},
    ],
    "👑 主输入方案": [
        {"file": "wanxiang.schema.yaml", "name": "基础版主方案 (wanxiang)"},
        {"file": "wanxiang_pro.schema.yaml", "name": "增强版主方案 (wanxiang_pro)"},
    ],
    "🧩 附属扩展方案": [
        {"file": "wanxiang_english.schema.yaml", "name": "英文方案 (english)"},
        {"file": "wanxiang_mixedcode.schema.yaml", "name": "混合编码方案 (mixedcode)"},
        {"file": "wanxiang_reverse.schema.yaml", "name": "反查方案 (reverse)"},
        {"file": "wanxiang_t9.schema.yaml", "name": "T9九宫格方案 (t9)"},
    ]
}
# ============== 键盘按键与 Rime 标识符映射表 ==============
RIME_KEY_MAP = {
    " ": "space", "!": "exclam", "\"": "quotedbl", "#": "numbersign", "$": "dollar",
    "%": "percent", "&": "ampersand", "'": "apostrophe", "(": "parenleft", ")": "parenright",
    "*": "asterisk", "+": "plus", ",": "comma", "-": "minus", ".": "period", "/": "slash",
    ":": "colon", ";": "semicolon", "<": "less", "=": "equal", ">": "greater", "?": "question",
    "@": "at", "[": "bracketleft", "\\": "backslash", "]": "bracketright", "^": "asciicircum",
    "_": "underscore", "`": "grave", "{": "braceleft", "|": "bar", "}": "braceright", "~": "asciitilde"
}

# 辅助函数：安全读写嵌套字典 (全面支持 Rime 的 @0 数组语法)
def _get_nested_val(d, path, default=None):
    if not path: return default
    curr = d
    for k in path.split('/'):
        # 1. 解析字典类型
        if hasattr(curr, 'get') and k in curr:
            curr = curr[k]
        # 2. 解析列表类型 (兼容 Rime 的 @ 索引语法)
        elif (isinstance(curr, list) or hasattr(curr, 'append')) and k.startswith('@'):
            try:
                idx = int(k[1:]) # 把 "@7" 变成数字 7
                if 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return default
            except ValueError:
                return default
        # 3. 找不到则退回默认值
        else:
            return default
    return curr

def _set_nested_val(d, path, val):
    keys = path.split('/')
    curr = d
    for k in keys[:-1]:
        if k not in curr or not isinstance(curr[k], dict): curr[k] = {}
        curr = curr[k]
    curr[keys[-1]] = val
# —— GitHub 链接 ——
GITHUB_LINKS = [
    ("万象拼音项目主页", "https://github.com/amzxyz/rime_wanxiang"),
    ("万象语法模型与词库工具", "https://github.com/amzxyz/RIME-LMDG"),
    ("CNB国内仓库",   "https://cnb.cool/amzxyz/rime-wanxiang"),
]

# —— 在线更新相关常量 ——
OWNER = "amzxyz"
REPO = "rime_wanxiang"
CNB_REPO = "rime-wanxiang"
MODEL_REPO = "RIME-LMDG"
DICT_TAG = "dict-nightly"
MODEL_FILE = "wanxiang-lts-zh-hans.gram"
MODEL_TAG = "LTS"

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
    use_mirror: bool
    whitelist: List[str]
    current_versions: Dict[str, str]
    clean_build: bool
    clean_before: bool
    custom_url: Optional[str] # 自定义下载源 URL
    server_path: str = ""   # 算法服务路径 (WeaselServer.exe)
    deployer_path: str = "" # 部署工具路径 (WeaselDeployer.exe)
    force_update: bool = False #强制更新
class PathDetector:
    @staticmethod
    def detect() -> Dict[str, str]:
        detected = {'rime_user_dir': '', 'weasel_server': '', 'weasel_deployer': ''}
        
        if SYSTEM_TYPE == 'windows':
            import winreg
            try:
                # 1. 找 RimeUserDir
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Rime\Weasel") as key:
                    detected['rime_user_dir'], _ = winreg.QueryValueEx(key, "RimeUserDir")
                
                # 2. 找 Weasel 安装目录
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Rime\Weasel") as key:
                    root, _ = winreg.QueryValueEx(key, "WeaselRoot")
                    if root:
                        detected['weasel_server'] = os.path.join(root, "WeaselServer.exe")
                        detected['weasel_deployer'] = os.path.join(root, "WeaselDeployer.exe")
            except: pass
            
            # 回退机制：如果没找到，尝试在默认 AppData 找 UserDir
            if not detected['rime_user_dir']:
                appdata = os.environ.get('APPDATA', '')
                if appdata: detected['rime_user_dir'] = os.path.join(appdata, 'Rime')
                
        elif SYSTEM_TYPE == 'macos':
            detected['rime_user_dir'] = os.path.expanduser('~/Library/Rime')
            # macOS 下没有独立的 exe，通常是通过命令控制 Squirrel
        else:
             detected['rime_user_dir'] = os.path.expanduser('~/.local/share/fcitx5/rime')
             
        return detected

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

        self.headers_cnb = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.cnb.web+json"}
        self.headers_gh = {"User-Agent": "Rime-Wanxiang-Tool"}
        if self.cfg.github_token:
            self.headers_gh["Authorization"] = f"Bearer {self.cfg.github_token}"
            
    def log(self, msg): self.log_sig.emit(msg)
    def stop(self): self._stop = True

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
            try:
                subprocess.run(['killall', 'Squirrel'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except: pass

    def _start_and_deploy(self):
        """执行 Rime 部署/重载"""
        # 1. 强制清理 build (如勾选)
        if self.cfg.clean_build:
            build_dir = os.path.join(self.cfg.rime_dir, "build")
            if os.path.exists(build_dir):
                try:
                    shutil.rmtree(build_dir)
                    self.log("🧹 已强制删除 build 目录，触发全量重新编译。")
                except: pass

        # 2. Windows 逻辑 (小狼毫)
        if SYSTEM_TYPE == 'windows':
            try:
                if self.cfg.server_path and os.path.exists(self.cfg.server_path):
                    subprocess.Popen([self.cfg.server_path], creationflags=0x08000000)
                    time.sleep(3)
                if self.cfg.deployer_path and os.path.exists(self.cfg.deployer_path):
                    subprocess.Popen([self.cfg.deployer_path, "/deploy"], creationflags=0x08000000)
                    self.log("✅ Windows 部署指令已发送。")
            except Exception as e:
                self.log(f"❌ Windows 部署调用失败: {e}")

        # 3. macOS 逻辑 (鼠须管)
        elif SYSTEM_TYPE == 'macos':
            try:
                subprocess.run(['osascript', '-e', 'tell application "Squirrel" to reload configuration'], check=True)
                self.log("✅ macOS 部署通知已发送。")
            except: pass

        # 4. Linux 逻辑 (Fcitx5/IBus)
        elif SYSTEM_TYPE == 'android/linux':
            im = self._get_linux_im_system()
            if im == "fcitx5":
                self._deploy_linux_fcitx5_safe()
            elif im == "ibus":
                self._deploy_linux_ibus()
    def _deploy_linux_fcitx5_safe(self):
        """Linux Fcitx5 部署方案 (使用 dbus-send)"""
        self.log(">>> [Fcitx5] 正在触发 Rime 部署 (dbus-send)...")
        dbus_tool = shutil.which("dbus-send")
        
        if not dbus_tool:
            self.log("❌ 错误: 未找到 dbus-send 工具。请检查系统是否安装了 dbus。")
            return

        try:
            # 2. 构建命令 (dbus-send 强制指定类型为 string 和 variant)
            cmd = [
                dbus_tool,
                "--session",
                "--dest=org.fcitx.Fcitx5",
                "--type=method_call",
                "/controller",
                "org.fcitx.Fcitx.Controller1.SetConfig",
                "string:fcitx://config/addon/rime/deploy",
                "variant:string:"  # 注意这里，对应 Fcitx5 需要的 variant 类型空值
            ]
            
            self.log("📡 发送 DBus 信号指令: " + " ".join(cmd))
            clean_env = os.environ.copy()
            if 'LD_LIBRARY_PATH' in clean_env:
                clean_env['LD_LIBRARY_PATH'] = clean_env.get('LD_LIBRARY_PATH_ORIG', '')
            subprocess.run(cmd, env=clean_env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.log("✅ Fcitx5 部署信号发送成功。")

        except subprocess.CalledProcessError as e:
            # 划重点：把底层真正的英文报错内容解出来！
            error_details = e.stderr.decode('utf-8', errors='ignore').strip() if e.stderr else "无详细错误信息"
            self.log(f"❌ 部署失败 (命令返回非零): {e.returncode}")
            self.log(f"🔍 详细原因: {error_details}")
        except Exception as e:
            self.log(f"❌ 发送指令时发生异常: {e}")

    def _deploy_linux_ibus(self):
        """Linux IBus 部署方案 (保持原样)"""
        self.log("📡 [IBus] 正在重启 IBus 以触发重载...")
        ibus_cmd = shutil.which("ibus")
        if ibus_cmd:
            try:
                subprocess.run([ibus_cmd, "restart"], check=True)
                self.log("✅ [IBus] 重启指令已发送")
            except Exception as e:
                self.log(f"❌ IBus 重启指令失败: {e}")

    def _get_linux_im_system(self):
        """简单探测当前运行的输入法框架 (保持原样)"""
        try:
            if shutil.which("pgrep"):
                if subprocess.run(["pgrep", "fcitx5"], stdout=subprocess.DEVNULL).returncode == 0: return "fcitx5"
                if subprocess.run(["pgrep", "ibus-daemon"], stdout=subprocess.DEVNULL).returncode == 0: return "ibus"
        except: pass
        return "unknown"

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
        """获取 API 数据 (保持原样)"""
        # 1. === 检查缓存 ===
        if url in self._api_cache:
            return self._api_cache[url]

        # 2. === 准备请求 ===
        headers = {"Accept": "application/json"} if is_cnb else self.headers_gh
        
        # 3. === 发起网络请求 ===
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                
                # 4. === 写入缓存 (关键步骤) ===
                self._api_cache[url] = data
                return data
            else:
                self.log(f"[Warn] API 请求失败 ({r.status_code}): {url}")
                return None
        except Exception as e:
            self.log(f"[Warn] API 连接异常: {e}")
            return None

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
            
            self.log(f"⚡ [{src_name}] 跳过 API 检查，直接连接: {real_fn}")
            return {
                "url": direct_url, "tag": release_tag, "src": src_name,
                "hash": "", "time": "", "name": real_fn
            }
        # --- 以下是原有逻辑：方案组件尝试走 CNB API，模型走直链 ---
        cnb_info = None
        if self.cfg.use_mirror:
            cnb_url = f"https://cnb.cool/{OWNER}/{repo_cnb}/-/releases"
            headers = {"User-Agent": "curl/7.68.0", "Accept": "application/json"}
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
        self.log(f"⏳ 正在连接 GitHub API 查找: {pattern} ...")
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
        
        return None
    def _download(self, url, dest):
        """增强版下载：带重试、断点续传保护、完整性校验"""
        max_retries = 3
        timeout_sec = 60
        
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    self.log(f"🔄 网络波动，正在进行第 {attempt}/{max_retries} 次重试...")
                
                h = self.headers_cnb if "cnb.cool" in url else self.headers_gh
                
                # 发起请求
                with requests.get(url, headers=h, stream=True, timeout=timeout_sec) as r:
                    r.raise_for_status()
                    
                    # 获取预期大小
                    total_size = int(r.headers.get('content-length', 0))
                    downloaded_size = 0
                    
                    with open(dest, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=16384):
                            if self._stop: return False
                            if chunk:
                                f.write(chunk)
                                downloaded_size += len(chunk)
                                self.progress_sig.emit("下载中", downloaded_size, total_size)
                
                # === [关键修改] 下载后的完整性校验 ===
                
                # 1. 检查文件是否存在且不为空
                if not os.path.exists(dest) or os.path.getsize(dest) == 0:
                    raise Exception("下载失败：文件为空或未写入")
                
                # 2. 如果服务器提供了大小，校验本地文件大小是否一致
                local_size = os.path.getsize(dest)
                if total_size > 0 and local_size != total_size:
                    raise Exception(f"文件不完整 (预期 {total_size} 字节，实际 {local_size} 字节)")
                
                return True # 只有通过校验才算成功

            except Exception as e:
                self.log(f"⚠️ 下载出错 (第{attempt}次): {str(e)}")
                # 删除可能损坏的残留文件
                if os.path.exists(dest):
                    try: os.remove(dest)
                    except: pass
                
                if attempt < max_retries:
                    time.sleep(2) # 稍等后重试
                else:
                    self.log("❌ 下载彻底失败，请检查网络或代理设置。")
                    return False
        return False

    def _detect_smart_root(self, extract_root: str, task_type: str) -> str:
        """智能解压根目录检测"""
        self.log(f"🔎 正在智能分析解压路径 ({task_type})...")
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
                self.log(f"🚀 开始更新任务 | 模式: {mode_dict.get(self.cfg.scope, '未知')}")
                self.log(f"📂 目标目录: {self.cfg.rime_dir}")
                
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
                # --- 2. 纯下载循环 (进程活跃中) ---
                for task_type, gh_repo, cnb_repo, pattern, final_dest, specific_tag in tasks:
                    if self._stop: break
                    
                    self.log(f"\n📦 正在检查 {task_type}...")
                    
                    if task_type == 'CustomZip':
                        remote_data = {"url": self.cfg.custom_url, "tag": "custom", "src": "Custom URL", "hash": "", "time": "", "name": "custom.zip"}
                    else:
                        # 传入 task_type 参数
                        remote_data = self._check_url(cnb_repo, gh_repo, pattern, specific_tag, task_type)
                    
                    if not remote_data:
                        self.log(f"⚠️ 跳过: 未能获取到 {task_type} 的远程资源。"); continue

                    url, tag, remote_hash = remote_data['url'], remote_data['tag'], remote_data.get('hash')
                    should_skip = False
                    if task_type == '预览方案':
                        self.log(f"   ℹ️ [检测结果] {task_type} (内测)")
                        self.log(f"      ✨ 预览版不参与版本比对，直接执行覆盖下载！")
                        should_skip = False  # 永远不跳过
                        
                    elif task_type == '方案组件':
                        if tag.lower().startswith('v'): tag = tag[1:]
                        local_ver = self.cfg.current_versions.get('方案组件', "0.0.0")
                        if local_ver == "0.0.0": local_ver = "未记录"
                        
                        self.log(f"   ℹ️ [检测结果] {task_type}")
                        self.log(f"      版本对比: 本地[{local_ver}] vs 在线[{tag}]")
                        
                        if not self.cfg.force_update and tag == local_ver:
                            self.log(f"      ✨ 版本一致: {tag} 已最新，跳过。")
                            should_skip = True

                    elif task_type == 'CustomZip':
                        self.log(f"   ℹ️ [检测结果] 自定义压缩包直连")
                        
                    else:
                        key_map = {'词库组件': 'dict_hash', '语法模型': 'model_hash'}
                        key = key_map.get(task_type, "")
                        local_hash = self.cfg.current_versions.get(key, "")
                        
                        d_l = local_hash[:8] if local_hash else "无"
                        d_r = remote_hash[:8] if remote_hash else "无(直链模式)"
                        
                        self.log(f"   ℹ️ [检测结果] {task_type} (独立更新通道)")
                        self.log(f"      Hash对比: 本地[{d_l}] vs 在线[{d_r}]")
                        
                        if not self.cfg.force_update:
                            if remote_hash and local_hash == remote_hash:
                                self.log(f"      ✨ 校验一致: 文件未改变，跳过。")
                                should_skip = True

                    if should_skip: continue

                    self.log(f"🌐 来源: [{remote_data['src']}] | 🚀 正在下载...")
                    fname = os.path.basename(url.split('?')[0]) or f"update_{task_type}.tmp"
                    local_download_path = os.path.join(temp_root, fname)
                    
                    if self._download(url, local_download_path):
                        if task_type == '语法模型' and remote_hash:
                            if self._calculate_sha256(local_download_path) != remote_hash:
                                self.log(f"❌ 错误: 文件校验失败，跳过安装。"); continue
                        
                        # 核心点：只添加到列表，暂不安装
                        pending_tasks.append({
                            'type': task_type,
                            'path': local_download_path,
                            'dest': final_dest,
                            'ver': tag,
                            'hash': remote_hash
                        })
                        self.log(f"📥 {task_type} 下载完毕，进入安装队列。")

                # --- 3. 统一杀进程 ---
                if not pending_tasks and not self.cfg.clean_before:
                    self.log("✅ 检查完毕，无需更新。")
                    self.done_sig.emit(True, "所有组件已是最新。"); return
                time.sleep(2)
                if self._stop: return

                self.log(f"\n{'='*40}")
                self.log("🛑 下载全部完成，正在终止进程以开始安装...")
                self._kill_rime_process() # 此时才杀进程

                if self.cfg.clean_before:
                    self.log("🧹 [清理] 正在执行Clean模式...")
                    target = os.path.join(self.cfg.rime_dir, "dicts") if self.cfg.scope == 2 else self.cfg.rime_dir
                    self._clean_dir_recursive(target)

                # --- 4. 统一安装循环 ---
                for task in pending_tasks:
                    if self._stop: break
                    
                    t_type = task['type']
                    src_path = task['path']
                    dst_dir = task['dest']
                    
                    self.log(f"📦 正在安装: {t_type} ...")
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

                            self._safe_merge_dir(real_source_dir, dst_dir)

                        if not self.cfg.custom_url:
                            # 修改这里：只有正式版方案才记录版本号
                            if t_type == '方案组件':
                                self.version_sig.emit("方案组件", task['ver'])
                            
                            real_hash = task['hash']
                            if not real_hash and os.path.exists(src_path):
                                real_hash = self._calculate_sha256(src_path)

                            # 修改这里：不记录预览方案的 Hash
                            if real_hash:
                                if t_type == '词库组件': self.version_sig.emit("dict_hash", real_hash)
                                elif t_type == '语法模型': self.version_sig.emit("model_hash", real_hash)
                        
                        needs_deploy = True
                        self.log(f"✅ {t_type} 安装成功。")

                    except Exception as e:
                        self.log(f"❌ 安装 {t_type} 失败: {e}")

                # --- 5. 部署 ---
                if needs_deploy or self.cfg.clean_build:
                    self.log("⚙️ 正在触发部署...")
                    self._start_and_deploy()
                    self.done_sig.emit(True, "✨ 更新并部署完成。")
                else:
                    self.done_sig.emit(True, "更新流程结束。")

            except Exception as e:
                import traceback
                self.log(f"❌ 严重错误: {e}")
                self.done_sig.emit(False, f"更新异常: {e}")
# ============== 检查更新机制 ==============
class CheckUpdateWorker(QThread):
    result_sig = Signal(dict)

    def run(self):
        results = {}
        headers = {"User-Agent": "Rime-Wanxiang-Tool"}
        
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
            r = requests.get("https://api.github.com/repos/amzxyz/rime_wanxiang/releases", headers=headers, timeout=8)
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
            r = requests.get(f"https://api.github.com/repos/amzxyz/rime_wanxiang/releases/tags/{DICT_TAG}", headers=headers, timeout=8)
            if r.status_code == 200:
                assets = r.json().get('assets', [])
                remote_hash = next(((a.get('sha256', '') or (a.get('digest', '').split(':')[-1] if 'digest' in a else '')) for a in assets if 'dicts.zip' in a['name']), "")
                results['dict'] = remote_hash[:8] if remote_hash else DICT_TAG
            else: results['dict'] = DICT_TAG
        except: results['dict'] = '网络错误'

        try:
            r = requests.get(f"https://api.github.com/repos/amzxyz/RIME-LMDG/releases/tags/{MODEL_TAG}", headers=headers, timeout=8)
            if r.status_code == 200:
                assets = r.json().get('assets', [])
                remote_hash = next(((a.get('sha256', '') or (a.get('digest', '').split(':')[-1] if 'digest' in a else '')) for a in assets if a['name'] == MODEL_FILE), "")
                results['model'] = remote_hash[:8] if remote_hash else 'model'
            else: results['model'] = 'model'
        except: results['model'] = '网络错误'
        
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
class YamlFixDialog(QDialog):
    """内置的 YAML 冲突修复编辑器"""
    def __init__(self, parent, file_path, key_name, error_details):
        super().__init__(parent)
        self.setWindowTitle("🛠️ 配置文件修复工具")
        self.resize(800, 600)
        self.file_path = file_path

        lay = QVBoxLayout(self)

        # --- 顶部警告信息 ---
        lbl_warn = QLabel(f"⚠️ 发现冲突的重复配置项：<b>【 {key_name} 】</b><br>"
                          f"请在下方编辑器中找到报错的行数，将多余的项删除或加上 # 注释，然后点击保存。")
        lbl_warn.setStyleSheet("color: #d9534f; font-size: 14px; margin-bottom: 5px;")
        lay.addWidget(lbl_warn)

        # --- 错误详情（方便看行号） ---
        lbl_details = QLabel(error_details)
        lbl_details.setStyleSheet("background-color: #f8f9fa; padding: 5px; border: 1px solid #ccc;")
        lbl_details.setWordWrap(True)
        lay.addWidget(lbl_details)

        # --- 文本编辑器 ---
        self.editor = QPlainTextEdit()
        # 设置等宽字体
        font = self.editor.font()
        font.setFamily("Consolas")
        font.setPointSize(11)
        self.editor.setFont(font)
        # 支持不自动换行（写代码更舒服）
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        lay.addWidget(self.editor)

        # 加载文件内容
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self.editor.setPlainText(f.read())
        except Exception as e:
            self.editor.setPlainText(f"无法读取文件：{e}")

        # --- 底部按钮 ---
        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 保存修改并重试")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet("background-color: #5cb85c; color: white; padding: 6px 15px; font-weight: bold; border-radius: 4px;")
        btn_save.clicked.connect(self.save_and_accept)

        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        lay.addLayout(btn_box)

    def save_and_accept(self):
        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                f.write(self.editor.toPlainText())
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法写入文件:\n{e}")
class YamlDuplicateFixDialog(QDialog):
    """智能 YAML 重复键冲突提取与修复弹窗"""
    def __init__(self, parent, file_path, key_name, lines_info):
        super().__init__(parent)
        self.setWindowTitle("🧩 智能修复：配置项冲突")
        self.setMinimumWidth(650)
        self.file_path = file_path
        self.lines_info = lines_info  # 结构: [(行索引, 原始文本), ...]

        lay = QVBoxLayout(self)

        # --- 顶部说明 ---
        lbl_warn = QLabel(
            f"⚠️ 检测到键名 <b>【 {key_name} 】</b> 在文件中被定义了多次！<br>"
            "YAML 语法要求同层级不能有重复项。请在下方对比并处理。<br>"
            "👉 <b>处理方式：</b>如果要保留请直接修改（如改名或改值）；<span style='color:#d9534f;'>若要删除某项，请直接清空该输入框！</span>"
        )
        lbl_warn.setStyleSheet("font-size: 13px; margin-bottom: 10px;")
        lay.addWidget(lbl_warn)

        self.edits = []
        
        # --- 动态生成上下对比输入框 ---
        for i, (l_idx, text) in enumerate(self.lines_info):
            # 区分一下原定义和后来的重复定义
            title = f"📝 第 {l_idx + 1} 行 (原始定义)" if i == 0 else f"💥 第 {l_idx + 1} 行 (冲突定义)"
            gb = QGroupBox(title)
            gb.setStyleSheet("QGroupBox { font-weight: bold; color: #333; }")
            flay = QVBoxLayout(gb)

            edit = QLineEdit(text.strip('\n'))
            # 使用等宽字体，保留缩进感
            font = edit.font()
            font.setFamily("Consolas")
            font.setPointSize(11)
            edit.setFont(font)
            
            edit.setPlaceholderText("（清空此框将自动删除该行代码）")
            
            flay.addWidget(edit)
            lay.addWidget(gb)
            self.edits.append(edit)

        # --- 底部按钮 ---
        btn_box = QHBoxLayout()
        btn_cancel = QPushButton("取消加载")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 落地保存并继续")
        btn_save.setCursor(Qt.PointingHandCursor)
        btn_save.setStyleSheet("background-color: #d9534f; color: white; font-weight: bold; padding: 6px 20px; border-radius: 4px;")
        btn_save.clicked.connect(self.save_and_accept)

        btn_box.addStretch()
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        lay.addLayout(btn_box)

    def save_and_accept(self):
        try:
            # 1. 读出所有行
            with open(self.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # 2. 定点替换：根据行号精准写回
            for i, (l_idx, old_text) in enumerate(self.lines_info):
                new_text = self.edits[i].text()
                if not new_text.strip():
                    # 用户清空了这一行，直接将该行置空（相当于删除，且不影响后续行号索引）
                    lines[l_idx] = "" 
                else:
                    lines[l_idx] = new_text + "\n"

            # 3. 写入文件
            with open(self.file_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)

            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法写入文件:\n{e}")
# 智能异步缓存预读线程
class YamlCacheWorker(QThread):
    finished_sig = Signal(str, object, dict)
    all_finished_sig = Signal()
    
    def __init__(self, rime_dir, files):
        super().__init__()
        self.rime_dir = rime_dir
        self.files = files
        self._stop = False
        
    def run(self):
        if not HAS_RUAMEL: 
            self.all_finished_sig.emit()
            return
        from ruamel.yaml import YAML
        yaml = YAML(); yaml.preserve_quotes = True
        
        for f in self.files:
            if self._stop: break
            sp = os.path.join(self.rime_dir, f)
            if f.endswith(".schema.yaml"):
                c_name = f.replace(".schema.yaml", ".custom.yaml")
            elif f.endswith(".yaml"):
                c_name = f.replace(".yaml", ".custom.yaml")
            else:
                c_name = ""
                
            cp = os.path.join(self.rime_dir, c_name) if c_name else ""
            
            try:
                s_data = None
                if os.path.exists(sp):
                    with open(sp, 'r', encoding='utf-8') as file: s_data = yaml.load(file)
                
                c_patch = {}
                if cp and os.path.exists(cp):
                    with open(cp, 'r', encoding='utf-8') as file:
                        c_data = yaml.load(file)
                        if c_data: c_patch = c_data.get('patch', {})
                        
                if s_data is not None:
                    self.finished_sig.emit(f, s_data, c_patch)
            except: pass
            
        if not self._stop:
            self.all_finished_sig.emit()  # 发送完工信号
# 专为 schema_list 定制的特制复选框工厂
class SchemaCheckboxesWidget(QWidget):
    needs_resize = Signal(int)
    
    def __init__(self, rime_dir, current_val):
        super().__init__()
        # 整体大背景：纯白 + 莫兰迪绿边框
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 12, 12, 12)
        self.lay.setSpacing(6) 
        self.checkboxes = []
        self.setStyleSheet("background-color: transparent;")
        
        import glob, os
        schemas = []
        
        # 1. 核心过滤名单：加入 wanxiang_t9
        ALLOWED_SCHEMAS = ["wanxiang", "wanxiang_pro", "wanxiang_english", "wanxiang_t9"]
        
        search_path = os.path.join(rime_dir, "*.schema.yaml")
        for f_path in glob.glob(search_path):
            s_id = os.path.basename(f_path).replace(".schema.yaml", "")
            
            if s_id not in ALLOWED_SCHEMAS:
                continue
                
            s_name = s_id 
            try:
                with open(f_path, 'r', encoding='utf-8') as file:
                    for line in file:
                        line = line.strip()
                        if line.startswith("name:"):
                            s_name = line.split("name:", 1)[1].strip().strip('\'"')
                            break
            except: pass
            
            schemas.append({'id': s_id, 'name': s_name})
            
        # 按照名单顺序排序
        schemas.sort(key=lambda x: ALLOWED_SCHEMAS.index(x['id']) if x['id'] in ALLOWED_SCHEMAS else 99)
            
        active_ids = []
        if isinstance(current_val, list):
            for item in current_val:
                if isinstance(item, dict) and 'schema' in item:
                    active_ids.append(item['schema'])
        
        if not schemas:
            lbl = QLabel("⚠️ 未找到核心方案文件")
            lbl.setStyleSheet("color: #d9534f; font-weight: bold;")
            self.lay.addWidget(lbl)
            h = 45
        else:
            for s in schemas:
                # 每行一个容器
                row_w = QWidget()
                # 关键：去掉行容器的背景和边框，防止“套娃”变丑
                row_w.setStyleSheet("background: transparent; border: none;")
                row_lay = QHBoxLayout(row_w)
                row_lay.setContentsMargins(0, 2, 0, 2)
                row_lay.setSpacing(12)
                
                # [√] 复选框部分
                cb = QCheckBox(s['name'])
                cb.setProperty("schema_id", s['id'])
                # 设置复选框样式：加粗字体，莫兰迪绿色的勾选感
                cb.setStyleSheet("QCheckBox { font-size: 14px; font-weight: bold; }")
                if s['id'] in active_ids: cb.setChecked(True)
                cb.clicked.connect(self.validate_at_least_one)
                # (id) 莫兰迪绿圈圈部分
                lbl_id = QLabel(s['id'])
                lbl_id.setStyleSheet("""
                    QLabel {
                        background-color: rgba(97, 161, 101, 0.15); 
                        color: #61A165; 
                        border-radius: 12px; 
                        padding: 2px 12px; 
                        font-size: 11px; 
                        font-weight: bold;
                        font-family: 'Consolas', 'Monaco', monospace;
                        border: 1px solid rgba(97, 161, 101, 0.3);
                    }
                """)
                
                row_lay.addWidget(cb)
                row_lay.addWidget(lbl_id)
                row_lay.addStretch() 
                
                self.lay.addWidget(row_w)
                self.checkboxes.append(cb)
                
            h = len(schemas) * 38 + 24
            
        self.setFixedHeight(h)
        self.setSizePolicy(self.sizePolicy().Policy.Expanding, self.sizePolicy().Policy.Fixed)
        
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, lambda: self.needs_resize.emit(h))
            
    def get_value(self):
        res = []
        for cb in self.checkboxes:
            if cb.isChecked(): res.append({'schema': cb.property("schema_id")})
        return res
    def validate_at_least_one(self):
        """核心逻辑：确保至少保留一个方案"""
        checked_boxes = [cb for cb in self.checkboxes if cb.isChecked()]
        
        if len(checked_boxes) == 0:
            sender = self.sender()
            if sender:
                sender.setChecked(True)
            from PySide6.QtWidgets import QMessageBox
            msg = QMessageBox(self)
            msg.setWindowTitle("提示")
            msg.setText("⚠️ 输入法必须至少保留一个启用方案！")
            msg.setIcon(QMessageBox.Information)
            msg.exec()
# ============== GUI ==============
class MainWin(QWidget):
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
        self.tabs.addTab(self.tab_yaml, "高级设置(YAML开发中)")
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
        
        self.check_worker = CheckUpdateWorker() # 恢复原来的无参数调用
        self.check_worker.result_sig.connect(self.on_check_update_result)
        self.check_worker.start()
        
    def on_check_update_result(self, remote_vers):
        self.status.setText("就绪")
        
        # 恢复读取没有后缀的 dict_hash 和 model_hash
        local_dict = self.settings.value("installed_versions/dict_hash", "0.0.0")
        local_dict_display = local_dict[:8] if len(local_dict) > 8 else local_dict
        
        local_model = self.settings.value("installed_versions/model_hash", "0.0.0")
        local_model_display = local_model[:8] if len(local_model) > 8 else local_model
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
        self.rb_src_auto = QRadioButton("自动(CNB>GitHub)")
        self.rb_src_gh = QRadioButton("GitHub")
        self.bg_src.addButton(self.rb_src_auto, 1)
        # [视觉容器] GitHub + 检查更新
        self.gh_frame = QFrame()
        self.gh_frame.setObjectName("ghBox")
        # 样式已移交 apply_palette 统一管理，支持暗黑模式切换
        gh_lay = QHBoxLayout(self.gh_frame)
        gh_lay.setContentsMargins(8, 2, 8, 2)
        
        self.rb_src_gh = QRadioButton("GitHub")
        self.bg_src.addButton(self.rb_src_gh, 0)
        
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
        
        gh_lay.addWidget(self.rb_src_gh)
        gh_lay.addSpacing(10)
        gh_lay.addWidget(self.btn_check_update)
        self.rb_src_auto.setChecked(True)
        row_src.addWidget(self.rb_src_auto)
        row_src.addSpacing(15)
        row_src.addWidget(self.gh_frame)
        row_src.addStretch()
        self.upd_token = QLineEdit(); self.upd_token.setPlaceholderText("GitHub Token (可选)")
        self.upd_token.setEchoMode(QLineEdit.Password)
        
        form.addRow("Rime目录:", r_rime)
        form.addRow("下载源:", self.row_src_widget)
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
        is_auto_mirror = (self.bg_src.checkedId() == 1)
        
        # 获取检测到的路径
        srv_path = getattr(self, 'detected_server', '')
        dep_path = getattr(self, 'detected_deployer', '')

        cfg = UpdateConfig(
            scope=self.bg_scope.checkedId(),
            scheme_type='base' if self.bg_ver.button(1).isChecked() else 'pro',
            aux_scheme=aux_key,
            rime_dir=rime_dir,
            github_token=self.upd_token.text(),
            use_mirror=is_auto_mirror,
            whitelist=whitelist_lines,
            current_versions=versions,
            clean_before=clean_mode,
            clean_build=self.chk_clean_build.isChecked(),
            custom_url=custom_url,
            server_path=srv_path,
            deployer_path=dep_path,
            force_update=self.chk_force.isChecked()
        )
        
        self.log.clear()
        self.log.appendPlainText(">>> 开始在线更新任务")
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
        if self.upd_worker: self.upd_worker.stop()

    def on_update_done(self, ok, msg):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.tabs.setEnabled(True)
        self.status.setText("完成" if ok else "失败")
        self.log.appendPlainText(msg)
        if ok: QMessageBox.information(self, "完成", msg)
        else: QMessageBox.warning(self, "错误", msg)
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
    def _build_tab_schema_config(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)

        if not HAS_RUAMEL:
            warn = QLabel("⚠️ 缺少 ruamel.yaml 库，无法安全读写 YAML。\n请在终端运行: pip install ruamel.yaml 后重启工具。")
            warn.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 14px;")
            lay.addWidget(warn)
            lay.addStretch()
            return w

        from PySide6.QtWidgets import QSplitter, QFrame, QTreeWidget, QHeaderView, QStackedWidget

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(8) 

        # ==================== 左侧：导航与搜索结果区 ====================
        self.left_frame = QFrame()
        self.left_frame.setObjectName("leftNavFrame")
        left_lay = QVBoxLayout(self.left_frame)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        
        self.left_frame.setMinimumWidth(220)

        nav_tool_lay = QHBoxLayout()
        nav_tool_lay.setSpacing(1)
        
        btn_style = """
            QPushButton { background-color: transparent; color: #61A165; font-weight: bold; font-size: 13px; padding: 10px 5px; border: none; border-bottom: 1px solid #A8C7AA; }
            QPushButton:hover { background-color: rgba(97, 161, 101, 0.1); }
            QPushButton:pressed { background-color: rgba(97, 161, 101, 0.2); }
        """
        self.btn_scan_nav = QPushButton("📂 更换目录")
        self.btn_scan_nav.setCursor(Qt.PointingHandCursor)
        self.btn_scan_nav.setStyleSheet(btn_style + "border-top-left-radius: 6px;")
        self.btn_scan_nav.clicked.connect(self.load_other_directory)
        
        self.btn_refresh_nav = QPushButton("🔄 重新加载")
        self.btn_refresh_nav.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_nav.setStyleSheet(btn_style + "border-top-right-radius: 6px; border-left: 1px solid #A8C7AA;")
        self.btn_refresh_nav.clicked.connect(self.scan_rime_directory)

        nav_tool_lay.addWidget(self.btn_scan_nav)
        nav_tool_lay.addWidget(self.btn_refresh_nav)
        left_lay.addLayout(nav_tool_lay)
        self.nav_tree = QTreeWidget()
        self.nav_tree.setHeaderHidden(True)
        self.nav_tree.setFrameShape(QFrame.NoFrame) 
        self.nav_tree.setRootIsDecorated(False) 
        self.nav_tree.setItemsExpandable(False) 
        self.nav_tree.setIndentation(18) 

        self.nav_tree.setObjectName("leftNavTree")
        self.nav_tree.itemClicked.connect(self.on_nav_item_clicked)
        left_lay.addWidget(self.nav_tree)
        self.splitter.addWidget(self.left_frame)

        # ==================== 右侧：配置展示区 ====================
        right_widget = QWidget()
        right_lay = QVBoxLayout(right_widget)
        right_lay.setContentsMargins(10, 0, 0, 0)
        right_lay.setSpacing(10)

        h_tools = QHBoxLayout()
        self.lbl_current_target = QLabel("请在左侧选择文件")
        self.lbl_current_target.setStyleSheet("color: #888; font-style: italic; font-weight: bold; margin-left: 10px;")
        h_tools.addWidget(self.lbl_current_target)
        
        h_tools.addStretch()

        self.bg_save_mode = QButtonGroup(self)
        self.rb_patch_mode = QRadioButton("🪡 补丁模式")
        self.rb_direct_mode = QRadioButton("⚠️ 直写模式")
        
        self.rb_patch_mode.setToolTip("推荐：修改将存入 .custom.yaml，保护原文件。")
        self.rb_direct_mode.setToolTip("警告：修改将直接覆盖原文件！(不支持 patch 的文件必须使用此项)")
        
        radio_style = """
            QRadioButton { font-size: 13px; font-weight: bold; }
            QRadioButton::indicator { width: 14px; height: 14px; border-radius: 7px; border: 1px solid #A8C7AA; background-color: white; }
            QRadioButton::indicator:checked { background-color: #61A165; border: 2px solid #C1D4C3; }
            QRadioButton:disabled { color: #aaa; }
            QRadioButton::indicator:disabled { background-color: #eee; border: 1px solid #ccc; }
        """
        self.rb_patch_mode.setStyleSheet(radio_style)
        self.rb_direct_mode.setStyleSheet(radio_style)
        
        self.bg_save_mode.addButton(self.rb_patch_mode, 0)
        self.bg_save_mode.addButton(self.rb_direct_mode, 1)
        
        pref_mode = self.settings.value("ui/save_mode", 0, type=int)
        if pref_mode == 1: self.rb_direct_mode.setChecked(True)
        else: self.rb_patch_mode.setChecked(True)
        
        def on_save_mode_clicked(idx):
            self.settings.setValue("ui/save_mode", idx)
            if self.current_edit_file:
                curr_item = self.nav_tree.currentItem()
                if curr_item: 
                    self.on_nav_item_clicked(curr_item, 0)
                
        self.bg_save_mode.idClicked.connect(on_save_mode_clicked)
        
        h_tools.addWidget(self.rb_patch_mode)
        h_tools.addWidget(self.rb_direct_mode)
        h_tools.addSpacing(15) 

        self.btn_save_yaml = QPushButton("💾 保存修改")
        self.btn_save_yaml.setCursor(Qt.PointingHandCursor)
        self.btn_save_yaml.setStyleSheet("""
            QPushButton { background-color: #61A165; color: white; padding: 6px 20px; border-radius: 15px; font-weight: bold; font-size: 13px; }
            QPushButton:hover { background-color: #559159; }
            QPushButton:disabled { background-color: #A8C7AA; color: #F0F5F1; }
        """)
        self.btn_save_yaml.clicked.connect(self.save_yaml_config)
        self.btn_save_yaml.setEnabled(False)
        h_tools.addWidget(self.btn_save_yaml)

        right_lay.addLayout(h_tools)

        self.cfg_stack = QStackedWidget()
        
        self.loading_page = QWidget()
        self.loading_page.setObjectName("loadingPage")
        load_lay = QVBoxLayout(self.loading_page)
        self.lbl_giant_load = QLabel("⏳ 准备就绪...")
        self.lbl_giant_load.setAlignment(Qt.AlignCenter)
        self.lbl_giant_load.setStyleSheet("font-size: 22px; font-weight: bold; color: #49814D;")
        load_lay.addWidget(self.lbl_giant_load)
        self.cfg_stack.addWidget(self.loading_page)
        
        right_lay.addWidget(self.cfg_stack)

        self.splitter.addWidget(right_widget)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([220, 800])
        lay.addWidget(self.splitter)

        self.current_edit_file = ""
        self.current_custom_file = ""
        self._yaml_widgets = {}
        self._yaml_base_values = {}
        self._yaml_dynamic_lists = {}
        self._ui_cache = {}  
        return w
    def _create_cfg_tree(self):
        """工厂函数：生成带绝美样式的 QTreeWidget"""
        from PySide6.QtWidgets import QTreeWidget, QHeaderView, QAbstractItemView
        from PySide6.QtCore import Qt
        
        tree = QTreeWidget()
        tree.setHeaderLabels(["设置项目", "当前配置值", "功能说明"])
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        tree.header().setSectionResizeMode(1, QHeaderView.Interactive)
        tree.setColumnWidth(1, 450)
        tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        tree.header().setStretchLastSection(False)
        tree.setAlternatingRowColors(False) 
        tree.setSelectionMode(QAbstractItemView.NoSelection)
        tree.setFocusPolicy(Qt.NoFocus)
        
        # 【完美解法】：使用 Qt 原生的 palette() 变量，不写死任何颜色！
        # 这样它会自动跟随系统的明暗主题，彻底告别发白！
        tree.setStyleSheet("""
            QTreeWidget { 
                font-size: 14px; 
                border: 1px solid palette(midlight); 
                border-radius: 8px; 
                background-color: transparent; 
                outline: none; 
            }
            QTreeWidget::item { 
                min-height: 42px; 
                border-bottom: 1px solid palette(alternate-base); 
            }
            QTreeWidget::item:selected, QTreeWidget::item:focus { 
                background-color: transparent; 
                border: none; 
                border-bottom: 1px solid palette(highlight); 
            }
            QHeaderView::section { 
                background-color: palette(window); 
                font-size: 14px; 
                font-weight: bold; 
                padding: 10px; 
                border: none; 
                border-bottom: 2px solid #61A165; 
            }
        """)
        return tree
    # 模块化全局中控台
    def _dynamic_row_height(self, item, text):
        """公用小工具：动态撑开行高，防止文字换行时压扁输入框"""
        from PySide6.QtCore import QSize
        lines = text.count('\n') + 1
        h = max(46, 26 + lines * 20)
        item.setSizeHint(0, QSize(-1, h))
        item.setSizeHint(1, QSize(-1, h))
        item.setSizeHint(2, QSize(-1, h))

    def _get_active_bindings(self):
        """公用小工具：统一获取当前生效的快捷键列表 (全域文件扫描)"""
        bindings = []
        # 遍历内存中加载的所有配置文件和补丁，不漏掉任何一个角落！
        for fname, (d_data, d_patch) in self._yaml_cache.items():
            # 1. 抓取原文底包
            base_b = _get_nested_val(d_data, "key_binder/bindings", [])
            if isinstance(base_b, list): 
                bindings.extend(base_b)
            
            # 2. 抓取 Custom 补丁
            if isinstance(d_patch, dict):
                if "key_binder/bindings" in d_patch and isinstance(d_patch["key_binder/bindings"], list):
                    bindings.extend(d_patch["key_binder/bindings"])
                elif "key_binder" in d_patch and isinstance(d_patch["key_binder"], dict) and isinstance(d_patch["key_binder"].get("bindings"), list):
                    bindings.extend(d_patch["key_binder"]["bindings"])
                    
        return bindings

    def _render_global_business_page(self, tree_widget):
        """总控分发：按顺序调用独立的业务渲染器"""
        self._render_feature_page_size(tree_widget)  # 功能1：候选数
        self._render_feature_paging(tree_widget)     # 功能2：翻页键
        self._render_feature_cand_keys(tree_widget)  # 功能3：次选与三选
        self._render_feature_auto_freq(tree_widget)  # 功能3.5：自动调频
        self._render_feature_main_dict(tree_widget)  # 功能3.8：主词库防覆盖 (新增)
        self._render_feature_super_tips(tree_widget) # 功能4：超级提示
        self._render_feature_reverse_lookup(tree_widget) # 功能5：反查快捷键
        self._render_feature_grammar_model(tree_widget)  # 模型参数注入
    def _render_feature_grammar_model(self, tree):
        """专属渲染器：语法模型 (LMDG) 推荐参数一键配置"""
        from PySide6.QtWidgets import QTreeWidgetItem, QComboBox, QWidget, QHBoxLayout, QLabel
        from PySide6.QtCore import Qt

        item = QTreeWidgetItem(tree, ["🧠 语法模型一键配置 (LMDG)", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        container = QWidget()
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(0, 4, 0, 4)
        c_lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        combo = QComboBox()
        combo.setFixedHeight(34); combo.setFixedWidth(180)
        # 提供三个操作态，严格遵守 WYSIWYG
        combo.addItems(["保持当前配置", "写入推荐参数", "清除推荐参数 (恢复默认)"])
        
        
        c_lay.addWidget(combo)
        tree.setItemWidget(item, 1, container)
        
        lbl = QLabel("一键将最优的 language、词频惩罚以及 translator 关联参数完美写入配置。")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 13px; padding: 4px;")
        tree.setItemWidget(item, 2, lbl)
        
        self._dynamic_row_height(item, lbl.text())
        
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["grammar_model"] = combo
        tree._py_refs.extend([container, combo, lbl])
    def _render_feature_page_size(self, tree):
        from PySide6.QtWidgets import QTreeWidgetItem, QLineEdit, QWidget, QHBoxLayout, QLabel
        from PySide6.QtGui import QIntValidator
        from PySide6.QtCore import Qt

        item = QTreeWidgetItem(tree, ["🔢 全局候选词个数", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        container = QWidget()
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(0, 4, 0, 4)
        c_lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        edit = QLineEdit()
        # 视觉对齐：强行锁死宽度 180
        edit.setFixedHeight(34); edit.setFixedWidth(180)
        
        edit.setValidator(QIntValidator(1, 10)) 
        
        # 智能读取：同时查阅 default 的底包和 custom 补丁
        d_data, d_patch = self._yaml_cache.get("default.yaml", ({}, {}))
        v_def = 6
        if isinstance(d_patch, dict) and "menu/page_size" in d_patch: current_val = d_patch["menu/page_size"]
        elif isinstance(d_patch, dict) and "menu" in d_patch and isinstance(d_patch["menu"], dict) and "page_size" in d_patch["menu"]: current_val = d_patch["menu"]["page_size"]
        else: current_val = _get_nested_val(d_data, "menu/page_size", v_def)
        
        edit.setText(str(current_val))
        
        c_lay.addWidget(edit)
        tree.setItemWidget(item, 1, container)
        
        lbl = QLabel()
        lbl.setWordWrap(True)
        tree.setItemWidget(item, 2, lbl)
        
        desc = "一键同步修改 default.yaml 及所有主方案的候选数。"
        def validate(text):
            if not text.strip():
                msg = f"❌ 不能为空！请输入 1-10 的数字。\n{desc}"
                lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
            else:
                try:
                    val = int(text)
                    if 1 <= val <= 10:
                        msg = f"✅ 当前值为 {val}。\n{desc}"
                        lbl.setStyleSheet("color: #61A165; font-size: 13px; padding: 4px;")
                    else:
                        msg = f"❌ 数值越界！必须在 1 到 10 之间。\n{desc}"
                        lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
                except:
                    msg = f"❌ 格式错误！\n{desc}"
                    lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
            lbl.setText(msg)
            self._dynamic_row_height(item, msg)

        edit.textChanged.connect(validate)
        validate(edit.text())
        
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["page_size"] = edit
        tree._py_refs.extend([container, edit, lbl])

    def _render_feature_paging(self, tree):
        from PySide6.QtWidgets import QTreeWidgetItem, QComboBox, QWidget, QHBoxLayout, QLabel
        from PySide6.QtCore import Qt

        item = QTreeWidgetItem(tree, ["↔️ 翻页按键习惯", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        container = QWidget()
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(0, 4, 0, 4)
        c_lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        combo = QComboBox()
        # 视觉对齐：强行锁死宽度 180
        combo.setFixedHeight(34); combo.setFixedWidth(180)
        combo.addItems(["默认 (PageUp/Dn)", "逗号句号 ( , . )", "中括号 ( [ ] )", "减号等号 ( - = )"])
        
        
        accs = set()
        for b in self._get_active_bindings():
            if isinstance(b, dict) and str(b.get("send", "")).lower() in ["page_up", "page_down", "prior", "next"]:
                accs.add(str(b.get("accept", "")).lower())
        
        curr = "默认 (PageUp/Dn)"
        if "minus" in accs or "-" in accs: curr = "减号等号 ( - = )"
        elif "bracketleft" in accs or "[" in accs: curr = "中括号 ( [ ] )"
        elif "comma" in accs or "," in accs: curr = "逗号句号 ( , . )"
        combo.setCurrentText(curr)
        
        c_lay.addWidget(combo)
        tree.setItemWidget(item, 1, container)
        
        lbl = QLabel()
        lbl.setWordWrap(True)
        tree.setItemWidget(item, 2, lbl)
        
        combo.currentTextChanged.connect(lambda t: self._check_conflict_paging(t, lbl, item))
        self._check_conflict_paging(combo.currentText(), lbl, item)
        
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["paging"] = combo
        tree._py_refs.extend([container, combo, lbl])

    def _render_feature_cand_keys(self, tree):
        from PySide6.QtWidgets import QTreeWidgetItem, QLineEdit, QWidget, QHBoxLayout, QLabel
        from PySide6.QtCore import Qt

        item = QTreeWidgetItem(tree, ["2️⃣3️⃣ 次选 / 三选快捷键", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        container = QWidget()
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(0, 4, 0, 4)
        c_lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        inv_map = {v: k for k, v in RIME_KEY_MAP.items()} 
        
        lbl2 = QLabel("次选 (2):")
        lbl2.setStyleSheet("font-size: 13px; font-weight: bold; ")
        edit2 = QLineEdit()
        # 视觉对齐：两个框各占 60，配合间距正好和 180 差不多宽
        edit2.setFixedHeight(34); edit2.setFixedWidth(60); edit2.setAlignment(Qt.AlignCenter)

        
        lbl3 = QLabel(" 三选 (3):")
        lbl3.setStyleSheet("font-size: 13px; font-weight: bold; ")
        edit3 = QLineEdit()
        edit3.setFixedHeight(34); edit3.setFixedWidth(60); edit3.setAlignment(Qt.AlignCenter)


        key2, key3 = "", ""
        for b in self._get_active_bindings():
            if isinstance(b, dict):
                snd = str(b.get("send", "")).lower()
                acc = str(b.get("accept", "")).lower()
                if acc in ["2", "kp_2", "3", "kp_3"]: continue
                if snd == "2": key2 = acc
                elif snd == "3": key3 = acc
        
        edit2.setText(inv_map.get(key2, key2))
        edit3.setText(inv_map.get(key3, key3))
        
        c_lay.addWidget(lbl2); c_lay.addWidget(edit2)
        c_lay.addWidget(lbl3); c_lay.addWidget(edit3)
        c_lay.addStretch()
        tree.setItemWidget(item, 1, container)
        
        lbl = QLabel()
        lbl.setWordWrap(True)
        tree.setItemWidget(item, 2, lbl)
        
        def check_cand_conflicts():
            t2 = edit2.text().strip()
            t3 = edit3.text().strip()
            target_syms = [x for x in [t2, t3] if x]
            self._check_conflict_base(target_syms, ["2", "3"], lbl, item)
            
        edit2.textChanged.connect(check_cand_conflicts)
        edit3.textChanged.connect(check_cand_conflicts)
        check_cand_conflicts() 
        
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["cand_keys"] = (edit2, edit3)
        tree._py_refs.extend([container, lbl2, edit2, lbl3, edit3, lbl])
    def _render_feature_auto_freq(self, tree):
        """专属渲染器：全局自动调频控制 (enable_user_dict)"""
        from PySide6.QtWidgets import QTreeWidgetItem, QComboBox, QWidget, QHBoxLayout, QLabel
        from PySide6.QtCore import Qt

        item = QTreeWidgetItem(tree, ["📈 自动调频 (用户词频记忆)", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        container = QWidget()
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(0, 4, 0, 4)
        c_lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        combo = QComboBox()
        combo.setFixedHeight(34); combo.setFixedWidth(180)
        combo.addItems(["开启 (true)", "关闭 (false)"])
        
        
        # 🌟 智能三重探测：探测 default(看谁是主力) -> 探测 patch(看用户改没改) -> 探测 schema(看底层默认)
        base_data, base_patch = self._yaml_cache.get("wanxiang.schema.yaml", ({}, {}))
        pro_data, pro_patch = self._yaml_cache.get("wanxiang_pro.schema.yaml", ({}, {}))
        def_data, def_patch = self._yaml_cache.get("default.yaml", ({}, {}))

        # 1. 揪出当前主力方案是谁
        active_schema = "wanxiang_pro" # 默认假定是 Pro
        schema_list = def_patch.get("schema_list") if isinstance(def_patch, dict) and "schema_list" in def_patch else _get_nested_val(def_data, "schema_list", [])
        
        if isinstance(schema_list, list):
            for s in schema_list:
                s_id = s.get("schema") if isinstance(s, dict) else ""
                if s_id in ["wanxiang", "wanxiang_pro"]:
                    active_schema = s_id
                    break
        
        # 2. 提取配置的通用函数 (带严格布尔强转)
        def extract_bool(patch_dict, schema_data, fallback_val):
            # 优先读补丁
            if isinstance(patch_dict, dict):
                v = patch_dict.get("translator/enable_user_dict")
                if v is None and "translator" in patch_dict and isinstance(patch_dict["translator"], dict):
                    v = patch_dict["translator"].get("enable_user_dict")
                if v is not None:
                    return str(v).lower() == 'true' if isinstance(v, str) else bool(v)
            # 其次读底层文件
            if isinstance(schema_data, dict):
                v = _get_nested_val(schema_data, "translator/enable_user_dict")
                if v is not None:
                    return str(v).lower() == 'true' if isinstance(v, str) else bool(v)
            return fallback_val

        # 3. 完美对应：你是谁，我就读谁的真实数据
        if active_schema == "wanxiang_pro":
            current_val = extract_bool(pro_patch, pro_data, True)
        else:
            current_val = extract_bool(base_patch, base_data, True)

        combo.setCurrentIndex(0 if current_val else 1)
        
        c_lay.addWidget(combo)
        tree.setItemWidget(item, 1, container)
        
        lbl = QLabel("全局控制是否开启输入法对你打过的词进行动态记忆与自动词频调整。")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 13px; padding: 4px;")
        tree.setItemWidget(item, 2, lbl)
        
        self._dynamic_row_height(item, lbl.text())
        
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["auto_freq"] = combo
        tree._py_refs.extend([container, combo, lbl])
    def _render_feature_main_dict(self, tree):
        """专属渲染器：全局主词库独立命名 (防覆盖)"""
        from PySide6.QtWidgets import QTreeWidgetItem, QLineEdit, QWidget, QHBoxLayout, QLabel
        from PySide6.QtCore import Qt

        item = QTreeWidgetItem(tree, ["📚 主词库独立命名 (防更新覆盖)", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        container = QWidget()
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(0, 4, 0, 4)
        c_lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        edit = QLineEdit()
        edit.setFixedHeight(34); edit.setFixedWidth(180)
        
        
        # 探测 patch(看用户改没改) -> 探测 schema(看底层默认)
        base_data, base_patch = self._yaml_cache.get("wanxiang.schema.yaml", ({}, {}))
        pro_data, pro_patch = self._yaml_cache.get("wanxiang_pro.schema.yaml", ({}, {}))
        def_data, def_patch = self._yaml_cache.get("default.yaml", ({}, {}))
        
        # 1. 揪出当前主力方案是谁
        active_schema = "wanxiang_pro" # 默认假定是 Pro
        schema_list = def_patch.get("schema_list") if isinstance(def_patch, dict) and "schema_list" in def_patch else _get_nested_val(def_data, "schema_list", [])
        
        if isinstance(schema_list, list):
            for s in schema_list:
                s_id = s.get("schema") if isinstance(s, dict) else ""
                if s_id in ["wanxiang", "wanxiang_pro"]:
                    active_schema = s_id
                    break # 找到排在最前面的万象方案，认定为主力
                    
        # 2. 提取配置的通用函数
        def extract_dict(patch_dict, schema_data, fallback_name):
            # 优先读用户补丁
            if isinstance(patch_dict, dict):
                v = patch_dict.get("translator/dictionary")
                if not v and "translator" in patch_dict and isinstance(patch_dict["translator"], dict):
                    v = patch_dict["translator"].get("dictionary")
                if v: return v
            # 其次读底层文件
            if isinstance(schema_data, dict):
                v = _get_nested_val(schema_data, "translator/dictionary")
                if v: return v
            return fallback_name

        # 3. 完美对应：你是谁，我就读谁的真实数据
        if active_schema == "wanxiang_pro":
            current_val = extract_dict(pro_patch, pro_data, "wanxiang_pro")
        else:
            current_val = extract_dict(base_patch, base_data, "wanxiang")

        edit.setText(str(current_val))
        
        c_lay.addWidget(edit)
        tree.setItemWidget(item, 1, container)
        
        lbl = QLabel()
        lbl.setWordWrap(True)
        tree.setItemWidget(item, 2, lbl)
        
        desc = "自定义词库名称（如 wanxianguser）。\n保存后将自动把原词库复制一份，后续在线更新官方方案时，绝不会覆盖！"
        
        def validate(text):
            t = text.strip()
            if not t:
                msg = f"❌ 不能为空！请输入词库名称（恢复默认请填 wanxiang 或 wanxiang_pro）。\n{desc}"
                lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
            elif not t.replace("_", "").isalnum():
                msg = f"❌ 格式错误！词库名只能包含字母、数字和下划线。\n{desc}"
                lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
            else:
                msg = f"✅ 当前引用的主词库为: {t}.dict.yaml\n{desc}"
                lbl.setStyleSheet("color: #61A165; font-size: 13px; padding: 4px;")
            lbl.setText(msg)
            self._dynamic_row_height(item, msg)

        edit.textChanged.connect(validate)
        validate(edit.text())
        
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["main_dict"] = edit
        tree._py_refs.extend([container, edit, lbl])
    def _render_feature_super_tips(self, tree):
        """专属渲染器：超级提示 (super_tips) 全局同步 - 完美支持多行数组与防冲突"""
        from PySide6.QtWidgets import QTreeWidgetItem, QLineEdit, QWidget, QHBoxLayout, QLabel
        from PySide6.QtCore import Qt

        root_item = QTreeWidgetItem(tree, ["💡 超级提示模块 (super_tips)", "", "控制实时提示数据的路径、按键与屏蔽类型"])
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsSelectable)
        
        
        def get_current_val(path_str, default_val):
            pro_data, pro_patch = self._yaml_cache.get("wanxiang_pro.schema.yaml", ({}, {}))
            base_data, base_patch = self._yaml_cache.get("wanxiang.schema.yaml", ({}, {}))
            
            if isinstance(pro_patch, dict):
                if path_str in pro_patch: return pro_patch[path_str]
                if "super_tips" in pro_patch and isinstance(pro_patch["super_tips"], dict):
                    sub_k = path_str.split("/")[-1]
                    if sub_k in pro_patch["super_tips"]: return pro_patch["super_tips"][sub_k]
            
            if isinstance(base_patch, dict):
                if path_str in base_patch: return base_patch[path_str]
                if "super_tips" in base_patch and isinstance(base_patch["super_tips"], dict):
                    sub_k = path_str.split("/")[-1]
                    if sub_k in base_patch["super_tips"]: return base_patch["super_tips"][sub_k]
            
            val = _get_nested_val(pro_data, path_str)
            if val is not None: return val
            
            val = _get_nested_val(base_data, path_str)
            return val if val is not None else default_val

        db_name_val = get_current_val("super_tips/db_name", "lua/tips")
        tips_key_val = get_current_val("super_tips/tips_key", "comma")
        
        disabled_types = get_current_val("super_tips/disabled_types", [])
        if not isinstance(disabled_types, list): disabled_types = []
        clean_dt = [str(x) for x in disabled_types if x and "禁用类型" not in str(x)]
        dt_str = "\n".join(clean_dt)
        
        nodes = [
            ("db_name", "数据库路径", db_name_val, "默认: lua/tips", "str"),
            ("tips_key", "提示上屏按键", tips_key_val, "用于上屏提示内容的按键（默认 comma 逗号）", "str"),
            ("disabled_types", "🚫 屏蔽的提示类型", dt_str, "一行填一个。\n可选类型：偏旁，符号，化学式，时间，组字，翻译，表情，货币，车牌，单位", "list")
        ]
        
        widgets = {}
        for key, title, val, desc, v_type in nodes:
            item = QTreeWidgetItem(root_item, [f"  ↳ {title}", "", ""])
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            
            container = QWidget()
            c_lay = QHBoxLayout(container)
            c_lay.setContentsMargins(0, 4, 0, 4)
            c_lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            if v_type == "str":
                edit = QLineEdit()
                edit.setFixedHeight(34); edit.setFixedWidth(180) 
                
                edit.setText(str(val))
                c_lay.addWidget(edit)
                widgets[key] = edit
            else:
                edit = DynamicMultiLineWidget(val, "直接回车换行")
                edit.setFixedWidth(180)
                c_lay.addWidget(edit)
                widgets[key] = edit
                edit.needs_resize.connect(lambda h, itm=item: self._dynamic_row_height(itm, desc))
            
            c_lay.addStretch()
            tree.setItemWidget(item, 1, container)
            
            lbl = QLabel(desc)
            lbl.setStyleSheet("font-size: 13px; padding: 4px;")
            lbl.setWordWrap(True)
            tree.setItemWidget(item, 2, lbl)
            
            # 单独把 tips_key 拎出来，挂上咱们的冲突扫描引擎！
            if key == "tips_key":
                def check_tips_conflict(text, l=lbl, itm=item, d=desc):
                    t = text.strip()
                    if not t:
                        msg = f"❌ 不能为空！请输入一个按键。\n{d}"
                        l.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
                        l.setText(msg)
                        self._dynamic_row_height(itm, msg)
                    else:
                        # 传入空数组 []，代表跟任何绑定的键冲突都不行
                        self._check_conflict_base([t], [], l, itm)
                
                edit.textChanged.connect(check_tips_conflict)
                check_tips_conflict(edit.text()) # 初始触发一次
            else:
                self._dynamic_row_height(item, desc)
                
            tree._py_refs.extend([container, edit, lbl])

        root_item.setExpanded(True)
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["super_tips"] = widgets
    def _render_feature_reverse_lookup(self, tree):
        """专属渲染器：全局反查快捷键 (一键同步 prefix/key/正则/字符集，带防冲突)"""
        from PySide6.QtWidgets import QTreeWidgetItem, QLineEdit, QWidget, QHBoxLayout, QLabel
        from PySide6.QtCore import Qt

        item = QTreeWidgetItem(tree, ["🔍 拆字与笔画反查键", "", ""])
        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        
        container = QWidget()
        c_lay = QHBoxLayout(container)
        c_lay.setContentsMargins(0, 4, 0, 4)
        c_lay.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        edit = QLineEdit()
        edit.setFixedHeight(34); edit.setFixedWidth(180)
        
        edit.setMaxLength(1)
        
        # 智能读取当前配置 (优先读补丁)
        d_data, d_patch = self._yaml_cache.get("wanxiang.schema.yaml", ({}, {}))
        
        def get_val(path_str, def_v):
            if isinstance(d_patch, dict):
                if path_str in d_patch: return d_patch[path_str]
                parts = path_str.split('/')
                if len(parts) == 2 and parts[0] in d_patch and isinstance(d_patch[parts[0]], dict):
                    if parts[1] in d_patch[parts[0]]: return d_patch[parts[0]][parts[1]]
            val = _get_nested_val(d_data, path_str)
            return val if val is not None else def_v

        current_val = get_val("wanxiang_lookup/key", "`")
        edit.setText(str(current_val))
        
        c_lay.addWidget(edit)
        tree.setItemWidget(item, 1, container)
        
        lbl = QLabel()
        lbl.setWordWrap(True)
        tree.setItemWidget(item, 2, lbl)
        
        desc = "自动同步 prefix、key、正则表达式和 alphabet 字符集。"
        
        def validate(text):
            t = text.strip()
            if not t:
                msg = f"❌ 不能为空！请输入一个符号。\n{desc}"
                lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
                lbl.setText(msg)
                self._dynamic_row_height(item, msg)
            elif len(t) != 1 or t.isalnum():
                msg = f"❌ 格式错误！必须是非字母、非数字的符号。\n{desc}"
                lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
                lbl.setText(msg)
                self._dynamic_row_height(item, msg)
            else:
                self._check_conflict_base([t], [], lbl, item, check_alphabet=False)

        edit.textChanged.connect(validate)
        validate(edit.text())
        
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["reverse_lookup"] = edit
        tree._py_refs.extend([container, edit, lbl])
    def _check_conflict_base(self, target_symbols, ignore_sends, lbl, item, check_alphabet=True):
        """共用的底层冲突扫描引擎：支持正则免疫与编码集、分隔符开关"""
        if not target_symbols:
            msg = "✨ 安全：当前选项无系统级冲突风险\n(实时检测按键是否被占用)"
            lbl.setText(msg); lbl.setStyleSheet("color: #61A165; font-size: 13px; padding: 4px;")
            self._dynamic_row_height(item, msg)
            return

        conflicts = []
        target_names = [RIME_KEY_MAP.get(sym, sym) for sym in target_symbols]
        # 白名单放行
        IGNORE_SCHEMAS = ["wanxiang_english.schema.yaml", "wanxiang_mixedcode.schema.yaml", "wanxiang_reverse.schema.yaml", "wanxiang_chaifen.schema.yaml"]

        for fname, (data, patch) in self._yaml_cache.items():
            if fname in IGNORE_SCHEMAS: continue
            
            # 1. 查输入编码集、分隔符、首字母 (仅在需要时检查)
            if check_alphabet:
                alpha = str(_get_nested_val(data, "speller/alphabet", ""))
                delimiter = str(_get_nested_val(data, "speller/delimiter", ""))
                initials = str(_get_nested_val(data, "speller/initials", ""))
                
                for sym in target_symbols:
                    if len(sym) == 1:
                        if sym in alpha: 
                            conflicts.append(f"[{fname}] 已被【输入编码集】(alphabet) 占用: '{sym}'")
                        if sym in delimiter:
                            conflicts.append(f"[{fname}] 已被【拼写分隔符】(delimiter) 占用: '{sym}'")
                        if sym in initials:
                            conflicts.append(f"[{fname}] 已被【首字母集】(initials) 占用: '{sym}'")
            
            # 2. 查快捷键
            bindings = _get_nested_val(data, "key_binder/bindings", [])
            if isinstance(bindings, list):
                for b in bindings:
                    if not isinstance(b, dict): continue
                    if "match" in b: continue 
                    
                    acc = str(b.get("accept", "")).lower()
                    snd = str(b.get("send", "")).lower()
                    if snd in ignore_sends: continue # 免死金牌
                    
                    for sym, name in zip(target_symbols, target_names):
                        if name.lower() == acc or sym == acc or f"+{name.lower()}" in acc or f"+{sym}" in acc: 
                            conflicts.append(f"[{fname}] 全局快捷键已绑定: {acc}")
            
            # 3. 查以词定字
            sel_char = str(_get_nested_val(data, "super_processor/select_character", ""))
            for sym, name in zip(target_symbols, target_names):
                if sym in sel_char or name in sel_char: conflicts.append(f"[{fname}] 以词定字占用: '{sym}'")

        if conflicts:
            uniq_c = list(set(conflicts))
            msg = "❌ 警告！检测到严重冲突:\n" + "\n".join(uniq_c[:2])
            if len(uniq_c) > 2: msg += f"\n...等共 {len(uniq_c)} 处冲突"
            lbl.setText(msg); lbl.setStyleSheet("color: #d9534f; font-weight: bold; font-size: 13px; padding: 4px;")
        else:
            msg = "✅ 扫描通过：未发现按键冲突\n(当前方案安全可用)"
            lbl.setText(msg); lbl.setStyleSheet("color: #61A165; font-weight: bold; font-size: 13px; padding: 4px;")
        
        self._dynamic_row_height(item, msg)

    def _check_conflict_paging(self, text, lbl, item):
        target_syms = []
        if text == "逗号句号 ( , . )": target_syms = [",", "."]
        elif text == "中括号 ( [ ] )": target_syms = ["[", "]"]
        elif text == "减号等号 ( - = )": target_syms = ["-", "="]
        self._check_conflict_base(target_syms, ["page_up", "page_down", "prior", "next"], lbl, item)

    def _check_conflict_semicolon(self, checked, lbl, item):
        target_syms = [";"] if checked else []
        self._check_conflict_base(target_syms, ["2"], lbl, item)
    def jump_to_reference(self, text):
        """智能解析文本中的引用文件，支持外部和内部键穿透"""
        if not text: return
        target_base = ""
        import re
        
        # 1. 优先提取带有 :/ 的外部文件标识 (如 wanxiang_algebra:/mixed/全拼)
        match = re.search(r'([a-zA-Z0-9_]+):/', text)
        if match:
            target_base = match.group(1)
        else:
            for line in text.splitlines():
                line = line.strip().lstrip('- ')
                if line and not line.startswith('#'):
                    target_base = line.split(':')[0].strip()
                    break
                    
        if not target_base:
            QMessageBox.information(self, "提示", "未找到有效的跨文件引用路径。")
            return
        possible_names = [f"{target_base}.yaml", f"{target_base}.schema.yaml", f"{target_base}.dict.yaml"]
        
        # 4. 遍历左侧导航树，寻找目标文件并物理翻页
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        it = QTreeWidgetItemIterator(self.nav_tree)
        while it.value():
            item = it.value()
            file_name = item.data(0, Qt.UserRole)
            if file_name in possible_names:
                self.nav_tree.setCurrentItem(item)
                self.on_nav_item_clicked(item, 0)
                self.log.appendPlainText(f"🔗 穿透引擎：已成功跳转至 {file_name}")
                return
            it += 1
            
        QMessageBox.warning(self, "穿透失败", f"左侧导航树中未找到名为 '{target_base}' 的目标文件，请确认该文件在 Rime 目录下存在。")
    def load_other_directory(self):
        d = self.get_existing_directory("选择包含万象配置的 Rime 目录")
        if d:
            self.upd_rime.setText(d) 
            self.scan_rime_directory()

    def scan_rime_directory(self):
        rime_dir = self.upd_rime.text().strip()
        self._loaded_rime_dir = rime_dir  # 记录当前绑定的目录
        
        from PySide6.QtWidgets import QTreeWidgetItem
        self.nav_tree.clear()
        
        # 锁定左右两边，切到全屏置灰遮罩层
        self.left_frame.setEnabled(False)
        self.btn_save_yaml.setEnabled(False)
        self.cfg_stack.setCurrentWidget(self.loading_page)
        self.lbl_giant_load.setText("⏳ 正在扫描目录与分析配置文件，请稍候...")
        self.lbl_giant_load.setStyleSheet("font-size: 24px; font-weight: bold; color: #428bca;")
        
        # 清空除加载页(index 0)以外的所有缓存 UI
        if hasattr(self, 'cfg_stack'):
            while self.cfg_stack.count() > 1:
                w = self.cfg_stack.widget(1)
                self.cfg_stack.removeWidget(w)
                w.deleteLater()
        if hasattr(self, '_ui_cache'): self._ui_cache.clear()

        if not rime_dir or not os.path.exists(rime_dir):
            self.lbl_giant_load.setText("⚠️ 未找到万象拼音配置 (目录无效)")
            self.lbl_giant_load.setStyleSheet("font-size: 24px; font-weight: bold; color: #d9534f;")
            self.left_frame.setEnabled(True)
            return

        feature_root = QTreeWidgetItem(self.nav_tree, ["⚙️ 全局功能中控台"])
        feature_root.setFlags(feature_root.flags() & ~Qt.ItemIsSelectable)
        font = feature_root.font(0); font.setBold(True); feature_root.setFont(0, font)
        feature_root.setBackground(0, QColor("#E2ECE3")) 
        
        item = QTreeWidgetItem(feature_root, ["🌟 常用综合设置 (一键联动)"])
        item.setData(0, Qt.UserRole, "VIRTUAL_GLOBAL")
        feature_root.setExpanded(True)

        found_count = 0
        all_files_to_cache = []
        for category, file_list in FILE_INDEX_META.items():
            cat_item = QTreeWidgetItem(self.nav_tree, [category])
            cat_item.setFlags(cat_item.flags() & ~Qt.ItemIsSelectable)
            cat_item.setFont(0, font); cat_item.setBackground(0, QColor("#E2ECE3")) 
            
            has_child = False
            for f_info in file_list:
                f_name = f_info["file"]
                f_path = os.path.join(rime_dir, f_name)
                if os.path.exists(f_path):
                    all_files_to_cache.append(f_name)
                    item = QTreeWidgetItem(cat_item, [f_info["name"]])
                    item.setToolTip(0, f_name)
                    item.setData(0, Qt.UserRole, f_name)
                    has_child = True
                    found_count += 1
            if has_child: cat_item.setExpanded(True)
            else: cat_item.setHidden(True)

        if found_count == 0:
            self.lbl_giant_load.setText("⚠️ 未找到万象拼音配置 (当前目录无方案)")
            self.lbl_giant_load.setStyleSheet("font-size: 24px; font-weight: bold; color: #d9534f;")
            self.left_frame.setEnabled(True)
        else:
            self.lbl_current_target.clear()
            self.nav_tree.header().setStretchLastSection(False)
            self.nav_tree.resizeColumnToContents(0)
            ideal_width = max(220, min(self.nav_tree.columnWidth(0) + 35, 350))
            self.nav_tree.header().setStretchLastSection(True)
            self.left_frame.setMinimumWidth(ideal_width)
            current_sizes = self.splitter.sizes()
            total_width = sum(current_sizes) if sum(current_sizes) > 0 else self.width()
            self.splitter.setSizes([ideal_width, total_width - ideal_width])
            
            # 后台线程启动
            self._yaml_cache.clear()
            self.files_to_prebuild = list(set(all_files_to_cache))
            self.cache_worker = YamlCacheWorker(rime_dir, self.files_to_prebuild)
            self.cache_worker.finished_sig.connect(self._on_cache_loaded)
            self.cache_worker.all_finished_sig.connect(self._on_all_yaml_parsed)
            self.cache_worker.start()

    def _on_cache_loaded(self, fname, s_data, c_patch):
        self._yaml_cache[fname] = (s_data, c_patch)

    def _on_all_yaml_parsed(self):
        """数据解析完毕，开启丝滑的智能预缓存"""
        self.lbl_giant_load.setText("🚀 正在后台预构建配置面板...")
        self.lbl_giant_load.setStyleSheet("font-size: 24px; font-weight: bold; color: #61A165;")
        
        if "VIRTUAL_GLOBAL" not in self._ui_cache:
            new_tree = self._create_cfg_tree()
            new_tree._py_refs = []
            self._ui_cache["VIRTUAL_GLOBAL"] = {'tree': new_tree, 'widgets': {}, 'base': {}, 'lists': {}}
            self.cfg_stack.addWidget(new_tree)
            self._render_global_business_page(new_tree) 

        self.ui_build_queue = []
        is_direct_checked = self.rb_direct_mode.isChecked()
        if hasattr(self, 'files_to_prebuild'):
            for f in self.files_to_prebuild:
                self.ui_build_queue.append((f, is_direct_checked))

        total_tasks = len(self.ui_build_queue)

        def build_next():
            if not self.ui_build_queue:
                # ====== 预缓存全部完成 ======
                self.left_frame.setEnabled(True)
                
                # 默认定位到“综合板块” (左侧树第0个大类的第0个子项)
                if self.nav_tree.topLevelItemCount() > 0:
                    global_cat = self.nav_tree.topLevelItem(0)
                    if global_cat.childCount() > 0:
                        global_item = global_cat.child(0)
                        self.nav_tree.setCurrentItem(global_item)
                        self.on_nav_item_clicked(global_item, 0)
                return
            
            fname, is_direct = self.ui_build_queue.pop(0)
            cache_key = f"{fname}_direct" if is_direct else f"{fname}_patch"
            curr_idx = total_tasks - len(self.ui_build_queue)
            self.lbl_giant_load.setText(f"🚀 正在预构建界面缓存 ({curr_idx}/{total_tasks})\n\n📄 {fname}")
            QApplication.processEvents()
            if cache_key not in self._ui_cache:
                self._build_and_cache_yaml_ui(fname, activate=False, force_direct_mode=is_direct)
            from PySide6.QtCore import QTimer
            QTimer.singleShot(15, build_next)

        build_next()
        
    def on_nav_item_clicked(self, item, col):
        """物理翻页，双缓存秒切隔离"""
        target_id = item.data(0, Qt.UserRole)
        if not target_id: return 

        if target_id == "VIRTUAL_GLOBAL":
            self.lbl_current_target.setText("⚙️ 当前配置：全局综合设置 (跨文件联动)")
            cache = self._ui_cache.get("VIRTUAL_GLOBAL")
            if cache:
                self.cfg_stack.setCurrentWidget(cache['tree'])
                self._yaml_widgets = cache['widgets']
                self._yaml_base_values = cache['base']
                self._yaml_dynamic_lists = cache['lists']
            
            # 赋予身份，并开启保存按钮
            self.current_edit_file = "VIRTUAL_GLOBAL" 
            self.btn_save_yaml.setEnabled(True) 
            
            # 允许用户自由选择“补丁模式”或“直写模式”！
            self.rb_patch_mode.setEnabled(True)
            self.rb_direct_mode.setEnabled(True)
            # 恢复用户的记忆选择
            pref = self.settings.value("ui/save_mode", 0, type=int)
            if pref == 1: self.rb_direct_mode.setChecked(True)
            else: self.rb_patch_mode.setChecked(True)
            return

        self.current_edit_file = target_id
        self.lbl_current_target.setText(f"📄 {target_id}")
        self.btn_save_yaml.setEnabled(True)
        is_custom_supported = target_id.endswith(".schema.yaml") or target_id == "default.yaml"
        if is_custom_supported:
            self.rb_patch_mode.setEnabled(True)
            self.rb_direct_mode.setEnabled(True)
            pref = self.settings.value("ui/save_mode", 0, type=int)
            if pref == 1: self.rb_direct_mode.setChecked(True)
            else: self.rb_patch_mode.setChecked(True)
        else:
            self.rb_direct_mode.setChecked(True) 
            self.rb_patch_mode.setEnabled(False) 
            self.rb_direct_mode.setEnabled(False) 

        if target_id.endswith(".schema.yaml"):
            base_id = target_id.replace(".schema.yaml", "")
            self.current_custom_file = f"{base_id}.custom.yaml"
        elif target_id.endswith(".yaml"):
            base_id = target_id.replace(".yaml", "")
            self.current_custom_file = f"{base_id}.custom.yaml"

        # 核心：根据当前模式计算专属 Cache Key (双缓存隔离)
        is_direct = self.rb_direct_mode.isChecked()
        cache_key = f"{target_id}_direct" if is_direct else f"{target_id}_patch"

        if cache_key in self._ui_cache:
            cache = self._ui_cache[cache_key]
            self.cfg_stack.setCurrentWidget(cache['tree'])
            self._yaml_widgets = cache['widgets']
            self._yaml_base_values = cache['base']
            self._yaml_dynamic_lists = cache['lists']
        else:
            self._build_and_cache_yaml_ui(target_id, activate=True, force_direct_mode=is_direct)

    def _build_and_cache_yaml_ui(self, target_id, activate=False, force_direct_mode=None):
        import shiboken6
        from PySide6.QtWidgets import QTreeWidgetItem, QHeaderView, QLineEdit, QComboBox, QCheckBox, QWidget, QHBoxLayout, QPushButton, QDialog
        from PySide6.QtCore import Qt, QSize, QTimer
        from PySide6.QtGui import QFont, QColor

        rime_dir = self.upd_rime.text().strip()
        schema_path = os.path.join(rime_dir, target_id)
        
        if target_id.endswith(".schema.yaml"):
            base_id = target_id.replace(".schema.yaml", "")
            target_custom_file = f"{base_id}.custom.yaml"
        elif target_id.endswith(".yaml"):
            base_id = target_id.replace(".yaml", "")
            target_custom_file = f"{base_id}.custom.yaml"
        else:
            target_custom_file = ""
            
        custom_path = os.path.join(rime_dir, target_custom_file) if target_custom_file else ""
        is_supported_file = target_id.endswith(".schema.yaml") or target_id in ["default.yaml", "wanxiang_algebra.yaml"]
        
        new_tree = self._create_cfg_tree()
        new_tree._py_refs = [] 
        new_tree.setUpdatesEnabled(False)
        self.cfg_stack.addWidget(new_tree)
        
        file_widgets = {}
        file_base_values = {}
        file_dynamic_lists = {}

        if not is_supported_file:
            QTreeWidgetItem(new_tree, ["该文件可视化未接入", "", "请直接编辑文本。"])
            self._ui_cache[f"{target_id}_direct"] = {'tree': new_tree, 'widgets': file_widgets, 'base': file_base_values, 'lists': file_dynamic_lists}
            if activate:
                self.cfg_stack.setCurrentWidget(new_tree)
                self._yaml_widgets = file_widgets
                self._yaml_base_values = file_base_values
                self._yaml_dynamic_lists = file_dynamic_lists
            return

        style_m = ""
        
        def safe_apply_size(itm, h):
            try:
                if shiboken6.isValid(itm) and itm.treeWidget(): itm.setSizeHint(0, QSize(-1, h))
            except: pass
            
        def safe_apply_height(wdg, h):
            try:
                if shiboken6.isValid(wdg): wdg.setFixedHeight(h)
            except: pass

        def sanitize_val(val):
            if hasattr(val, 'keys'): return {str(k): sanitize_val(v) for k, v in val.items()}
            elif isinstance(val, (list, tuple)) or hasattr(val, 'append'): return [sanitize_val(x) for x in val]
            elif val is None: return None
            elif isinstance(val, bool): return bool(val)
            elif isinstance(val, float): return float(val)
            elif isinstance(val, int): return int(val)
            else: return str(val)

        is_direct_mode = self.rb_direct_mode.isChecked() if force_direct_mode is None else force_direct_mode
        cache_key = f"{target_id}_direct" if is_direct_mode else f"{target_id}_patch"

        if target_id in self._yaml_cache:
            schema_data, c_patch_raw = self._yaml_cache[target_id]
            custom_patch = {} if is_direct_mode else c_patch_raw
        else:
            from ruamel.yaml import YAML
            from ruamel.yaml.constructor import DuplicateKeyError
            yaml = YAML(); yaml.preserve_quotes = True
            try:
                if os.path.exists(schema_path):
                    with open(schema_path, 'r', encoding='utf-8') as f: schema_data = yaml.load(f)
                else: schema_data = {}
                
                c_patch_raw = {}
                if os.path.exists(custom_path):
                    with open(custom_path, 'r', encoding='utf-8') as f:
                        c_data = yaml.load(f) or {}; c_patch_raw = c_data.get('patch', {}) or {}
                        
                self._yaml_cache[target_id] = (schema_data, c_patch_raw)
                custom_patch = {} if is_direct_mode else c_patch_raw
            except DuplicateKeyError as e:
                key_name = str(e.problem).split("found duplicate key")[-1].split("with value")[0].strip(' "\'')
                with open(schema_path, 'r', encoding='utf-8') as f: all_lines = f.readlines()
                import re
                pattern = re.compile(r'^\s*[\'"]?' + re.escape(key_name) + r'[\'"]?\s*:')
                actual_lines = [i for i, line_content in enumerate(all_lines) if pattern.search(line_content)]
                lines_info = [(actual_lines[0], all_lines[actual_lines[0]]), (actual_lines[-1], all_lines[actual_lines[-1]])] if len(actual_lines) >= 2 else []
                dlg = YamlDuplicateFixDialog(self, schema_path, key_name, lines_info)
                if dlg.exec() == QDialog.Accepted:
                    self.cfg_stack.removeWidget(new_tree); new_tree.deleteLater()
                    return self._build_and_cache_yaml_ui(target_id, activate)
                else:
                    self.cfg_stack.removeWidget(new_tree); new_tree.deleteLater(); return
            except Exception as e:
                QMessageBox.critical(self, "解析出错", str(e)); return

        def get_patch_val(patch_dict, path_str):
            if not patch_dict: return None
            exact_match = patch_dict.get(path_str)
            if exact_match is not None: return exact_match
            
            flat_merges = {}
            prefix = path_str + "/"
            for k, v in patch_dict.items():
                if str(k).startswith(prefix):
                    sub_k = str(k)[len(prefix):]
                    # 绝不把 /+ 的加号当做字典的 key 提取进去
                    if "/" not in sub_k and sub_k != "+": 
                        flat_merges[sub_k] = v
            
            parts = path_str.split('/')
            is_append_path = path_str.endswith("/+")
            if is_append_path:
                parts = parts[:-2] + [parts[-2] + "/+"]
                
            curr = patch_dict
            found_nested = True
            for p in parts:
                if isinstance(curr, dict) and p in curr: curr = curr[p]
                else: found_nested = False; break
                
            if found_nested and isinstance(curr, dict) and not is_append_path:
                merged = dict(curr)
                if flat_merges: merged.update(flat_merges)
                return merged
            elif flat_merges and not is_append_path: return flat_merges
            elif found_nested: return curr
            return None

        def refresh_indices(p_item):
            try:
                for i in range(p_item.childCount()): p_item.child(i).setText(0, f"  [{i}] 🔹")
            except: pass

        def swap_rows(p_item, idx1, idx2):
            if 0 <= idx1 < p_item.childCount() and 0 <= idx2 < p_item.childCount():
                iw1 = new_tree.itemWidget(p_item.child(idx1), 1); iw2 = new_tree.itemWidget(p_item.child(idx2), 1)
                if hasattr(iw1, 'get_key_value'):
                    k1, v1 = iw1.get_key_value(); k2, v2 = iw2.get_key_value(); iw1.set_key_value(k2, v2); iw2.set_key_value(k1, v1)
                else:
                    v1, v2 = iw1.get_value(), iw2.get_value(); iw1.input_field.setText(v2); iw2.input_field.setText(v1)

        def swap_blocks(p_item, idx1, idx2):
            if 0 <= idx1 < p_item.childCount() and 0 <= idx2 < p_item.childCount():
                i_max, i_min = max(idx1, idx2), min(idx1, idx2)
                item_max = p_item.takeChild(i_max); item_min = p_item.takeChild(i_min)
                p_item.insertChild(i_min, item_max); p_item.insertChild(i_max, item_min)
                refresh_indices(p_item)

        def add_dynamic_row(p_item, val_s, ins_idx=-1):
            child = QTreeWidgetItem(); child.setFlags(child.flags() & ~Qt.ItemIsSelectable)
            if ins_idx == -1: p_item.addChild(child)
            else: p_item.insertChild(ins_idx, child)
            input_w = DynamicInputWidget(val_s, "填入配置")
            action_w = DynamicActionWidget(KNOWN_COMPONENTS_DESC.get(val_s.split(":")[0].strip() if ":" in val_s else val_s, "配置项"))
            
            new_tree._py_refs.extend([input_w, action_w])
            
            input_w.value_changed.connect(lambda v: action_w.desc_label.setText(KNOWN_COMPONENTS_DESC.get(v.split(":")[0].strip() if ":" in v else v, "自定义")))
            def on_h(): action_w.show_buttons(); input_w.set_hover_state(True)
            def off_h(): 
                import shiboken6
                QTimer.singleShot(50, lambda: (action_w.hide_buttons(), input_w.set_hover_state(False) if hasattr(input_w, 'set_hover_state') else None) if shiboken6.isValid(input_w) and not input_w.underMouse() and not action_w.underMouse() else None)
            
            input_w.hover_in.connect(on_h); input_w.hover_out.connect(off_h)
            action_w.hover_in.connect(on_h); action_w.hover_out.connect(off_h)
            
            action_w.add_requested.connect(lambda p=p_item, c=child: add_dynamic_row(p, "", p.indexOfChild(c)+1))
            action_w.move_up_requested.connect(lambda p=p_item, c=child: swap_rows(p, p.indexOfChild(c), p.indexOfChild(c)-1))
            action_w.move_down_requested.connect(lambda p=p_item, c=child: swap_rows(p, p.indexOfChild(c), p.indexOfChild(c)+1))
            action_w.delete_requested.connect(lambda p=p_item, c=child: (p.removeChild(c), refresh_indices(p)))
            
            new_tree.setItemWidget(child, 1, input_w); new_tree.setItemWidget(child, 2, action_w)
            refresh_indices(p_item)

        def add_dynamic_block(parent_item, block_data, template, insert_index=-1):
            block_item = QTreeWidgetItem(); block_item.setBackground(0, QColor("#F8FAF8"))
            if insert_index == -1: parent_item.addChild(block_item)
            else: parent_item.insertChild(insert_index, block_item)
            opt_v = block_data.get("name") or block_data.get("accept") or block_data.get("option")
            if not opt_v and "options" in block_data and isinstance(block_data["options"], list) and block_data["options"]: opt_v = f"开关组: {block_data['options'][0]}..."
            if not opt_v: opt_v = "新规则块"
            block_item.setText(0, f"📦 规则块: {opt_v}")
            action_w = DynamicActionWidget("展开配置项")
            
            new_tree._py_refs.append(action_w)
            
            action_w.hover_in.connect(action_w.show_buttons); action_w.hover_out.connect(action_w.hide_buttons)
            action_w.add_requested.connect(lambda p=parent_item, b=block_item, t=template: add_dynamic_block(p, {}, t, p.indexOfChild(b) + 1))
            action_w.move_up_requested.connect(lambda p=parent_item, b=block_item: swap_blocks(p, p.indexOfChild(b), p.indexOfChild(b) - 1))
            action_w.move_down_requested.connect(lambda p=parent_item, b=block_item: swap_blocks(p, p.indexOfChild(b), p.indexOfChild(b) + 1))
            action_w.delete_requested.connect(lambda p=parent_item, b=block_item: p.removeChild(b))
            new_tree.setItemWidget(block_item, 2, action_w)

            child_widgets = {}
            sub_item_refs = {}
            for key, info in template.items():
                val = block_data.get(key)
                sub_item = QTreeWidgetItem(block_item, [info["title"], "", info.get("desc", "")])
                sub_item.setFlags(sub_item.flags() & ~Qt.ItemIsSelectable)
                sub_item_refs[key] = sub_item
                v_type = info["type"]
                w = None
                if v_type == "bool":
                    w = QCheckBox("开启")
                    bool_val = str(val).lower() == 'true' if isinstance(val, str) else bool(val)
                    w.setChecked(bool_val)
                elif v_type == "select":
                    w = QComboBox(); w.addItems(info["options"]); w.setStyleSheet(style_m); w.setFixedHeight(36)
                    w.setCurrentText("true" if val is True else "false" if val is False else str(val or ""))
                elif v_type in ["list_text", "raw_yaml"]:
                    clean_v = sanitize_val(val)
                    if v_type == "raw_yaml":
                        if isinstance(clean_v, (dict, list)):
                            from ruamel.yaml import YAML
                            from io import StringIO
                            _y = YAML()
                            _y.default_flow_style = False
                            buf = StringIO()
                            _y.dump(clean_v, buf)
                            txt_v = buf.getvalue().strip()
                        else:
                            txt_v = str(clean_v if clean_v is not None else "")
                    else:
                        if isinstance(clean_v, list):
                            if all(len(str(x)) <= 10 and '\n' not in str(x) for x in clean_v): txt_v = "[" + ", ".join(str(x) for x in clean_v) + "]"
                            else: txt_v = "\n".join(str(x) for x in clean_v)
                        else: txt_v = str(clean_v if clean_v is not None else "")
                    w = DynamicMultiLineWidget(txt_v, "支持输入任意多行文本或规则...")
                    w.needs_resize.connect(lambda h, itm=sub_item: safe_apply_size(itm, h))
                elif v_type == "action_kv":
                    pk = info.get("preset_keys", {})
                    a_k, a_v = "", ""
                    for pk_key in pk:
                        if pk_key in block_data: a_k = pk_key; a_v = block_data[pk_key]; break
                    w = DynamicKeyValueWidget(a_k, a_v, pk)
                    w.needs_resize.connect(lambda h, itm=sub_item: safe_apply_size(itm, h))
                else:
                    if isinstance(val, list): display_text = "[" + ", ".join(str(x) for x in val) + "]"
                    else: display_text = str(val if val is not None else "")
                    w = QLineEdit(display_text); w.setStyleSheet(style_m); w.setFixedHeight(36)
                    if key in ["option", "accept"]: w.textChanged.connect(lambda text, item=block_item: item.setText(0, f"📦 规则块: {text}") if shiboken6.isValid(item) else None)
                if w: 
                    new_tree.setItemWidget(sub_item, 1, w)
                    child_widgets[key] = (w, v_type, sub_item)
            
            for key, info in template.items():
                if "visible_if" in info:
                    def build_updater(target_item, conditions):
                        def _update():
                            visible = True
                            for c_k, c_vals in conditions.items():
                                widget_info = child_widgets.get(c_k, (None, None, None))
                                c_w, c_type = widget_info[0], widget_info[1]
                                if c_w and c_type == "select" and c_w.currentText() not in c_vals: visible = False
                            target_item.setHidden(not visible)
                        return _update
                    updater = build_updater(sub_item_refs[key], info["visible_if"])
                    for c_k in info["visible_if"].keys():
                        widget_info = child_widgets.get(c_k, (None, None, None))
                        c_w, c_type = widget_info[0], widget_info[1]
                        if c_type == "select": c_w.currentIndexChanged.connect(lambda _, u=updater: u())
                    updater() 
            block_item.setData(0, Qt.UserRole, child_widgets)

        def create_widget(f_path, v_type, n_info, curr_v, p_item):
            if v_type == "dynamic_block_list":
                t = n_info.get("template", {})
                if not curr_v or not isinstance(curr_v, list): add_dynamic_block(p_item, {}, t)
                else:
                    for b_data in curr_v: add_dynamic_block(p_item, b_data, t)
                file_dynamic_lists[f_path] = (p_item, "block_list"); return None

            if v_type == "dynamic_kv_list":
                pk = n_info.get("preset_keys", {})
                def add_kv(par, ks, vs):
                    c = QTreeWidgetItem(); par.addChild(c); c.setFlags(c.flags() & ~Qt.ItemIsSelectable)
                    iw = DynamicKeyValueWidget(ks, vs, pk)
                    aw = DynamicActionWidget(pk.get(ks, "参数说明"))
                    new_tree._py_refs.extend([iw, aw])
                    iw.needs_resize.connect(lambda h, itm=c: safe_apply_size(itm, h))
                    iw.key_changed.connect(lambda k: aw.desc_label.setText(pk.get(k, "")))
                    def on_h(): aw.show_buttons(); iw.set_hover_state(True)
                    def off_h(): QTimer.singleShot(50, lambda: (aw.hide_buttons(), iw.set_hover_state(False)) if shiboken6.isValid(iw) and not iw.underMouse() and not aw.underMouse() else None)
                    iw.hover_in.connect(on_h); iw.hover_out.connect(off_h)
                    aw.hover_in.connect(on_h); aw.hover_out.connect(off_h)
                    aw.add_requested.connect(lambda p=par: add_kv(p, "", "")); aw.delete_requested.connect(lambda p=par, child_node=c: p.removeChild(child_node))
                    new_tree.setItemWidget(c, 1, iw); new_tree.setItemWidget(c, 2, aw)
                    refresh_indices(par)
                    
                if not curr_v or not isinstance(curr_v, dict): add_kv(p_item, "", "")
                else:
                    for k, v in curr_v.items(): add_kv(p_item, k, v)
                file_dynamic_lists[f_path] = (p_item, "kv_list"); return None

            if v_type in ["dynamic_list", "dynamic_map"]:
                if not curr_v: add_dynamic_row(p_item, "")
                else:
                    if isinstance(curr_v, dict): items = curr_v.items()
                    elif isinstance(curr_v, list): items = curr_v
                    else: items = [curr_v]
                    for x in items: add_dynamic_row(p_item, f"{x[0]}: {x[1]}" if isinstance(x, tuple) else str(x))
                if v_type == "dynamic_map": file_dynamic_lists[f_path] = (p_item, "map_list")
                else: file_dynamic_lists[f_path] = (p_item, "str_list")
                return None

            if v_type == "schema_checkboxes":
                real_w = SchemaCheckboxesWidget(rime_dir, curr_v)
                real_w.needs_resize.connect(lambda h, itm=p_item: safe_apply_size(itm, h))
                file_widgets[f_path] = (real_w, v_type); return real_w
            if v_type == "algebra_patch":
                real_w = AlgebraPatchWidget(curr_v, is_pro=("wanxiang_pro" in target_id), is_direct=is_direct_mode)
                real_w.needs_resize.connect(lambda h, itm=p_item: safe_apply_size(itm, h))
                file_widgets[f_path] = (real_w, v_type); return real_w
            if v_type == "reverse_algebra":
                real_w = ReverseAlgebraWidget(curr_v, is_direct=is_direct_mode)
                file_widgets[f_path] = (real_w, v_type); return real_w
            if v_type == "english_algebra":
                real_w = EnglishAlgebraWidget(curr_v, is_direct=is_direct_mode)
                file_widgets[f_path] = (real_w, v_type); return real_w
            if v_type == "mixed_algebra":
                real_w = MixedAlgebraWidget(curr_v, is_direct=is_direct_mode)
                file_widgets[f_path] = (real_w, v_type); return real_w
            real_w = None
            if v_type in ["str", "int"]:
                if isinstance(curr_v, list): display_text = "[" + ", ".join(str(x) for x in curr_v) + "]"
                else: display_text = str(curr_v if curr_v is not None else "")
                real_w = QLineEdit(display_text); real_w.setStyleSheet(style_m); real_w.setFixedHeight(36)
            elif v_type == "bool":
                real_w = QCheckBox("启用")
                bool_val = str(curr_v).lower() == 'true' if isinstance(curr_v, str) else bool(curr_v)
                real_w.setChecked(bool_val)
            elif v_type == "select":
                real_w = QComboBox(); real_w.addItems(n_info.get("options", [])); real_w.setStyleSheet(style_m); real_w.setFixedHeight(36)
                val_str = "true" if curr_v is True else "false" if curr_v is False else str(curr_v) if curr_v is not None else ""
                real_w.setCurrentText(val_str)
            elif v_type in ["list_text", "raw_yaml"]:
                clean_v = sanitize_val(curr_v) 
                if v_type == "raw_yaml":
                    if isinstance(clean_v, (dict, list)):
                        from ruamel.yaml import YAML
                        from io import StringIO
                        _y = YAML()
                        _y.default_flow_style = False
                        buf = StringIO()
                        _y.dump(clean_v, buf)
                        txt_v = buf.getvalue().strip()
                    else:
                        txt_v = str(clean_v if clean_v is not None else "")
                else:
                    if isinstance(clean_v, list):
                        if all(len(str(x)) <= 10 and '\n' not in str(x) for x in clean_v): txt_v = "[" + ", ".join(str(x) for x in clean_v) + "]"
                        else: txt_v = "\n".join(str(x) for x in clean_v)
                    else: txt_v = str(clean_v if clean_v is not None else "")
                real_w = DynamicMultiLineWidget(txt_v, "支持输入任意多行文本或规则...") 
                real_w.needs_resize.connect(lambda h, itm=p_item: safe_apply_size(itm, h))
            else:
                if isinstance(curr_v, list): display_text = "[" + ", ".join(str(x) for x in curr_v) + "]"
                else: display_text = str(curr_v if curr_v is not None else "")
                real_w = QLineEdit(display_text); real_w.setStyleSheet(style_m); real_w.setFixedHeight(36)
            
            if real_w: 
                file_widgets[f_path] = (real_w, v_type)
                has_jump = n_info.get("jumpable")
                has_action = n_info.get("action_btn")
                if (has_jump or has_action) and v_type in ["str", "list_text", "raw_yaml"]:
                    wrapper = QWidget(); wrap_lay = QHBoxLayout(wrapper); wrap_lay.setContentsMargins(0, 0, 0, 0)
                    wrap_lay.addWidget(real_w, stretch=1)
                    btn = QPushButton(n_info.get("action_btn") or "🔗 穿透"); btn.setCursor(Qt.PointingHandCursor)
                    btn.setStyleSheet("QPushButton { background-color: transparent; border: 1px solid #61A165; color: #61A165; border-radius: 4px; padding: 4px 12px; font-weight: bold; } QPushButton:hover { background-color: #61A165; color: white; }")
                    
                    new_tree._py_refs.append(btn)
                    
                    if has_jump:
                        if v_type == "str": btn.clicked.connect(lambda: self.jump_to_reference(real_w.text()))
                        else: btn.clicked.connect(lambda: self.jump_to_reference(real_w.text_field.toPlainText()))
                    elif has_action: btn.clicked.connect(lambda: self.do_import_switches(real_w.text_field))
                    wrap_lay.addWidget(btn, alignment=Qt.AlignTop if v_type in ["list_text", "raw_yaml"] else Qt.AlignVCenter)
                    if v_type in ["list_text", "raw_yaml"]:
                        real_w.needs_resize.connect(lambda h, wdg=wrapper: safe_apply_height(wdg, h))
                        wrapper.setFixedHeight(max(real_w.height(), 40))
                    return wrapper
            return real_w

        try:
            if target_id == "wanxiang_algebra.yaml":
                for version_key, version_val in schema_data.items():
                    QApplication.processEvents()
                    if not isinstance(version_val, dict): continue
                    root = QTreeWidgetItem(new_tree, [f"📁 {version_key}", "", "版本 / 功能模块"])
                    root.setFont(0, QFont("", 11, QFont.Bold)); root.setForeground(0, QColor("#61A165"))
                    for input_type, rules_val in version_val.items():
                        item = QTreeWidgetItem(root, [f"📝 {input_type}", "", "正则转写段落 (支持直接复制与修改)"])
                        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                        path = f"{version_key}/{input_type}"
                        
                        p_val = get_patch_val(custom_patch, path)
                        appended_val = get_patch_val(custom_patch, path + "/+")
                        
                        if isinstance(rules_val, dict) and isinstance(p_val, dict):
                            display_val = dict(rules_val)
                            display_val.update(p_val)
                        elif isinstance(rules_val, list) or isinstance(p_val, list) or appended_val is not None:
                            display_val = list(rules_val or [])
                            if p_val is not None: 
                                display_val = p_val if isinstance(p_val, list) else [p_val]
                            if appended_val is not None:
                                if isinstance(appended_val, list): display_val.extend(appended_val)
                                else: display_val.append(appended_val)
                        else:
                            display_val = p_val if p_val is not None else rules_val
                            
                        file_base_values[path] = {'schema': rules_val, 'display': display_val} 
                        widget = create_widget(path, "raw_yaml", {}, display_val, item)
                        if widget: new_tree.setItemWidget(item, 1, widget)
            else:
                for meta_k, r_info in SCHEMA_META_CONFIG.items():
                    QApplication.processEvents()
                    has_match = bool(r_info.get("_match_file"))
                    if has_match and r_info["_match_file"] != target_id: continue
                    if meta_k == "speller" and target_id in ["wanxiang_reverse.schema.yaml", "wanxiang_english.schema.yaml", "wanxiang_mixedcode.schema.yaml"]: continue
                    
                    rk = r_info.get("_root_key", meta_k)
                    in_base = rk in schema_data
                    in_patch = rk in custom_patch or any(p.startswith(f"{rk}/") for p in custom_patch.keys())
                    if not has_match and not (in_base or in_patch): continue
                    
                    root = QTreeWidgetItem(new_tree, [r_info.get("_title", meta_k), "", ""])
                    root.setFont(0, QFont("", 11, QFont.Bold)); root.setForeground(0, QColor("#61A165"))
                    rd = schema_data.get(rk, {}) if in_base else {}
                    
                    for nk, ni in r_info["nodes"].items():
                        item = QTreeWidgetItem(root, [ni["title"], "", ni.get("desc", "")])
                        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                        path = rk if nk == "__self__" else f"{rk}/{nk}"
                        val_from_schema = rd if nk == "__self__" else (_get_nested_val(rd, nk) if isinstance(rd, dict) else rd)
                            
                        p_val = get_patch_val(custom_patch, path)
                        appended_val = get_patch_val(custom_patch, path + "/+")
                        
                        if isinstance(val_from_schema, dict) and isinstance(p_val, dict):
                            display_val = dict(val_from_schema)
                            display_val.update(p_val)
                        elif isinstance(val_from_schema, list) or isinstance(p_val, list) or appended_val is not None:
                            display_val = list(val_from_schema or [])
                            if p_val is not None: 
                                display_val = p_val if isinstance(p_val, list) else [p_val]
                            if appended_val is not None:
                                if isinstance(appended_val, list): display_val.extend(appended_val)
                                else: display_val.append(appended_val)
                        else:
                            display_val = p_val if p_val is not None else val_from_schema
                            
                        file_base_values[path] = {'schema': val_from_schema, 'display': display_val}
                        widget = create_widget(path, ni["type"], ni, display_val, item)
                        if widget: new_tree.setItemWidget(item, 1, widget)

            new_tree.expandAll()
            
            self._ui_cache[cache_key] = {'tree': new_tree, 'widgets': file_widgets, 'base': file_base_values, 'lists': file_dynamic_lists}
            
            if activate:
                self.cfg_stack.setCurrentWidget(new_tree)
                self._yaml_widgets = file_widgets
                self._yaml_base_values = file_base_values
                self._yaml_dynamic_lists = file_dynamic_lists
            new_tree.setUpdatesEnabled(True)
        except Exception as e:
            import traceback; self.log.appendPlainText(traceback.format_exc())
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "解析出错", str(e))
    def _safe_assign(self, parent, key, new_val):
        """精准在位更新，保留 YAML 容器的所有注释"""
        if isinstance(parent, list):
            old_val = parent[key] if key < len(parent) else None
        else:
            old_val = parent.get(key) if hasattr(parent, 'get') else None

        if isinstance(old_val, dict) and isinstance(new_val, dict):
            # 字典：在位更新
            for k in list(old_val.keys()):
                if k not in new_val: del old_val[k]
            for k, v in new_val.items():
                self._safe_assign(old_val, k, v)
                
        elif isinstance(old_val, list) and isinstance(new_val, list):
            min_len = min(len(old_val), len(new_val))
            # 1. 替换已存在的元素
            for i in range(min_len):
                self._safe_assign(old_val, i, new_val[i])
            # 2. 追加新元素
            if len(new_val) > len(old_val):
                for i in range(len(old_val), len(new_val)):
                    old_val.append(new_val[i])
            # 3. 删除多余元素
            elif len(old_val) > len(new_val):
                del old_val[len(new_val):]
                
        else:
            # 基础类型直接赋值
            parent[key] = new_val
    def save_yaml_config(self):
        """双引擎保存：所见即所得（WYSIWYG），精准保护原文件与智能结构探测"""
        if not HAS_RUAMEL: return
        # 如果是全局业务中控台，走专门的保存通道！
        if self.current_edit_file == "VIRTUAL_GLOBAL":
            self._save_virtual_global()
            return
        if not self._yaml_base_values:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "请稍候", "配置数据正在后台加载中，请等左侧文件树出现后再试。")
            return
        
        import os
        from PySide6.QtWidgets import QMessageBox
        rime_dir = self.upd_rime.text().strip()
        target_id = self.current_edit_file
        schema_path = os.path.join(rime_dir, target_id)
        custom_path = os.path.join(rime_dir, self.current_custom_file)

        patches_to_apply = {}
        patches_to_remove = []

        def is_really_changed(cur, base):
            import json
            def normalize(obj):
                if isinstance(obj, dict):
                    cleaned = {str(k): normalize(v) for k, v in obj.items() if v is not None and str(v).strip() != ""}
                    return cleaned if cleaned else ""
                elif isinstance(obj, (list, tuple)) or hasattr(obj, 'append'):
                    cleaned = [normalize(x) for x in obj if x is not None and str(x).strip() != ""]
                    return cleaned if cleaned else ""
                # === [核心修复]：强制将字符串 "true"/"false" 降维打击成纯正的布尔值 ===
                elif isinstance(obj, str) and obj.lower() in ['true', 'false']:
                    return obj.lower() == 'true'
                elif isinstance(obj, bool): return obj
                elif obj is None: return ""
                else: return str(obj).strip()
            
            return json.dumps(normalize(cur), sort_keys=True, ensure_ascii=False) != json.dumps(normalize(base), sort_keys=True, ensure_ascii=False)

        def is_empty(v):
            if v is None or v == "": return True
            if isinstance(v, (list, dict)) and not v: return True
            return False

        def smart_seq(val):
            if isinstance(val, list):
                from ruamel.yaml.comments import CommentedSeq
                seq = CommentedSeq(val)
                if all(len(str(x)) <= 10 and '\n' not in str(x) for x in val): seq.fa.set_flow_style()
                return seq
            return val

        from ruamel.yaml import YAML
        _safe_yaml = YAML(typ='safe')

        def parse_list_text(txt, orig_val=None, base_val=None, key_name=""):
            txt = txt.strip()
            # 🌟 智能自愈：只要底层是数组或名字带 format/rules，绝对不降级为字符串！
            is_array = isinstance(orig_val, list) or isinstance(base_val, list) or "format" in key_name or "rules" in key_name
            if not txt: return [] if is_array else None
            
            if txt.startswith('[') and txt.endswith(']'):
                try: 
                    res = _safe_yaml.load(txt)
                    return res if isinstance(res, list) else [res]
                except: return [txt]
                
            if '\n' in txt: return [line.strip() for line in txt.splitlines() if line.strip()]
            if ',' in txt: return [x.strip() for x in txt.split(',') if x.strip()]
            if is_array: return [txt]
            try: return _safe_yaml.load(txt)
            except: return txt

        allowed_paths = set()
        if target_id == "wanxiang_algebra.yaml":
            for path in self._yaml_widgets.keys(): allowed_paths.add(path)
            for path in getattr(self, '_yaml_dynamic_lists', {}).keys(): allowed_paths.add(path)
        else:
            for meta_k, r_info in SCHEMA_META_CONFIG.items():
                match_f = r_info.get("_match_file")
                if match_f and match_f != target_id: continue
                rk = r_info.get("_root_key", meta_k)
                for nk in r_info["nodes"].keys():
                    allowed_paths.add(rk if nk == "__self__" else f"{rk}/{nk}")

        is_direct_mode = self.rb_direct_mode.isChecked()

        # ================= 1. 收集静态表单项 =================
        for full_path, (widget, v_type) in self._yaml_widgets.items():
            if full_path not in allowed_paths: continue

            base_info = self._yaml_base_values.get(full_path, {})
            schema_val = base_info.get('schema')
            display_val = base_info.get('display')
            current_val = None

            if v_type == "schema_checkboxes": current_val = widget.get_value()
            elif v_type == "algebra_patch": current_val = widget.get_value()
            elif v_type == "reverse_algebra": current_val = widget.get_value()
            elif v_type == "english_algebra": current_val = widget.get_value()
            elif v_type == "mixed_algebra": current_val = widget.get_value()
            elif v_type == "bool": current_val = widget.isChecked()
            elif v_type == "int":
                try: current_val = int(widget.text().strip())
                except: current_val = widget.text().strip()
            elif v_type == "select":
                val_str = widget.currentText()
                if val_str not in ["默认/不指定", ""]:
                    try: current_val = int(val_str)
                    except: current_val = val_str
            elif v_type == "list_text":
                current_val = parse_list_text(widget.text_field.toPlainText(), orig_val=display_val, base_val=schema_val, key_name=full_path.split('/')[-1])
            elif v_type == "raw_yaml":
                txt = widget.text_field.toPlainText().strip()
                if txt:
                    try: current_val = _safe_yaml.load(txt)
                    except: current_val = [line.strip() for line in txt.splitlines() if line.strip()]
            else:
                val_str = widget.text().strip()
                if val_str:
                    if val_str.startswith('[') and val_str.endswith(']'):
                        try: current_val = _safe_yaml.load(val_str)
                        except: current_val = val_str
                    elif val_str.isdigit(): current_val = int(val_str)
                    else: current_val = val_str

            current_val = smart_seq(current_val)

            if is_direct_mode:
                if is_really_changed(current_val, schema_val):
                    patches_to_apply[full_path] = current_val
            else:
                if isinstance(current_val, dict):
                    schema_dict = schema_val if isinstance(schema_val, dict) else {}
                    display_dict = display_val if isinstance(display_val, dict) else {}
                    
                    for k, v in current_val.items():
                        sub_path = f"{full_path}/{k}"
                        if k in ["__include", "__patch"]:
                            patches_to_apply[sub_path] = v
                        elif is_really_changed(v, schema_dict.get(k)): 
                            patches_to_apply[sub_path] = v
                        else: 
                            patches_to_remove.append(sub_path)
                            
                    for k in display_dict:
                        if k not in current_val:
                            patches_to_remove.append(f"{full_path}/{k}")
                elif isinstance(current_val, list):
                    if is_really_changed(current_val, display_val):
                        is_special = full_path.endswith("/__patch") or full_path.endswith("/__include")
                        if is_empty(current_val) or (not is_special and not is_really_changed(current_val, schema_val)):
                            patches_to_remove.append(full_path)
                            patches_to_remove.append(full_path + "/+")
                        else:
                            is_append = False
                            schema_list = schema_val if isinstance(schema_val, list) else []
                            n = len(schema_list)

                            if "__patch" not in full_path and len(current_val) >= n and not is_really_changed(current_val[:n], schema_list):
                                is_append = True
                                appended_items = current_val[n:]
                            
                            if is_append and appended_items:
                                patches_to_apply[full_path + "/+"] = appended_items
                                patches_to_remove.append(full_path)
                            elif is_append and not appended_items:
                                patches_to_remove.append(full_path)
                                patches_to_remove.append(full_path + "/+")
                            else:
                                patches_to_apply[full_path] = current_val
                                patches_to_remove.append(full_path + "/+")
                else:
                    if is_really_changed(current_val, display_val):
                        is_special = full_path.endswith("/__patch") or full_path.endswith("/__include")
                        if is_empty(current_val) or (not is_special and not is_really_changed(current_val, schema_val)):
                            patches_to_remove.append(full_path)
                        else:
                            patches_to_apply[full_path] = current_val

        # ================= 2. 处理动态列表与块 =================
        for full_path, (parent_item, list_type) in getattr(self, '_yaml_dynamic_lists', {}).items():
            if full_path not in allowed_paths: continue

            base_info = self._yaml_base_values.get(full_path, {})
            schema_val = base_info.get('schema')
            display_val = base_info.get('display')
            current_tree = self.cfg_stack.currentWidget()
            import shiboken6
            
            if list_type == "str_list":
                current_val = []
                for i in range(parent_item.childCount()):
                    w = current_tree.itemWidget(parent_item.child(i), 1)
                    if isinstance(w, DynamicInputWidget):
                        val = w.get_value()
                        if val: current_val.append(val)
                current_val = smart_seq(current_val)

            elif list_type == "block_list":
                current_val = []  
                for i in range(parent_item.childCount()):
                    child = parent_item.child(i)
                    child_widgets = child.data(0, Qt.UserRole)
                    if not child_widgets: continue
                    
                    original_dict = display_val[i] if isinstance(display_val, list) and i < len(display_val) and isinstance(display_val[i], dict) else {}
                    from ruamel.yaml.comments import CommentedMap
                    block_dict = CommentedMap(original_dict) 
                    
                    is_empty_or_hidden = True
                    for key, widget_info in child_widgets.items():
                        if len(widget_info) == 3:
                            w, v_type, sub_item = widget_info
                            if sub_item.isHidden(): continue 
                        else:
                            w, v_type = widget_info 
                            
                        if not shiboken6.isValid(w): continue
                        
                        val = None
                        if v_type == "action_kv":
                            ak, av = w.get_key_value()
                            if ak and av: block_dict[ak] = av; is_empty_or_hidden = False
                            continue
                        elif v_type == "bool": 
                            val = w.isChecked()
                            if not val and key not in original_dict: continue
                        elif v_type == "select": 
                            val = w.currentText()
                            if not val or val == "默认/不指定": val = None
                        elif v_type == "list_text": 
                            val = parse_list_text(w.text_field.toPlainText())
                            if not val and isinstance(original_dict.get(key), list): val = []
                        else:
                            txt = w.text().strip()
                            if txt:
                                if txt.startswith('[') and txt.endswith(']'):
                                    from ruamel.yaml import YAML
                                    try: val = YAML(typ='safe').load(txt)
                                    except: val = txt
                                elif txt.lower() == "true": val = True
                                elif txt.lower() == "false": val = False
                                else: val = int(txt) if txt.isdigit() else txt
                        
                        val = smart_seq(val)
                        if val is not None and val != "": 
                            block_dict[key] = val
                            is_empty_or_hidden = False
                        else:
                            if key in block_dict: del block_dict[key]
                            
                    if not is_empty_or_hidden and block_dict: current_val.append(block_dict) 

            elif list_type == "map_list":
                current_val = {}
                for i in range(parent_item.childCount()):
                    w = current_tree.itemWidget(parent_item.child(i), 1)
                    if isinstance(w, DynamicInputWidget):
                        val = w.get_value()
                        if val and ":" in val:
                            k, v = val.split(":", 1)
                            current_val[k.strip()] = v.strip()

            elif list_type == "kv_list":
                current_val = {}
                for i in range(parent_item.childCount()):
                    w = current_tree.itemWidget(parent_item.child(i), 1)
                    if hasattr(w, 'get_key_value'):
                        k, v = w.get_key_value()
                        if k and v: 
                            desc = w.preset_keys.get(k, "")
                            if "(true/false)" in desc.lower(): v = True if v.lower() == "true" else False
                            elif "数字" in desc:
                                try: v = int(v)
                                except: pass
                            elif "填列表" in desc or "数组" in desc:
                                v = parse_list_text(str(v), orig_val=[], base_val=[], key_name=k)
                            current_val[k] = smart_seq(v)

            if is_direct_mode:
                if is_really_changed(current_val, schema_val):
                    patches_to_apply[full_path] = current_val
            else:
                if isinstance(current_val, dict):
                    raw_patch = self._yaml_cache.get(target_id, ({}, {}))[1]
                    is_full_override = full_path in raw_patch and isinstance(raw_patch[full_path], dict)
                    
                    if is_full_override:
                        if is_really_changed(current_val, display_val):
                            is_special = full_path.endswith("/__patch") or full_path.endswith("/__include")
                            if is_empty(current_val) or (not is_special and not is_really_changed(current_val, schema_val)):
                                patches_to_remove.append(full_path)
                            else:
                                patches_to_apply[full_path] = current_val
                    else:
                        schema_dict = schema_val if isinstance(schema_val, dict) else {}
                        display_dict = display_val if isinstance(display_val, dict) else {}
                        
                        for k, v in current_val.items():
                            sub_path = f"{full_path}/{k}"
                            if k in ["__include", "__patch"]: 
                                patches_to_apply[sub_path] = v
                            elif is_really_changed(v, schema_dict.get(k)): 
                                patches_to_apply[sub_path] = v
                            else: 
                                patches_to_remove.append(sub_path)
                                
                        for k in display_dict:
                            if k not in current_val: patches_to_remove.append(f"{full_path}/{k}")
                else:
                    if is_really_changed(current_val, display_val):
                        is_special = full_path.endswith("/__patch") or full_path.endswith("/__include")
                        if is_empty(current_val) or (not is_special and not is_really_changed(current_val, schema_val)):
                            patches_to_remove.append(full_path)
                            patches_to_remove.append(full_path + "/+")
                        else:
                            is_append = False
                            schema_list = schema_val if isinstance(schema_val, list) else []
                            n = len(schema_list)
                            
                            if len(current_val) >= n and not is_really_changed(current_val[:n], schema_list):
                                is_append = True
                                appended_items = current_val[n:]
                            
                            if is_append and appended_items:
                                patches_to_apply[full_path + "/+"] = appended_items
                                patches_to_remove.append(full_path)
                            elif is_append and not appended_items:
                                patches_to_remove.append(full_path)
                                patches_to_remove.append(full_path + "/+")
                            else:
                                patches_to_apply[full_path] = current_val
                                patches_to_remove.append(full_path + "/+")

        # 底层智能写入引擎
        from ruamel.yaml import YAML
        yaml = YAML(); yaml.preserve_quotes = True; yaml.width = 1024
        yaml.indent(mapping=2, sequence=4, offset=2)

        try:
            if is_direct_mode:
                if os.path.exists(schema_path):
                    with open(schema_path, 'r', encoding='utf-8') as f: target_data = yaml.load(f) or {}
                else: target_data = {}

                from ruamel.yaml.comments import CommentedMap, CommentedSeq
                def parse_p(p_str): return p_str.split('/')
                
                for path, val in patches_to_apply.items():
                    parts = parse_p(path); curr = target_data
                    for i, p in enumerate(parts[:-1]):
                        next_p = parts[i+1]
                        if p.startswith('@'): 
                            idx = int(p[1:])
                            while len(curr) <= idx: curr.append(None)
                            if curr[idx] is None: curr[idx] = CommentedSeq() if next_p.startswith('@') else CommentedMap()
                            curr = curr[idx]
                        else:
                            if p not in curr: curr[p] = CommentedSeq() if next_p.startswith('@') else CommentedMap()
                            curr = curr[p]
                    last = parts[-1]
                    if last.startswith('@'):
                        idx = int(last[1:])
                        while len(curr) <= idx: curr.append(None)
                        self._safe_assign(curr, idx, val)
                    else: self._safe_assign(curr, last, val)

                for path in patches_to_remove:
                    parts = parse_p(path); curr = target_data
                    try:
                        for p in parts[:-1]: curr = curr[int(p[1:])] if p.startswith('@') else curr[p]
                        last = parts[-1]
                        if last.startswith('@'): del curr[int(last[1:])]
                        elif last in curr: del curr[last]
                    except: pass

                with open(schema_path, 'w', encoding='utf-8') as f: yaml.dump(target_data, f)
                self.log.appendPlainText(f"⚠️ [直写] {target_id} 已修改! (更新 {len(patches_to_apply)} 项)")
                
                if target_id in self._yaml_cache:
                    _, old_patch = self._yaml_cache[target_id]
                    self._yaml_cache[target_id] = (target_data, old_patch)
                    
            else:
                custom_data = {}
                if os.path.exists(custom_path):
                    with open(custom_path, 'r', encoding='utf-8') as f: custom_data = yaml.load(f) or {}

                if not patches_to_apply and not patches_to_remove:
                    self.log.appendPlainText("💡 未检测到任何改动，取消保存。")
                    return

                if 'patch' not in custom_data or custom_data['patch'] is None: custom_data['patch'] = {}
                
                from ruamel.yaml.comments import CommentedMap
                def set_patch_val(p_dict, path, val):
                    if path.endswith("/__patch") or path.endswith("/__include"):
                        base_path, op = path.rsplit('/', 1)
                        if base_path not in p_dict or not isinstance(p_dict[base_path], dict):
                            p_dict[base_path] = CommentedMap()
                        p_dict[base_path][op] = val
                        
                        _node = p_dict[base_path]
                        if "__include" in _node and "__patch" in _node:
                            _keys = list(_node.keys())
                            if _keys.index("__include") > _keys.index("__patch"):
                                _v_patch = _node.pop("__patch")
                                _node["__patch"] = _v_patch
                                
                        if path in p_dict: del p_dict[path] 
                        return
                        
                    parts = path.split('/')
                    if path.endswith("/+"):
                        parts = parts[:-2] + [parts[-2] + "/+"]
                        
                    for i in range(1, len(parts)):
                        parent_path = '/'.join(path.split('/')[:i])
                        if parent_path in p_dict and isinstance(p_dict[parent_path], dict):
                            _node = p_dict[parent_path]
                            sub_parts = parts[i:]
                            for p in sub_parts[:-1]:
                                if p not in _node or not isinstance(_node[p], dict): _node[p] = {}
                                _node = _node[p]
                            self._safe_assign(_node, sub_parts[-1], val)
                            return
                    self._safe_assign(p_dict, path, val)

                def del_patch_val(p_dict, path):
                    if path.endswith("/__patch") or path.endswith("/__include"):
                        base_path, op = path.rsplit('/', 1)
                        if base_path in p_dict and isinstance(p_dict[base_path], dict):
                            if op in p_dict[base_path]:
                                del p_dict[base_path][op]
                                if not p_dict[base_path]: del p_dict[base_path] # 空了连母节点一起删
                        if path in p_dict: del p_dict[path]
                        return
                        
                    if path in p_dict:
                        del p_dict[path]
                        return
                    parts = path.split('/')
                    if path.endswith("/+"):
                        parts = parts[:-2] + [parts[-2] + "/+"]
                        
                    for i in range(1, len(parts)):
                        parent_path = '/'.join(path.split('/')[:i])
                        if parent_path in p_dict and isinstance(p_dict[parent_path], dict):
                            _node = p_dict[parent_path]
                            sub_parts = parts[i:]
                            try:
                                for p in sub_parts[:-1]: _node = _node[p]
                                del _node[sub_parts[-1]]
                            except: pass
                            return
                for p, v in patches_to_apply.items(): set_patch_val(custom_data['patch'], p, v)
                for p in patches_to_remove: del_patch_val(custom_data['patch'], p)
                    
                if 'patch' in custom_data and not custom_data['patch']: del custom_data['patch']

                with open(custom_path, 'w', encoding='utf-8') as f: yaml.dump(custom_data, f)
                self.log.appendPlainText(f"💾 [补丁] {self.current_custom_file} 已保存! (更新 {len(patches_to_apply)} 项, 剔除 {len(patches_to_remove)} 项)")

                if target_id in self._yaml_cache:
                    old_schema, _ = self._yaml_cache[target_id]
                    self._yaml_cache[target_id] = (old_schema, custom_data.get('patch', {}))

            for p, v in patches_to_apply.items():
                if p in self._yaml_base_values:
                    if is_direct_mode: self._yaml_base_values[p]['schema'] = v
                    self._yaml_base_values[p]['display'] = v
            for p in patches_to_remove:
                if p in self._yaml_base_values:
                    if is_direct_mode: self._yaml_base_values[p]['schema'] = None
                    self._yaml_base_values[p]['display'] = self._yaml_base_values[p].get('schema')

            # 仅删除另一个对立模式的过期缓存，当前界面保留不闪烁
            other_mode_key = f"{self.current_edit_file}_{'patch' if is_direct_mode else 'direct'}"
            if other_mode_key in self._ui_cache:
                w = self._ui_cache[other_mode_key]['tree']
                self.cfg_stack.removeWidget(w)
                w.deleteLater()
                del self._ui_cache[other_mode_key]
            reply = QMessageBox.information(self, "保存成功", "配置已精准写入对应文件。\n是否立即触发 Rime 部署以生效？", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes: self._start_and_deploy_from_main()

        except Exception as e:
            import traceback; self.log.appendPlainText(traceback.format_exc())
            QMessageBox.critical(self, "失败", f"写入错误: {e}")
    def _save_virtual_global(self):
        """智能双轨保存引擎：集成 5 大核心功能，支持空补丁智能自毁与脏值写入"""
        widgets = self._ui_cache.get("VIRTUAL_GLOBAL", {}).get("widgets", {})
        if not widgets: return
        
        from PySide6.QtWidgets import QMessageBox
        import os
        
        # 提取所有界面数据并校验
        # -- 候选数 --
        page_size_txt = widgets["page_size"].text().strip()
        if not page_size_txt or not (1 <= int(page_size_txt) <= 10):
            QMessageBox.warning(self, "校验失败", "⚠️ 保存中断：\n候选数不能为空且必须在 1-10 之间！")
            return 
        auto_freq_widget = widgets.get("auto_freq")
        auto_freq_val = True if auto_freq_widget and auto_freq_widget.currentIndex() == 0 else False
        main_dict_widget = widgets.get("main_dict")
        main_dict_val = main_dict_widget.text().strip() if main_dict_widget else ""
        if main_dict_widget and (not main_dict_val or not main_dict_val.replace("_", "").isalnum()):
            QMessageBox.warning(self, "校验失败", "⚠️ 保存中断：\n词库名称只能包含字母、数字和下划线且不能为空！")
            return
        # 新增提取：语法模型一键配置 --
        grammar_widget = widgets.get("grammar_model")
        grammar_action = grammar_widget.currentIndex() if grammar_widget else 0


        page_size_val = int(page_size_txt)
        
        # -- 翻页键 --
        paging_style = widgets["paging"].currentText()
        
        # -- 次选/三选 --
        cand_widgets = widgets.get("cand_keys")
        val2 = cand_widgets[0].text().strip() if cand_widgets else ""
        val3 = cand_widgets[1].text().strip() if cand_widgets else ""
        rime_val2 = RIME_KEY_MAP.get(val2, val2)
        rime_val3 = RIME_KEY_MAP.get(val3, val3)
        
        # -- 反查快捷键 (修复丢失的 rev_key 变量) --
        rev_widget = widgets.get("reverse_lookup")
        rev_key = rev_widget.text().strip() if rev_widget else ""
        if rev_widget and (not rev_key or len(rev_key) != 1 or rev_key.isalnum()):
            QMessageBox.warning(self, "校验失败", "⚠️ 保存中断：\n反查快捷键必须是单个符号（不能是字母或数字）！")
            return
            
        # -- 超级提示 --
        st_widgets = widgets.get("super_tips")
        db_name_val, tips_key_val, dt_list = "", "", []
        if st_widgets:
            db_name_val = st_widgets["db_name"].text().strip()
            tips_key_val = st_widgets["tips_key"].text().strip()
            dt_text = st_widgets["disabled_types"].text_field.toPlainText().strip()
            dt_list = [line.strip() for line in dt_text.splitlines() if line.strip()]

        is_direct = self.rb_direct_mode.isChecked()
        
        try:
            from ruamel.yaml import YAML
            from ruamel.yaml.comments import CommentedMap, CommentedSeq
            yaml = YAML(); yaml.preserve_quotes = True; yaml.indent(mapping=2, sequence=4, offset=2)
            rime_dir = self.upd_rime.text().strip()
            updated_files = []
            deleted_files = [] 
            
            # 智能落盘工具：自动处理垃圾回收与内存对齐
            def _smart_write(file_path, data, f_name, is_dir):
                if not is_dir:
                    keys = list(data.keys())
                    if not keys or (keys == ["patch"] and not data.get("patch")):
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            deleted_files.append(os.path.basename(file_path))
                        if f_name in self._yaml_cache:
                            self._yaml_cache[f_name] = (self._yaml_cache[f_name][0], {})
                        return False 
                    if "patch" not in data: data["patch"] = {}
                
                with open(file_path, 'w', encoding='utf-8') as f: yaml.dump(data, f)
                if f_name in self._yaml_cache:
                    old_schema, old_patch = self._yaml_cache[f_name]
                    if is_dir: self._yaml_cache[f_name] = (data, old_patch)
                    else: self._yaml_cache[f_name] = (old_schema, data.get("patch", {}))
                return True

            # 动作 写入候选数
            for f_name in ["default.yaml", "wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"]:
                base_f_path = os.path.join(rime_dir, f_name)
                if not os.path.exists(base_f_path): continue 

                target_file = f_name if is_direct else f_name.replace(".yaml", "").replace(".schema", "") + ".custom.yaml"
                f_path = os.path.join(rime_dir, target_file)
                base_data = self._yaml_cache.get(f_name, ({}, {}))[0]
                base_page_size = _get_nested_val(base_data, "menu/page_size", 6)
                
                if not os.path.exists(f_path) and not is_direct: target_data = {"patch": {}}
                elif os.path.exists(f_path):
                    with open(f_path, 'r', encoding='utf-8') as f: target_data = yaml.load(f) or {}
                else: continue 
                
                modified = False
                if is_direct:
                    old_ps = _get_nested_val(target_data, "menu/page_size", None)
                    if old_ps != page_size_val:
                        if "menu" not in target_data: target_data["menu"] = {}
                        target_data["menu"]["page_size"] = page_size_val
                        modified = True
                else:
                    if "patch" not in target_data or target_data["patch"] is None: target_data["patch"] = {}
                    if page_size_val != base_page_size:
                        if target_data["patch"].get("menu/page_size") != page_size_val:
                            target_data["patch"]["menu/page_size"] = page_size_val
                            modified = True
                    else:
                        if "menu/page_size" in target_data["patch"]:
                            del target_data["patch"]["menu/page_size"]
                            modified = True
                            
                if modified:
                    if _smart_write(f_path, target_data, f_name, is_direct):
                        if target_file not in updated_files: updated_files.append(target_file)
            # 动作 同步自动调频 (translator/enable_user_dict)
            if auto_freq_widget:
                for f_name in ["wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"]:
                    base_f_path = os.path.join(rime_dir, f_name)
                    if not os.path.exists(base_f_path): continue 

                    target_file = f_name if is_direct else f_name.replace(".schema.yaml", ".custom.yaml")
                    f_path = os.path.join(rime_dir, target_file)
                    
                    base_data = self._yaml_cache.get(f_name, ({}, {}))[0]
                    base_val = _get_nested_val(base_data, "translator/enable_user_dict", True)
                    
                    if not os.path.exists(f_path) and not is_direct: target_data = {"patch": {}}
                    elif os.path.exists(f_path):
                        with open(f_path, 'r', encoding='utf-8') as f: target_data = yaml.load(f) or {}
                    else: continue 
                    
                    modified = False
                    
                    if is_direct:
                        if "translator" not in target_data: target_data["translator"] = {}
                        if target_data["translator"].get("enable_user_dict") != auto_freq_val:
                            target_data["translator"]["enable_user_dict"] = auto_freq_val
                            modified = True
                    else:
                        if "patch" not in target_data or target_data["patch"] is None: target_data["patch"] = {}
                        if auto_freq_val != base_val:
                            if target_data["patch"].get("translator/enable_user_dict") != auto_freq_val:
                                target_data["patch"]["translator/enable_user_dict"] = auto_freq_val
                                modified = True
                        else:
                            if "translator/enable_user_dict" in target_data["patch"]:
                                del target_data["patch"]["translator/enable_user_dict"]
                                modified = True

                    if modified:
                        if _smart_write(f_path, target_data, f_name, is_direct):
                            if target_file not in updated_files: updated_files.append(target_file)
            # 动作 同步主词库名称 (自动防覆盖处理)
            if main_dict_val:
                import shutil
                dst_dict = os.path.join(rime_dir, f"{main_dict_val}.dict.yaml")
                if main_dict_val not in ["wanxiang", "wanxiang_pro"] and not os.path.exists(dst_dict):
                    src_pro = os.path.join(rime_dir, "wanxiang_pro.dict.yaml")
                    src_base = os.path.join(rime_dir, "wanxiang.dict.yaml")
                    if os.path.exists(src_pro):
                        shutil.copy2(src_pro, dst_dict)
                        self.log.appendPlainText(f"📦 已自动为您复制提取独立词库: {main_dict_val}.dict.yaml (基于 Pro)")
                    elif os.path.exists(src_base):
                        shutil.copy2(src_base, dst_dict)
                        self.log.appendPlainText(f"📦 已自动为您复制提取独立词库: {main_dict_val}.dict.yaml (基于 Base)")

                for f_name in ["wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"]:
                    base_f_path = os.path.join(rime_dir, f_name)
                    if not os.path.exists(base_f_path): continue 
                    target_file = f_name if is_direct else f_name.replace(".schema.yaml", ".custom.yaml")
                    f_path = os.path.join(rime_dir, target_file)
                    base_data = self._yaml_cache.get(f_name, ({}, {}))[0]
                    schema_default_dict = "wanxiang_pro" if "pro" in f_name else "wanxiang"
                    orig_dict = _get_nested_val(base_data, "translator/dictionary", schema_default_dict)
                    if main_dict_val in ["wanxiang", "wanxiang_pro"]:
                        target_val = schema_default_dict
                    else:
                        target_val = main_dict_val
                    
                    if not os.path.exists(f_path) and not is_direct: target_data = {"patch": {}}
                    elif os.path.exists(f_path):
                        with open(f_path, 'r', encoding='utf-8') as f: target_data = yaml.load(f) or {}
                    else: continue 
                    
                    modified = False
                    
                    if is_direct:
                        def set_direct(path, val):
                            nonlocal modified
                            keys = path.split('/')
                            curr = target_data
                            for k in keys[:-1]:
                                if k not in curr: curr[k] = {}
                                curr = curr[k]
                            if curr.get(keys[-1]) != val: curr[keys[-1]] = val; modified = True
                                
                        set_direct("translator/dictionary", target_val)
                        set_direct("user_dict_set/dictionary", target_val)
                        set_direct("add_user_dict/dictionary", target_val)
                    else:
                        if "patch" not in target_data or target_data["patch"] is None: target_data["patch"] = {}
                        def patch_field(k, nv, bv):
                            nonlocal modified
                            if nv != bv:
                                if target_data["patch"].get(k) != nv: self._safe_assign(target_data["patch"], k, nv); modified = True
                            elif k in target_data["patch"]: del target_data["patch"][k]; modified = True
                                    
                        patch_field("translator/dictionary", target_val, orig_dict)
                        patch_field("user_dict_set/dictionary", target_val, orig_dict)
                        patch_field("add_user_dict/dictionary", target_val, orig_dict)

                    if modified:
                        if _smart_write(f_path, target_data, f_name, is_direct):
                            if target_file not in updated_files: updated_files.append(target_file)
            # 同步语法模型参数 (LMDG 一键配置)
            if grammar_action in [1, 2]:  # 1: 写入推荐参数, 2: 清除参数
                # 使用 CommentedMap 保证写入 YAML 时的字段顺序极其优美！
                from ruamel.yaml.comments import CommentedMap
                g_map = CommentedMap()
                g_map["language"] = "wanxiang-lts-zh-hans"
                g_map["collocation_max_length"] = 7
                g_map["collocation_min_length"] = 3
                g_map["collocation_penalty"] = -10
                g_map["non_collocation_penalty"] = 3
                g_map["weak_collocation_penalty"] = -35
                g_map["unseen_two_char_penalty"] = 0
                g_map["rear_penalty"] = -8

                for f_name in ["wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"]:
                    base_f_path = os.path.join(rime_dir, f_name)
                    if not os.path.exists(base_f_path): continue 

                    target_file = f_name if is_direct else f_name.replace(".schema.yaml", ".custom.yaml")
                    f_path = os.path.join(rime_dir, target_file)
                    
                    if not os.path.exists(f_path) and not is_direct: target_data = {"patch": {}}
                    elif os.path.exists(f_path):
                        with open(f_path, 'r', encoding='utf-8') as f: target_data = yaml.load(f) or {}
                    else: continue 
                    
                    modified = False
                    
                    if is_direct:
                        def set_d(path, val, remove=False):
                            nonlocal modified
                            keys = path.split('/')
                            curr = target_data
                            if remove:
                                for k in keys[:-1]:
                                    if k not in curr: return
                                    curr = curr[k]
                                if keys[-1] in curr:
                                    del curr[keys[-1]]; modified = True
                                return
                            
                            for k in keys[:-1]:
                                if k not in curr: curr[k] = {}
                                curr = curr[k]
                            if curr.get(keys[-1]) != val:
                                curr[keys[-1]] = val; modified = True

                        if grammar_action == 1:
                            set_d("grammar", g_map)
                            set_d("translator/contextual_suggestions", False)
                            set_d("translator/max_homophones", 8)
                            set_d("translator/max_homographs", 8)
                        else:
                            set_d("grammar", None, True)
                            set_d("translator/contextual_suggestions", None, True)
                            set_d("translator/max_homophones", None, True)
                            set_d("translator/max_homographs", None, True)
                    else:
                        if "patch" not in target_data or target_data["patch"] is None: target_data["patch"] = {}
                        patch_dict = target_data["patch"]
                        
                        def set_p(k, v, remove=False):
                            nonlocal modified
                            if remove:
                                if k in patch_dict: del patch_dict[k]; modified = True
                            else:
                                if patch_dict.get(k) != v: patch_dict[k] = v; modified = True
                                
                        if grammar_action == 1:
                            set_p("grammar", g_map)
                            set_p("translator/contextual_suggestions", False)
                            set_p("translator/max_homophones", 8)
                            set_p("translator/max_homographs", 8)
                        else:
                            set_p("grammar", None, True)
                            set_p("translator/contextual_suggestions", None, True)
                            set_p("translator/max_homophones", None, True)
                            set_p("translator/max_homographs", None, True)

                    if modified:
                        if _smart_write(f_path, target_data, f_name, is_direct):
                            if target_file not in updated_files: updated_files.append(target_file)
            # 动作 同步超级提示 (super_tips)
            if st_widgets:
                seq = CommentedSeq(dt_list)
                if all(len(str(x)) <= 15 for x in dt_list): seq.fa.set_flow_style() 

                for f_name in ["wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"]:
                    base_f_path = os.path.join(rime_dir, f_name)
                    if not os.path.exists(base_f_path): continue 

                    target_file = f_name if is_direct else f_name.replace(".schema.yaml", ".custom.yaml")
                    f_path = os.path.join(rime_dir, target_file)
                    base_data = self._yaml_cache.get(f_name, ({}, {}))[0]
                    base_st = base_data.get("super_tips", {})
                    base_db, base_key = base_st.get("db_name", "lua/tips"), base_st.get("tips_key", "comma")
                    base_dt = base_st.get("disabled_types", [])
                    if not isinstance(base_dt, list): base_dt = []
                    
                    if not os.path.exists(f_path) and not is_direct: target_data = {"patch": {}}
                    elif os.path.exists(f_path):
                        with open(f_path, 'r', encoding='utf-8') as f: target_data = yaml.load(f) or {}
                    else: continue 
                    
                    modified = False
                    if is_direct:
                        if "super_tips" not in target_data: target_data["super_tips"] = {}
                        if target_data["super_tips"].get("db_name") != db_name_val:
                            target_data["super_tips"]["db_name"] = db_name_val; modified = True
                        if target_data["super_tips"].get("tips_key") != tips_key_val:
                            target_data["super_tips"]["tips_key"] = tips_key_val; modified = True
                        
                        cur_dt = target_data["super_tips"].get("disabled_types", [])
                        if not isinstance(cur_dt, list): cur_dt = []
                        if cur_dt != dt_list:
                            if dt_list: self._safe_assign(target_data["super_tips"], "disabled_types", seq)
                            else: target_data["super_tips"].pop("disabled_types", None)
                            modified = True
                    else:
                        if "patch" not in target_data or target_data["patch"] is None: target_data["patch"] = {}
                        def patch_field(k, nv, bv):
                            nonlocal modified
                            if nv != bv:
                                if target_data["patch"].get(k) != nv: self._safe_assign(target_data["patch"], k, nv); modified = True
                            elif k in target_data["patch"]: del target_data["patch"][k]; modified = True
                                    
                        patch_field("super_tips/db_name", db_name_val, base_db)
                        patch_field("super_tips/tips_key", tips_key_val, base_key)
                        
                        if dt_list != base_dt:
                            if target_data["patch"].get("super_tips/disabled_types") != dt_list:
                                self._safe_assign(target_data["patch"], "super_tips/disabled_types", seq if dt_list else CommentedSeq())
                                modified = True
                        elif "super_tips/disabled_types" in target_data["patch"]:
                            del target_data["patch"]["super_tips/disabled_types"]; modified = True

                    if modified:
                        if _smart_write(f_path, target_data, f_name, is_direct):
                            if target_file not in updated_files: updated_files.append(target_file)

            # 动作 同步反查快捷键
            if rev_key:
                for f_name in ["wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"]:
                    base_f_path = os.path.join(rime_dir, f_name)
                    if not os.path.exists(base_f_path): continue 

                    target_file = f_name if is_direct else f_name.replace(".schema.yaml", ".custom.yaml")
                    f_path = os.path.join(rime_dir, target_file)
                    
                    base_data = self._yaml_cache.get(f_name, ({}, {}))[0]
                    old_key = _get_nested_val(base_data, "wanxiang_lookup/key", "`")
                    
                    if not os.path.exists(f_path) and not is_direct: target_data = {"patch": {}}
                    elif os.path.exists(f_path):
                        with open(f_path, 'r', encoding='utf-8') as f: target_data = yaml.load(f) or {}
                    else: continue 
                    
                    modified = False
                    esc_key = '\\' + rev_key if rev_key in r".^$*+?{}[]\|()" else rev_key
                    new_pattern = f"^{esc_key}[A-Za-z]*$"
                    
                    if is_direct:
                        def set_direct(path, val):
                            nonlocal modified
                            keys = path.split('/')
                            curr = target_data
                            for k in keys[:-1]:
                                if k not in curr: curr[k] = {}
                                curr = curr[k]
                            if curr.get(keys[-1]) != val: self._safe_assign(curr, keys[-1], val); modified = True
                                
                        set_direct("wanxiang_reverse/prefix", rev_key)
                        set_direct("wanxiang_lookup/key", rev_key)
                        set_direct("recognizer/patterns/wanxiang_reverse", new_pattern)
                        
                        alpha = _get_nested_val(target_data, "speller/alphabet", "")
                        if alpha:
                            new_alpha = alpha
                            if old_key in new_alpha and old_key != rev_key: new_alpha = new_alpha.replace(old_key, "")
                            if rev_key not in new_alpha: new_alpha += rev_key
                            if new_alpha != alpha: set_direct("speller/alphabet", new_alpha)
                    else:
                        if "patch" not in target_data or target_data["patch"] is None: target_data["patch"] = {}
                        def patch_field(k, nv, bv):
                            nonlocal modified
                            if nv != bv:
                                if target_data["patch"].get(k) != nv: self._safe_assign(target_data["patch"], k, nv); modified = True
                            elif k in target_data["patch"]: del target_data["patch"][k]; modified = True
                                    
                        patch_field("wanxiang_reverse/prefix", rev_key, _get_nested_val(base_data, "wanxiang_reverse/prefix", "`"))
                        patch_field("wanxiang_lookup/key", rev_key, old_key)
                        patch_field("recognizer/patterns/wanxiang_reverse", new_pattern, _get_nested_val(base_data, "recognizer/patterns/wanxiang_reverse", "^`[A-Za-z]*$"))
                        
                        base_alpha = _get_nested_val(base_data, "speller/alphabet", "")
                        if base_alpha:
                            new_alpha = base_alpha
                            if old_key in new_alpha and old_key != rev_key: new_alpha = new_alpha.replace(old_key, "")
                            if rev_key not in new_alpha: new_alpha += rev_key
                            patch_field("speller/alphabet", new_alpha, base_alpha)

                    if modified:
                        if _smart_write(f_path, target_data, f_name, is_direct):
                            if target_file not in updated_files: updated_files.append(target_file)

            # 动作 处理翻页和次选/三选
            for f_name in ["default.yaml", "wanxiang.schema.yaml", "wanxiang_pro.schema.yaml"]:
                base_f_path = os.path.join(rime_dir, f_name)
                if not os.path.exists(base_f_path): continue 

                target_file = "default.yaml" if f_name == "default.yaml" and is_direct else f_name.replace(".schema.yaml", ".custom.yaml") if f_name != "default.yaml" and not is_direct else f_name if is_direct else "default.custom.yaml"
                f_path = os.path.join(rime_dir, target_file)
                if not os.path.exists(f_path) and not is_direct: target_data = {"patch": {}}
                elif os.path.exists(f_path):
                    with open(f_path, 'r', encoding='utf-8') as f: target_data = yaml.load(f) or {}
                else: continue
                
                modified = False
                base_data = self._yaml_cache.get(f_name, ({}, {}))[0]
                
                if is_direct:
                    key_binder = target_data.get("key_binder", {})
                    bindings = key_binder.get("bindings", []) if isinstance(key_binder, dict) else []
                    if not isinstance(bindings, list): bindings = []
                    new_bindings = []
                    
                    for b in bindings:
                        if not isinstance(b, dict): continue
                        acc = str(b.get("accept", "")).lower()
                        snd = str(b.get("send", "")).lower()
                        is_paging = acc in ["comma", "period", "bracketleft", "bracketright", "minus", "equal", ",", ".", "[", "]", "-", "="] and snd in ["page_up", "page_down", "prior", "next"]
                        is_cand = snd in ["2", "3"] and acc not in ["2", "kp_2", "3", "kp_3"]
                        if is_paging or is_cand: continue
                        new_bindings.append(b)
                    
                    if f_name != "default.yaml":
                        if paging_style == "逗号句号 ( , . )":
                            new_bindings.append(CommentedMap({"when": "paging", "accept": "comma", "send": "Page_Up"}))
                            new_bindings.append(CommentedMap({"when": "has_menu", "accept": "period", "send": "Page_Down"}))
                        elif paging_style == "中括号 ( [ ] )":
                            new_bindings.append(CommentedMap({"when": "paging", "accept": "bracketleft", "send": "Page_Up"}))
                            new_bindings.append(CommentedMap({"when": "has_menu", "accept": "bracketright", "send": "Page_Down"}))
                        elif paging_style == "减号等号 ( - = )":
                            new_bindings.append(CommentedMap({"when": "has_menu", "accept": "minus", "send": "Page_Up"}))
                            new_bindings.append(CommentedMap({"when": "has_menu", "accept": "equal", "send": "Page_Down"}))
                        
                        if rime_val2: new_bindings.append(CommentedMap({"when": "has_menu", "accept": rime_val2, "send": 2}))
                        if rime_val3: new_bindings.append(CommentedMap({"when": "has_menu", "accept": rime_val3, "send": 3}))
                    
                    if new_bindings != bindings:
                        if "key_binder" not in target_data: target_data["key_binder"] = {}
                        self._safe_assign(target_data["key_binder"], "bindings", new_bindings)
                        modified = True
                else:
                    patch_dict = target_data.get("patch", {}) or {}
                    if "key_binder/bindings" in patch_dict and isinstance(patch_dict["key_binder/bindings"], list):
                        old_b = patch_dict["key_binder/bindings"]
                        cleaned_b = []
                        for b in old_b:
                            if not isinstance(b, dict): continue
                            acc = str(b.get("accept", "")).lower()
                            snd = str(b.get("send", "")).lower()
                            is_paging = acc in ["comma", "period", "bracketleft", "bracketright", "minus", "equal", ",", ".", "[", "]", "-", "="] and snd in ["page_up", "page_down", "prior", "next"]
                            is_cand = snd in ["2", "3"] and acc not in ["2", "kp_2", "3", "kp_3"]
                            if is_paging or is_cand: continue
                            cleaned_b.append(b)
                        if cleaned_b != old_b:
                            if cleaned_b: self._safe_assign(patch_dict, "key_binder/bindings", cleaned_b)
                            else: del patch_dict["key_binder/bindings"]
                            modified = True
                    
                    append_key = "key_binder/bindings/+"
                    bindings = patch_dict.get(append_key, [])
                    if not isinstance(bindings, list): bindings = []
                    new_bindings = []
                    
                    for b in bindings:
                        if not isinstance(b, dict): continue
                        acc = str(b.get("accept", "")).lower()
                        snd = str(b.get("send", "")).lower()
                        is_paging = acc in ["comma", "period", "bracketleft", "bracketright", "minus", "equal", ",", ".", "[", "]", "-", "="] and snd in ["page_up", "page_down", "prior", "next"]
                        is_cand = snd in ["2", "3"] and acc not in ["2", "kp_2", "3", "kp_3"]
                        if is_paging or is_cand: continue
                        new_bindings.append(b)
                        
                    if f_name != "default.yaml":
                        base_bindings = _get_nested_val(base_data, "key_binder/bindings", [])
                        base_accs = set()
                        base_key2, base_key3 = "", ""
                        if isinstance(base_bindings, list):
                            for b in base_bindings:
                                if not isinstance(b, dict): continue
                                acc = str(b.get("accept", "")).lower()
                                snd = str(b.get("send", "")).lower()
                                if snd in ["page_up", "page_down", "prior", "next"]: base_accs.add(acc)
                                if snd == "2" and acc not in ["2", "kp_2", "3", "kp_3"]: base_key2 = acc
                                if snd == "3" and acc not in ["2", "kp_2", "3", "kp_3"]: base_key3 = acc
                        
                        base_paging = "默认 (PageUp/Dn)"
                        if "minus" in base_accs or "-" in base_accs: base_paging = "减号等号 ( - = )"
                        elif "bracketleft" in base_accs or "[" in base_accs: base_paging = "中括号 ( [ ] )"
                        elif "comma" in base_accs or "," in base_accs: base_paging = "逗号句号 ( , . )"
                        
                        if paging_style != base_paging:
                            if paging_style == "逗号句号 ( , . )":
                                new_bindings.append(CommentedMap({"when": "paging", "accept": "comma", "send": "Page_Up"}))
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": "period", "send": "Page_Down"}))
                            elif paging_style == "中括号 ( [ ] )":
                                new_bindings.append(CommentedMap({"when": "paging", "accept": "bracketleft", "send": "Page_Up"}))
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": "bracketright", "send": "Page_Down"}))
                            elif paging_style == "减号等号 ( - = )":
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": "minus", "send": "Page_Up"}))
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": "equal", "send": "Page_Down"}))
                        
                        if rime_val2 and rime_val2 != base_key2:
                            new_bindings.append(CommentedMap({"when": "has_menu", "accept": rime_val2, "send": 2}))
                        if rime_val3 and rime_val3 != base_key3:
                            new_bindings.append(CommentedMap({"when": "has_menu", "accept": rime_val3, "send": 3}))

                    if new_bindings != bindings:
                        if new_bindings: self._safe_assign(patch_dict, append_key, new_bindings)
                        elif append_key in patch_dict: del patch_dict[append_key]
                        modified = True
                    
                    if modified: target_data["patch"] = patch_dict

                if modified:
                    if _smart_write(f_path, target_data, f_name, is_direct):
                        if target_file not in updated_files: updated_files.append(target_file)
            
            if updated_files or deleted_files:
                msg_parts = []
                if updated_files: msg_parts.append(f"🌟 已同步配置至: {', '.join(list(set(updated_files)))}")
                if deleted_files: msg_parts.append(f"🧹 已自动清理无用补丁: {', '.join(list(set(deleted_files)))}")
                
                final_msg = "\n".join(msg_parts)
                self.log.appendPlainText(final_msg)
                for k in list(self._ui_cache.keys()):
                    if k != "VIRTUAL_GLOBAL" and k.endswith("_patch" if is_direct else "_direct"):
                        w = self._ui_cache[k]['tree']
                        self.cfg_stack.removeWidget(w)
                        w.deleteLater()
                        del self._ui_cache[k]
                reply = QMessageBox.information(self, "保存成功", 
                                                f"以【{'直写' if is_direct else '补丁'}模式】全局配置已同步。\n\n"
                                                f"是否立即触发 Rime 部署以生效？", 
                                                QMessageBox.Yes | QMessageBox.No)
                if reply == QMessageBox.Yes: self._start_and_deploy_from_main()
            else:
                self.log.appendPlainText("💡 未检测到任何改动，无文件被修改。")
                QMessageBox.information(self, "提示", "与方案原生配置相同，无需修改。\n(没有文件被更改)")
            
        except Exception as e:
            import traceback; self.log.appendPlainText(traceback.format_exc())
            QMessageBox.critical(self, "全局保存失败", str(e))
    def _start_and_deploy_from_main(self):
        self.log.appendPlainText("⚙️ 正在触发部署...")
        if SYSTEM_TYPE == 'windows':
            dep_path = getattr(self, 'detected_deployer', '')
            if dep_path and os.path.exists(dep_path):
                subprocess.Popen([dep_path, "/deploy"], creationflags=0x08000000)
                self.log.appendPlainText("✅ Windows 部署指令已发送。")
        elif SYSTEM_TYPE == 'macos':
            try:
                subprocess.run(['osascript', '-e', 'tell application "Squirrel" to reload configuration'], check=True)
                self.log.appendPlainText("✅ macOS 部署通知已发送。")
            except: pass

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
            if dark:
                from PySide6.QtWidgets import QApplication, QStyleFactory
                from PySide6.QtGui import QPalette, QColor
                from PySide6.QtCore import Qt
                
                QApplication.setStyle(QStyleFactory.create("Fusion"))
                pal = QPalette()
                pal.setColor(QPalette.Window, QColor(53, 53, 53))
                pal.setColor(QPalette.WindowText, Qt.white)
                pal.setColor(QPalette.Base, QColor(35, 35, 35))
                pal.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
                pal.setColor(QPalette.Text, Qt.white)
                pal.setColor(QPalette.Button, QColor(53, 53, 53))
                pal.setColor(QPalette.ButtonText, Qt.white)
                pal.setColor(QPalette.Highlight, QColor(42, 130, 218))
                pal.setColor(QPalette.HighlightedText, Qt.black)
                QApplication.setPalette(pal)
                
                self.tabs.setStyleSheet("""
                    QTabWidget::pane { border: 1px solid #444; top: -1px; border-radius: 4px; }
                    QTabBar::tab { background-color: #353535; color: #ccc; border: 1px solid #444; padding: 6px 16px; margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px; }
                    QTabBar::tab:selected { background-color: #2b542c; color: white; border: 1px solid #5cb85c; font-weight: bold; }
                    QTabBar::tab:hover:!selected { background-color: #444; }
                """)
                self.progress.setStyleSheet("""
                    QProgressBar { border: 1px solid #444; border-radius: 4px; text-align: center; background-color: #353535; color: #eee; font-weight: bold; }
                    QProgressBar::chunk { background-color: #49814D; border-radius: 3px; }
                """)
                self.gh_frame.setStyleSheet("#ghBox { background-color: #2b302b; border: 1px solid #445044; border-radius: 5px; }")
                
                # 暗黑模式 - 莫兰迪绿高级样式
                yaml_theme_css = """
                    QTreeWidget { font-size: 14px; border: 1px solid #444; border-radius: 8px; background-color: #2b2b2b; outline: none; color: #eee; }
                    QTreeWidget::item { min-height: 42px; border-bottom: 1px solid #444; }
                    QTreeWidget::item:selected, QTreeWidget::item:focus { background-color: transparent; color: #fff; border: none; border-bottom: 1px solid #444; }
                    QHeaderView::section { background-color: #353535; color: #eee; font-size: 14px; font-weight: bold; padding: 10px; border: none; border-bottom: 1px solid #444; }
                    
                    QLineEdit, QComboBox, QPlainTextEdit {
                        background-color: transparent; 
                        border: 1px solid #49814D;
                        border-radius: 4px;
                        padding: 4px 8px;
                        color: #eee;
                        selection-background-color: #61A165;
                        selection-color: black;
                    }
                    QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover {
                        border: 1px solid #61A165;
                    }
                    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
                        border: 1px solid #61A165;
                        background-color: rgba(97, 161, 101, 0.05);
                    }
                    QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
                        border: 1px solid #444; color: #888;
                    }
                    
                    QComboBox::drop-down { border: none; width: 24px; }
                    QComboBox QAbstractItemView { background-color: #353535; color: #eee; selection-background-color: #61A165; selection-color: black; border: 1px solid #49814D; }
                    
                    QGroupBox { 
                        border: 1px solid #49814D; 
                        border-radius: 5px; 
                        margin-top: 15px;
                        padding-top: 10px;
                        background-color: transparent;
                        font-weight: bold; 
                        color: #eee; 
                    }
                    QGroupBox::title { 
                        subcontrol-origin: margin; 
                        subcontrol-position: top left;
                        left: 10px; 
                        padding: 0 5px; 
                        color: #eee;
                    }
                    
                    #leftNavFrame { border: 1px solid #444; border-radius: 6px; background-color: #2b2b2b; }
                    #leftNavTree { background-color: transparent; font-size: 13px; outline: none; selection-background-color: transparent; color: #eee; }
                    #leftNavTree::branch { background-color: transparent; }
                    #leftNavTree::item { padding: 8px 6px; border-radius: 4px; margin: 2px 4px; }
                    #leftNavTree::item:hover { background-color: rgba(97, 161, 101, 0.3); }
                    #leftNavTree::item:selected { background-color: #49814D; color: white; font-weight: bold; }
                    
                    #loadingPage { background-color: rgba(43, 43, 43, 0.95); border-radius: 8px; border: 1px solid #444; }
                """
                self.setStyleSheet(yaml_theme_css)

            else:
                from PySide6.QtWidgets import QApplication, QStyleFactory
                QApplication.setStyle(QStyleFactory.create("Fusion"))
                QApplication.setPalette(QApplication.style().standardPalette())
                
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
                
                # 亮色模式 - 莫兰迪绿高级样式
                yaml_theme_css = """
                    QTreeWidget { font-size: 14px; border: 1px solid #E0E0E0; border-radius: 8px; background-color: white; outline: none; color: #333; }
                    QTreeWidget::item { min-height: 42px; border-bottom: 1px solid #F5F5F5; }
                    QTreeWidget::item:selected, QTreeWidget::item:focus { background-color: transparent; color: #333; border: none; border-bottom: 1px solid #F5F5F5; }
                    QHeaderView::section { background-color: #F0F5F1; color: #333; font-size: 14px; font-weight: bold; padding: 10px; border: none; border-bottom: 1px solid #C1D4C3; }
                    
                    QLineEdit, QComboBox, QPlainTextEdit {
                        background-color: transparent;
                        border: 1px solid #A8C7AA;
                        border-radius: 4px;
                        padding: 4px 8px;
                        color: #333;
                        selection-background-color: #61A165;
                        selection-color: white;
                    }
                    QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover {
                        border: 1px solid #61A165;
                    }
                    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
                        border: 1px solid #61A165;
                        background-color: rgba(97, 161, 101, 0.05);
                    }
                    QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled {
                        border: 1px solid #ddd; color: #aaa;
                    }
                    
                    QComboBox::drop-down { border: none; width: 24px; }
                    QComboBox QAbstractItemView { background-color: #FFFFFF; color: #333; selection-background-color: #E2ECE3; selection-color: #333; border: 1px solid #A8C7AA; }
                    
                    QGroupBox { 
                        border: 1px solid #61A165;
                        border-radius: 5px; 
                        margin-top: 15px; 
                        padding-top: 10px; 
                        background-color: transparent;
                        font-weight: bold; 
                        color: #333; 
                    }
                    QGroupBox::title { 
                        subcontrol-origin: margin; 
                        subcontrol-position: top left;
                        left: 10px; 
                        padding: 0 5px; 
                        color: #333;
                    }
                    
                    #leftNavFrame { border: 1px solid #61A165; border-radius: 6px; background-color: #F8FAF8; }
                    #leftNavTree { background-color: transparent; font-size: 13px; outline: none; selection-background-color: transparent; color: #333; }
                    #leftNavTree::branch { background-color: transparent; }
                    #leftNavTree::item { padding: 8px 6px; border-radius: 4px; margin: 2px 4px; }
                    #leftNavTree::item:hover { background-color: rgba(97, 161, 101, 0.1); }
                    #leftNavTree::item:selected { background-color: #61A165; color: white; font-weight: bold; }
                    
                    #loadingPage { background-color: rgba(240, 245, 241, 0.95); border-radius: 8px; border: 1px solid #C1D4C3; }
                """
                self.setStyleSheet(yaml_theme_css)

            self.settings.setValue('ui/dark', dark)
            
            # 【细节】：联动 Windows 标题栏变黑（沉浸式暗色模式）
            import sys
            if sys.platform == 'win32':
                try:
                    import ctypes
                    hwnd = int(self.winId())
                    rendering_mode = ctypes.c_int(1 if dark else 0)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(rendering_mode), ctypes.sizeof(rendering_mode))
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(rendering_mode), ctypes.sizeof(rendering_mode))
                except Exception:
                    pass

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
            s.setValue('upd/src_mode', self.bg_src.checkedId()) # 保存GitHub/自动模式
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
            src_mode = int(s.value('upd/src_mode', 1))
            if self.bg_src.button(src_mode):
                self.bg_src.button(src_mode).setChecked(True)
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
        self.bg_src.button(1).setChecked(True)
        self.upd_token.clear()
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
    else:
        if trans.load("qtbase_zh_CN", path):
            app.installTranslator(trans)
    w = MainWin()
    w.show()
    sys.exit(app.exec())
if __name__ == '__main__':
    main()