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

 [万象拼音-全拼双拼-声调辅助-反查辅助-中英混输](https://github.com/amzxyz/rime_wanxiang)   

| 词库类型 | 文件名称     | 描述                   |
|----------|--------------|------------------------|
| 字表  | `chars.dict`  | 包含CJK字库基础区所有具有读音的字，不计多音43324字|
| 基础词库   | `base.dict`  | 包含2-3字词组|
| 关联词库 | `correlation.dict` | 包含4字词组,不含由基础词库中同音最高频组合成的词汇|
| 联想词库 | `suggestion.dict` | 包含5字以上词组,当输入四个字之后形成联想候选|
| 兼容词库 | `compatible.dict` | 包含多音字词组,用于兼容词组的多种读音场景|
| 错音错字 | `corrections.dict` | 错音错字词组 ,用于兼容经常使用但是实际上在字、音是错的场景|


### 模型使用方法：
⚠️⚠️⚠️ 云插件和模型二者不可兼得，云插件会无差别占用翻译器特定长度的候选，因此就等于模型失效，所以使用云就放弃模型好了！

**软件**：小狼毫、鼠须管直接配置即可，fcitx5需要配合安装```librime-plugin-octagram```不同的Linux发行版包名可能不同

**参数**：
配置如下：

```
__include: octagram   #启用语法模型
#语法模型
octagram:
  __patch:
    grammar:
      language: wanxiang-lts-zh-hans
      collocation_max_length: 8         #命中的最长词组
      collocation_min_length: 3         #命中的最短词组，搭配词频健全的词库时候应当最小值设为3避开2字高频词
      collocation_penalty: -10          #默认-12 对常见搭配词组施加的惩罚值。较高的负值会降低这些搭配被选中的概率，防止过于频繁地出现某些固定搭配。
      non_collocation_penalty: -12      #默认-12 对非搭配词组施加的惩罚值。较高的负值会降低非搭配词组被选中的概率，避免不合逻辑或不常见的词组组合。
      weak_collocation_penalty: -24     #默认-24 对弱搭配词组施加的惩罚值。保持默认值通常是为了有效过滤掉不太常见但仍然合理的词组组合。
      rear_penalty: -30                 #默认-18 对词组中后续词语的位置施加的惩罚值。较高的负值会降低某些词语在句子后部出现的概率，防止句子结构不自然。
    translator/contextual_suggestions: false
    translator/max_homophones: 5
    translator/max_homographs: 5
```

### 词库脚本使用方法：

想要建立与万象一致的编码以及辅助码可以借助仓库两个脚本进行，文件名称已经表明了他的用途

首先保证python依赖的安装，下载release词库刷新工具包，解压到文件夹，在这个文件夹打开终端执行下面脚本

脚本打开后可以编辑参数，输入输出路径等编辑好保存，确保输出路径不存在同名文件避免被覆盖

“rime固定词典和用户词典刷新为带声调编码.py” 可以用于固定词库、细胞词库制作或者用户词库迁移；

“rime固定词典或者用户词典刷新为带辅助码的格式.py” 可以将你的词库刷新为携带辅助码的词库与wanxiang_pro一致的词库，需要注意的是，你可以直接使用单字表作为辅助码数据源，完成辅助码的刷新。

当然你也可以维护自己的辅助码，格式为：```你{tab}ab```，使用这样的数据源来作为辅助码数据源

以上两个脚本可以帮助你完成辅助码和注音，让你轻松建立与万象一致的词库

### 鸣谢：
分词工具：具有多种编程语言变种的词典分词工具"[结巴分词](https://github.com/fxsjy/jieba)"

拼音标注：支持多种拼音标注类型的汉字转拼音工具"[python-pinyin](https://github.com/mozillazg/python-pinyin)"

### 友链：

一切皆可萌：[适合二次元爱好者的细胞词库](https://github.com/suiginko/moetype)

### 赞赏：
如果觉得项目好用，可以请AMZ喝咖啡

   <img src="https://github.com/amzxyz/rime_wanxiang/blob/wanxiang/custom/%E8%B5%9E%E8%B5%8F.jpg" width="400">   

