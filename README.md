## 重磅发布：基于48GB超大规模语料的RIME中文语法模型与词库构建
**——万象语法模型、万象向量词库**

### 项目简介
- 在庞大且多样的中文语料库基础上，我们构建了一个性能优异、覆盖面广的中文语法模型和高效的词库。此次发布的语法模型和词库构建，融合了来自社区问答、博文互动、公众号、百科词条、新闻报道、歌词、诗词文学、歇后语、绕口令、酒店外卖评论、法律文献、地区描述、文学作品以及诗词等多领域的内容，总体语料~~32G~~48G规模，更加均衡，清洗更加细致。该项目愿景：**致力于提供RIME最强基础底座，做最精准的读音标注、做最精准的词频统计、最恰当的分词词库以及基于现有条件打造了一个高命中率、精确的输入模型。顺便为pypinyin维护出一个高质量拼音标注元数据库**；

- 项目中的rime词库全部使用AI辅助筛选和人工校对，遴选出优质的词组。词库是全部带声调全拼，所有的词频是基于词组和拼音双键统计的，区别了如："那里 哪里" 这种类似场景下对于单字的词频，而不是全部归并到na的拼音下。单字词频是在词组语句中加上拼音最后拆解为单字及其对应拼音的组合，因此单字词频也是区分多音字的。 由于语料规模巨大，很多单字达到了10亿级别，词频经过对数归一化处理，缩短词频易于维护且文件储存更少的字节。如何迁移到你的方案？[点击迁移词库](https://github.com/amzxyz/rime-wanxiang-data/wiki/%E5%B0%86%E4%B8%87%E8%B1%A1%E8%AF%8D%E5%BA%93%E8%BF%81%E7%A7%BB%E5%88%B0%E4%BD%A0%E7%9A%84%E9%A1%B9%E7%9B%AE)
- **万象词库中的带声调拼音标注+词组构成+词频是整个万象项目的核心，是使用体验的基石，方案的其它功能皆可自定义，我希望使用者可以基于词库+转写的方式获得输入体验** [万象词库问题收集反馈表](https://docs.qq.com/smartsheet/DWHZsdnZZaGh5bWJI?viewId=vUQPXH&tab=BB08J2)
- [关于声调标注的修正你可以PR到该文件，制表符分隔](https://github.com/amzxyz/rime-wanxiang-data/blob/main/pinyin_data/%E8%AF%8D%E7%BB%84.dict.yaml)

[模型下载](https://github.com/amzxyz/rime-wanxiang-data/releases)    |    [模型配置说明](https://github.com/amzxyz/rime-wanxiang-data/wiki/%E8%AF%AD%E8%A8%80%E6%A8%A1%E5%9E%8B%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%AF%B4%E6%98%8E)    |    [构建教程](https://github.com/amzxyz/rime-build-grammar-word-frequency/wiki/%E4%BD%BF%E7%94%A8%E6%95%99%E7%A8%8B%EF%BC%9ARime-%E8%BE%93%E5%85%A5%E6%B3%95%E8%AF%AD%E8%A8%80%E6%A8%A1%E5%9E%8B%E6%9E%84%E5%BB%BA%E5%85%A8%E6%B5%81%E7%A8%8B)

- 词库文件对应说明：

 示例项目：

 [万象拼音-全拼双拼-声调辅助-反查辅助-中英混输](https://github.com/amzxyz/rime-wanxiang)

| 词库类型 | 文件名称     | 描述                   |
|----------|--------------|------------------------|
| 字表  | [`zi.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/zi.dict.yaml)  | 包含CJK字库基础区所有具有读音的字，不计多音43324字|
| 基础词库   | [`jichu.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/jichu.dict.yaml)  | 包含构成可用性的基本单元|
| 兼容词库 | [`duoyin.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/duoyin.dict.yaml) | 包含多音字词组,用于兼容词组的多种读音场景|
| 错音错字 | [`cuoyin.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/cuoyin.dict.yaml) | 包含易读错误易写错误的词条，可供输入和程序进行视觉提示|
| 分类词库 | [`diming.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/diming.dict.yaml) | 收录国内行政区划地区名称|
| 分类词库 | [`yiren.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/yiren.dict.yaml) | 艺人姓名|
| 分类词库 | [`mingren.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/mingren.dict.yaml) | 名人姓名|
| 扩展词库 | [`huaxue.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/huaxue.dict.yaml) | 化学类词汇|
| 扩展词库 | [`yaopin.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/yaopin.dict.yaml) | 药品类词汇|
| 扩展词库 | [`yixue.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/yixue.dict.yaml) | 医学类词汇|
| 扩展词库 | [`wuzhong.dict.yaml`](https://github.com/amzxyz/rime-wanxiang-data/blob/wanxiang/dicts/wuzhong.dict.yaml) | 收录动植物名称|




### 语法模型

Gram 是最适合输入法的模型类型。在 Rime 中，它类似词库，但更灵活：能基于已有“材料”（如“住在”“礼物1”“里屋2”）动态组合出“住在礼物”片段。传统做法依赖词库硬编码“住在里屋”，即便 500 万词也难覆盖全，且检索依赖编码分段翻译，易卡顿。

使用 Gram 可跳出词库维护的深坑——专业领域词库易得，日常用语却难以全面。一个语句流模型能省去大量人工维护。它基于 C++ 前缀树扫描，内存中仅映射一块区域，无需加载到内存，速度极快，因此可部署于翻译器阶段。这与所谓的智能模型完全不同，即消耗算力，又不能用于翻译器阶段，只能依赖UI搞延迟上屏，这个体验完全不如，有范围的穷举广覆盖。

大模型时代不应单纯拒绝“大”，否则将错失巨大助力。

### 如何评价效果：

仓库组件`rime-schema-compare`来自gaboolic/rime-schema-compare：他是一个py自动调用librime内核进行解码并对结果进行统计的脚本程序

评测结果如下(更差结果的方案就不体现了，有兴趣朋友可以自己进行测试)。以下测试均使用万象语法模型：

模型单独下载置入：`tools/benchmark/rime-schema-compare/vendor`中相应的gram方案文件夹即可

```
【总体】
  [rime_frost]
    句子正确率: 61.71%  (137944/223535 句完全匹配)
    文字正确率: 92.77%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 92.55%

  [rime_frost_with_gram]
    句子正确率: 75.42%  (168601/223535 句完全匹配)
    文字正确率: 96.02%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 95.63%

  [wanxiang]
    句子正确率: 62.34%  (139358/223535 句完全匹配)
    文字正确率: 93.5%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 93.17%

  [rime_wanxiang_with_gram]
    句子正确率: 76.86%  (171817/223535 句完全匹配)
    文字正确率: 96.32%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 95.99%
```

[📊 整句评测报告](artifacts/benchmark_all_corpus_20260626T204334Z_report.txt)

是否完全评价呢？ 答案是否定的：

语句流往往是高频聚合场景下来回弯弯绕，只要词频统计的问题不大，基本上能得到一致性较高的结果，而输入不仅仅是这些，就像万象能打出来的那些词：

多加冰、练完腿、煎个鸡蛋等等，很生活，却很难出现在语料中，万象词库与万象用户致力于持续收集、维护、修正那些3-5个字，让体验持续进化。

从数据来看万象语法模型让句子正确率提升了15%，使用中1%的进化都会有很大的感知何况是15%。

#### 使用方法：

**软件**：

小狼毫、鼠须管直接配置即可，fcitx5需要配合安装```librime-plugin-octagram```不同的Linux发行版包名可能不同

**说明**：

1. 基于拼音权重排序序列优化，对形码无特殊处理，因此只推荐运用在以拼音序列为基础的词库中，当然更推荐使用万象词库，数据间有更多优化。

2. 支持简体字模型：wanxiang-lts-zh-hans ， 繁体字模型：wanxiang-lts-zh-hant ，名称一个字母区别注意区分。

**参数**：
配置如下：

注意该参数只适用于万象词库，别的词库可根据实际需求微调！再提：词库的词组、编码、排序权重等结构组成与模型加权是一场精密的计算，维持着微妙的平衡，因此只有万象词库才能发挥得更好，原则上不支持形码。

```
__include: octagram   #启用语法模型
#语法模型
octagram:
  __patch:
    grammar:
      language: wanxiang-lts-zh-hans
      collocation_max_length: 6
      collocation_min_length: 2
      collocation_penalty: -14
      non_collocation_penalty: -6
      weak_collocation_penalty: -100
      rear_penalty: -18
    translator/contextual_suggestions: false
    translator/max_homophones: 8
```

### 词库处理方法：

使用万象工具箱操作，一看就懂，支持刷拼音、刷辅助码、转换简码、用户词库提炼等功能

## 仓库结构

| 路径 | 作用 |
|---|---|
| `dicts/` | 简体词库，保持公开 Raw 下载路径不变 |
| `dicts_hant/` | 繁体词库，保持公开 Raw 下载路径不变 |
| `pinyin_data/` | 拼音和标注源数据 |
| `extra-dicts.json` | 附加词库目录，客户端启动时动态读取 |
| `apps/desktop/` | 万象 PC 工具与高级设置 |
| `apps/android/` | 万象 Android 更新器 |
| `tools/corpus/` | 语料清洗、解析和分词脚本 |
| `tools/model/` | 语法模型和排序脚本 |
| `tools/quality/` | 质量检查和词条筛选脚本 |
| `tools/rime/` | Rime 词典转换与刷拼音、辅助码工具 |
| `tools/benchmark/rime-schema-compare/` | 基于 librime 的输入准确率评测工具 |
| `vendor/python/` | 随项目分发的第三方 Python 源码 |
| `platform/windows/ahk/` | Windows 快捷键工具和相关运行文件 |

## 附加词库目录

`extra-dicts.json` 是客户端读取的公开配置。每个项目只维护一个稳定的 `id` 和一个显示名称：

```json
[
  {"id": "fangyan", "name": "国内方言词库"}
]
```

客户端会将 `id` 映射到 `dicts/{id}.dict.yaml`，不在配置中填写扩展名。新增词库只需新增词库文件和此配置项，不需要同步修改客户端代码。

## 构建入口

- PC 工具：`apps/desktop/wanxiang-tools.py`
- Android 更新器：`apps/android/wanxiang-updater/`
- 输入法评测：`tools/benchmark/rime-schema-compare/`
- 统一构建：`.github/workflows/wanxiang-tools.yml`

Android 工程中的 `pypinyin` 和 `advanced_settings` 副本由 CI 从 `vendor/python/pypinyin/` 和 `apps/desktop/advanced_settings/` 生成。请修改源目录，不要直接修改生成副本。

## 数据来源与生成文件

词库、拼音数据和语法模型属于持续生成和人工校对的数据资产。构建产物、评测报告、平台二进制和 Android Python 副本可能由 CI 生成；发布时应记录生成提交、工具版本和上游依赖版本。

## 第三方组件与许可证

本仓库同时包含原创数据、原创程序、第三方源码、Git 子模块和运行时依赖。根目录项目许可证不自动覆盖第三方组件。

完整清单见 [`NOTICE.md`](NOTICE.md)。其中：

- `pypinyin` 位于 `vendor/python/pypinyin/`，遵循上游 MIT 许可证；
- `tqdm` 位于 `vendor/python/tqdm/`，遵循其上游文件对应的 MPL-2.0 或 MIT 许可证；
- `rime-schema-compare` 及其 `vendor/` 子模块遵循各自上游许可证；
- `PySide6/Qt`、`ruamel.yaml`、`requests`、`PyYAML`、`python-dotenv`、PyInstaller 和 Chaquopy 是构建或运行依赖，发布二进制时应同时

### 鸣谢：
分词工具：具有多种编程语言变种的词典分词工具"[结巴分词](https://github.com/fxsjy/jieba)"

拼音标注：支持多种拼音标注类型的汉字转拼音工具"[python-pinyin](https://github.com/mozillazg/python-pinyin)"

### 友链：

一切皆可萌：[适合二次元爱好者的细胞词库](https://github.com/suiginko/moetype)

### 赞赏：
如果觉得项目好用，可以请AMZ喝咖啡

   <img src="https://github.com/amzxyz/rime-wanxiang/blob/wanxiang/custom/%E8%B5%9E%E8%B5%8F.jpg" width="400">

