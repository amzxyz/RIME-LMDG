# 万象移动端更新器模块规划

| 文件 | 职责 |
| --- | --- |
| `MainActivity.kt` | 页面导航、设置状态、更新按钮和任务状态展示 |
| `UpdateModels.kt` | `TaskState`、下载源常量、任务状态模型 |
| `UpdateEngine.kt` | 下载队列、重试、ZIP 解压、任务部署流程 |
| `ExtraDictModule.kt` | 附加词库 Raw 下载地址、目标辅助码读取、Python 处理桥接和输出重命名 |
| `AdvancedSettingsModule.kt` | 高级设置目录选择、SAF 临时镜像、元数据字段表单、补丁/直写保存 |
| `advanced_settings_mobile.py` | 复用桌面 `RimeYamlEngine`、`FILE_INDEX_META`、`SCHEMA_META_CONFIG` 的无界面桥接 |
| `advanced_settings/core.py` / `metadata.py` | 桌面高级设置的 YAML 编译、补丁、校验、原子写入和字段元数据 |
| `mobile_tools_bridge.py` | 桌面工具的严格词条/拼音段对齐、辅助码刷新和 Lite 去声调逻辑 |
| `PinyinToolScreen.kt` / `pinyin_bridge.py` | 独立拼音转换功能 |
| `RootShell.kt` | Root 目录读写与权限操作 |

高级设置不再把 YAML 当普通文本编辑。扫描时只显示桌面工具登记在 `FILE_INDEX_META` 中的源文件，并按 `SCHEMA_META_CONFIG` 生成字段；补丁模式写对应 `.custom.yaml`，直写模式修改源文件，保存前执行同一套 YAML 校验和原子写入。SAF 目录会暂存受控 YAML 文件，保存后同步回授权目录。

附加词库 Pro 处理通过 Chaquopy 调用 `mobile_tools_bridge.py` 的严格对齐实现：汉字、非汉字块和拼音段按相对位置对齐，无法可靠对齐时保留原行，避免把其他字的辅助码错位写入。Lite 使用桌面工具的声调映射；Pure/Base 保留原文件。
