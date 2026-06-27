# rime-schema-compare

用 **Python + librime** 对比多套 Rime 词库方案的 **整句解码准确率**。[librime](https://github.com/rime/librime)
当前 `librime` 进程内评测支持 **Windows / macOS / Linux**，会按平台自动查找动态库：Windows 使用 `rime.dll`，macOS 使用 `librime*.dylib`，Linux 使用 `librime.so*`。

## 最新评测结果 
[查看rime多方案最新评测结果（调用librime）](report/latest.md)

[查看其他windows输入法最新评测结果（黑盒模拟按键的方式测试）](report/other_latest.md)

最新评测结果表明，[白霜拼音](https://github.com/gaboolic/rime-frost)以及[万象拼音](https://github.com/amzxyz/rime_wanxiang)使用ngrams模型均超越了微软拼音。

## 各套方案说明

默认参与对比的方案在 `src/rime_schema_compare/config.py` 的 `DEFAULT_VENDORS` 中定义：每个条目包含 **vendor 键**（命令行与报表列名）、**子目录**、以及 **主 schema_id**（librime 里选用的方案 ID）。

默认对比的基础方案均按“**无语言模型、无用户词库**”口径评测：不额外挂载 `.gram` 模型文件，且评测前会清理 `userdb` 并通过 `custom.yaml` 禁用 `translator/enable_user_dict`。所有 `*_with_gram` 变体也统一复用同一个 [`wanxiang-lts-zh-hans.gram`](https://github.com/amzxyz/RIME-LMDG/releases)，仅在各自方案目录下额外挂载该语言模型，其余仍保持禁用用户词库。

| Vendor 键 | 目录 | 主 schema | 说明 |
|-----------|------|-----------|------|
| `mingyuepinyin` | `vendor/mingyuepinyin` | `luna_pinyin_simp` | 明月拼音（简体全拼），与 Rime 自带 Luna 系方案同源的一类发行 |
| `mingyuepinyin_with_gram` | `vendor/mingyuepinyin_with_gram` | `luna_pinyin_simp` | 带 `wanxiang-lts-zh-hans` ngram 模型的明月拼音；其余配置与 `vendor/mingyuepinyin` 保持一致 |
| `rime_ice` | `vendor/rime-ice` | `rime_ice` | 雾凇拼音 |
| `rime_ice_with_gram` | `vendor/rime-ice_with_gram` | `rime_ice` | 带 `wanxiang-lts-zh-hans` ngram 模型的雾凇拼音；其余配置与 `vendor/rime-ice` 保持一致 |
| `rime_frost` | `vendor/rime-frost` | `rime_frost` | 白霜拼音（rime-frost） |
| `rime_frost_with_gram` | `vendor/rime-frost_with_gram` | `rime_frost` | 带 `wanxiang-lts-zh-hans` ngram 模型的白霜拼音；其余配置与 `vendor/rime-frost` 保持一致 |
| `wanxiang` | `vendor/rime_wanxiang` | `wanxiang` | 万象拼音（子模块跟踪分支 `wanxiang`，见 [.gitmodules](.gitmodules)） |
| `rime_wanxiang_with_gram` | `vendor/rime_wanxiang_with_gram` | `wanxiang` | 带 `ngrams` 模型文件的万象拼音；其余配置与 `vendor/rime_wanxiang` 保持一致 |
| `rime_wubi_sentens_wubi86` | `vendor/rime-wubi-sentence` | `wubi86` | `gaboolic/rime-wubi-sentence` 的五笔整句 `wubi86` 方案；输入串按单字形码表取前 2 码连续拼接 |
| `rime_wubi_sentens_wubi86_with_gram` | `vendor/rime-wubi-sentence_with_gram` | `wubi86` | 带 `wanxiang-lts-zh-hans` ngram 模型的五笔整句 `wubi86` 方案；其余配置与 `vendor/rime-wubi-sentence` 保持一致 |

各方案的实际 YAML、编译产物与用户状态都放在各自的 `vendor/...` 目录下；所有方案共用的只读资源放在 [`vendor/data`](vendor/data)（不存在会自动创建）。需要让所有方案看到同一套程序级配置或补丁时，把文件放在 `vendor/data`（例如从小狼毫安装目录复制或做符号链接）。

## 如何执行评测脚本

### 前置条件

- 已安装可用的 **librime** 运行环境，且动态库及其依赖可被加载：
  - Windows：`rime.dll`（例如小狼毫自带）
  - macOS：`librime*.dylib`
  - Linux：`librime.so*`
- **Python 3.10+** 建议。
- **Git 子模块** 已拉取（首次体积较大）：

```bash
git submodule update --init --recursive --depth 1
```

### 安装依赖

```bash
pip install -r requirements.txt
```


### 运行命令

通过 `librime` 测试各个 Rime 输入方案，推荐直接运行 Python CLI；仓库会按当前系统自动解析动态库，也可手动用 `RIME_LIBRARY`（兼容旧变量 `RIME_DLL`）指定绝对路径：

```bash
python scripts/benchmark_sentences.py
python scripts/benchmark_sentences.py --corpus data/corpus/news.txt
RIME_LIBRARY=/absolute/path/to/librime python scripts/benchmark_sentences.py
```

Windows 下也可以继续使用 PowerShell 入口：

```
./scripts/run_test.ps1
```

### 运行 Windows 拼音输入法黑盒评测

Windows 下可单独跑系统/第三方拼音输入法的 GUI 黑盒评测。推荐使用通用入口：

```bash
python scripts/benchmark_windows_pinyin.py --ime microsoft_pinyin
python scripts/benchmark_windows_pinyin.py --ime microsoft_pinyin --corpus data/corpus/news.txt
python scripts/benchmark_windows_pinyin.py --ime sogou_pinyin
python scripts/benchmark_windows_pinyin.py --ime microsoft_pinyin sogou_pinyin
```

也可以用 PowerShell 入口一次同时评测微软拼音和搜狗拼音，并生成 `report/other_latest.md`：

```bash
./scripts/run_blackbox_test.ps1
```

默认口径固定为：

- 宿主程序是 `Notepad`
- 输入法由 `--ime` 指定，目前支持 `microsoft_pinyin`、`sogou_pinyin`
- 先预处理全部语料，再按输入法整批运行；例如先完整跑微软拼音，再完整跑搜狗拼音
- 对每句发送**连续全拼**
- 按 `Space` 提交第 1 候选
- 读取最终上屏文本，统计整句准确率与字级准确率

注意：

- 这是 **Windows 系统输入法黑盒评测**，不是像 `librime` 那样的进程内调用。
- 结果会受到 **Windows 版本、输入法版本、是否联网、个性化词频、当前系统输入法状态** 的影响。
- 跑黑盒评测时需要保持前台焦点稳定，不要手动切窗口或输入。
- 当前脚本会先解析系统里的 `InputMethodTips`，再切换到目标输入法；默认通过 Windows API 设置目标输入法并校验已切到正确 profile。若机器上的输入法顺序或系统行为有变化，黑盒结果仍可能出现波动。

### 输出文件（`artifacts/`）

未指定 `--corpus` 时，文件名前缀一般为 `benchmark_all_corpus_<时间戳>`；单语料时为 `benchmark_<语料标签>_<时间戳>`。

| 文件 | 内容 |
|------|------|
| `*_*.csv` | 宽表：每句一行，`gold` 后接各方案各自的 `*_input` / 句子是否判对 / 单句字级准确率 / 预测 / 错误信息 |
| `*_long.csv` | 窄表：每句 × 每方案一行；含该方案实际输入串 `input`，行序为先方案后句子 |
| `*_long_by_sentence.csv` | 同上结构；行序为先句子后方案 |
| `*_scheme_compare.txt` | 各方案**独有判对**及相对其它方案的**多判对**句子列表 |
| `*_summary.csv` | 按语料 × 方案汇总 |
| `*_report.txt` | 中文摘要：句子正确率、文字正确率等 |
| `*.json` | 完整 JSON（含窄表级 `per_sentence`） |

进度与阶段日志在 **stderr**（简体中文 Windows 控制台多为 GBK，避免乱码勿强行把 stderr 设为 UTF-8）。阶段前缀包括：`[启动]`、`[语料列表]`、`[分句]`、`[预过滤]`、`[输入串 x]`、`[librime:加载方案 x]`、`[librime:解码 x]`、`[汇总]`、`[写出结果]` 等。若使用 UTF-8 终端（如 `chcp 65001`），stderr 中的中文通常也能正常显示。

## 评测细节

### 指标与同义词

对每条参与评测的句子，用 **整句是否完全一致** 统计句子级准确率；字级用 **Levenshtein 编辑距离** 汇总得到 macro CER（总编辑量 / 金文总字数）。比较前可做 **同义词归一化**（默认规则 + `data/eval_synonyms.json`，例如 其它→其他、他/她/它→他、的/地/得→的），可用 `--eval-synonyms` 覆盖。

Windows 拼音输入法黑盒脚本复用同一套分句、过滤、同义词归一化和 Levenshtein 统计逻辑，因此输出的 `sentence_accuracy_percent` 与 `character_accuracy_percent` 可以和当前 Rime 结果并排看；但两者**不能视为完全同口径的引擎裸对比**，因为黑盒路径包含宿主窗口、系统 IME 状态与机器环境因素。

### 语料切分

实现见 [`src/rime_schema_compare/text_pipeline.py`](src/rime_schema_compare/text_pipeline.py)（`split_sentences` 与相关辅助函数）。要点如下：

- 先按 **换行** 分成行，空行丢弃；再对每行按标点切分。
- **全角 `，`、`。`** 以及 **半角 `,`** 均为切分点；**半角 `.`** 仅在 **非小数**（两侧为数字的 `.` 不切，如 `68.4`）时切分。
- 使用 **弯引号 「”** 配对深度：`：“` / `:"` 后进入引号内；闭引号 `”` 前切分并出层；避免把小数点当句号。
- 去掉段首尾的孤立引号与空白；**含顿号 `、`或书名号 `《》《`** 的片段 **整段丢弃**（不参与评测）。
- 切分后的片段还须满足下面「参与评测」的过滤条件。

### 哪些片段会进入「金句 + 输入串」流水线

与 `benchmark_sentences.py` 中准备阶段一致：

- 片段内 **不得** 含 ASCII 数字或拉丁字母。
- 去掉空白后须为 **纯 CJK 统一表意文字**（`U+4E00`–`U+9FFF`），不含符号或其它文字。
- 纯汉字片段长度须 **不少于 `MIN_EVAL_HANZI_CHARS`（默认 5）**。
- 拼音类方案由 `pypinyin` 的 `lazy_pinyin(..., Style.NORMAL)` 生成 **连续小写全拼** 作为输入。
- `rime_wubi_sentens_wubi86` 读取 `vendor/rime-wubi-sentence/program/wubi86.dict.yaml` 的单字码表，对每个汉字取对应形码的**前 2 个字母**并串接成输入；若句中任一字缺码，则该句对该方案跳过。
- `rime_wubi_sentens_wubi86_with_gram` 读取 `vendor/rime-wubi-sentence_with_gram/program/wubi86.dict.yaml` 的单字码表，对每个汉字取对应形码的**前 2 个字母**并串接成输入；若句中任一字缺码，则该句对该方案跳过。
- `rime_wubi_sentens_tiger` 读取 `vendor/rime-wubi-sentence/program/tiger.dict.yaml` 的单字码表，对每个汉字取对应形码的**前 2 个字母**并串接成输入；若句中任一字缺码，则该句对该方案跳过。
- `rime_wubi_sentens_ziyuan` 读取 `vendor/rime-wubi-sentence/cn_dicts_ziyuan/8105.dict.yaml` 的单字码表，对每个汉字取对应形码的**前 2 个字母**并串接成输入；若句中任一字缺码，则该句对该方案跳过。

### 加载方案（librime 目录）

[`RimeDistroRunner`](src/rime_schema_compare/rime_runner.py) 对每个 vendor：

- **`shared_data_dir`**：固定为仓库下 **`vendor/data`**。
- **`user_data_dir`**：该方案对应的 **`vendor/<子目录>`**（即各子模块根目录），用于读取该发行自己的 `build`、词典与用户侧配置。

切换方案时调用 `switch_distro`：若目录或 schema 变化，会 **关闭旧会话、重新 `initialize`**，再为后续解码做准备。

### 选择方案（schema）

每个 vendor 对应唯一的 **`schema_id`**（见上表）。评测在加载该 vendor 后调用 **`select_schema(session_id, schema_id)`** 打开批量解码会话（`begin_decode_batch`），整段语料在同一 session 内逐句 `feed_input`。

命令行 **`--vendors`** 只决定 **跑哪些 vendor**，不改变各 vendor 自带的 `schema_id`；若要换主方案，需改 `config.py` 中对应 `VendorConfig.schema_id`。

### 关闭用户词库

为保证对比的是 **词库方案本身** 而非个人累计词频，跑基准前会对每个将评测的 `user_data_dir` 调用 [`prepare_vendor_for_benchmark`](src/rime_schema_compare/benchmark_env.py)：

1. **删除** 目录下所有 **`*.userdb`**（LevelDB 式文件夹或文件），去掉已有用户词典。
2. **合并写入** `{schema_id}.custom.yaml`，在 `patch` 中设置 **`translator/enable_user_dict: false`**，禁用译者组件的用户词典。

因此评测前会 **修改** 各 `vendor/*` 下的 custom 与用户库文件；若需保留本地状态，请先备份或使用单独工作副本。

## 仓库布局速查

| 路径 | 作用 |
|------|------|
| [`src/rime_schema_compare/call_librime.py`](src/rime_schema_compare/call_librime.py) | Rime 动态库（`rime.dll` / `librime*.dylib` / `librime.so*`）的 ctypes 封装 |
| [`scripts/benchmark_sentences.py`](scripts/benchmark_sentences.py) | 主评测 CLI |
| [`data/corpus/`](data/corpus/) | 示例语料（UTF-8，可换成自己的文本） |


## License

本仓库自带的脚本与打包以原样提供；第三方组件见 [NOTICE](NOTICE)。各 `vendor/*` 仍遵循其上游许可证。
