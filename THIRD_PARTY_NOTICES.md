# 第三方组件声明

本项目自有代码采用 [Apache-2.0](LICENSE)，第三方组件保留各自许可。

| 组件 | 版本 | 许可 |
|---|---|---|
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU |
| [PySide6 / shiboken6](https://www.qt.io/qt-for-python) | 6.11.2 | LGPL-3.0，另有商业授权 |
| [pywebview](https://github.com/r0x0r/pywebview) | 6.2.1 | BSD-3-Clause |
| [pythonnet](https://github.com/pythonnet/pythonnet) | 3.1.0 | MIT |
| [pyJianYingDraft](https://github.com/GuanYixuan/pyJianYingDraft) | 0.3.0 | Apache-2.0，全文见 [组件许可](licenses/pyJianYingDraft-LICENSE.txt) |
| [pymediainfo](https://github.com/sbraz/pymediainfo) | 7.0.1 | MIT，随包 MediaInfo 库采用 BSD-2-Clause |
| [imageio](https://github.com/imageio/imageio) | 2.38.0 | BSD-2-Clause |
| [NumPy](https://numpy.org/) | 2.2.6 | BSD-3-Clause |
| [uiautomation](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) | 2.0.29 | Apache-2.0 |
| [comtypes](https://github.com/enthought/comtypes) | 1.4.17 | MIT |

构建工具 PyInstaller 采用 GPL-2.0-or-later 及其打包例外；Inno Setup 采用修改版 BSD 许可。
Qt 动态库由桌面构建单独收集，Qt 与 PySide6 的许可仍适用于这些组件。
系统 FFmpeg 为可选外部程序，本仓库不分发其二进制文件。

可选本地配音通过独立进程和 HTTP 接入 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)，
上游采用 MIT，版权属于 RVC-Boss。组件附属库、模型与音色遵循各自授权。

历史 PBD 读取器来自 [YeLikesss/KrkrPbdStandViewer](https://github.com/YeLikesss/KrkrPbdStandViewer)，
采用 AGPL-3.0；历史版本授权保持不变。当前入口使用 `pbd_codec.py`，没有旧实现回退。
格式资料包括 BLAKE2、xxHash、LZ4、ChaCha8 测试向量和 xp3-brute 0.3.7 的格式描述；
来源与支持范围见 [PBD 格式说明](文档/PBD格式.md)。曾接触旧实现，不能宣称严格净室。

本仓库不提供游戏素材、模型或音色，本项目许可不授予这些内容的权利。
