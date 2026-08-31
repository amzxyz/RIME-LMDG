from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from collections.abc import Mapping, Sequence
from io import StringIO
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton, QSplitter, QStackedWidget, QTreeWidget,
    QTreeWidgetItemIterator, QVBoxLayout, QWidget,
)

try:
    from ruamel.yaml import YAML
    HAS_RUAMEL = True
except ImportError:
    YAML = None
    HAS_RUAMEL = False

from .core import (
    ConflictSeverity, KeyClaim, LiveKeyRegistry, RimeKeyConflictEngine, RimeYamlEngine,
    RimeYamlError, SaveTransaction, is_managed_config_yaml, is_managed_source_yaml,
    is_rime_dictionary,
)
from .metadata import FILE_INDEX_META, KNOWN_COMPONENTS_DESC, RIME_KEY_MAP, SCHEMA_META_CONFIG
from .deployment import deploy_rime_platform
from .widgets import (
    AlgebraPatchWidget, DynamicActionWidget, DynamicInputWidget, DynamicKeyValueWidget,
    DynamicMultiLineWidget, EnglishAlgebraWidget, MixedAlgebraWidget, ReverseAlgebraWidget,
    SchemaCheckboxesWidget, YamlCacheWorker, YamlDuplicateFixDialog,
)


# 这些控件编辑的是 Rime 编译指令本身，而不是编译后 runtime 节点。
# 它们的“当前值/脏值基线”必须来自 schema + custom 按 literal patch 合成后的
# source_effective；普通控件仍读取完整 ConfigCompiler 生成的 runtime effective。
_SOURCE_EFFECTIVE_WIDGET_TYPES = frozenset({
    "algebra_patch",
    "reverse_algebra",
    "english_algebra",
    "mixed_algebra",
})


def _get_nested_val(data, path, default=None):
    return RimeYamlEngine().get_path(data, path, default)


def _set_nested_val(data, path, value):
    RimeYamlEngine().set_path(data, path, value)


