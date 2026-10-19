# Rime 评测结果

- 生成时间: 2026-04-21 20:18:52 +08:00
- 来源文件: `benchmark_all_corpus_20260421T121742Z_report.txt`

## Vendor 子模块版本

- `vendor/rime-frost`: `84878b8c6b2e2fdc4f11698ec236402ef57ac1fa`
- `vendor/rime-ice`: `2bd2983c6c74ea49b3a013f150ade7f3b8a27515`
- `vendor/rime_wanxiang` (`wanxiang`): `6299415ad5ebd203df5e8d9bc9c6a9929d4806d6`
- `vendor/rime-wubi-sentence`: `c3b26af601e41de49227f86633df00985e8d8a77`

## 评测摘要

```text
========================================================================
Rime 多方案整句评测 — 摘要报告
========================================================================
生成时间 (UTC): 20260421T121742Z
rime.dll: D:\vscode\rime_projs\rime-schema-compare\lib\rime.dll
模式: 全部语料 (data/corpus/*.txt)

语料文件:
  - news: D:\vscode\rime_projs\rime-schema-compare\data\corpus\news.txt
  - novel: D:\vscode\rime_projs\rime-schema-compare\data\corpus\novel.txt
  - prose: D:\vscode\rime_projs\rime-schema-compare\data\corpus\prose.txt
  - tech: D:\vscode\rime_projs\rime-schema-compare\data\corpus\tech.txt
  - test: D:\vscode\rime_projs\rime-schema-compare\data\corpus\test.txt

【总体】
  [mingyuepinyin]
    句子正确率: 49.59%  (122/246 句完全匹配)
    文字正确率: 89.83%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 89.87%

  [mingyuepinyin_with_gram]
    句子正确率: 36.99%  (91/246 句完全匹配)
    文字正确率: 86.15%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 86.18%

  [rime_ice]
    句子正确率: 59.35%  (146/246 句完全匹配)
    文字正确率: 92.28%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 92.67%

  [rime_ice_with_gram]
    句子正确率: 64.23%  (158/246 句完全匹配)
    文字正确率: 94.23%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 94.38%

  [rime_frost]
    句子正确率: 54.47%  (134/246 句完全匹配)
    文字正确率: 90.76%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 90.79%

  [rime_frost_with_gram]
    句子正确率: 68.7%  (169/246 句完全匹配)
    文字正确率: 94.91%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 94.98%

  [wanxiang]
    句子正确率: 47.97%  (118/246 句完全匹配)
    文字正确率: 88.78%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 89.06%

  [rime_wanxiang_with_gram]
    句子正确率: 66.67%  (164/246 句完全匹配)
    文字正确率: 94.84%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 94.79%

  [rime_wubi_sentens_wubi86]
    句子正确率: 50.41%  (124/246 句完全匹配)
    文字正确率: 91.09%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 91.36%

  [rime_wubi_sentens_wubi86_with_gram]
    句子正确率: 69.92%  (172/246 句完全匹配)
    文字正确率: 95.85%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 95.93%

------------------------------------------------------------------------
【语料: news】
  [mingyuepinyin]
    句子正确率: 58.33%  (21/36 句完全匹配)
    文字正确率: 91.27%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 92.24%

  [mingyuepinyin_with_gram]
    句子正确率: 47.22%  (17/36 句完全匹配)
    文字正确率: 84.23%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 84.82%

  [rime_ice]
    句子正确率: 91.67%  (33/36 句完全匹配)
    文字正确率: 98.87%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 98.74%

  [rime_ice_with_gram]
    句子正确率: 88.89%  (32/36 句完全匹配)
    文字正确率: 97.18%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 97.54%

  [rime_frost]
    句子正确率: 69.44%  (25/36 句完全匹配)
    文字正确率: 93.24%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 94.17%

  [rime_frost_with_gram]
    句子正确率: 88.89%  (32/36 句完全匹配)
    文字正确率: 97.46%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 97.98%

  [wanxiang]
    句子正确率: 72.22%  (26/36 句完全匹配)
    文字正确率: 91.55%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 93.03%

  [rime_wanxiang_with_gram]
    句子正确率: 86.11%  (31/36 句完全匹配)
    文字正确率: 96.9%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 97.27%

  [rime_wubi_sentens_wubi86]
    句子正确率: 50.0%  (18/36 句完全匹配)
    文字正确率: 91.27%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 91.94%

  [rime_wubi_sentens_wubi86_with_gram]
    句子正确率: 80.56%  (29/36 句完全匹配)
    文字正确率: 96.34%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 96.54%

------------------------------------------------------------------------
【语料: novel】
  [mingyuepinyin]
    句子正确率: 44.12%  (60/136 句完全匹配)
    文字正确率: 87.83%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 87.93%

  [mingyuepinyin_with_gram]
    句子正确率: 36.76%  (50/136 句完全匹配)
    文字正确率: 87.28%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 86.88%

  [rime_ice]
    句子正确率: 50.74%  (69/136 句完全匹配)
    文字正确率: 90.66%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 91.02%

  [rime_ice_with_gram]
    句子正确率: 62.5%  (85/136 句完全匹配)
    文字正确率: 93.85%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 93.96%

  [rime_frost]
    句子正确率: 47.79%  (65/136 句完全匹配)
    文字正确率: 88.45%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 88.32%

  [rime_frost_with_gram]
    句子正确率: 65.44%  (89/136 句完全匹配)
    文字正确率: 94.05%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 94.15%

  [wanxiang]
    句子正确率: 44.12%  (60/136 句完全匹配)
    文字正确率: 88.66%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 88.6%

  [rime_wanxiang_with_gram]
    句子正确率: 63.97%  (87/136 句完全匹配)
    文字正确率: 94.26%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 94.21%

  [rime_wubi_sentens_wubi86]
    句子正确率: 50.74%  (69/136 句完全匹配)
    文字正确率: 91.01%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 91.28%

  [rime_wubi_sentens_wubi86_with_gram]
    句子正确率: 64.71%  (88/136 句完全匹配)
    文字正确率: 94.67%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 94.83%

------------------------------------------------------------------------
【语料: prose】
  [mingyuepinyin]
    句子正确率: 44.74%  (17/38 句完全匹配)
    文字正确率: 90.65%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 90.83%

  [mingyuepinyin_with_gram]
    句子正确率: 23.68%  (9/38 句完全匹配)
    文字正确率: 84.76%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 84.9%

  [rime_ice]
    句子正确率: 52.63%  (20/38 句完全匹配)
    文字正确率: 90.04%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 91.56%

  [rime_ice_with_gram]
    句子正确率: 39.47%  (15/38 句完全匹配)
    文字正确率: 91.67%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 91.61%

  [rime_frost]
    句子正确率: 42.11%  (16/38 句完全匹配)
    文字正确率: 90.04%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 90.5%

  [rime_frost_with_gram]
    句子正确率: 50.0%  (19/38 句完全匹配)
    文字正确率: 93.5%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 93.43%

  [wanxiang]
    句子正确率: 34.21%  (13/38 句完全匹配)
    文字正确率: 84.55%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 84.21%

  [rime_wanxiang_with_gram]
    句子正确率: 47.37%  (18/38 句完全匹配)
    文字正确率: 93.5%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 93.29%

  [rime_wubi_sentens_wubi86]
    句子正确率: 47.37%  (18/38 句完全匹配)
    文字正确率: 90.65%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 91.81%

  [rime_wubi_sentens_wubi86_with_gram]
    句子正确率: 63.16%  (24/38 句完全匹配)
    文字正确率: 96.54%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 96.67%

------------------------------------------------------------------------
【语料: tech】
  [mingyuepinyin]
    句子正确率: 70.97%  (22/31 句完全匹配)
    文字正确率: 94.23%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 93.89%

  [mingyuepinyin_with_gram]
    句子正确率: 38.71%  (12/31 句完全匹配)
    文字正确率: 84.62%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 84.93%

  [rime_ice]
    句子正确率: 67.74%  (21/31 句完全匹配)
    文字正确率: 95.43%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 95.64%

  [rime_ice_with_gram]
    句子正确率: 67.74%  (21/31 句完全匹配)
    文字正确率: 95.19%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 95.02%

  [rime_frost]
    句子正确率: 74.19%  (23/31 句完全匹配)
    文字正确率: 96.15%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 96.58%

  [rime_frost_with_gram]
    句子正确率: 77.42%  (24/31 句完全匹配)
    文字正确率: 96.63%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 96.23%

  [wanxiang]
    句子正确率: 58.06%  (18/31 句完全匹配)
    文字正确率: 93.27%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 93.91%

  [rime_wanxiang_with_gram]
    句子正确率: 74.19%  (23/31 句完全匹配)
    文字正确率: 95.91%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 95.47%

  [rime_wubi_sentens_wubi86]
    句子正确率: 58.06%  (18/31 句完全匹配)
    文字正确率: 92.79%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 91.73%

  [rime_wubi_sentens_wubi86_with_gram]
    句子正确率: 87.1%  (27/31 句完全匹配)
    文字正确率: 98.56%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 98.79%

------------------------------------------------------------------------
【语料: test】
  [mingyuepinyin]
    句子正确率: 40.0%  (2/5 句完全匹配)
    文字正确率: 92.06%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 93.13%

  [mingyuepinyin_with_gram]
    句子正确率: 60.0%  (3/5 句完全匹配)
    文字正确率: 92.06%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 94.36%

  [rime_ice]
    句子正确率: 60.0%  (3/5 句完全匹配)
    文字正确率: 88.89%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 84.16%

  [rime_ice_with_gram]
    句子正确率: 100.0%  (5/5 句完全匹配)
    文字正确率: 100.0%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 100.0%

  [rime_frost]
    句子正确率: 100.0%  (5/5 句完全匹配)
    文字正确率: 100.0%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 100.0%

  [rime_frost_with_gram]
    句子正确率: 100.0%  (5/5 句完全匹配)
    文字正确率: 100.0%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 100.0%

  [wanxiang]
    句子正确率: 20.0%  (1/5 句完全匹配)
    文字正确率: 79.37%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 79.67%

  [rime_wanxiang_with_gram]
    句子正确率: 100.0%  (5/5 句完全匹配)
    文字正确率: 100.0%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 100.0%

  [rime_wubi_sentens_wubi86]
    句子正确率: 20.0%  (1/5 句完全匹配)
    文字正确率: 84.13%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 83.58%

  [rime_wubi_sentens_wubi86_with_gram]
    句子正确率: 80.0%  (4/5 句完全匹配)
    文字正确率: 96.83%  (全语料金文加权，基于 Levenshtein)
    文字正确率(逐句平均): 97.89%

========================================================================
【总耗时】全流程墙钟约 70033.61 ms（多语料）

【各语料耗时】
  · news
    读取文件: 0.14 ms
    分句: 0.16 ms
    预过滤: 0.83 ms
    [mingyuepinyin] 输入串: 2.08 ms, librime 加载: 342.11 ms, 开会话+选方案: 38.28 ms, 逐句解码: 107.1 ms
    [mingyuepinyin_with_gram] 输入串: 2.1 ms, librime 加载: 388.62 ms, 开会话+选方案: 53.88 ms, 逐句解码: 246.5 ms
    [rime_frost] 输入串: 1.9 ms, librime 加载: 598.19 ms, 开会话+选方案: 56.16 ms, 逐句解码: 558.43 ms
    [rime_frost_with_gram] 输入串: 2.1 ms, librime 加载: 598.37 ms, 开会话+选方案: 54.62 ms, 逐句解码: 591.36 ms
    [rime_ice] 输入串: 1.96 ms, librime 加载: 1103.54 ms, 开会话+选方案: 32.34 ms, 逐句解码: 103.2 ms
    [rime_ice_with_gram] 输入串: 1.91 ms, librime 加载: 1098.92 ms, 开会话+选方案: 31.19 ms, 逐句解码: 111.59 ms
    [rime_wanxiang_with_gram] 输入串: 2.1 ms, librime 加载: 360.09 ms, 开会话+选方案: 1292.91 ms, 逐句解码: 961.08 ms
    [rime_wubi_sentens_wubi86] 输入串: 78.96 ms, librime 加载: 826.26 ms, 开会话+选方案: 377.33 ms, 逐句解码: 97.14 ms
    [rime_wubi_sentens_wubi86_with_gram] 输入串: 79.11 ms, librime 加载: 803.41 ms, 开会话+选方案: 410.9 ms, 逐句解码: 108.19 ms
    [wanxiang] 输入串: 1.85 ms, librime 加载: 363.54 ms, 开会话+选方案: 1232.02 ms, 逐句解码: 953.95 ms
  · novel
    读取文件: 0.19 ms
    分句: 0.45 ms
    预过滤: 0.37 ms
    [mingyuepinyin] 输入串: 7.18 ms, librime 加载: 330.08 ms, 开会话+选方案: 22.66 ms, 逐句解码: 210.1 ms
    [mingyuepinyin_with_gram] 输入串: 7.63 ms, librime 加载: 345.83 ms, 开会话+选方案: 24.58 ms, 逐句解码: 365.93 ms
    [rime_frost] 输入串: 7.41 ms, librime 加载: 585.38 ms, 开会话+选方案: 65.16 ms, 逐句解码: 1765.57 ms
    [rime_frost_with_gram] 输入串: 7.3 ms, librime 加载: 599.04 ms, 开会话+选方案: 54.45 ms, 逐句解码: 1810.63 ms
    [rime_ice] 输入串: 7.44 ms, librime 加载: 1069.25 ms, 开会话+选方案: 34.17 ms, 逐句解码: 253.73 ms
    [rime_ice_with_gram] 输入串: 7.02 ms, librime 加载: 1079.52 ms, 开会话+选方案: 26.2 ms, 逐句解码: 286.72 ms
    [rime_wanxiang_with_gram] 输入串: 8.27 ms, librime 加载: 380.67 ms, 开会话+选方案: 1268.23 ms, 逐句解码: 2223.52 ms
    [rime_wubi_sentens_wubi86] 输入串: 22.09 ms, librime 加载: 821.33 ms, 开会话+选方案: 388.34 ms, 逐句解码: 345.13 ms
    [rime_wubi_sentens_wubi86_with_gram] 输入串: 27.44 ms, librime 加载: 839.59 ms, 开会话+选方案: 420.12 ms, 逐句解码: 375.43 ms
    [wanxiang] 输入串: 7.77 ms, librime 加载: 360.25 ms, 开会话+选方案: 1283.53 ms, 逐句解码: 2184.29 ms
  · prose
    读取文件: 0.18 ms
    分句: 0.12 ms
    预过滤: 0.09 ms
    [mingyuepinyin] 输入串: 2.61 ms, librime 加载: 372.8 ms, 开会话+选方案: 29.96 ms, 逐句解码: 71.49 ms
    [mingyuepinyin_with_gram] 输入串: 2.55 ms, librime 加载: 317.73 ms, 开会话+选方案: 24.84 ms, 逐句解码: 157.29 ms
    [rime_frost] 输入串: 2.64 ms, librime 加载: 597.89 ms, 开会话+选方案: 54.87 ms, 逐句解码: 495.3 ms
    [rime_frost_with_gram] 输入串: 2.64 ms, librime 加载: 588.95 ms, 开会话+选方案: 58.77 ms, 逐句解码: 491.42 ms
    [rime_ice] 输入串: 2.76 ms, librime 加载: 1070.43 ms, 开会话+选方案: 28.29 ms, 逐句解码: 87.01 ms
    [rime_ice_with_gram] 输入串: 2.71 ms, librime 加载: 1074.49 ms, 开会话+选方案: 26.51 ms, 逐句解码: 101.61 ms
    [rime_wanxiang_with_gram] 输入串: 2.71 ms, librime 加载: 387.21 ms, 开会话+选方案: 1301.84 ms, 逐句解码: 630.88 ms
    [rime_wubi_sentens_wubi86] 输入串: 6.09 ms, librime 加载: 828.38 ms, 开会话+选方案: 372.84 ms, 逐句解码: 128.7 ms
    [rime_wubi_sentens_wubi86_with_gram] 输入串: 6.02 ms, librime 加载: 830.45 ms, 开会话+选方案: 389.41 ms, 逐句解码: 146.21 ms
    [wanxiang] 输入串: 2.91 ms, librime 加载: 372.32 ms, 开会话+选方案: 1275.87 ms, 逐句解码: 604.42 ms
  · tech
    读取文件: 0.2 ms
    分句: 0.2 ms
    预过滤: 0.08 ms
    [mingyuepinyin] 输入串: 2.17 ms, librime 加载: 355.6 ms, 开会话+选方案: 27.61 ms, 逐句解码: 40.32 ms
    [mingyuepinyin_with_gram] 输入串: 2.12 ms, librime 加载: 317.8 ms, 开会话+选方案: 12.89 ms, 逐句解码: 111.22 ms
    [rime_frost] 输入串: 2.22 ms, librime 加载: 585.49 ms, 开会话+选方案: 65.05 ms, 逐句解码: 394.74 ms
    [rime_frost_with_gram] 输入串: 2.15 ms, librime 加载: 603.05 ms, 开会话+选方案: 58.61 ms, 逐句解码: 394.43 ms
    [rime_ice] 输入串: 2.3 ms, librime 加载: 1062.82 ms, 开会话+选方案: 29.91 ms, 逐句解码: 69.09 ms
    [rime_ice_with_gram] 输入串: 2.35 ms, librime 加载: 1097.45 ms, 开会话+选方案: 37.58 ms, 逐句解码: 79.88 ms
    [rime_wanxiang_with_gram] 输入串: 2.13 ms, librime 加载: 370.96 ms, 开会话+选方案: 1273.81 ms, 逐句解码: 421.4 ms
    [rime_wubi_sentens_wubi86] 输入串: 5.23 ms, librime 加载: 816.7 ms, 开会话+选方案: 384.22 ms, 逐句解码: 129.54 ms
    [rime_wubi_sentens_wubi86_with_gram] 输入串: 5.25 ms, librime 加载: 827.69 ms, 开会话+选方案: 385.91 ms, 逐句解码: 134.0 ms
    [wanxiang] 输入串: 2.14 ms, librime 加载: 368.03 ms, 开会话+选方案: 1278.76 ms, 逐句解码: 392.2 ms
  · test
    读取文件: 0.12 ms
    分句: 0.02 ms
    预过滤: 0.02 ms
    [mingyuepinyin] 输入串: 0.41 ms, librime 加载: 366.43 ms, 开会话+选方案: 16.96 ms, 逐句解码: 8.18 ms
    [mingyuepinyin_with_gram] 输入串: 0.4 ms, librime 加载: 336.12 ms, 开会话+选方案: 22.83 ms, 逐句解码: 35.8 ms
    [rime_frost] 输入串: 0.38 ms, librime 加载: 602.45 ms, 开会话+选方案: 79.82 ms, 逐句解码: 60.79 ms
    [rime_frost_with_gram] 输入串: 0.4 ms, librime 加载: 586.95 ms, 开会话+选方案: 56.49 ms, 逐句解码: 63.1 ms
    [rime_ice] 输入串: 0.4 ms, librime 加载: 1059.48 ms, 开会话+选方案: 27.31 ms, 逐句解码: 23.77 ms
    [rime_ice_with_gram] 输入串: 0.38 ms, librime 加载: 1070.68 ms, 开会话+选方案: 38.37 ms, 逐句解码: 25.81 ms
    [rime_wanxiang_with_gram] 输入串: 0.39 ms, librime 加载: 369.56 ms, 开会话+选方案: 1252.98 ms, 逐句解码: 67.9 ms
    [rime_wubi_sentens_wubi86] 输入串: 1.0 ms, librime 加载: 837.04 ms, 开会话+选方案: 364.77 ms, 逐句解码: 22.48 ms
    [rime_wubi_sentens_wubi86_with_gram] 输入串: 0.97 ms, librime 加载: 835.57 ms, 开会话+选方案: 390.09 ms, 逐句解码: 25.51 ms
    [wanxiang] 输入串: 0.41 ms, librime 加载: 366.14 ms, 开会话+选方案: 1293.47 ms, 逐句解码: 65.03 ms

========================================================================
同义词归一化（句级完全匹配与 CER 计算前）: 其它→其他；他/她/它→他；的/地/得→的

说明: 分句后仅「纯汉字」且不含 ASCII 数字/英文字母、汉字不少于 5 字的片段参与评测；其它片段已过滤。句子正确率 = 归一化后预测与金句完全一致的比例；文字正确率 = 全语料 (归一化后总字数−总编辑距离)/归一化后总字数。输入串按各 vendor 自身配置生成，可能是连续拼音，也可能是形码前缀串。
```

