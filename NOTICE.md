# 第三方组件与许可证声明

本文件记录 `https://github.com/amzxyz/rime-wanxiang-data` 中随项目源码、数据或发布包分发的第三方组件。
项目原创数据和代码的授权范围见 [`LICENSE-SCOPE.md`](LICENSE-SCOPE.md)。
第三方组件不因被复制到本仓库或被打包进发布物而改变其原许可证。

| 组件 | 仓库路径 | 来源 | 许可证/说明 |
|---|---|---|---|
| pypinyin | `vendor/python/pypinyin/` | [mozillazg/python-pinyin](https://github.com/mozillazg/python-pinyin)；当前源码声明版本 `0.53.0` | MIT |
| tqdm | `vendor/python/tqdm/` | [tqdm/tqdm](https://github.com/tqdm/tqdm) | 上游文件分别适用 MPL-2.0 或 MIT，随源码保留上游声明 |
| rime-schema-compare | `tools/benchmark/rime-schema-compare/` | [gaboolic/rime-schema-compare](https://github.com/gaboolic/rime-schema-compare) | 保留上游 NOTICE；当前仓库为源码快照，发布前应补充具体上游提交 |
| rime-frost | `tools/benchmark/rime-schema-compare/vendor/rime-frost` | [gaboolic/rime-frost](https://github.com/gaboolic/rime-frost) | 以子模块仓库许可证为准 |
| rime-ice | `tools/benchmark/rime-schema-compare/vendor/rime-ice` | [iDvel/rime-ice](https://github.com/iDvel/rime-ice) | 以子模块仓库许可证为准 |
| rime-wanxiang | `tools/benchmark/rime-schema-compare/vendor/rime_wanxiang` | [amzxyz/rime-wanxiang](https://github.com/amzxyz/rime-wanxiang) | 以子模块仓库许可证为准 |
| rime-wubi-sentence | `tools/benchmark/rime-schema-compare/vendor/rime-wubi-sentence` | [gaboolic/rime-wubi-sentence](https://github.com/gaboolic/rime-wubi-sentence) | 以子模块仓库许可证为准 |
| ruamel.yaml | 构建/运行依赖 | [yaml/ruamel.yaml](https://pypi.org/project/ruamel.yaml/) | MIT |
| requests | 构建/运行依赖 | [psf/requests](https://github.com/psf/requests) | Apache-2.0 |
| PyYAML | 评测依赖 | [yaml/pyyaml](https://github.com/yaml/pyyaml) | MIT |
| python-dotenv | 评测依赖 | [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) | BSD-3-Clause |
| PySide6 / Qt | 桌面程序运行时 | [Qt for Python](https://www.qt.io/qt-for-python) | 按使用的 LGPL/GPL 或商业许可证执行 |
| PyInstaller | 构建工具 | [pyinstaller/pyinstaller](https://github.com/pyinstaller/pyinstaller) | 以其上游许可证为准 |
| Chaquopy | Android 构建插件 | [chaquo.com](https://chaquo.com/chaquopy/) | 按项目使用版本的许可证和条款执行 |