class AdvancedSettingsMixin:
    def _build_tab_schema_config(self) -> QWidget:
        self._ensure_advanced_engines()
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
        
        right_lay.addWidget(self.cfg_stack, 1)

        self.yaml_issue_panel = QFrame()
        self.yaml_issue_panel.setObjectName("yamlIssuePanel")
        self.yaml_issue_panel.setStyleSheet(
            "QFrame#yamlIssuePanel { border: 1px solid #D6A24A; border-radius: 6px; "
            "background: rgba(214, 162, 74, 0.08); }"
        )
        issue_lay = QVBoxLayout(self.yaml_issue_panel)
        issue_lay.setContentsMargins(10, 8, 10, 8)
        issue_lay.setSpacing(6)

        issue_head = QHBoxLayout()
        self.lbl_yaml_issue_title = QLabel("⚠️ YAML 加载问题与修改建议")
        self.lbl_yaml_issue_title.setStyleSheet("font-weight: bold; color: #A66F16;")
        issue_head.addWidget(self.lbl_yaml_issue_title)
        issue_head.addStretch()

        self.btn_clear_yaml_issues = QPushButton("清空提示")
        self.btn_clear_yaml_issues.setFixedHeight(26)
        self.btn_clear_yaml_issues.clicked.connect(self._clear_yaml_issue_log)
        issue_head.addWidget(self.btn_clear_yaml_issues)
        issue_lay.addLayout(issue_head)

        self.yaml_issue_log = QPlainTextEdit()
        self.yaml_issue_log.setReadOnly(True)
        self.yaml_issue_log.setMaximumHeight(150)
        self.yaml_issue_log.setPlaceholderText("YAML 解析问题会显示在这里；不会阻塞整个高级设置界面。")
        issue_lay.addWidget(self.yaml_issue_log)

        self.yaml_issue_panel.hide()
        right_lay.addWidget(self.yaml_issue_panel)

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

    def _dynamic_row_height(self, item, text):
        """公用小工具：动态撑开行高，防止文字换行时压扁输入框"""
        from PySide6.QtCore import QSize
        lines = text.count('\n') + 1
        h = max(46, 26 + lines * 20)
        item.setSizeHint(0, QSize(-1, h))
        item.setSizeHint(1, QSize(-1, h))
        item.setSizeHint(2, QSize(-1, h))

    def _legacy_get_active_bindings(self):
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

    def _legacy_render_global_business_page(self, tree_widget):
        """总控分发：按顺序调用独立的业务渲染器"""
        self._render_feature_page_size(tree_widget)  # 功能1：候选数
        self._render_feature_paging(tree_widget)     # 功能2：翻页键
        self._render_feature_cand_keys(tree_widget)  # 功能3：次选与三选
        self._render_feature_auto_freq(tree_widget)  # 功能3.5：自动调频
        self._render_feature_main_dict(tree_widget)  # 功能3.8：主词库防覆盖 (新增)
        self._render_feature_super_tips(tree_widget) # 功能4：超级提示
        self._render_feature_reverse_lookup(tree_widget) # 功能5：反查快捷键
        self._render_feature_grammar_model(tree_widget)  # 模型参数注入

    def _effective_document_data(self, file_name):
        """返回 schema + custom/patch 合成后的最终配置，不让各界面自行猜补丁结构。"""
        self._ensure_advanced_engines()
        effective = self._effective_cache.get(file_name)
        if effective is not None:
            return effective

        schema_data, custom_patch = self._yaml_cache.get(file_name, ({}, {}))
        effective = self._yaml_engine.apply_patch(schema_data, custom_patch)
        self._effective_cache[file_name] = effective
        return effective

    def _effective_config_value(self, file_name, path, default=None):
        effective = self._effective_document_data(file_name)
        return self._yaml_engine.get_path(effective, path, default)

    def _primary_wanxiang_schema_file(self):
        """从 default 的最终 schema_list 中确定当前主方案。"""
        schema_list = self._effective_config_value("default.yaml", "schema_list", [])
        if isinstance(schema_list, list):
            for item in schema_list:
                schema_id = item.get("schema") if isinstance(item, dict) else str(item or "")
                if schema_id in {"wanxiang", "wanxiang_pro"}:
                    return f"{schema_id}.schema.yaml"

        if "wanxiang_pro.schema.yaml" in self._yaml_cache:
            return "wanxiang_pro.schema.yaml"
        return "wanxiang.schema.yaml"

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
        
        # 统一读取 schema + custom/patch 合成后的最终值。
        current_val = self._effective_config_value("default.yaml", "menu/page_size", 6)
        
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
        
        
        active_file = self._primary_wanxiang_schema_file()
        current_val = self._effective_config_value(
            active_file, "translator/enable_user_dict", True
        )
        if isinstance(current_val, str):
            current_val = current_val.lower() == "true"
        else:
            current_val = bool(current_val)

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
        
        
        active_file = self._primary_wanxiang_schema_file()
        fallback_name = "wanxiang_pro" if active_file.startswith("wanxiang_pro") else "wanxiang"
        current_val = self._effective_config_value(
            active_file, "translator/dictionary", fallback_name
        )

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
        
        
        active_file = self._primary_wanxiang_schema_file()

        def get_current_val(path_str, default_val):
            return self._effective_config_value(active_file, path_str, default_val)

        db_name_val = get_current_val("super_tips/db_name", "lua/tips")
        tips_key_val = get_current_val("super_tips/tips_key", "comma")
        
        disabled_types = get_current_val("super_tips/disabled_types", [])
        if not isinstance(disabled_types, list): disabled_types = []
        clean_dt = [str(x) for x in disabled_types if x is not None and str(x) != ""]
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
                        self._check_conflict_base(
                            [t], [], l, itm,
                            ignore_paths={"super_tips/tips_key"},
                        )
                
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
        
        # 统一读取主方案 schema + custom/patch 合成后的最终值。
        active_file = self._primary_wanxiang_schema_file()
        current_val = self._effective_config_value(
            active_file, "wanxiang_lookup/key", "`"
        )
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
                self._check_conflict_base(
                    [t], [], lbl, item, check_alphabet=False,
                    ignore_paths={"wanxiang_lookup/key", "wanxiang_reverse/prefix"},
                )

        edit.textChanged.connect(validate)
        validate(edit.text())
        
        self._ui_cache.setdefault("VIRTUAL_GLOBAL", {}).setdefault("widgets", {})["reverse_lookup"] = edit
        tree._py_refs.extend([container, edit, lbl])

    def _legacy_check_conflict_base(self, target_symbols, ignore_sends, lbl, item, check_alphabet=True):
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
        possible_names = [f"{target_base}.yaml", f"{target_base}.schema.yaml"]
        
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
        self._clear_yaml_issue_log()
        
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
            
            # 后台线程启动：三层缓存必须同步失效，避免重扫后 directive baseline 仍取旧值。
            self._yaml_cache.clear()
            self._effective_cache.clear()
            self._source_effective_cache.clear()
            self.files_to_prebuild = list(set(all_files_to_cache))
            self.cache_worker = YamlCacheWorker(rime_dir, self.files_to_prebuild)
            self.cache_worker.finished_sig.connect(self._on_cache_loaded)
            self.cache_worker.error_sig.connect(self._on_yaml_cache_error)
            self.cache_worker.all_finished_sig.connect(self._on_all_yaml_parsed)
            self.cache_worker.start()

    def _legacy_on_cache_loaded(self, fname, s_data, c_patch):
        self._yaml_cache[fname] = (s_data, c_patch)

    def _legacy_on_all_yaml_parsed(self):
        """数据编译完成后立即开放界面；具体 YAML 页面首次点击时再构建并缓存。"""
        self.lbl_giant_load.setText("✅ 配置加载完成\n\n页面将在首次打开时按需构建")
        self.lbl_giant_load.setStyleSheet(
            "font-size: 22px; font-weight: bold; color: #61A165;"
        )

        # 综合设置是启动后的默认页，只构建这一页。
        if "VIRTUAL_GLOBAL" not in self._ui_cache:
            new_tree = self._create_cfg_tree()
            new_tree._py_refs = []
            self._ui_cache["VIRTUAL_GLOBAL"] = {
                "tree": new_tree,
                "widgets": {},
                "base": {},
                "lists": {},
            }
            self.cfg_stack.addWidget(new_tree)
            self._render_global_business_page(new_tree)

        # 不再启动时逐个创建所有 schema 的 Qt 控件。
        # on_nav_item_clicked() 已具备 cache miss -> 构建 -> 缓存能力，
        # 因此每个方案只在用户第一次真正打开时创建一次界面。
        self.ui_build_queue = []
        self.left_frame.setEnabled(True)

        if self.nav_tree.topLevelItemCount() > 0:
            global_cat = self.nav_tree.topLevelItem(0)
            if global_cat.childCount() > 0:
                global_item = global_cat.child(0)
                self.nav_tree.setCurrentItem(global_item)
                self.on_nav_item_clicked(global_item, 0)

    def on_nav_item_clicked(self, item, col):
        """物理翻页，双缓存秒切隔离"""
        target_id = item.data(0, Qt.UserRole)
        if not target_id: return 

        if target_id == "VIRTUAL_GLOBAL":
            self.lbl_current_target.setText("⚙️ 当前配置：全局综合设置 (跨文件联动)")
            cache = self._ui_cache.get("VIRTUAL_GLOBAL")
            if cache:
                self.cfg_stack.setCurrentWidget(cache['tree'])

                # 一键联动页的 widgets 是直接保存的 QLineEdit/QComboBox 等控件，
                # 普通 YAML 页的 _yaml_widgets 则固定为：
                #     path -> (widget, value_type)
                # 两者不能共用同一个容器，否则实时冲突扫描会尝试拆包 QLineEdit。
                # 一键联动保存与冲突检测均直接读取 VIRTUAL_GLOBAL 缓存，
                # 因此这里保持普通 YAML 页面容器的类型不变量。
                self._yaml_widgets = {}
                self._yaml_base_values = {}
                self._yaml_dynamic_lists = {}
            
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

    def _legacy_build_and_cache_yaml_ui(self, target_id, activate=False, force_direct_mode=None):
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

        if target_id not in self._yaml_cache:
            if not self._load_document_into_cache(target_id, show_dialog=activate):
                self.cfg_stack.removeWidget(new_tree)
                new_tree.deleteLater()
                return

        schema_data, c_patch_raw = self._yaml_cache[target_id]
        source_effective_data = self._source_effective_cache.get(target_id)
        if source_effective_data is None:
            source_effective_data = self._yaml_engine.apply_patch(schema_data, c_patch_raw)
            self._source_effective_cache[target_id] = copy.deepcopy(source_effective_data)

        # 普通界面展示使用完整 runtime effective；编辑 __patch/__include 等编译指令
        # 的私有控件使用 source_effective（schema + custom 已合成，但指令尚未展开）。
        # 直写模式仍展示 schema 原值；补丁模式按控件语义选择 source/runtime effective。
        # 路径与补丁合成都由 RimeYamlEngine 统一完成。
        if is_direct_mode:
            effective_data = schema_data
        else:
            effective_data = self._effective_cache.get(target_id)
            if effective_data is None:
                effective_data = self._yaml_engine.apply_patch(schema_data, c_patch_raw)
                self._effective_cache[target_id] = effective_data

        missing_value = object()

        def get_effective_val(path_str, schema_fallback=missing_value):
            value = self._yaml_engine.get_path(effective_data, path_str, missing_value)
            if value is missing_value:
                return schema_fallback if schema_fallback is not missing_value else None
            return value

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

        def add_dynamic_row(
            p_item,
            val_s,
            ins_idx=-1,
            *,
            original_key=None,
            original_value=None,
            has_original=False,
        ):
            child = QTreeWidgetItem()
            child.setFlags(child.flags() & ~Qt.ItemIsSelectable)
            if ins_idx == -1:
                p_item.addChild(child)
            else:
                p_item.insertChild(ins_idx, child)

            input_w = DynamicInputWidget(val_s, "填入配置")
            action_w = DynamicActionWidget(
                KNOWN_COMPONENTS_DESC.get(
                    val_s.split(":")[0].strip() if ":" in val_s else val_s,
                    "配置项",
                )
            )

            # dynamic_map 的单行“key: value”只是界面表示，不是可靠的序列化格式。
            # 保存原始键值和原始显示文本；用户未编辑这一行时直接复用原始 YAML 值，
            # 从而保留 Tab、前导/尾随空格、空字符串以及值的真实类型。
            child.setData(
                0,
                Qt.UserRole + 1,
                {
                    "has_original": bool(has_original),
                    "key": copy.deepcopy(original_key),
                    "value": copy.deepcopy(original_value),
                    "display_text": str(val_s),
                },
            )

            new_tree._py_refs.extend([input_w, action_w])

            input_w.value_changed.connect(
                lambda value: action_w.desc_label.setText(
                    KNOWN_COMPONENTS_DESC.get(
                        value.split(":")[0].strip() if ":" in value else value,
                        "自定义",
                    )
                )
            )

            def on_h():
                action_w.show_buttons()
                input_w.set_hover_state(True)

            def off_h():
                import shiboken6
                QTimer.singleShot(
                    50,
                    lambda: (
                        action_w.hide_buttons(),
                        input_w.set_hover_state(False)
                        if hasattr(input_w, "set_hover_state") else None,
                    )
                    if shiboken6.isValid(input_w)
                    and not input_w.underMouse()
                    and not action_w.underMouse()
                    else None,
                )

            input_w.hover_in.connect(on_h)
            input_w.hover_out.connect(off_h)
            action_w.hover_in.connect(on_h)
            action_w.hover_out.connect(off_h)

            action_w.add_requested.connect(
                lambda p=p_item, c=child: add_dynamic_row(
                    p, "", p.indexOfChild(c) + 1
                )
            )
            action_w.move_up_requested.connect(
                lambda p=p_item, c=child: swap_rows(
                    p, p.indexOfChild(c), p.indexOfChild(c) - 1
                )
            )
            action_w.move_down_requested.connect(
                lambda p=p_item, c=child: swap_rows(
                    p, p.indexOfChild(c), p.indexOfChild(c) + 1
                )
            )
            action_w.delete_requested.connect(
                lambda p=p_item, c=child: (
                    p.removeChild(c),
                    refresh_indices(p),
                )
            )

            new_tree.setItemWidget(child, 1, input_w)
            new_tree.setItemWidget(child, 2, action_w)
            refresh_indices(p_item)
            return child

        def add_dynamic_block(parent_item, block_data, template, insert_index=-1):
            # 每个规则块保存自己的原始数据，移动、插入后也不再按列表下标猜原块。
            original_block = sanitize_val(block_data) if isinstance(block_data, dict) else {}

            block_item = QTreeWidgetItem()
            block_item.setBackground(0, QColor("#F8FAF8"))
            if insert_index == -1:
                parent_item.addChild(block_item)
            else:
                parent_item.insertChild(insert_index, block_item)

            opt_v = original_block.get("name") or original_block.get("accept") or original_block.get("option")
            if not opt_v and isinstance(original_block.get("options"), list) and original_block["options"]:
                opt_v = f"开关组: {original_block['options'][0]}..."
            if opt_v is None or opt_v == "":
                opt_v = "新规则块"
            block_item.setText(0, f"📦 规则块: {opt_v}")

            action_w = DynamicActionWidget("展开配置项")
            new_tree._py_refs.append(action_w)

            action_w.hover_in.connect(action_w.show_buttons)
            action_w.hover_out.connect(action_w.hide_buttons)
            action_w.add_requested.connect(
                lambda p=parent_item, b=block_item, temp=template:
                add_dynamic_block(p, {}, temp, p.indexOfChild(b) + 1)
            )
            action_w.move_up_requested.connect(
                lambda p=parent_item, b=block_item:
                swap_blocks(p, p.indexOfChild(b), p.indexOfChild(b) - 1)
            )
            action_w.move_down_requested.connect(
                lambda p=parent_item, b=block_item:
                swap_blocks(p, p.indexOfChild(b), p.indexOfChild(b) + 1)
            )
            action_w.delete_requested.connect(
                lambda p=parent_item, b=block_item: p.removeChild(b)
            )
            new_tree.setItemWidget(block_item, 2, action_w)

            child_widgets = {}
            sub_item_refs = {}

            for key, info in template.items():
                field_present = key in original_block
                val = original_block.get(key)

                sub_item = QTreeWidgetItem(
                    block_item,
                    [info["title"], "", info.get("desc", "")],
                )
                sub_item.setFlags(sub_item.flags() & ~Qt.ItemIsSelectable)
                sub_item_refs[key] = sub_item

                v_type = info["type"]
                w = None

                if v_type == "bool":
                    w = QCheckBox("开启")
                    if not field_present:
                        w.setTristate(True)
                        w.setCheckState(Qt.PartiallyChecked)
                        w.setText("未设置（继承）")
                    else:
                        bool_val = str(val).lower() == "true" if isinstance(val, str) else bool(val)
                        w.setChecked(bool_val)

                elif v_type == "select":
                    w = QComboBox()
                    w.addItems(info.get("options", []))
                    w.setStyleSheet(style_m)
                    w.setFixedHeight(36)
                    if field_present:
                        w.setCurrentText(
                            "true" if val is True
                            else "false" if val is False
                            else str(val if val is not None else "")
                        )
                    else:
                        w.setCurrentIndex(-1)

                elif v_type in ["list_text", "raw_yaml"]:
                    clean_v = sanitize_val(val)
                    if v_type == "raw_yaml":
                        if isinstance(clean_v, (dict, list)):
                            _y = YAML()
                            _y.default_flow_style = False
                            buf = StringIO()
                            _y.dump(clean_v, buf)
                            txt_v = buf.getvalue().strip()
                        else:
                            txt_v = str(clean_v if clean_v is not None else "")
                    else:
                        if isinstance(clean_v, list):
                            if all(len(str(x)) <= 10 and "\n" not in str(x) for x in clean_v):
                                txt_v = "[" + ", ".join(str(x) for x in clean_v) + "]"
                            else:
                                txt_v = "\n".join(str(x) for x in clean_v)
                        else:
                            txt_v = str(clean_v if clean_v is not None else "")

                    w = DynamicMultiLineWidget(
                        txt_v,
                        "支持输入任意多行文本或规则...",
                    )
                    w.needs_resize.connect(
                        lambda h, itm=sub_item: safe_apply_size(itm, h)
                    )

                elif v_type == "action_kv":
                    pk = info.get("preset_keys", {})
                    a_k, a_v = "", ""
                    for pk_key in pk:
                        if pk_key in original_block:
                            a_k = pk_key
                            a_v = original_block[pk_key]
                            break
                    w = DynamicKeyValueWidget(a_k, a_v, pk)
                    w.needs_resize.connect(
                        lambda h, itm=sub_item: safe_apply_size(itm, h)
                    )

                else:
                    if isinstance(val, list):
                        display_text = "[" + ", ".join(str(x) for x in val) + "]"
                    else:
                        display_text = str(val if val is not None else "")
                    w = QLineEdit(display_text)
                    w.setStyleSheet(style_m)
                    w.setFixedHeight(36)

                    if key in ["option", "accept", "name"]:
                        w.textChanged.connect(
                            lambda value, item=block_item:
                            item.setText(0, f"📦 规则块: {value or '新规则块'}")
                            if shiboken6.isValid(item) else None
                        )

                if w is not None:
                    new_tree.setItemWidget(sub_item, 1, w)
                    child_widgets[key] = (w, v_type, sub_item)

            for key, info in template.items():
                if "visible_if" not in info:
                    continue

                def build_updater(target_item, conditions):
                    def _update():
                        visible = True
                        for c_key, allowed_values in conditions.items():
                            widget_info = child_widgets.get(c_key, (None, None, None))
                            c_widget, c_type = widget_info[0], widget_info[1]
                            if (
                                c_widget
                                and c_type == "select"
                                and c_widget.currentText() not in allowed_values
                            ):
                                visible = False
                        target_item.setHidden(not visible)
                    return _update

                updater = build_updater(
                    sub_item_refs[key],
                    info["visible_if"],
                )
                for c_key in info["visible_if"].keys():
                    widget_info = child_widgets.get(c_key, (None, None, None))
                    c_widget, c_type = widget_info[0], widget_info[1]
                    if c_type == "select":
                        c_widget.currentIndexChanged.connect(
                            lambda _, update=updater: update()
                        )
                updater()

            block_item.setData(0, Qt.UserRole, child_widgets)
            block_item.setData(0, Qt.UserRole + 1, copy.deepcopy(original_block))
            block_item.setData(0, Qt.UserRole + 2, not bool(original_block))

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
                if not curr_v:
                    add_dynamic_row(p_item, "")
                elif v_type == "dynamic_map" and isinstance(curr_v, dict):
                    for map_key, map_value in curr_v.items():
                        add_dynamic_row(
                            p_item,
                            f"{map_key}: {map_value}",
                            original_key=map_key,
                            original_value=map_value,
                            has_original=True,
                        )
                else:
                    items = curr_v if isinstance(curr_v, list) else [curr_v]
                    for item_value in items:
                        add_dynamic_row(p_item, str(item_value))

                if v_type == "dynamic_map":
                    file_dynamic_lists[f_path] = (p_item, "map_list")
                else:
                    file_dynamic_lists[f_path] = (p_item, "str_list")
                return None

            if v_type == "schema_checkboxes":
                real_w = SchemaCheckboxesWidget(rime_dir, curr_v)
                real_w.needs_resize.connect(lambda h, itm=p_item: safe_apply_size(itm, h))
                file_widgets[f_path] = (real_w, v_type); return real_w
            if v_type == "algebra_patch":
                scheme_variant = (
                    "pro" if target_id == "wanxiang_pro.schema.yaml"
                    else "lite" if target_id == "wanxiang_lite.schema.yaml"
                    else "base"
                )
                real_w = AlgebraPatchWidget(
                    curr_v,
                    is_direct=is_direct_mode,
                    scheme_variant=scheme_variant,
                )
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
            if v_type in ["str", "int", "float", "number"]:
                if isinstance(curr_v, list): display_text = "[" + ", ".join(str(x) for x in curr_v) + "]"
                else: display_text = str(curr_v if curr_v is not None else "")
                real_w = QLineEdit(display_text); real_w.setStyleSheet(style_m); real_w.setFixedHeight(36)
            elif v_type == "bool":
                real_w = QCheckBox("启用")
                base_state = file_base_values.get(f_path, {})
                if not base_state.get("display_present", curr_v is not None):
                    real_w.setTristate(True)
                    real_w.setCheckState(Qt.PartiallyChecked)
                    real_w.setText("未设置（继承）")
                else:
                    bool_val = str(curr_v).lower() == "true" if isinstance(curr_v, str) else bool(curr_v)
                    real_w.setChecked(bool_val)
            elif v_type == "select":
                real_w = QComboBox(); real_w.addItems(n_info.get("options", [])); real_w.setStyleSheet(style_m); real_w.setFixedHeight(36)
                val_str = "true" if curr_v is True else "false" if curr_v is False else str(curr_v) if curr_v is not None else ""
                real_w.setCurrentText(val_str)
            elif v_type in ["list_text", "raw_yaml", "multiline_str"]:
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
                elif v_type == "multiline_str":
                    txt_v = str(clean_v if clean_v is not None else "")
                else:
                    if isinstance(clean_v, list):
                        if all(len(str(x)) <= 10 and '\n' not in str(x) for x in clean_v):
                            txt_v = "[" + ", ".join(str(x) for x in clean_v) + "]"
                        else:
                            txt_v = "\n".join(str(x) for x in clean_v)
                    else:
                        txt_v = str(clean_v if clean_v is not None else "")
                placeholder = "输入多行文本，保存时保持字符串类型" if v_type == "multiline_str" else "支持输入任意多行文本或规则..."
                real_w = DynamicMultiLineWidget(txt_v, placeholder)
                real_w.needs_resize.connect(lambda h, itm=p_item: safe_apply_size(itm, h))
            else:
                if isinstance(curr_v, list): display_text = "[" + ", ".join(str(x) for x in curr_v) + "]"
                else: display_text = str(curr_v if curr_v is not None else "")
                real_w = QLineEdit(display_text); real_w.setStyleSheet(style_m); real_w.setFixedHeight(36)
            
            if real_w: 
                file_widgets[f_path] = (real_w, v_type)
                has_jump = n_info.get("jumpable")
                has_action = n_info.get("action_btn")
                if (has_jump or has_action) and v_type in ["str", "list_text", "raw_yaml", "multiline_str"]:
                    wrapper = QWidget(); wrap_lay = QHBoxLayout(wrapper); wrap_lay.setContentsMargins(0, 0, 0, 0)
                    wrap_lay.addWidget(real_w, stretch=1)
                    btn = QPushButton(n_info.get("action_btn") or "🔗 穿透"); btn.setCursor(Qt.PointingHandCursor)
                    btn.setStyleSheet("QPushButton { background-color: transparent; border: 1px solid #61A165; color: #61A165; border-radius: 4px; padding: 4px 12px; font-weight: bold; } QPushButton:hover { background-color: #61A165; color: white; }")
                    
                    new_tree._py_refs.append(btn)
                    
                    if has_jump:
                        if v_type == "str": btn.clicked.connect(lambda: self.jump_to_reference(real_w.text()))
                        else: btn.clicked.connect(lambda: self.jump_to_reference(real_w.text_field.toPlainText()))
                    elif has_action: btn.clicked.connect(lambda: self.do_import_switches(real_w.text_field))
                    wrap_lay.addWidget(btn, alignment=Qt.AlignTop if v_type in ["list_text", "raw_yaml", "multiline_str"] else Qt.AlignVCenter)
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
                        
                        schema_marker = self._yaml_engine.get_path(schema_data, path, missing_value)
                        effective_marker = self._yaml_engine.get_path(effective_data, path, missing_value)
                        schema_present = schema_marker is not missing_value
                        display_present = effective_marker is not missing_value
                        val_from_schema = rules_val if not schema_present else schema_marker
                        display_val = val_from_schema if not display_present else effective_marker

                        file_base_values[path] = {
                            "schema": val_from_schema,
                            "display": display_val,
                            "schema_present": schema_present,
                            "display_present": display_present,
                        }
                        widget = create_widget(path, "raw_yaml", {}, display_val, item)
                        if widget: new_tree.setItemWidget(item, 1, widget)
            else:
                for meta_k, r_info in SCHEMA_META_CONFIG.items():
                    QApplication.processEvents()
                    match_file = r_info.get("_match_file")
                    match_files = r_info.get("_match_files") or ()
                    has_match = bool(match_file or match_files)
                    if match_file and match_file != target_id: continue
                    if match_files and target_id not in match_files: continue
                    
                    rk = r_info.get("_root_key", meta_k)
                    in_base = rk in schema_data
                    in_effective = isinstance(effective_data, dict) and rk in effective_data
                    if not has_match and not (in_base or in_effective): continue
                    
                    root = QTreeWidgetItem(new_tree, [r_info.get("_title", meta_k), "", ""])
                    root.setFont(0, QFont("", 11, QFont.Bold)); root.setForeground(0, QColor("#61A165"))
                    rd = schema_data.get(rk, {}) if in_base else {}
                    
                    for nk, ni in r_info["nodes"].items():
                        item = QTreeWidgetItem(root, [ni["title"], "", ni.get("desc", "")])
                        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                        path = rk if nk == "__self__" else f"{rk}/{nk}"
                        schema_marker = self._yaml_engine.get_path(schema_data, path, missing_value)
                        edits_compiler_directive = (
                            ni.get("baseline") == "source_effective"
                            or path.endswith("/__patch")
                            or path.endswith("/__include")
                            or ni["type"] in _SOURCE_EFFECTIVE_WIDGET_TYPES
                        )
                        baseline_kind = (
                            "source_effective"
                            if (not is_direct_mode and edits_compiler_directive)
                            else "runtime_effective"
                        )
                        display_tree = (
                            source_effective_data
                            if baseline_kind == "source_effective"
                            else effective_data
                        )
                        effective_marker = self._yaml_engine.get_path(display_tree, path, missing_value)
                        schema_present = schema_marker is not missing_value
                        display_present = effective_marker is not missing_value
                        val_from_schema = None if not schema_present else schema_marker
                        display_val = val_from_schema if not display_present else effective_marker

                        file_base_values[path] = {
                            "schema": val_from_schema,
                            "display": display_val,
                            "schema_present": schema_present,
                            "display_present": display_present,
                            "baseline_kind": baseline_kind,
                        }
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

    def _legacy_save_yaml_config(self):
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
        ABSENT = object()

        def is_really_changed(cur, base):
            """比较真实 YAML 值，不把“键不存在”、false、[]、{} 混为一谈。"""
            def canonical(value):
                if isinstance(value, Mapping):
                    return {
                        str(key): canonical(child)
                        for key, child in value.items()
                    }
                if isinstance(value, Sequence) and not isinstance(
                    value, (str, bytes, bytearray)
                ):
                    return [canonical(child) for child in value]
                if value is None:
                    return None
                if isinstance(value, bool):
                    return bool(value)
                if isinstance(value, int) and not isinstance(value, bool):
                    return int(value)
                if isinstance(value, float):
                    return float(value)
                return str(value)

            return canonical(cur) != canonical(base)

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

        def parse_list_text(
            txt,
            orig_val=ABSENT,
            base_val=ABSENT,
            key_name="",
        ):
            raw = txt.strip()
            original_is_list = isinstance(orig_val, list)
            base_is_list = isinstance(base_val, list)
            force_array = (
                original_is_list
                or base_is_list
                or "format" in key_name
                or "rules" in key_name
            )

            if not raw:
                if orig_val is ABSENT and base_val is ABSENT:
                    return ABSENT
                if original_is_list or base_is_list:
                    return []
                return None

            if raw.startswith("[") and raw.endswith("]"):
                try:
                    result = _safe_yaml.load(raw)
                    return result if isinstance(result, list) else [result]
                except Exception:
                    return [raw]

            if "\n" in raw:
                return [
                    line.strip()
                    for line in raw.splitlines()
                    if line.strip()
                ]

            if "," in raw:
                return [
                    item.strip()
                    for item in raw.split(",")
                    if item.strip()
                ]

            if force_array:
                return [raw]

            try:
                return _safe_yaml.load(raw)
            except Exception:
                return raw

        allowed_paths = set()
        if target_id == "wanxiang_algebra.yaml":
            for path in self._yaml_widgets.keys(): allowed_paths.add(path)
            for path in getattr(self, '_yaml_dynamic_lists', {}).keys(): allowed_paths.add(path)
        else:
            for meta_k, r_info in SCHEMA_META_CONFIG.items():
                match_f = r_info.get("_match_file")
                match_files = r_info.get("_match_files") or ()
                if match_f and match_f != target_id: continue
                if match_files and target_id not in match_files: continue
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
            elif v_type == "bool":
                if widget.isTristate() and widget.checkState() == Qt.PartiallyChecked:
                    current_val = ABSENT
                else:
                    current_val = widget.isChecked()
            elif v_type == "int":
                try:
                    current_val = int(widget.text().strip())
                except Exception:
                    current_val = widget.text().strip()
            elif v_type == "float":
                try:
                    current_val = float(widget.text().strip())
                except Exception:
                    current_val = widget.text().strip()
            elif v_type == "number":
                number_text = widget.text().strip()
                try:
                    if re.fullmatch(r"[+-]?\d+", number_text):
                        current_val = int(number_text)
                    else:
                        current_val = float(number_text)
                except Exception:
                    current_val = number_text
            elif v_type == "multiline_str":
                current_val = widget.text_field.toPlainText()
            elif v_type == "str":
                # 字符串可能有语义性的前导/尾随空白，例如：
                # speller/delimiter = " '"。不能使用 strip()。
                current_val = widget.text()
            elif v_type == "select":
                val_str = widget.currentText()
                if val_str not in ["默认/不指定", ""]:
                    try: current_val = int(val_str)
                    except: current_val = val_str
            elif v_type == "list_text":
                current_val = parse_list_text(
                    widget.text_field.toPlainText(),
                    orig_val=display_val if base_info.get("display_present", display_val is not None) else ABSENT,
                    base_val=schema_val if base_info.get("schema_present", schema_val is not None) else ABSENT,
                    key_name=full_path.split("/")[-1],
                )
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

            if current_val is ABSENT:
                continue

            current_val = smart_seq(current_val)
            display_present = base_info.get(
                "display_present",
                display_val is not None,
            )

            if not display_present and is_empty(current_val):
                continue

            # 未修改就不整理 custom，不补全可选空字段。
            if not is_really_changed(current_val, display_val):
                continue

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
                        if is_special:
                            # 编译指令控件：dirty 与“打开页面时的 source_effective”比较；
                            # 写入决策再与 raw schema 比较。恢复 schema 默认时删除 custom，
                            # 否则即使目标是空列表也必须显式写入，不能删除后让 schema 复活。
                            if not is_really_changed(current_val, schema_val):
                                patches_to_remove.append(full_path)
                                patches_to_remove.append(full_path + "/+")
                            else:
                                patches_to_apply[full_path] = current_val
                                patches_to_remove.append(full_path + "/+")
                        elif is_empty(current_val) or not is_really_changed(current_val, schema_val):
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
                else:
                    if is_really_changed(current_val, display_val):
                        is_special = full_path.endswith("/__patch") or full_path.endswith("/__include")
                        if is_special:
                            if not is_really_changed(current_val, schema_val):
                                patches_to_remove.append(full_path)
                            else:
                                patches_to_apply[full_path] = current_val
                        elif is_empty(current_val) or not is_really_changed(current_val, schema_val):
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
                    if not child_widgets:
                        continue

                    stored_original = child.data(0, Qt.UserRole + 1)
                    if isinstance(stored_original, dict):
                        original_dict = copy.deepcopy(stored_original)
                    elif (
                        isinstance(display_val, list)
                        and i < len(display_val)
                        and isinstance(display_val[i], dict)
                    ):
                        original_dict = copy.deepcopy(display_val[i])
                    else:
                        original_dict = {}

                    from ruamel.yaml.comments import CommentedMap
                    block_dict = CommentedMap(copy.deepcopy(original_dict))

                    for key, widget_info in child_widgets.items():
                        if len(widget_info) == 3:
                            w, v_type, sub_item = widget_info
                            if sub_item.isHidden():
                                continue
                        else:
                            w, v_type = widget_info

                        if not shiboken6.isValid(w):
                            continue

                        field_present = key in original_dict
                        original_value = (
                            original_dict[key]
                            if field_present else ABSENT
                        )
                        val = ABSENT

                        if v_type == "action_kv":
                            preset_keys = getattr(w, "preset_keys", {})
                            for preset_key in preset_keys:
                                block_dict.pop(preset_key, None)

                            action_key, action_value = w.get_key_value()
                            if action_key and action_value not in (None, ""):
                                # when/match/send/toggle/send_sequence/select 都是 Rime 字符串。
                                # 特别是 {space}、{Home}{Shift+Right} 不能交给 YAML.load，
                                # 否则 {space} 会被误解析成 {space: null}。
                                block_dict[action_key] = str(action_value)
                            continue

                        if v_type == "bool":
                            if (
                                w.isTristate()
                                and w.checkState() == Qt.PartiallyChecked
                            ):
                                if not field_present:
                                    block_dict.pop(key, None)
                                continue
                            val = w.isChecked()

                        elif v_type == "select":
                            selected = w.currentText().strip()
                            if not selected or selected == "默认/不指定":
                                val = ABSENT
                            elif isinstance(original_value, bool):
                                val = selected.lower() == "true"
                            else:
                                val = selected

                        elif v_type == "list_text":
                            raw_text = w.text_field.toPlainText()
                            if not raw_text.strip() and not field_present:
                                block_dict.pop(key, None)
                                continue

                            val = parse_list_text(
                                raw_text,
                                orig_val=original_value,
                                base_val=original_value,
                                key_name=key,
                            )

                        elif v_type == "raw_yaml":
                            raw_text = w.text_field.toPlainText().strip()
                            if not raw_text:
                                val = ABSENT
                            else:
                                try:
                                    val = _safe_yaml.load(raw_text)
                                except Exception:
                                    val = raw_text

                        else:
                            raw_text = w.text().strip()
                            if not raw_text:
                                val = ABSENT
                            else:
                                try:
                                    val = _safe_yaml.load(raw_text)
                                except Exception:
                                    val = raw_text

                        if val is ABSENT:
                            if field_present:
                                block_dict.pop(key, None)
                            else:
                                block_dict.pop(key, None)
                            continue

                        block_dict[key] = smart_seq(val)

                    meaningful = False
                    for value in block_dict.values():
                        if value is None or value == "":
                            continue
                        if isinstance(value, (list, dict)) and not value:
                            continue
                        meaningful = True
                        break

                    if block_dict and (original_dict or meaningful):
                        current_val.append(block_dict)

                current_val = smart_seq(current_val)

            elif list_type == "map_list":
                current_val = {}

                for i in range(parent_item.childCount()):
                    child = parent_item.child(i)
                    w = current_tree.itemWidget(child, 1)
                    if not isinstance(w, DynamicInputWidget):
                        continue

                    raw_line = w.input_field.text()
                    original = child.data(0, Qt.UserRole + 1)

                    # 未编辑的既有行直接复用原始 YAML 键值，禁止经过 strip()/str()/YAML.load。
                    if (
                        isinstance(original, dict)
                        and original.get("has_original")
                        and raw_line == original.get("display_text", "")
                    ):
                        current_val[copy.deepcopy(original.get("key"))] = copy.deepcopy(
                            original.get("value")
                        )
                        continue

                    if not raw_line or ":" not in raw_line:
                        continue

                    key_text, value_text = raw_line.split(":", 1)
                    map_key = key_text.strip()
                    if not map_key:
                        continue

                    # 界面生成格式固定为“key: value”，只移除冒号后由界面插入的一个空格；
                    # 不删除值本身的 Tab、尾随空格或其余前导空格。
                    if value_text.startswith(" "):
                        value_text = value_text[1:]

                    if value_text == "":
                        map_value = ""
                    else:
                        try:
                            parsed = _safe_yaml.load(value_text)
                            map_value = value_text if parsed is None else parsed
                        except Exception:
                            map_value = value_text

                    current_val[map_key] = map_value

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

            display_present = base_info.get(
                "display_present",
                display_val is not None,
            )

            if current_val is ABSENT:
                continue

            if not display_present and is_empty(current_val):
                continue

            # 动态块未改变时，绝不补全模板里的空字段，也不整理 custom。
            if not is_really_changed(current_val, display_val):
                continue

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

                self._yaml_engine.atomic_write_many({schema_path: target_data})
                self._advanced_save_detail = (
                    f"[直写] {target_id}：请求更新 {len(patches_to_apply)} 项"
                )
                
                    
            else:
                custom_data = {}
                if os.path.exists(custom_path):
                    with open(custom_path, 'r', encoding='utf-8') as f: custom_data = yaml.load(f) or {}

                if not patches_to_apply and not patches_to_remove:
                    self._advanced_save_detail = "界面值与当前配置一致，未生成写入内容。"
                    return

                if 'patch' not in custom_data or custom_data['patch'] is None: custom_data['patch'] = {}
                
                from ruamel.yaml.comments import CommentedMap, CommentedSeq

                def fresh_yaml_value(value, force_block_sequence=False):
                    if isinstance(value, Mapping):
                        result = CommentedMap()
                        result.fa.set_block_style()
                        for child_key, child_value in value.items():
                            result[child_key] = fresh_yaml_value(child_value)
                        return result

                    if isinstance(value, Sequence) and not isinstance(
                        value, (str, bytes, bytearray)
                    ):
                        result = CommentedSeq(
                            fresh_yaml_value(child_value)
                            for child_value in value
                        )
                        if force_block_sequence:
                            result.fa.set_block_style()
                        return result

                    return value

                def set_patch_val(p_dict, path, val):
                    if path.endswith("/__patch") or path.endswith("/__include"):
                        base_path, op = path.rsplit("/", 1)

                        if hasattr(p_dict, "fa"):
                            p_dict.fa.set_block_style()

                        old_node = p_dict.get(base_path)
                        new_node = CommentedMap()
                        new_node.fa.set_block_style()

                        if isinstance(old_node, Mapping):
                            for child_key, child_value in old_node.items():
                                if child_key != op:
                                    new_node[child_key] = child_value

                        force_block = (
                            isinstance(val, Sequence)
                            and not isinstance(val, (str, bytes, bytearray))
                        )
                        new_node[op] = fresh_yaml_value(
                            val,
                            force_block_sequence=force_block,
                        )

                        if "__include" in new_node and "__patch" in new_node:
                            ordered_node = CommentedMap()
                            ordered_node.fa.set_block_style()
                            ordered_node["__include"] = new_node["__include"]
                            ordered_node["__patch"] = new_node["__patch"]
                            for child_key, child_value in new_node.items():
                                if child_key not in ordered_node:
                                    ordered_node[child_key] = child_value
                            new_node = ordered_node

                        p_dict[base_path] = new_node
                        if path in p_dict:
                            del p_dict[path]
                        return

                    parts = path.split("/")
                    if path.endswith("/+"):
                        parts = parts[:-2] + [parts[-2] + "/+"]

                    for i in range(1, len(parts)):
                        parent_path = "/".join(path.split("/")[:i])
                        if parent_path in p_dict and isinstance(p_dict[parent_path], dict):
                            node = p_dict[parent_path]
                            sub_parts = parts[i:]
                            for part in sub_parts[:-1]:
                                if part not in node or not isinstance(node[part], dict):
                                    node[part] = {}
                                node = node[part]
                            self._safe_assign(node, sub_parts[-1], val)
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
                for p, v in patches_to_apply.items():
                    set_patch_val(custom_data['patch'], p, v)
                for p in patches_to_remove:
                    del_patch_val(custom_data['patch'], p)

                # custom 文件即使当前没有任何覆盖项，也保留明确的空 patch 映射。
                # 不删除 patch 键，否则整个文件会被序列化成 `{}`；
                # 也不使用 `patch:`（null），因为 Rime patch 语义要求这里是 map。
                if 'patch' not in custom_data or custom_data['patch'] is None:
                    custom_data['patch'] = CommentedMap()

                if hasattr(custom_data, "fa"):
                    custom_data.fa.set_block_style()
                if hasattr(custom_data['patch'], "fa"):
                    custom_data['patch'].fa.set_block_style()

                self._yaml_engine.atomic_write_many({custom_path: custom_data})
                self._advanced_save_detail = (
                    f"[补丁] {self.current_custom_file}：请求更新 {len(patches_to_apply)} 项，"
                    f"清理 {len(patches_to_remove)} 项"
                )


            # 仅删除另一个对立模式的过期缓存，当前界面保留不闪烁
            other_mode_key = f"{self.current_edit_file}_{'patch' if is_direct_mode else 'direct'}"
            if other_mode_key in self._ui_cache:
                w = self._ui_cache[other_mode_key]['tree']
                self.cfg_stack.removeWidget(w)
                w.deleteLater()
                del self._ui_cache[other_mode_key]
            self._advanced_save_changed = True
            self._advanced_save_summary = "配置已精准写入对应文件。"

        except Exception as e:
            self._advanced_save_failed = True
            import traceback; self.log.appendPlainText(traceback.format_exc())
            QMessageBox.critical(self, "失败", f"写入错误: {e}")

    def _legacy_save_virtual_global(self):
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

        global_cache = self._ui_cache.get("VIRTUAL_GLOBAL", {})
        current_state = self._capture_global_widget_state(widgets)
        baseline_state = global_cache.get("baseline")
        if not isinstance(baseline_state, dict):
            baseline_state = copy.deepcopy(current_state)
            baseline_state["grammar_action"] = 0
            global_cache["baseline"] = copy.deepcopy(baseline_state)

        dirty = {
            key: current_state.get(key) != baseline_state.get(key)
            for key in (
                "page_size", "paging", "cand2", "cand3", "auto_freq",
                "main_dict", "reverse_lookup", "super_tips_db",
                "super_tips_key", "super_tips_disabled",
            )
        }
        dirty["grammar_action"] = grammar_action in (1, 2)

        changed_features = [name for name, changed in dirty.items() if changed]
        if changed_features:
            self.log.appendPlainText(
                "🧭 一键联动仅处理已修改项目：" + ", ".join(changed_features)
            )

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
                            self._yaml_engine.atomic_write_many({file_path: None})
                            deleted_files.append(os.path.basename(file_path))
                        return False
                    if "patch" not in data: data["patch"] = {}
                
                self._yaml_engine.atomic_write_many({file_path: data})
                return True

            # 动作 写入候选数
            if dirty["page_size"]:
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
            if auto_freq_widget and dirty["auto_freq"]:
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
            if main_dict_val and dirty["main_dict"]:
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
            if st_widgets and any((
                dirty["super_tips_db"],
                dirty["super_tips_key"],
                dirty["super_tips_disabled"],
            )):
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
                        if dirty["super_tips_db"] and target_data["super_tips"].get("db_name") != db_name_val:
                            target_data["super_tips"]["db_name"] = db_name_val
                            modified = True
                        if dirty["super_tips_key"] and target_data["super_tips"].get("tips_key") != tips_key_val:
                            target_data["super_tips"]["tips_key"] = tips_key_val
                            modified = True

                        if dirty["super_tips_disabled"]:
                            cur_dt = target_data["super_tips"].get("disabled_types", [])
                            if not isinstance(cur_dt, list):
                                cur_dt = []
                            if cur_dt != dt_list:
                                if dt_list:
                                    self._safe_assign(target_data["super_tips"], "disabled_types", seq)
                                else:
                                    target_data["super_tips"].pop("disabled_types", None)
                                modified = True
                    else:
                        if "patch" not in target_data or target_data["patch"] is None: target_data["patch"] = {}
                        def patch_field(k, nv, bv):
                            nonlocal modified
                            if nv != bv:
                                if target_data["patch"].get(k) != nv: self._safe_assign(target_data["patch"], k, nv); modified = True
                            elif k in target_data["patch"]: del target_data["patch"][k]; modified = True
                                    
                        if dirty["super_tips_db"]:
                            patch_field("super_tips/db_name", db_name_val, base_db)
                        if dirty["super_tips_key"]:
                            patch_field("super_tips/tips_key", tips_key_val, base_key)

                        if dirty["super_tips_disabled"]:
                            if dt_list != base_dt:
                                if target_data["patch"].get("super_tips/disabled_types") != dt_list:
                                    self._safe_assign(
                                        target_data["patch"],
                                        "super_tips/disabled_types",
                                        seq if dt_list else CommentedSeq(),
                                    )
                                    modified = True
                            elif "super_tips/disabled_types" in target_data["patch"]:
                                del target_data["patch"]["super_tips/disabled_types"]
                                modified = True

                    if modified:
                        if _smart_write(f_path, target_data, f_name, is_direct):
                            if target_file not in updated_files: updated_files.append(target_file)

            # 动作 同步反查快捷键
            if rev_key and dirty["reverse_lookup"]:
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
                    base_pattern = _get_nested_val(
                        base_data,
                        "recognizer/patterns/wanxiang_reverse",
                        "^`[A-Za-z;]*$",
                    )
                    effective_old_key = self._effective_config_value(
                        f_name,
                        "wanxiang_lookup/key",
                        old_key,
                    )
                    effective_pattern = self._effective_config_value(
                        f_name,
                        "recognizer/patterns/wanxiang_reverse",
                        base_pattern,
                    )
                    new_pattern = self._replace_reverse_pattern_prefix(
                        effective_pattern,
                        effective_old_key,
                        rev_key,
                    )

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
                        patch_field(
                            "recognizer/patterns/wanxiang_reverse",
                            new_pattern,
                            base_pattern,
                        )
                        
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
            if any((dirty["paging"], dirty["cand2"], dirty["cand3"])):
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
                            remove_binding = (
                                (dirty["paging"] and is_paging)
                                or (dirty["cand2"] and is_cand and snd == "2")
                                or (dirty["cand3"] and is_cand and snd == "3")
                            )
                            if remove_binding:
                                continue
                            new_bindings.append(b)
                    
                        if f_name != "default.yaml":
                            if dirty["paging"] and paging_style == "逗号句号 ( , . )":
                                new_bindings.append(CommentedMap({"when": "paging", "accept": "comma", "send": "Page_Up"}))
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": "period", "send": "Page_Down"}))
                            elif dirty["paging"] and paging_style == "中括号 ( [ ] )":
                                new_bindings.append(CommentedMap({"when": "paging", "accept": "bracketleft", "send": "Page_Up"}))
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": "bracketright", "send": "Page_Down"}))
                            elif dirty["paging"] and paging_style == "减号等号 ( - = )":
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": "minus", "send": "Page_Up"}))
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": "equal", "send": "Page_Down"}))
                        
                            if dirty["cand2"] and rime_val2:
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": rime_val2, "send": 2}))
                            if dirty["cand3"] and rime_val3:
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": rime_val3, "send": 3}))
                    
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
                                remove_binding = (
                                    (dirty["paging"] and is_paging)
                                    or (dirty["cand2"] and is_cand and snd == "2")
                                    or (dirty["cand3"] and is_cand and snd == "3")
                                )
                                if remove_binding:
                                    continue
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
                            remove_binding = (
                                (dirty["paging"] and is_paging)
                                or (dirty["cand2"] and is_cand and snd == "2")
                                or (dirty["cand3"] and is_cand and snd == "3")
                            )
                            if remove_binding:
                                continue
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
                        
                            if dirty["paging"] and paging_style != base_paging:
                                if paging_style == "逗号句号 ( , . )":
                                    new_bindings.append(CommentedMap({"when": "paging", "accept": "comma", "send": "Page_Up"}))
                                    new_bindings.append(CommentedMap({"when": "has_menu", "accept": "period", "send": "Page_Down"}))
                                elif paging_style == "中括号 ( [ ] )":
                                    new_bindings.append(CommentedMap({"when": "paging", "accept": "bracketleft", "send": "Page_Up"}))
                                    new_bindings.append(CommentedMap({"when": "has_menu", "accept": "bracketright", "send": "Page_Down"}))
                                elif paging_style == "减号等号 ( - = )":
                                    new_bindings.append(CommentedMap({"when": "has_menu", "accept": "minus", "send": "Page_Up"}))
                                    new_bindings.append(CommentedMap({"when": "has_menu", "accept": "equal", "send": "Page_Down"}))
                        
                            if dirty["cand2"] and rime_val2 and rime_val2 != base_key2:
                                new_bindings.append(CommentedMap({"when": "has_menu", "accept": rime_val2, "send": 2}))
                            if dirty["cand3"] and rime_val3 and rime_val3 != base_key3:
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
                self._advanced_save_detail = final_msg
                for k in list(self._ui_cache.keys()):
                    if k != "VIRTUAL_GLOBAL" and k.endswith("_patch" if is_direct else "_direct"):
                        w = self._ui_cache[k]['tree']
                        self.cfg_stack.removeWidget(w)
                        w.deleteLater()
                        del self._ui_cache[k]
                self._advanced_save_changed = True
                self._advanced_save_summary = (
                    f"以【{'直写' if is_direct else '补丁'}模式】全局配置已同步。"
                )
            else:
                self._advanced_save_detail = "与当前配置一致，没有文件被修改。"
            
        except Exception as e:
            self._advanced_save_failed = True
            import traceback; self.log.appendPlainText(traceback.format_exc())
            QMessageBox.critical(self, "全局保存失败", str(e))

    def _find_tree_item(self, tree, title):
        def walk(item):
            if item.text(0) == title:
                return item
            for index in range(item.childCount()):
                found = walk(item.child(index))
                if found is not None:
                    return found
            return None

        for index in range(tree.topLevelItemCount()):
            found = walk(tree.topLevelItem(index))
            if found is not None:
                return found
        return None

    def _register_conflict_refresher(self, name, callback):
        if not hasattr(self, "_conflict_refreshers"):
            self._conflict_refreshers = {}
        self._conflict_refreshers[name] = callback

    def _refresh_all_conflict_labels(self):
        if getattr(self, "_refreshing_conflicts", False):
            return
        self._refreshing_conflicts = True
        try:
            for name in list(getattr(self, "_conflict_refreshers", {})):
                callback = self._conflict_refreshers.get(name)
                if callback:
                    callback()
        finally:
            self._refreshing_conflicts = False

    def _wire_global_live_conflicts(self, tree):
        if getattr(tree, "_advanced_live_wired", False):
            return
        tree._advanced_live_wired = True
        widgets = self._ui_cache.get("VIRTUAL_GLOBAL", {}).get("widgets", {})

        paging_item = self._find_tree_item(tree, "↔️ 翻页按键习惯")
        paging = widgets.get("paging")
        if paging_item is not None and paging is not None:
            label = tree.itemWidget(paging_item, 2)
            self._register_conflict_refresher("paging", lambda: self._check_conflict_paging(paging.currentText(), label, paging_item))
            paging.currentTextChanged.connect(lambda *_: self._refresh_all_conflict_labels())

        cand_item = self._find_tree_item(tree, "2️⃣3️⃣ 次选 / 三选快捷键")
        cand = widgets.get("cand_keys")
        if cand_item is not None and cand:
            label = tree.itemWidget(cand_item, 2)
            self._register_conflict_refresher(
                "candidate_keys",
                lambda: self._check_conflict_base(
                    [value for value in (cand[0].text().strip(), cand[1].text().strip()) if value],
                    ["2", "3"], label, cand_item,
                ),
            )
            cand[0].textChanged.connect(lambda *_: self._refresh_all_conflict_labels())
            cand[1].textChanged.connect(lambda *_: self._refresh_all_conflict_labels())

        tips_root = self._find_tree_item(tree, "💡 超级提示模块 (super_tips)")
        tips = widgets.get("super_tips") or {}
        tips_widget = tips.get("tips_key") if isinstance(tips, dict) else None
        if tips_root is not None and tips_widget is not None:
            tips_item = None
            for index in range(tips_root.childCount()):
                child = tips_root.child(index)
                if "提示上屏按键" in child.text(0):
                    tips_item = child; break
            if tips_item is not None:
                label = tree.itemWidget(tips_item, 2)
                self._register_conflict_refresher(
                    "super_tips",
                    lambda: self._check_conflict_base(
                        [tips_widget.text().strip()] if tips_widget.text().strip() else [],
                        [], label, tips_item,
                        ignore_paths={"super_tips/tips_key"},
                    ),
                )
                tips_widget.textChanged.connect(lambda *_: self._refresh_all_conflict_labels())

        reverse_item = self._find_tree_item(tree, "🔍 拆字与笔画反查键")
        reverse = widgets.get("reverse_lookup")
        if reverse_item is not None and reverse is not None:
            label = tree.itemWidget(reverse_item, 2)
            self._register_conflict_refresher(
                "reverse_lookup",
                lambda: self._check_conflict_base(
                    [reverse.text().strip()] if reverse.text().strip() else [],
                    [], label, reverse_item, check_alphabet=False,
                    ignore_paths={"wanxiang_lookup/key", "wanxiang_reverse/prefix"},
                ),
            )
            reverse.textChanged.connect(lambda *_: self._refresh_all_conflict_labels())

        self._refresh_all_conflict_labels()

    def _capture_global_widget_state(self, widgets=None):
        """读取一键联动页面当前值，用于精确判断真正被修改的功能。"""
        if widgets is None:
            widgets = self._ui_cache.get("VIRTUAL_GLOBAL", {}).get("widgets", {})

        page_widget = widgets.get("page_size")
        page_text = page_widget.text().strip() if page_widget else ""
        try:
            page_size = int(page_text)
        except (TypeError, ValueError):
            page_size = page_text

        paging_widget = widgets.get("paging")
        paging = paging_widget.currentText() if paging_widget else ""

        cand_widgets = widgets.get("cand_keys")
        cand2 = cand_widgets[0].text().strip() if cand_widgets else ""
        cand3 = cand_widgets[1].text().strip() if cand_widgets else ""

        auto_widget = widgets.get("auto_freq")
        auto_freq = bool(auto_widget and auto_widget.currentIndex() == 0)

        dict_widget = widgets.get("main_dict")
        main_dict = dict_widget.text().strip() if dict_widget else ""

        reverse_widget = widgets.get("reverse_lookup")
        reverse_lookup = reverse_widget.text().strip() if reverse_widget else ""

        tips_widgets = widgets.get("super_tips") or {}
        if isinstance(tips_widgets, dict):
            db_widget = tips_widgets.get("db_name")
            key_widget = tips_widgets.get("tips_key")
            disabled_widget = tips_widgets.get("disabled_types")
        else:
            db_widget = key_widget = disabled_widget = None

        tips_db = db_widget.text().strip() if db_widget else ""
        tips_key = key_widget.text().strip() if key_widget else ""
        disabled_text = disabled_widget.text_field.toPlainText() if disabled_widget is not None else ""
        disabled_types = tuple(line.strip() for line in disabled_text.splitlines() if line.strip())

        grammar_widget = widgets.get("grammar_model")
        grammar_action = grammar_widget.currentIndex() if grammar_widget else 0

        return {
            "page_size": page_size,
            "paging": paging,
            "cand2": cand2,
            "cand3": cand3,
            "auto_freq": auto_freq,
            "main_dict": main_dict,
            "reverse_lookup": reverse_lookup,
            "super_tips_db": tips_db,
            "super_tips_key": tips_key,
            "super_tips_disabled": disabled_types,
            "grammar_action": grammar_action,
        }

    def _sync_global_widget_baseline(self, *, reset_actions=False):
        """更新一键联动基线；只改内存，不刷新或重建页面。"""
        cache = self._ui_cache.get("VIRTUAL_GLOBAL", {})
        widgets = cache.get("widgets", {})
        if not widgets:
            return

        if reset_actions:
            grammar_widget = widgets.get("grammar_model")
            if grammar_widget is not None:
                grammar_widget.setCurrentIndex(0)

        state = self._capture_global_widget_state(widgets)
        state["grammar_action"] = 0
        cache["baseline"] = copy.deepcopy(state)

    @staticmethod
    def _replace_reverse_pattern_prefix(pattern, old_key, new_key):
        """只替换反查正则前缀，保留 [A-Za-z;] 等后续规则。"""
        pattern = str(pattern or "")
        old_key = str(old_key or "")
        new_key = str(new_key or "")
        escaped_new = re.escape(new_key)

        if not pattern or not pattern.startswith("^"):
            return f"^{escaped_new}[A-Za-z;]*$"

        escaped_old = re.escape(old_key)
        old_prefix = "^" + escaped_old
        if old_key and pattern.startswith(old_prefix):
            return "^" + escaped_new + pattern[len(old_prefix):]

        raw_prefix = "^" + old_key
        if old_key and pattern.startswith(raw_prefix):
            return "^" + escaped_new + pattern[len(raw_prefix):]

        if len(pattern) >= 2:
            return "^" + escaped_new + pattern[2:]
        return f"^{escaped_new}[A-Za-z;]*$"

    def _render_global_business_page(self, tree_widget):
        self._conflict_refreshers = {}
        self._legacy_render_global_business_page(tree_widget)
        self._wire_global_live_conflicts(tree_widget)
        self._sync_global_widget_baseline()

    def _ensure_advanced_engines(self):
        if not hasattr(self, "_yaml_engine"):
            self._yaml_engine = RimeYamlEngine()
        if not hasattr(self, "_key_conflict_engine"):
            self._key_conflict_engine = RimeKeyConflictEngine(self._yaml_engine)
        if not hasattr(self, "_live_key_registry"):
            self._live_key_registry = LiveKeyRegistry()
        if not hasattr(self, "_effective_cache"):
            self._effective_cache = {}
        if not hasattr(self, "_source_effective_cache"):
            self._source_effective_cache = {}
        if not hasattr(self, "_yaml_load_errors"):
            self._yaml_load_errors = {}

    @staticmethod
    def _custom_name_for(file_name):
        if file_name.endswith(".schema.yaml"):
            return file_name.replace(".schema.yaml", ".custom.yaml")
        if file_name == "default.yaml":
            return "default.custom.yaml"
        return ""

    def _clear_yaml_issue_log(self):
        if hasattr(self, "yaml_issue_log"):
            self.yaml_issue_log.clear()
        if hasattr(self, "yaml_issue_panel"):
            self.yaml_issue_panel.hide()

    def _yaml_error_advice(self, file_name, error):
        issue = getattr(error, "issue", None)
        if issue is not None:
            location = f"{issue.parent_path or '<根节点>'}/{issue.key}"
            lines = f"第 {issue.first_line + 1}、{issue.second_line + 1} 行"

            if issue.key in {"__patch", "__include"}:
                advice = (
                    "修改建议：同一父节点下只保留一个特殊键，并将多个来源改成列表，例如：\n"
                    f"  {issue.key}:\n"
                    "    - 第一个来源\n"
                    "    - 第二个来源"
                )
            else:
                advice = "修改建议：删除其中一个重复键，或将两段配置合并到同一个键值中。"

            return f"❌ {file_name}\n位置：{location}（{lines}）\n{advice}"

        return (
            f"❌ {file_name}\n错误：{error}\n"
            "修改建议：检查错误附近的缩进、冒号、引号和列表符号；"
            "修正后重新扫描，或主动点击左侧该方案重新加载。"
        )

    def _on_yaml_cache_error(self, file_name, error):
        self._ensure_advanced_engines()
        self._yaml_load_errors[file_name] = error
        message = f"❌ 高级设置未加载 {file_name}: {error}"

        if hasattr(self, "log"):
            self.log.appendPlainText(message)

        if hasattr(self, "yaml_issue_log"):
            if self.yaml_issue_log.toPlainText().strip():
                self.yaml_issue_log.appendPlainText("\n" + "─" * 48)
            self.yaml_issue_log.appendPlainText(self._yaml_error_advice(file_name, error))
            self.yaml_issue_panel.show()

    def _on_cache_loaded(self, fname, s_data, c_patch, effective=None):
        self._ensure_advanced_engines()
        self._yaml_cache[fname] = (s_data, c_patch)
        self._source_effective_cache[fname] = self._yaml_engine.apply_patch(s_data, c_patch)
        self._effective_cache[fname] = effective if effective is not None else self._source_effective_cache[fname]
        self._yaml_load_errors.pop(fname, None)

    def _on_all_yaml_parsed(self):
        if self._yaml_load_errors:
            first_name, first_error = next(iter(self._yaml_load_errors.items()))
            self.lbl_giant_load.setText(f"⚠️ 部分 YAML 未加载：{first_name}\n{first_error}")
            self.lbl_giant_load.setStyleSheet("font-size:18px; font-weight:bold; color:#d9534f;")
        self._legacy_on_all_yaml_parsed()

    def _load_document_into_cache(self, target_id, *, show_dialog=True):
        self._ensure_advanced_engines()
        rime_dir = self.upd_rime.text().strip()
        schema_path = os.path.join(rime_dir, target_id)
        custom_name = self._custom_name_for(target_id)
        custom_path = os.path.join(rime_dir, custom_name) if custom_name else ""
        try:
            document = self._yaml_engine.load_pair(schema_path, custom_path)
        except RimeYamlError as error:
            self._yaml_load_errors[target_id] = error
            if show_dialog and error.issue:
                dialog = YamlDuplicateFixDialog(self, error.issue)
                if dialog.exec() == QDialog.Accepted:
                    return self._load_document_into_cache(target_id, show_dialog=show_dialog)
            elif show_dialog:
                QMessageBox.critical(self, "YAML 解析失败", str(error))
            return False
        self._yaml_cache[target_id] = (document.schema, document.patch)
        self._source_effective_cache[target_id] = copy.deepcopy(
            getattr(document, "source_effective", self._yaml_engine.apply_patch(document.schema, document.patch))
        )
        self._effective_cache[target_id] = document.effective
        self._yaml_load_errors.pop(target_id, None)
        return True

    def _build_and_cache_yaml_ui(self, target_id, activate=False, force_direct_mode=None):
        # 后台扫描已经生成 schema / source_effective / runtime effective。
        # 页面构建只消费缓存；仅在缓存确实缺失时才重新读盘编译。
        if target_id != "VIRTUAL_GLOBAL":
            cache_ready = (
                target_id in self._yaml_cache
                and target_id in self._effective_cache
                and target_id in self._source_effective_cache
            )
            if not cache_ready and not self._load_document_into_cache(
                target_id, show_dialog=activate
            ):
                return
        return self._legacy_build_and_cache_yaml_ui(
            target_id, activate, force_direct_mode
        )

    def _schema_conflict_scopes(self):
        """按可独立切换的方案建立冲突池，不让不同方案互相报告。"""
        self._ensure_advanced_engines()
        available = set(self._effective_cache)
        if not available:
            return {}

        common_files = {
            name for name in ("default.yaml", "wanxiang_algebra.yaml")
            if name in available
        }

        default_data = self._effective_cache.get("default.yaml", {})
        schema_list = self._yaml_engine.get_path(default_data, "schema_list", [])
        root_files = []

        if isinstance(schema_list, list):
            for item in schema_list:
                schema_id = None
                if isinstance(item, dict):
                    schema_id = item.get("schema") or item.get("schema_id")
                elif item:
                    schema_id = item

                if not schema_id:
                    continue

                file_name = str(schema_id)
                if not file_name.endswith(".yaml"):
                    file_name = f"{file_name}.schema.yaml"

                if file_name in available and file_name not in root_files:
                    root_files.append(file_name)

        if not root_files:
            for file_name in (
                "wanxiang.schema.yaml",
                "wanxiang_pro.schema.yaml",
                "wanxiang_t9.schema.yaml",
            ):
                if file_name in available:
                    root_files.append(file_name)

        if not root_files:
            root_files = sorted(
                name for name in available
                if name.endswith(".schema.yaml")
            )

        def add_dependencies(file_name, files):
            if file_name in files or file_name not in available:
                return

            files.add(file_name)
            data = self._effective_cache.get(file_name, {})
            dependencies = self._yaml_engine.get_path(
                data, "schema/dependencies", []
            )
            if not isinstance(dependencies, list):
                return

            for dependency in dependencies:
                dep_file = str(dependency)
                if not dep_file.endswith(".yaml"):
                    dep_file = f"{dep_file}.schema.yaml"
                add_dependencies(dep_file, files)

        scopes = {}
        for root_file in root_files:
            files = set(common_files)
            add_dependencies(root_file, files)
            scopes[root_file] = sorted(files)

        return scopes

    def _relevant_conflict_scopes(self):
        scopes = self._schema_conflict_scopes()
        current_file = getattr(self, "current_edit_file", "") or ""

        if not current_file or current_file == "VIRTUAL_GLOBAL":
            return scopes

        matched = {
            scope_name: files
            for scope_name, files in scopes.items()
            if current_file in files
        }
        if matched:
            return matched

        if current_file in self._effective_cache:
            files = [
                name for name in ("default.yaml", current_file)
                if name in self._effective_cache
            ]
            return {current_file: files}

        return scopes

    def _active_schema_files(self):
        """兼容旧接口：返回所有独立作用域的文件并集。"""
        files = set()
        for scope_files in self._schema_conflict_scopes().values():
            files.update(scope_files)
        return sorted(files)

    def _disk_claims_by_scope(self):
        self._ensure_advanced_engines()
        result = {}

        for scope_name, file_names in self._relevant_conflict_scopes().items():
            claims = []
            for file_name in file_names:
                effective = self._effective_cache.get(file_name)
                if effective is not None:
                    claims.extend(
                        self._key_conflict_engine.collect_claims(
                            effective,
                            file_name,
                            origin="disk",
                        )
                    )
            result[scope_name] = claims

        return result

    def _disk_claims(self):
        """兼容旧调用；真正两两检测必须使用按作用域结果。"""
        claims = []
        for scope_claims in self._disk_claims_by_scope().values():
            claims.extend(scope_claims)
        return claims

    def _widget_text(self, widget):
        if widget is None:
            return ""
        if hasattr(widget, "text"):
            return widget.text().strip()
        if hasattr(widget, "currentText"):
            return widget.currentText().strip()
        return ""

    def _refresh_live_registry(self):
        self._ensure_advanced_engines()
        self._live_key_registry.clear()
        widgets = self._ui_cache.get("VIRTUAL_GLOBAL", {}).get("widgets", {}) if hasattr(self, "_ui_cache") else {}

        paging = widgets.get("paging")
        if paging:
            mapping = {
                "逗号句号 ( , . )": ((",", "send:page_up", "paging"), (".", "send:page_down", "has_menu")),
                "中括号 ( [ ] )": (("[", "send:page_up", "paging"), ("]", "send:page_down", "has_menu")),
                "减号等号 ( - = )": (("-", "send:page_up", "has_menu"), ("=", "send:page_down", "has_menu")),
            }
            claims = []
            for index, (value, action, context) in enumerate(mapping.get(paging.currentText(), ())):
                key = self._key_conflict_engine.normalize_key(value)
                if key:
                    claims.append(KeyClaim(key, action, context, "<界面>", "global/paging", str(index), "ui"))
            self._live_key_registry.set_claims("global/paging", claims)

        cand = widgets.get("cand_keys")
        if cand:
            claims = []
            for slot, action, edit in (("second", "send:2", cand[0]), ("third", "send:3", cand[1])):
                key = self._key_conflict_engine.normalize_key(edit.text().strip())
                if key:
                    claims.append(KeyClaim(key, action, "has_menu", "<界面>", "global/candidate_keys", slot, "ui"))
            self._live_key_registry.set_claims("global/candidate_keys", claims)

        super_tips = widgets.get("super_tips") or {}
        tips_widget = super_tips.get("tips_key") if isinstance(super_tips, dict) else None
        if tips_widget:
            key = self._key_conflict_engine.normalize_key(tips_widget.text().strip())
            self._live_key_registry.set_claims("global/super_tips", [
                KeyClaim(key, "super_tips", "composing", "<界面>", "super_tips/tips_key", origin="ui")
            ] if key else [])

        reverse = widgets.get("reverse_lookup")
        if reverse:
            key = self._key_conflict_engine.normalize_key(reverse.text().strip())
            self._live_key_registry.set_claims("global/reverse_lookup", [
                KeyClaim(key, "reverse_lookup", "composing", "<界面>", "wanxiang_lookup/key", origin="ui")
            ] if key else [])

        # 当前普通 YAML 页面中可识别的热键字段也加入实时注册表。
        # 已由综合设置专用控件接管的路径不重复注册，避免“界面值 ↔ 界面值”自相冲突。
        managed_paths = set()
        if tips_widget:
            managed_paths.add("super_tips/tips_key")
        if reverse:
            managed_paths.update({"wanxiang_lookup/key", "wanxiang_reverse/prefix"})

        generic_claims = []
        for path, value in getattr(self, "_yaml_widgets", {}).items():
            if path in managed_paths:
                continue

            # 普通 YAML 页登记为 (widget, value_type)。
            # 对未知来源或旧缓存中的裸控件直接跳过，冲突提示绝不能因控件形态异常
            # 打断输入事件。
            if not isinstance(value, (tuple, list)) or len(value) != 2:
                continue

            widget, value_type = value
            if value_type in {"bool", "int", "float", "number", "list_text", "raw_yaml", "multiline_str", "schema_checkboxes"}:
                continue
            if path == "super_processor/select_character":
                raw = self._widget_text(widget)
                for slot, action, key in zip(("first", "last"), ("select_first_character", "select_last_character"), self._key_conflict_engine.parse_key_slots(raw, 2)):
                    if key:
                        generic_claims.append(KeyClaim(key, action, "has_menu", "<界面>", path, slot, "ui"))
            elif path.endswith(("/hotkey", "/tips_key", "/trigger")) or path in {"wanxiang_lookup/key", "wanxiang_reverse/prefix"}:
                key = self._key_conflict_engine.normalize_key(self._widget_text(widget))
                if key:
                    generic_claims.append(KeyClaim(key, f"ui:{path}", "composing", "<界面>", path, origin="ui"))
        self._live_key_registry.set_claims("generic", generic_claims)

    def _apply_live_overrides(self, disk, live):
        # 界面实时值代表该 YAML 路径的待保存最终值，按路径覆盖磁盘声明，
        # 不能因为 action 标签一个叫 english_trigger、一个叫 ui:path 就重复计算。
        override_paths = {claim.yaml_path for claim in live}
        override_actions = {
            claim.action for claim in live
            if claim.yaml_path.startswith("global/")
        }

        filtered = []
        for claim in disk:
            if claim.yaml_path in override_paths:
                continue
            if claim.action in override_actions:
                continue
            if claim.action in {
                "send:page_up", "send:page_down", "send:prior", "send:next"
            } and any(item.yaml_path == "global/paging" for item in live):
                continue
            if claim.action in {"send:2", "send:3"} and any(
                item.yaml_path == "global/candidate_keys" for item in live
            ):
                continue
            if claim.action == "super_tips" and any(
                item.yaml_path == "super_tips/tips_key" for item in live
            ):
                continue
            if claim.action in {"reverse_lookup", "reverse_prefix"} and any(
                item.yaml_path == "wanxiang_lookup/key" for item in live
            ):
                continue
            filtered.append(claim)

        return filtered + live

    def _claims_with_live_overrides_by_scope(self):
        self._refresh_live_registry()
        live = self._live_key_registry.all_claims()

        return {
            scope_name: self._apply_live_overrides(disk_claims, live)
            for scope_name, disk_claims
            in self._disk_claims_by_scope().items()
        }

    def _claims_with_live_overrides(self):
        """兼容旧调用；真正冲突检测必须使用按作用域版本。"""
        claims = []
        for scope_claims in self._claims_with_live_overrides_by_scope().values():
            claims.extend(scope_claims)
        return claims

    def _get_active_bindings(self):
        bindings = []
        for file_name in self._active_schema_files():
            effective = self._effective_cache.get(file_name, {})
            current = self._yaml_engine.get_path(effective, "key_binder/bindings", [])
            if isinstance(current, list):
                bindings.extend(copy.deepcopy(current))
        return bindings

    def _infer_current_actions(self, target_symbols, ignore_sends):
        actions = {str(value).lower() for value in ignore_sends}
        widgets = self._ui_cache.get("VIRTUAL_GLOBAL", {}).get("widgets", {}) if hasattr(self, "_ui_cache") else {}
        target_canon = {self._key_conflict_engine.normalize_key(value).canonical for value in target_symbols if self._key_conflict_engine.normalize_key(value)}
        super_tips = widgets.get("super_tips") or {}
        tips_widget = super_tips.get("tips_key") if isinstance(super_tips, dict) else None
        if tips_widget:
            key = self._key_conflict_engine.normalize_key(tips_widget.text().strip())
            if key and key.canonical in target_canon:
                actions.add("super_tips")
        reverse = widgets.get("reverse_lookup")
        if reverse:
            key = self._key_conflict_engine.normalize_key(reverse.text().strip())
            if key and key.canonical in target_canon:
                actions.update({"reverse_lookup", "reverse_prefix"})
        return actions

    def _check_conflict_base(
        self, target_symbols, ignore_sends, lbl, item,
        check_alphabet=True, ignore_paths=None,
    ):
        if not target_symbols:
            msg = "✨ 安全：当前选项无系统级冲突风险\n(实时检测按键、别名与变种占用)"
            lbl.setText(msg); lbl.setStyleSheet("color:#61A165; font-size:13px; padding:4px;")
            self._dynamic_row_height(item, msg)
            return

        current_actions = self._infer_current_actions(
            target_symbols, ignore_sends
        )
        ignored_yaml_paths = {str(path) for path in (ignore_paths or ())}
        conflict_map = {}

        for scope_name, claims in self._claims_with_live_overrides_by_scope().items():
            # 同一个业务字段在 wanxiang / pro / t9 等独立 schema 中复用同一按键
            # 不构成跨方案冲突。当前控件自己的 YAML 路径从每个 scope 中剔除，
            # 仍保留同一 scope 内“其他路径占用同一键”的真实提示。
            scoped_claims = [
                claim for claim in claims
                if claim.yaml_path not in ignored_yaml_paths
            ]
            scoped_conflicts = self._key_conflict_engine.find_for_targets(
                target_symbols,
                scoped_claims,
                ignore_actions=current_actions,
                check_alphabet=check_alphabet,
            )

            skipped_self = set()
            for conflict in scoped_conflicts:
                claim = conflict.right
                signature = (
                    claim.action,
                    claim.yaml_path,
                    claim.slot,
                    claim.key.canonical,
                )
                if (
                    claim.origin == "ui"
                    and claim.action in current_actions
                    and signature not in skipped_self
                ):
                    skipped_self.add(signature)
                    continue

                unique_key = (
                    int(conflict.severity),
                    conflict.right.identity,
                    conflict.reason,
                    conflict.left.key.canonical,
                )
                conflict_map.setdefault(unique_key, conflict)

        conflicts = sorted(
            conflict_map.values(),
            key=lambda item: (
                -int(item.severity),
                item.right.source_file,
                item.right.yaml_path,
                item.right.slot,
            ),
        )

        high_risk = [c for c in conflicts if c.severity >= ConflictSeverity.ERROR]
        notices = [c for c in conflicts if c.severity >= ConflictSeverity.VARIANT]
        if high_risk:
            shown = high_risk[:3]
            msg = "⚠️ 高风险按键复用（仅供参考，不影响保存）：\n" + "\n".join(c.format_line() for c in shown)
            if len(high_risk) > len(shown): msg += f"\n…另有 {len(high_risk) - len(shown)} 处"
            style = "color:#C97828; font-weight:bold; font-size:13px; padding:4px;"
        elif notices:
            shown = notices[:3]
            msg = "ℹ️ 按键复用提示（仅供参考，不影响保存）：\n" + "\n".join(c.format_line() for c in shown)
            if len(notices) > len(shown): msg += f"\n…另有 {len(notices) - len(shown)} 处"
            style = "color:#8A6D3B; font-weight:bold; font-size:13px; padding:4px;"
        else:
            msg = "✅ 未发现明显按键复用\n(静态审计仅供参考，运行时行为仍由状态、处理顺序和 Lua 逻辑决定)"
            style = "color:#61A165; font-weight:bold; font-size:13px; padding:4px;"
        lbl.setText(msg); lbl.setStyleSheet(style); self._dynamic_row_height(item, msg)

    def _validate_dynamic_duplicate_keys(self):
        errors = []
        tree = self.cfg_stack.currentWidget() if hasattr(self, "cfg_stack") else None
        if tree is None:
            return errors
        for full_path, (parent_item, list_type) in getattr(self, "_yaml_dynamic_lists", {}).items():
            if list_type not in {"kv_list", "block_list"}:
                continue
            seen = {}
            for index in range(parent_item.childCount()):
                child = parent_item.child(index)
                widget = tree.itemWidget(child, 1)
                if hasattr(widget, "get_key"):
                    key = widget.get_key()
                    if key:
                        if key in seen:
                            errors.append(f"{full_path}: 第 {seen[key] + 1} 与第 {index + 1} 行重复参数 {key}")
                        seen[key] = index
        return errors

    def _validate_before_save(self):
        """只拦截能够确定会破坏配置结构的问题。

        按键复用受输入状态、processor 顺序、tag、match 以及 Lua 内部逻辑影响，
        静态分析结果仅用于界面提示，绝不作为保存门禁。
        """
        return list(dict.fromkeys(self._validate_dynamic_duplicate_keys()))

    def _planned_save_paths(self, *, global_mode=False):
        """计算本次允许修改的精确文件集合。

        不根据扩展名扫描目录；未列入本集合的文件不会被事务读取、校验或回滚。
        """
        rime_dir = Path(self.upd_rime.text().strip())
        is_direct = self.rb_direct_mode.isChecked()
        planned = set()

        if global_mode:
            if is_direct:
                names = {
                    "default.yaml",
                    "wanxiang.schema.yaml",
                    "wanxiang_pro.schema.yaml",
                }
            else:
                names = {
                    "default.custom.yaml",
                    "wanxiang.custom.yaml",
                    "wanxiang_pro.custom.yaml",
                }
            planned.update(rime_dir / name for name in names)

            # 综合设置唯一可能新建的非纯 YAML 文件是用户明确命名的词典副本。
            widgets = self._ui_cache.get("VIRTUAL_GLOBAL", {}).get("widgets", {})
            main_dict_widget = widgets.get("main_dict")
            main_dict_name = main_dict_widget.text().strip() if main_dict_widget else ""
            if (
                main_dict_name
                and main_dict_name not in {"wanxiang", "wanxiang_pro"}
                and main_dict_name.replace("_", "").isalnum()
            ):
                dict_target = rime_dir / f"{main_dict_name}.dict.yaml"
                # 原始逻辑只在目标不存在时复制，不会覆盖既有词典。
                if not dict_target.exists():
                    planned.add(dict_target)
            return planned

        target_name = str(getattr(self, "current_edit_file", "") or "")
        if not is_managed_source_yaml(target_name):
            raise RimeYamlError(f"当前文件不在高级设置管理清单中：{target_name}")

        if is_direct:
            planned.add(rime_dir / target_name)
        else:
            custom_name = self._custom_name_for(target_name)
            if not custom_name or not is_managed_config_yaml(custom_name):
                raise RimeYamlError(f"当前文件不支持补丁模式：{target_name}")
            planned.add(rime_dir / custom_name)
        return planned

    def _validate_changed_rime_files(self, changed_paths):
        """只检查本次计划内、实际发生变化的文件。"""
        for path in changed_paths:
            path = Path(path)
            if is_managed_config_yaml(path):
                if path.exists():
                    self._yaml_engine.validate_file(str(path))
                continue
            if is_rime_dictionary(path):
                # Rime 词典是 YAML 头 + TSV 正文，绝不全文交给 YAML 解析器。
                continue
            raise RimeYamlError(f"保存过程出现未授权文件变化：{path.name}")

    def _log_controlled_save_plan(self, planned_paths):
        names = ", ".join(path.name for path in sorted(planned_paths, key=lambda item: item.name))
        self.log.appendPlainText(
            "🛡️ 受控保存范围：" + (names or "无") +
            "\n   未列入范围的词典、用户数据、installation.yaml 等不会被读取或校验。"
        )

    def _prompt_deploy_after_commit(self, summary, changed_names):
        """事务提交后再询问部署；显式记录每一步，禁止静默失败。"""
        self.log.appendPlainText(
            f"🟡 保存事务已提交，准备询问部署：{changed_names}"
        )

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("保存成功")
        box.setText(summary)
        box.setInformativeText("保存事务已经提交。是否立即触发 Rime 部署以生效？")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        box.setWindowModality(Qt.WindowModal)
        box.show()
        box.raise_()
        box.activateWindow()
        reply = box.exec()

        if reply != QMessageBox.Yes:
            self.log.appendPlainText("💡 用户选择暂不部署。")
            return

        self.log.appendPlainText("🚀 用户已确认，正在触发 Rime 部署……")
        try:
            result = self._start_and_deploy_from_main()
        except Exception as error:
            result = (False, f"部署调用发生异常：{error}")

        if isinstance(result, tuple):
            ok, message = bool(result[0]), str(result[1])
        elif isinstance(result, bool):
            ok = result
            message = "部署指令已发送。" if ok else "部署调用未成功。"
        else:
            # 兼容旧版无返回值方法：只有明确日志无法判断，因此按失败处理，避免静默。
            ok = False
            message = "部署方法未返回执行结果，请检查部署器检测逻辑。"

        if ok:
            self.log.appendPlainText(f"✅ {message}")
        else:
            self.log.appendPlainText(f"❌ {message}")
            QMessageBox.warning(self, "部署未触发", message)

    def _sync_current_page_effective_baseline(self, target_id):
        """提交后更新当前页面的完整比较基线，不重建界面。"""
        if not target_id or target_id == "VIRTUAL_GLOBAL":
            return

        schema_data, _ = self._yaml_cache.get(target_id, ({}, {}))
        effective_data = self._effective_cache.get(target_id, schema_data)
        source_effective_data = self._source_effective_cache.get(target_id, schema_data)
        is_direct_mode = self.rb_direct_mode.isChecked()

        cache_key = f"{target_id}_{'direct' if is_direct_mode else 'patch'}"
        page_cache = self._ui_cache.get(cache_key, {})
        base_values = page_cache.get("base")
        if not isinstance(base_values, dict):
            base_values = self._yaml_base_values

        missing = object()
        for path, base_info in base_values.items():
            if not isinstance(base_info, dict):
                continue

            schema_value = self._yaml_engine.get_path(schema_data, path, missing)
            if is_direct_mode:
                display_data = schema_data
            elif base_info.get("baseline_kind") == "source_effective":
                display_data = source_effective_data
            else:
                display_data = effective_data
            display_value = self._yaml_engine.get_path(display_data, path, missing)

            schema_present = schema_value is not missing
            display_present = display_value is not missing

            base_info["schema_present"] = schema_present
            base_info["display_present"] = display_present
            base_info["schema"] = copy.deepcopy(schema_value) if schema_present else None
            base_info["display"] = (
                copy.deepcopy(display_value)
                if display_present
                else copy.deepcopy(base_info["schema"])
            )

        if self.current_edit_file == target_id:
            self._yaml_base_values = base_values

    def _reload_committed_advanced_state(self, changed_paths):
        """事务提交后，以磁盘中的 schema + custom 为唯一真值重新加载。"""
        if not changed_paths:
            return []

        rime_dir = Path(self.upd_rime.text().strip())
        changed_abs = {os.path.abspath(str(path)) for path in changed_paths}
        reloaded = []

        # 只检查当前已受控的配置文件，不扫描整个目录。
        for target_id in list(self._yaml_cache.keys()):
            managed_paths = {os.path.abspath(str(rime_dir / target_id))}
            custom_name = self._custom_name_for(target_id)
            if custom_name:
                managed_paths.add(os.path.abspath(str(rime_dir / custom_name)))

            if not (managed_paths & changed_abs):
                continue

            if self._load_document_into_cache(target_id, show_dialog=False):
                reloaded.append(target_id)
            else:
                self.log.appendPlainText(
                    f"⚠️ 文件已提交，但未能重新加载最终状态：{target_id}"
                )

        current_target = self.current_edit_file
        if current_target in reloaded:
            self._sync_current_page_effective_baseline(current_target)
            self.log.appendPlainText(
                f"🔄 当前最终配置状态已同步：{current_target} = schema + custom"
            )

        return reloaded

    def _run_controlled_save(self, *, global_mode=False):
        self._ensure_advanced_engines()
        errors = self._validate_before_save()
        if errors:
            QMessageBox.warning(
                self,
                "保存前结构校验未通过",
                "保存已中止：\n\n" + "\n".join(f"• {item}" for item in errors[:12]),
            )
            return

        try:
            planned_paths = self._planned_save_paths(global_mode=global_mode)
        except Exception as error:
            QMessageBox.critical(self, "保存范围无效", str(error))
            return

        self._advanced_save_failed = False
        self._advanced_save_changed = False
        self._advanced_save_detail = ""
        self._advanced_save_summary = "全局配置已保存。" if global_mode else "配置已保存。"
        self._log_controlled_save_plan(planned_paths)

        try:
            with SaveTransaction(planned_paths) as transaction:
                if global_mode:
                    self._legacy_save_virtual_global()
                else:
                    self._legacy_save_yaml_config()

                if self._advanced_save_failed:
                    raise RuntimeError("保存过程中出现错误，已回滚本次计划内文件")

                changed_paths = transaction.changed_paths()
                self._validate_changed_rime_files(changed_paths)
                transaction.commit()

            self._advanced_save_changed = bool(changed_paths)
            if changed_paths:
                self._reload_committed_advanced_state(changed_paths)
                changed_names = ", ".join(path.name for path in changed_paths)
                self._advanced_save_summary = f"已提交：{changed_names}"
                detail = getattr(self, "_advanced_save_detail", "").strip()
                self.log.appendPlainText(f"✅ 受控保存已提交：{changed_names}")
                if detail:
                    self.log.appendPlainText(f"   {detail}")
            else:
                self._advanced_save_summary = "当前配置与磁盘内容一致。"
                self.log.appendPlainText("💡 本次未产生文件变化，无需保存或部署。")
        except Exception as error:
            self.log.appendPlainText(f"❌ 受控保存已回滚：{error}")
            QMessageBox.critical(self, "保存已回滚", str(error))
            return

        if global_mode:
            self._sync_global_widget_baseline(reset_actions=True)
            self.log.appendPlainText("🔄 一键联动当前状态已更新。")

        # 保存只更新当前内存缓存；不重新扫描目录、不清空页面、不预构建全部面板。
        # “重新加载”仅由用户点击左侧按钮、更换目录或外部文件变化时显式触发。
        if changed_paths:
            deploy_names = ", ".join(path.name for path in changed_paths)
            self._prompt_deploy_after_commit(self._advanced_save_summary, deploy_names)
        else:
            QMessageBox.information(
                self,
                "无需保存",
                "当前界面配置与磁盘文件一致。\n\n没有文件被修改，也不会触发部署。",
            )

    def save_yaml_config(self):
        if self.current_edit_file == "VIRTUAL_GLOBAL":
            return self._save_virtual_global()
        return self._run_controlled_save(global_mode=False)

    def _save_virtual_global(self):
        return self._run_controlled_save(global_mode=True)


    def _start_and_deploy_from_main(self):
        """宿主未覆盖时的统一平台部署兜底。"""
        system_type = (
            "windows" if sys.platform.startswith("win")
            else "macos" if sys.platform == "darwin"
            else "android/linux"
        )
        logger = self.log.appendPlainText if hasattr(self, "log") else None
        return deploy_rime_platform(
            system_type,
            log=logger,
            server_path=str(getattr(self, "detected_server", "") or ""),
            deployer_path=str(getattr(self, "detected_deployer", "") or ""),
        )