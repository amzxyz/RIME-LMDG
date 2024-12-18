## 重磅发布：基于32GB超大规模语料的RIME中文语言模型与词库构建
**——万象语言模型、万象原子词库**

### 项目简介
- 在庞大且多样的中文语料库基础上，我们构建了一个性能优异、覆盖面广的中文语言模型和高效的词库。此次发布的语言模型和词库构建，融合了来自社区问答、博文互动、公众号、百科词条、新闻报道、歌词、诗词文学、歇后语、绕口令、酒店外卖评论、法律文献、地区描述、文学作品以及诗词等多领域的内容，总体语料32G规模，更加均衡，清洗更加细致。该项目愿景：**致力于提供RIME最强基础底座，做最精准的读音标注、做最精准的词频统计、最恰当的分词词库以及基于现有条件打造了一个高命中率、精确的输入模型**；
- 同时项目中维护的单字拼音词典涵盖cjk基本区到扩展G区以及康熙部首区，基于汉典基础上手动维护更多读音，可能是单文本词库中比较全面的；
- 项目中的rime词库全部使用AI辅助筛选和人工校对，遴选出优质的词组。词库是全部带声调全拼，所有的词频是基于词组和拼音双键统计的，区别了如："那里 哪里" 这种类似场景下对于单字的词频，而不是全部归并到na的拼音下。单字词频是在词组语句中加上拼音最后拆解为单字及其对应拼音的组合，因此单字词频也是区分多音字的。 由于语料规模巨大，很多单字达到了10亿级别，词频经过对数归一化处理，缩短词频易于维护且文件储存更少的字节。如何迁移到你的方案？[点击迁移词库](https://github.com/amzxyz/RIME-LMDG/wiki/%E5%B0%86%E9%A3%9E%E5%A3%B0%E8%AF%8D%E5%BA%93%E8%BF%81%E7%A7%BB%E5%88%B0%E4%BD%A0%E7%9A%84%E9%A1%B9%E7%9B%AE)  

[模型下载](https://github.com/amzxyz/RIME-LMDG/releases)    |    [模型配置说明](https://github.com/amzxyz/RIME-LMDG/wiki/%E8%AF%AD%E8%A8%80%E6%A8%A1%E5%9E%8B%E5%8F%82%E6%95%B0%E9%85%8D%E7%BD%AE%E8%AF%B4%E6%98%8E)    |    [使用及构建教程详见](https://github.com/amzxyz/rime-build-grammar-word-frequency/wiki/%E4%BD%BF%E7%94%A8%E6%95%99%E7%A8%8B%EF%BC%9ARime-%E8%BE%93%E5%85%A5%E6%B3%95%E8%AF%AD%E8%A8%80%E6%A8%A1%E5%9E%8B%E6%9E%84%E5%BB%BA%E5%85%A8%E6%B5%81%E7%A8%8B)  

- 模型文件版本说明：v是版本号，n是模型级别，m是百兆尺寸
  
|文件大小|2级模型|3级模型|
|------|------|------|
|100M|v1n2m1|v1n3m1|
|200M|v1n2m2|v1n3m2|
|300M|v1n2m3|v1n3m3|

- 词库文件对应说明：

 示例项目：
 
  [万象拼音增强版-多维直接辅助码与任意拼音方案的组合](https://github.com/amzxyz/rime_wanxiang_pro)  |  [万象拼音基础版-全拼双拼间接辅助码版本](https://github.com/amzxyz/rime_wanxiang)   

| 词库类型 | 文件名称     | 描述                   |
|----------|--------------|------------------------|
| 大字表  | `large.dict`  | 包含CJK字库基础区所有具有读音的字，不计多音43324字|
| 基础词库   | `base.dict`  | 包含2-3字词组|
| 扩展词库 | `ext.dict` | 包含常用的词组    |
| 全字表 | `full.dict` | 包含CJK所有有字，汉字大全|

只需要将这一段内容放在方案文件，重新部署即可使用！

```
__include: octagram   #启用语言模型
#语言模型
octagram:
  __patch:
    grammar:
      language: amz-v2n3m1-zh-hans  
      collocation_max_length: 5
      collocation_min_length: 2
    translator/contextual_suggestions: true
    translator/max_homophones: 7
    translator/max_homographs: 7
```
