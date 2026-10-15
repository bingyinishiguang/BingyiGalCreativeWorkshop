# 冰翼Gal创作工坊

一个运行在 Windows 上的本地 Galgame 素材与视频创作工具，仍在开发中。

- 合成立绘，管理立绘、背景、视频与音频素材。
- 导入剧情，安排人物、表情、对白、配音与 BGM，生成可继续编辑的剪映草稿。
- 校对已有剪映草稿的字幕，调整样式、修复素材路径，直接保存新草稿或备份后干净覆盖。
- 将日语原稿与中文对照稿按语义匹配，使用本地识别的词级时间安排字幕，沿用草稿示例的人物立绘格式。
- 按需接入语音识别、翻译、聊天模型和外置配音组件。
- 使用取用精灵浏览立绘并拖入剪辑软件。

源码运行需要 Windows、Python 3.11 以上：

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.\启动冰翼Gal创作工坊.bat
```

首次打开可在合成工作台导入素材包，或进入工具箱选择制作流程。剧情生成器提供原创示例短剧；游戏素材、音色和模型需自行准备。

MP4 预览与部分音视频处理需要可从 PATH 调用的 FFmpeg / FFprobe。思源字体为可选；未安装时剧情使用 Windows 中文字体。配音与 AI 服务均可选，模型不会自动下载。

源码版默认将数据保存在项目的 `工作数据` 中；桌面安装版使用 `%APPDATA%\BingyiGalCreativeWorkshop`。密钥与工作数据不提交到公开仓库。

使用说明：[剧情生成器](文档/Galgame剧情生成器.md)、[字幕助手](文档/AI字幕助手.md)、[素材配音与人物](文档/素材配音与人物工作流.md)、[剪映草稿工作流](docs/剪映草稿工作流.md)、[素材包格式](文档/素材包格式.md)。

开发、测试与打包见 [开发说明](DEVELOPMENT.md)。

代码采用 [Apache-2.0](LICENSE)。第三方声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
