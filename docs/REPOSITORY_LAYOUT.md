# 仓库结构说明

本仓库同时维护万象词库数据、桌面工具、Android 更新器、词库处理脚本和输入法评测工具。
公开数据路径保持稳定，程序源码与第三方依赖按职责分层。

| 目录 | 作用 |
|---|---|
| `dicts/` | 简体词库公开发布目录 |
| `dicts_hant/` | 繁体词库公开发布目录 |
| `pinyin_data/` | 拼音及标注源数据 |
| `apps/desktop/` | PC 工具与高级设置 |
| `apps/android/` | Android 更新器 |
| `tools/corpus/` | 语料处理 |
| `tools/model/` | 模型构建和排序 |
| `tools/quality/` | 质量检查 |
| `tools/rime/` | Rime 词库转换 |
| `tools/benchmark/` | 输入准确率评测 |
| `vendor/python/` | 随项目分发的第三方 Python 源码 |
| `platform/windows/` | Windows 专用工具 |

Android 端的 `pypinyin` 和 `advanced_settings` 是生成副本，源代码分别来自 `vendor/python/pypinyin/` 和 `apps/desktop/advanced_settings/`。
