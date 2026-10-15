# 开发说明

## 结构

Python 提供本机 HTTP 服务与素材处理，`ui/` 使用 HTML、CSS 和 JavaScript。`app_launcher.py` 通过 pywebview 创建桌面窗口，`desktop_pet.py` 使用 PySide6 / QML 提供取用精灵。

| 入口 | 职责 |
|---|---|
| `sprite_composer.py` | 素材扫描、合成、本机服务与基础接口 |
| `production_api.py` | 素材库、时间轴、配音和创作接口 |
| `rough_cut.py` | 粗剪项目与剪映草稿输出 |
| `gal_story.py`、`gal_story_render.py`、`gal_story_draft.py` | 剧情、画面预览与草稿生成 |
| `existing_draft.py`、`draft_video_tools.py` | 已有草稿校对、独立副本与素材修复 |
| `ai_subtitle_assistant.py`、`assistant_model.py` | 可选字幕任务与模型工具调用 |
| `local_tts.py`、`tts_bundle.py` | 外置配音组件接入 |

## 测试

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests
npm install
npx playwright install chromium
```

界面测试需要本机预览服务。以下预览使用合成素材和独立目录：

```powershell
.venv\Scripts\python.exe tools\production_preview.py --data-root 工作数据\preview
```

在另一个终端读取该目录的 `preview-url.txt`，将 URL 传给测试：

```powershell
node tests\ui_compact_shell.cjs http://127.0.0.1:端口/ 工作数据\shell-check
node tests\ui_guided_workspaces.cjs http://127.0.0.1:端口/ 工作数据\guided-check
```

测试通过 `BINGYI_PLAYWRIGHT` 和 `BINGYI_CHROME` 支持自定义依赖位置。`.js` 工作流片段由相应测试运行器调用；部分专项测试需要额外合成素材或指定输入，不直接读取个人工程。

## Windows 桌面与安装包

运行 `打包桌面版.bat` 安装固定版本依赖，生成 `dist/BingyiGalCreativeWorkshop`；再运行 `安装包制作.bat`，需要 Inno Setup 6。构建也可直接运行：

```powershell
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean BingyiGalCreativeWorkshop.spec
.venv\Scripts\python.exe tools\build_installer.py
```

主程序、取用精灵和兼容取用窗分别打包。工作数据、游戏素材、语音模型与外置配音组件不进入主软件包。FFmpeg 为外部依赖，不从开发机自动收入安装包。WebView2 引导程序的放置与安装行为见 `tools/build_installer.py`。

加密草稿适配目前支持已测试的剪映 7.2.2.53989 ABI，需要指定包含 `videoeditor.dll` 的安装目录。冻结版使用独立的工坊子进程，不要求另装 Python；外部 Python 可作为可选覆盖。语音识别仍需要单独准备 faster-whisper 环境和模型。

冻结版验收工具 `tools/verify_production_build.py` 使用隔离 APPDATA，生成合成草稿并检查依赖与取用精灵。不同剪映版本的最终画面、播放及保存重开，需要在剪映中验证。

