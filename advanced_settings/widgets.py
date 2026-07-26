from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .core import RimeYamlEngine, RimeYamlError, YamlDuplicateIssue, is_managed_source_yaml

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
        
        schemas = []
        
        # 只检查明确允许出现在方案列表中的文件，不使用目录通配扫描。
        ALLOWED_SCHEMAS = ["wanxiang", "wanxiang_pro", "wanxiang_english", "wanxiang_t9"]
        
        for s_id in ALLOWED_SCHEMAS:
            f_path = os.path.join(rime_dir, f"{s_id}.schema.yaml")
            if not os.path.isfile(f_path):
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


class YamlDuplicateFixDialog(QDialog):
    """精确显示同层级重复键；编辑完整文件并在保存前重新解析。"""

    def __init__(self, parent, issue: YamlDuplicateIssue):
        super().__init__(parent)
        self.issue = issue
        self.engine = RimeYamlEngine()
        self.setWindowTitle("🧩 YAML 同层级重复键修复")
        self.resize(900, 680)

        layout = QVBoxLayout(self)
        parent_path = issue.parent_path or "<根节点>"
        warning = QLabel(
            f"⚠️ 文件：<b>{Path(issue.file_path).name}</b><br>"
            f"同层级路径：<b>{parent_path}</b><br>"
            f"重复键：<b>{issue.key}</b>，位置：第 {issue.first_line + 1} 行与第 {issue.second_line + 1} 行。<br>"
            "不同父节点下的 __patch / __include 是合法的；这里只处理解析器确认的同层级重复。"
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#d9534f; font-size:13px; padding:8px;")
        layout.addWidget(warning)

        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = self.editor.font(); font.setFamily("Consolas"); font.setPointSize(11); self.editor.setFont(font)
        try:
            self.editor.setPlainText(Path(issue.file_path).read_text(encoding="utf-8"))
        except Exception as error:
            self.editor.setPlainText(f"无法读取文件：{error}")
        layout.addWidget(self.editor, 1)

        self.status = QLabel("请保留需要的定义，删除或改名同层级中多余的一项。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存、校验并重试")
        buttons.accepted.connect(self.save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        cursor = self.editor.textCursor()
        cursor.movePosition(cursor.Start)
        for _ in range(max(0, issue.second_line)):
            cursor.movePosition(cursor.Down)
        self.editor.setTextCursor(cursor)
        self.editor.centerCursor()

    def save_and_accept(self):
        path = Path(self.issue.file_path)
        text = self.editor.toPlainText()
        temp_path = path.with_name(f".{path.name}.validate.tmp")
        try:
            temp_path.write_text(text, encoding="utf-8")
            self.engine.validate_file(str(temp_path))
            original = path.read_bytes() if path.exists() else None
            try:
                os.replace(temp_path, path)
                self.engine.validate_file(str(path))
            except Exception:
                if original is None:
                    if path.exists(): path.unlink()
                else:
                    path.write_bytes(original)
                raise
            self.accept()
        except RimeYamlError as error:
            issue = error.issue
            if issue:
                self.status.setText(
                    f"❌ 仍有同层级重复键：{issue.parent_path or '<根节点>'}/{issue.key}，"
                    f"第 {issue.first_line + 1}、{issue.second_line + 1} 行。"
                )
            else:
                self.status.setText(f"❌ YAML 校验失败：{error}")
            self.status.setStyleSheet("color:#d9534f; font-weight:bold;")
        except Exception as error:
            self.status.setText(f"❌ 保存失败：{error}")
            self.status.setStyleSheet("color:#d9534f; font-weight:bold;")
        finally:
            try:
                if temp_path.exists(): temp_path.unlink()
            except Exception:
                pass


class YamlCacheWorker(QThread):
    finished_sig = Signal(str, object, dict, object)
    error_sig = Signal(str, object)
    all_finished_sig = Signal()

    def __init__(self, rime_dir, files):
        super().__init__()
        self.rime_dir = rime_dir
        self.files = files
        self._stop = False
        self.engine = RimeYamlEngine()

    def run(self):
        for file_name in self.files:
            if self._stop:
                break
            if not is_managed_source_yaml(file_name):
                self.error_sig.emit(
                    file_name,
                    RimeYamlError(f"高级设置拒绝加载未登记文件：{file_name}"),
                )
                continue
            schema_path = os.path.join(self.rime_dir, file_name)
            if file_name.endswith(".schema.yaml"):
                custom_name = file_name.replace(".schema.yaml", ".custom.yaml")
            elif file_name == "default.yaml":
                custom_name = "default.custom.yaml"
            else:
                custom_name = ""
            custom_path = os.path.join(self.rime_dir, custom_name) if custom_name else ""
            try:
                document = self.engine.load_pair(schema_path, custom_path)
                self.finished_sig.emit(file_name, document.schema, document.patch, document.effective)
            except Exception as error:
                self.error_sig.emit(file_name, error)
        if not self._stop:
            self.all_finished_sig.emit()

    def stop(self):
        self._stop = True
