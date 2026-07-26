"""高级设置元数据。由主程序拆分，保持原配置结构。"""

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

RIME_KEY_MAP = {
    " ": "space", "!": "exclam", "\"": "quotedbl", "#": "numbersign", "$": "dollar",
    "%": "percent", "&": "ampersand", "'": "apostrophe", "(": "parenleft", ")": "parenright",
    "*": "asterisk", "+": "plus", ",": "comma", "-": "minus", ".": "period", "/": "slash",
    ":": "colon", ";": "semicolon", "<": "less", "=": "equal", ">": "greater", "?": "question",
    "@": "at", "[": "bracketleft", "\\": "backslash", "]": "bracketright", "^": "asciicircum",
    "_": "underscore", "`": "grave", "{": "braceleft", "|": "bar", "}": "braceright", "~": "asciitilde"
}
