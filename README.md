## 重磅发布：基于32GB超大规模语料的RIME中文语法模型与词库构建
**——万象语法模型、万象向量词库**      [![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/amzxyz/RIME-LMDG)

### 项目简介
- 在庞大且多样的中文语料库基础上，我们构建了一个性能优异、覆盖面广的中文语法模型和高效的词库。此次发布的语法模型和词库构建，融合了来自社区问答、博文互动、公众号、百科词条、新闻报道、歌词、诗词文学、歇后语、绕口令、酒店外卖评论、法律文献、地区描述、文学作品以及诗词等多领域的内容，总体语料32G规模，更加均衡，清洗更加细致。该项目愿景：**致力于提供RIME最强基础底座，做最精准的读音标注、做最精准的词频统计、最恰当的分词词库以及基于现有条件打造了一个高命中率、精确的输入模型。顺便为pypinyin维护出一个高质量拼音标注元数据库**；
- 同时项目中维护的单字拼音词典涵盖cjk基本区到扩展G区以及康熙部首区，基于汉典基础上手动维护更多读音，可能是单文本词库中比较全面的；
- 项目中的rime词库全部使用AI辅助筛选和人工校对，遴选出优质的词组。词库是全部带声调全拼，所有的词频是基于词组和拼音双键统计的，区别了如："那里 哪里" 这种类似场景下对于单字的词频，而不是全部归并到na的拼音下。单字词频是在词组语句中加上拼音最后拆解为单字及其对应拼音的组合，因此单字词频也是区分多音字的。 由于语料规模巨大，很多单字达到了10亿级别，词频经过对数归一化处理，缩短词频易于维护且文件储存更少的字节。如何迁移到你的方案？[点击迁移词库](https://github.com/amzxyz/RIME-LMDG/wiki/%E5%B0%86%E4%B8%87%E8%B1%A1%E8%AF%8D%E5%BA%93%E8%BF%81%E7%A7%BB%E5%88%B0%E4%BD%A0%E7%9A%84%E9%A1%B9%E7%9B%AE)
- **万象词库中的带声调拼音标注+词组构成+词频是整个万象项目的核心，是使用体验的基石，方案的其它功能皆可自定义，我希望使用者可以基于词库+转写的方式获得输入体验** [万象词库问题收集反馈表](https://docs.qq.com/smartsheet/DWHZsdnZZaGh5bWJI?viewId=vUQPXH&tab=BB08J2)
- [关于声调标注的修正你可以PR到该文件，制表符分隔](https://github.com/amzxyz/RIME-LMDG/blob/main/pinyin_data/%E8%AF%8D%E7%BB%84.dict.yaml)

[模型下载](https://github.com/amzxyz/RIME-LMDG/releases)    |    [模型配置说明](https://github.com/amzxyz/RIME-LMDG/wiki/%E8%AF%AD%E8%A8%80%E6%A8%A1%E5%9E%8B%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%AF%B4%E6%98%8E)    |    [构建教程](https://github.com/amzxyz/rime-build-grammar-word-frequency/wiki/%E4%BD%BF%E7%94%A8%E6%95%99%E7%A8%8B%EF%BC%9ARime-%E8%BE%93%E5%85%A5%E6%B3%95%E8%AF%AD%E8%A8%80%E6%A8%A1%E5%9E%8B%E6%9E%84%E5%BB%BA%E5%85%A8%E6%B5%81%E7%A8%8B)  

- 词库文件对应说明：

 示例项目：

 [万象拼音-全拼双拼-声调辅助-反查辅助-中英混输](https://github.com/amzxyz/rime-wanxiang)   

| 词库类型 | 文件名称     | 描述                   |
|----------|--------------|------------------------|
| 字表  | `zi.dict`  | 包含CJK字库基础区所有具有读音的字，不计多音43324字|
| 基础词库   | `jichu.dict`  | 包含2-4字词组，保证一个基础体验，值得保留读音的、需要多候选的|
| 联想词库 | `lianxiang.dict` | 包含5字以上词组,大部分可拆分组合已经进了模型留下的都稍显特殊，当他们聚集在一起有时候看起来没那么有用|
| 兼容词库 | `duoyin.dict` | 包含多音字词组,用于兼容词组的多种读音场景|
| 错音错字 | `cuoyin.dict` | 错音错字词组 ,用于兼容经常使用但是实际上在字、音是错的场景|


### 语法模型

Gram 是最适合输入法的模型类型。在 Rime 中，它类似词库，但更灵活：能基于已有“材料”（如“住在”“礼物1”“里屋2”）动态组合出“住在礼物”片段。传统做法依赖词库硬编码“住在里屋”，即便 500 万词也难覆盖全，且检索依赖编码分段翻译，易卡顿。

使用 Gram 可跳出词库维护的深坑——专业领域词库易得，日常用语却难以全面。一个语句流模型能省去大量人工维护。它基于 C++ 前缀树扫描，内存中仅映射一块区域，无需加载到内存，速度极快，因此可部署于翻译器阶段。这与所谓的智能模型完全不同，即消耗算力，又不能用于翻译器阶段，只能依赖UI搞延迟上屏，这个体验完全不如，有范围的穷举广覆盖。

大模型时代不应单纯拒绝“大”，否则将错失巨大助力。


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
      collocation_min_length: 3
      collocation_penalty: -14
      non_collocation_penalty: -6
      weak_collocation_penalty: -100
      rear_penalty: -20
    translator/contextual_suggestions: false
    translator/max_homophones: 8
```

### 词库处理方法：

使用万象工具箱操作，一看就懂，支持刷拼音、刷辅助码、转换简码、用户词库提炼等功能

### 鸣谢：
分词工具：具有多种编程语言变种的词典分词工具"[结巴分词](https://github.com/fxsjy/jieba)"

拼音标注：支持多种拼音标注类型的汉字转拼音工具"[python-pinyin](https://github.com/mozillazg/python-pinyin)"

### 友链：

一切皆可萌：[适合二次元爱好者的细胞词库](https://github.com/suiginko/moetype)

### 赞赏：
如果觉得项目好用，可以请AMZ喝咖啡

   <img src="https://github.com/amzxyz/rime-wanxiang/blob/wanxiang/custom/%E8%B5%9E%E8%B5%8F.jpg" width="400">   

