"""Qt Quick 立绘取用精灵与总览窗口，提供原生 PNG 拖放。"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import uuid
from pathlib import Path

from sprite_library import SpriteLibrary
import app_paths
import time

#使用 Basic 样式以支持自定义控件，生产与测试保持一致。
QT_QUICK_CONTROLS_STYLE = "Basic"


def _pet_log(message: str) -> None:
    """向启动日志追加取用精灵状态；失败不影响运行。"""
    try:
        from datetime import datetime
        log_path = app_paths.resolve_data_dir() / app_paths.STARTUP_LOG_NAME
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[pet {datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
    except Exception:
        pass


def apply_render_backend(app) -> str:
    """按配置选择 Qt Quick 渲染后端；默认软件渲染以兼容多显示器。"""
    forced = (os.environ.get("BGW_QT_BACKEND") or "").strip().lower()
    if forced:
        os.environ["QSG_RHI_BACKEND"] = forced
        _pet_log(f"渲染后端：由 BGW_QT_BACKEND 强制为 {forced}")
        return forced

    hardware_ok = False
    detail = ""
    try:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext

        context = QOpenGLContext()
        if context.create():
            surface = QOffscreenSurface()
            surface.create()
            hardware_ok = bool(context.makeCurrent(surface))
            detail = "OpenGL 上下文可用"
            context.doneCurrent()
        else:
            detail = "无法创建 OpenGL 上下文"
    except Exception as error:  #缺 DLL / 驱动异常都归到这里
        detail = f"探测显卡失败：{type(error).__name__}: {error}"

    if hardware_ok:
        _pet_log(f"渲染后端：硬件加速（{detail}）")
        return "hardware"

    os.environ["QSG_RHI_BACKEND"] = "software"
    try:
        from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
    except Exception as error:
        _pet_log(f"切换软件渲染时出错（继续尝试）：{error}")
    _pet_log(f"渲染后端：自动退回软件渲染（{detail}）")
    return "software"


def apply_qml_style() -> str:
    """在加载任何 QML 之前固定 Quick Controls 样式，返回实际使用的样式名。"""
    from PySide6.QtQuickControls2 import QQuickStyle

    QQuickStyle.setStyle(QT_QUICK_CONTROLS_STYLE)
    return QT_QUICK_CONTROLS_STYLE


PET_SIZES = {
    "S": (160, 230),
    "M": (240, 345),
    "L": (320, 460),
}
PET_SIZE_ORDER = tuple(PET_SIZES)
GALLERY_PAGE_SIZE = 60


#纯逻辑：立绘切换顺序与窗口状态

def build_roster(library: SpriteLibrary, search: str = "", favorites: bool = False,
                 limit: int = 10000) -> list[dict]:
    """按图库排序返回普通分区中仍存在的图片，不修改图库。"""
    result = library.list(False, search=(search or "").strip()[:100],
                          favorite=favorites, limit=limit)
    return [item for item in result["items"] if not item.get("missing")]


def build_gallery_page(library: SpriteLibrary, search: str = "", favorites: bool = False,
                       offset: int = 0, limit: int = GALLERY_PAGE_SIZE,
                       tag: str = "", game: str = "", character: str = "") -> dict:
    """按原始游标分页，跳过丢失图片；图片解码交给 Qt 异步处理。"""
    safe_offset = max(0, int(offset))
    page_limit = max(1, min(int(limit), 100))
    result = library.list(False, search=(search or "").strip()[:100],
                          game=(game or "").strip()[:150],
                          character=(character or "").strip()[:150],
                          tag=(tag or "").strip()[:30],
                          favorite=bool(favorites), limit=page_limit,
                          offset=safe_offset)
    items = []
    for item in result["items"]:
        if item.get("missing"):
            continue
        thumb = library.thumbnail_path(item["id"])
        if thumb.is_file():
            image_path = thumb
        else:
            path = library.file(item["id"], False)
            if path is None:
                continue
            image_path = path
        items.append({"item": item, "imagePath": image_path})
    raw_fetched = len(result["items"])
    has_more = raw_fetched == page_limit
    next_offset = safe_offset + raw_fetched
    return {"items": items, "hasMore": has_more, "nextOffset": next_offset,
            "total": result["total"], "offset": safe_offset, "limit": page_limit,
            "tags": result.get("tags") or [], "games": result.get("games") or [],
            "characters": result.get("characters") or [],
            #作品与角色筛选相互约束，可选项来自同一次图库查询。
            "scopedGames": result.get("scopedGames") or [],
            "gameCharacters": result.get("gameCharacters") or {}}


def cycle_index(length: int, current: int, step: int) -> int:
    """在长度为 length 的列表里从 current 前进 step 位，首尾循环。"""
    if length <= 0:
        return -1
    return (current + step) % length


def _sanitize_rect(value: object) -> dict | None:
    """检查窗口尺寸与有限坐标；无效几何返回 None。"""
    if not isinstance(value, dict):
        return None
    try:
        x, y = int(value["x"]), int(value["y"])
        width, height = int(value["width"]), int(value["height"])
    except (KeyError, TypeError, ValueError, OverflowError):
        #将非有限几何视为无效值，兼容 int(inf) 的 OverflowError。
        return None
    if not (280 <= width <= 2000 and 360 <= height <= 2000):
        return None
    if abs(x) > 20000 or abs(y) > 20000:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def next_index(length: int, current: int) -> int:
    return cycle_index(length, current, 1)


def prev_index(length: int, current: int) -> int:
    return cycle_index(length, current, -1)


def clamp_to_area(x: int, y: int, width: int, height: int,
                  area_x: int, area_y: int, area_w: int, area_h: int) -> tuple[int, int]:
    """把窗口左上角坐标夹紧到可用屏幕区域内，保证不会在多显示器或
        不同缩放比例下完全跑出屏幕。"""
    max_x = area_x + max(0, area_w - width)
    max_y = area_y + max(0, area_h - height)
    clamped_x = min(max(x, area_x), max_x)
    clamped_y = min(max(y, area_y), max_y)
    return clamped_x, clamped_y


def default_pet_position(width: int, height: int, area_x: int, area_y: int,
                         area_w: int, area_h: int) -> tuple[int, int]:
    """计算首次出现位置：工作区右侧偏下，并避开任务栏。"""
    right_margin = min(48, max(24, round(area_w * 0.02)))
    x = area_x + area_w - width - right_margin
    y = area_y + round(area_h * 0.62)
    y = min(y, area_y + area_h - height - 16)
    return clamp_to_area(x, y, width, height, area_x, area_y, area_w, area_h)


def gallery_window_position(pet_x: int, pet_y: int, pet_w: int, pet_h: int,
                            gallery_w: int, gallery_h: int, area_x: int, area_y: int,
                            area_w: int, area_h: int, gap: int = 14) -> tuple[int, int]:
    """对齐总览与桌宠中心，并将窗口限制在可用屏幕区域。"""
    x = pet_x + pet_w // 2 - gallery_w // 2
    y = pet_y + pet_h // 2 - gallery_h // 2
    return clamp_to_area(x, y, gallery_w, gallery_h,
                         area_x + 10, area_y + 10,
                         max(0, area_w - 20), max(0, area_h - 20))


def cycle_size_tier(current: str) -> str:
    """S → M → L → S 循环，无效值回到默认 M。"""
    if current not in PET_SIZE_ORDER:
        return "M"
    return PET_SIZE_ORDER[(PET_SIZE_ORDER.index(current) + 1) % len(PET_SIZE_ORDER)]


def size_tier_label(tier: str) -> str:
    """档位的中文名（托盘菜单与状态提示共用，避免两处各写一份）。"""
    return {"S": "小", "M": "中", "L": "大"}.get(tier, tier)


def tier_for_size(width: int, height: int) -> str | None:
    """按像素尺寸匹配档位；自定义尺寸返回 None。"""
    for name, (w, h) in PET_SIZES.items():
        if int(width) == w and int(height) == h:
            return name
    return None


class DesktopPetState:
    """以原子写入保存位置、尺寸档位和当前立绘。"""

    DEFAULT_TIER = "M"
    DEFAULT_WIDTH, DEFAULT_HEIGHT = PET_SIZES[DEFAULT_TIER]

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.file = self.data_dir / app_paths.PET_STATE_NAME
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        default = {
            "x": None,
            "y": None,
            "width": self.DEFAULT_WIDTH,
            "height": self.DEFAULT_HEIGHT,
            "sizeTier": self.DEFAULT_TIER,
            "spriteId": "",
            #保存总览窗口几何，恢复时校正到可用屏幕。
            "galleryRect": None,
            #None = 没有自定义默认位置，启动时按"工作区右侧偏下"自动摆放。
            "defaultX": None,
            "defaultY": None,
        }
        try:
            content = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
        if not isinstance(content, dict):
            return default

        def _finite_number(value: object) -> float | None:
            """拒绝 NaN、Infinity 和非数字值。"""
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            try:
                return float(value) if math.isfinite(value) else None
            except (TypeError, ValueError):
                return None

        merged = dict(default)
        for key in ("width", "height"):
            number = _finite_number(content.get(key))
            if number is not None and 80 <= number <= 2000:
                merged[key] = int(number)
        for key in ("x", "y", "defaultX", "defaultY"):
            number = _finite_number(content.get(key))
            if number is not None:
                merged[key] = int(number)
        tier = content.get("sizeTier")
        if tier in PET_SIZES:
            merged["sizeTier"] = tier
            merged["width"], merged["height"] = PET_SIZES[tier]
        else:
            #旧状态没有档位，统一迁移到新版默认 M，真正实现“首次升级后缩小”。
            merged["sizeTier"] = self.DEFAULT_TIER
            merged["width"], merged["height"] = PET_SIZES[merged["sizeTier"]]
        sprite_id = content.get("spriteId")
        if isinstance(sprite_id, str) and len(sprite_id) <= 64:
            merged["spriteId"] = sprite_id
        merged["galleryRect"] = _sanitize_rect(content.get("galleryRect"))
        return merged

    def save_gallery_rect(self, x: int, y: int, width: int, height: int) -> None:
        """只更新总览窗口的位置尺寸，不动桌宠自己的几何。"""
        current = self.load()
        current["galleryRect"] = _sanitize_rect(
            {"x": int(x), "y": int(y), "width": int(width), "height": int(height)})
        self._write(current)

    def save(self, x: int, y: int, width: int, height: int, sprite_id: str = "",
             size_tier: str = DEFAULT_TIER) -> dict:
        tier = size_tier if size_tier in PET_SIZES else self.DEFAULT_TIER
        width, height = PET_SIZES[tier]
        current = self.load()
        values = {
            "x": int(x),
            "y": int(y),
            "width": int(width),
            "height": int(height),
            "sizeTier": tier,
            "spriteId": str(sprite_id)[:64],
            #保留总览窗口几何：save() 会整份覆写状态文件，不带上就会把用户
            #精心拖好的总览位置丢掉（这是"整份覆写"最容易踩的坑）。
            "galleryRect": current.get("galleryRect"),
            #同理保留用户设定的默认位置 —— 否则每次拖动桌宠都会把它抹掉。
            "defaultX": current.get("defaultX"),
            "defaultY": current.get("defaultY"),
        }
        self._write(values)
        return values

    def save_default_position(self, x: int, y: int) -> dict:
        """保存固定的默认位置，与会随拖动更新的最近位置分开。"""
        current = self.load()
        current["defaultX"] = None if x is None else int(x)
        current["defaultY"] = None if y is None else int(y)
        self._write(current)
        return current

    def clear_default_position(self) -> dict:
        """同时清除默认位置与最近位置，使下一次启动恢复自动摆放。"""
        current = self.load()
        current["defaultX"] = None
        current["defaultY"] = None
        current["x"] = None
        current["y"] = None
        self._write(current)
        return current

    def clear_default_only(self) -> dict:
        """只清除默认位置、保留"上次位置"（留给将来"取消钉住但留在原地"的场景）。"""
        return self.save_default_position(None, None)


    def _write(self, values: dict) -> None:
        temporary = self.data_dir / f"pet-state-{uuid.uuid4().hex}.tmp"
        try:
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            os.replace(temporary, self.file)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


#Qt 界面层：仅在 PySide6 可用时加载

def _topmost_log(message: str) -> None:
    """记录置顶状态，日志最多保留 200 行。"""
    try:
        path = app_paths.resolve_data_dir() / "topmost.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > 200:
            path.write_text("\n".join(lines[-200:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def launch_tray_process(tray_dir, icon):
    """以独立进程启动托盘，源码态和冻结态使用各自入口。"""
    creation = 0
    if os.name == "nt":
        #DETACHED_PROCESS | CREATE_NO_WINDOW：托盘不弹黑框，
        #也不随桌宠控制台关闭而一起挂掉。
        creation = 0x00000008 | 0x08000000
    if getattr(sys, "frozen", False):
        arguments = [sys.executable, "--tray",
                     "--data-dir", str(tray_dir), "--icon", str(icon)]
        working_dir = str(Path(sys.executable).resolve().parent)
        launch_target = f"{Path(sys.executable).name} --tray"
    else:
        script = Path(__file__).resolve().parent / "pet_tray.py"
        if not script.is_file():
            _topmost_log(f"TRAY 未启动：找不到 {script}")
            return None
        arguments = [sys.executable, str(script),
                     "--data-dir", str(tray_dir), "--icon", str(icon)]
        working_dir = str(script.parent)
        launch_target = script.name
    try:
        process = subprocess.Popen(
            arguments, cwd=working_dir, creationflags=creation, close_fds=True)
    except Exception as error:
        _topmost_log(f"TRAY 启动失败：{type(error).__name__}: {error}")
        return None
    _topmost_log(f"TRAY 已启动 pid={process.pid} 目标={launch_target}")
    return process


def run_desktop_pet(library_root: Path | None = None) -> int:
    """启动桌宠窗口。需要 Windows + PySide6，并复用已验证的原生拖放。"""
    if os.name != "nt":
        raise RuntimeError("冰翼取用精灵目前仅支持 Windows")
    try:
        from PySide6.QtCore import (QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl,
                                    Property, Signal, Slot)
        from PySide6.QtGui import QGuiApplication, QIcon
        from PySide6.QtQml import QQmlApplicationEngine
        from PySide6.QtQuickControls2 import QQuickStyle
    except ImportError as error:  #pragma: no cover - 依赖缺失时给出明确提示
        _topmost_log(f"PET_INIT_FAILED {error!r}")
        raise RuntimeError(
            "桌宠 Qt 运行库加载失败，请使用修复后的完整安装包。"
            if app_paths.is_frozen() else
            "缺少 PySide6。请先在项目 .venv 中执行：pip install PySide6"
        ) from error

    from windows_file_drag import (DroppedOnForbiddenTarget, cleanup_drag_copy, drag_file,
                                  make_draggable_copy, set_drag_dir, sprite_filename)

    #托盘是独立进程（QtWidgets 与 QtQuick 不能同进程），通过文件通信。
    import pet_tray

    code_dir = Path(__file__).resolve().parent
    data_dir = app_paths.resolve_data_dir()
    root = (library_root or data_dir / "exports" / app_paths.LIBRARY_DIR_NAME).resolve()
    library = SpriteLibrary(root)
    state = DesktopPetState(data_dir)

    #剪映/PR 按路径引用素材，临时目录 + 自动清理 = 工程"媒体丢失"。
    try:
        from app_settings import AppSettings

        drag_dir = AppSettings(data_dir).drag_directory()
    except Exception:
        drag_dir = None
    set_drag_dir(drag_dir)

    class DesktopPetBridge(QObject):
        """QML 与立绘库 / 原生拖放之间的桥。"""

        imageChanged = Signal()
        titleChanged = Signal()
        favoriteChanged = Signal()
        indexChanged = Signal()
        statusChanged = Signal()
        dragStateChanged = Signal()
        sizeTierChanged = Signal()
        emptyChanged = Signal()
        loadingChanged = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            self._roster: list[dict] = []
            self._index = -1
            self._image = ""
            self._title = ""
            self._favorite = False
            self._status = "按住人物拖动，即可发送真实 PNG"
            self._dragging = False
            #仅恢复本次拖放隐藏过的总览，避免从桌宠拖放时意外打开总览。
            self._gallery_hidden_for_drag = False
            self._empty = False
            #首次加载与重新构建名册均标记 loading，避免闪现空态。
            self._loading = True
            self._ready = False
            self._window = None
            self._gallery_window = None
            self._size_tier = state.load()["sizeTier"]
            #托盘菜单要用屏幕可用区域来校验「默认位置」是否还放得下。
            #QML 侧启动时会调 setScreenArea() 把它填进来，拿不到就退回一个常见分辨率。
            self._screen_area = (0, 0, 1920, 1080)
            #托盘通信目录与进程句柄（托盘是独立进程，见 pet_tray.py）
            self._tray_dir = data_dir
            self._tray_process = None
            self.reload()

        #数据
        def reload(self) -> None:
            self._set_loading(True)
            try:
                self._roster = build_roster(library)
            finally:
                #无论成功失败都要退出 loading，否则界面会永远停在"正在整理"
                self._ready = True
                self._set_loading(False)
            self._empty = not self._roster
            self.emptyChanged.emit()
            if not self._roster:
                self._index = -1
                self._set_image("")
                self._set_title("立绘库还是空的")
                self._set_favorite(False)
                self.indexChanged.emit()
                return
            saved = state.load()
            target = 0
            if saved["spriteId"]:
                for i, item in enumerate(self._roster):
                    if item["id"] == saved["spriteId"]:
                        target = i
                        break
            self._select(target)

        def _current(self) -> dict | None:
            if 0 <= self._index < len(self._roster):
                return self._roster[self._index]
            return None

        def _select(self, index: int) -> None:
            if not self._roster:
                return
            self._index = index % len(self._roster)
            item = self._roster[self._index]
            path = library.file(item["id"], False)
            if path is None:
                #文件丢失则跳过，继续找下一张可用的
                self._roster.pop(self._index)
                if not self._roster:
                    self.reload()
                    return
                self._select(self._index % len(self._roster))
                return
            self._set_image(QUrl.fromLocalFile(str(path)).toString())
            name = item["displayName"] or f"{item['character']} / {item['face']}"
            if item["favorite"]:
                name = "★ " + name
            self._set_title(name)
            self._set_favorite(bool(item["favorite"]))
            self.indexChanged.emit()

        def _set_image(self, value: str) -> None:
            if value != self._image:
                self._image = value
                self.imageChanged.emit()

        def _set_title(self, value: str) -> None:
            if value != self._title:
                self._title = value
                self.titleChanged.emit()

        def _set_favorite(self, value: bool) -> None:
            if value != self._favorite:
                self._favorite = value
                self.favoriteChanged.emit()

        def _set_status(self, value: str) -> None:
            if value != self._status:
                self._status = value
                self.statusChanged.emit()

        def _set_loading(self, value: bool) -> None:
            if value != self._loading:
                self._loading = value
                self.loadingChanged.emit()

        #QML 可见属性
        @Property(str, notify=imageChanged)
        def imageUrl(self) -> str:
            return self._image

        @Property(str, notify=titleChanged)
        def title(self) -> str:
            return self._title

        @Property(bool, notify=favoriteChanged)
        def favorite(self) -> bool:
            return self._favorite

        @Property(int, notify=indexChanged)
        def count(self) -> int:
            return len(self._roster)

        @Property(int, notify=indexChanged)
        def index(self) -> int:
            return self._index

        @Property(bool, notify=emptyChanged)
        def isEmpty(self) -> bool:
            return self._empty

        @Property(bool, notify=loadingChanged)
        def loading(self) -> bool:
            """是否正在重建名册（首次装载也算）。空态与加载态必须分开显示。"""
            return self._loading

        @Property(bool, notify=loadingChanged)
        def ready(self) -> bool:
            """首次名册装载是否完成。未完成时界面显示"正在整理"，不显示空态。"""
            return self._ready

        @Property(str, notify=statusChanged)
        def status(self) -> str:
            return self._status

        @Property(bool, notify=dragStateChanged)
        def dragging(self) -> bool:
            return self._dragging

        @Property(str, notify=sizeTierChanged)
        def sizeTier(self) -> str:
            return self._size_tier

        #操作
        @Slot()
        def nextSprite(self) -> None:
            if self._roster:
                self._select(next_index(len(self._roster), self._index))

        @Slot()
        def prevSprite(self) -> None:
            if self._roster:
                self._select(prev_index(len(self._roster), self._index))

        @Slot()
        def toggleFavorite(self) -> None:
            item = self._current()
            if not item:
                return
            new_value = not item["favorite"]
            updated = library.update(item["id"], False, item["displayName"],
                                     item["note"], new_value, item["tags"])
            if updated is None:
                self._set_status("收藏失败：找不到该立绘")
                return
            item["favorite"] = bool(updated["favorite"])
            self._set_favorite(bool(updated["favorite"]))
            name = updated["displayName"] or f"{updated['character']} / {updated['face']}"
            self._set_title(("★ " if updated["favorite"] else "") + name)
            self._set_status("已收藏" if updated["favorite"] else "已取消收藏")

        @Slot()
        def setScreenArea(self) -> None:
            """由 QML 在启动时告知屏幕可用区域（供托盘菜单校验默认位置）。"""
            try:
                screen = (self._window.screen() if self._window else None) or QGuiApplication.primaryScreen()
                available = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
                self._screen_area = (available.x(), available.y(),
                                     available.width(), available.height())
            except Exception:
                pass

        @Slot()
        def trayTogglePet(self) -> None:
            """托盘：显示 / 隐藏桌宠。隐藏后仍可从托盘图标或菜单找回。"""
            if self._window is None:
                return
            from PySide6.QtQuick import QQuickWindow

            visible = self._window.isVisible() and \
                self._window.visibility() != QQuickWindow.Visibility.Minimized
            if visible:
                self._window.hide()
                self._set_status("桌宠已隐藏 · 可从右下角托盘图标找回")
            else:
                self._window.show()
                self._window.requestActivate()
                self._set_status("桌宠已显示")
            self.syncTray()

        @Slot(str, str, int, int, int, int)
        def logGalleryGeometry(self, phase: str, saved: str,
                               x: int, y: int, width: int, height: int) -> None:
            """记录总览窗口几何的读写事实（排查"尺寸记忆不生效"用）。"""
            _topmost_log(f"GALLERY {phase} 读到={saved} 实际=({x},{y}) {width}x{height}")

        @Slot(result=str)
        def pinDefaultPosition(self) -> str:
            """将桌宠当前几何保存为默认位置。"""
            if self._window is None:
                return ""
            x, y = int(self._window.x()), int(self._window.y())
            state.save_default_position(x, y)
            self._set_status(f"已把桌宠当前位置设为默认 · ({x}, {y})")
            self.syncTray()
            return f"{x},{y}"

        @Slot()
        def trayPinPosition(self) -> None:
            """托盘：把桌宠当前位置设为默认（下次启动回到这里）。"""
            if self._window is None:
                return
            x, y = int(self._window.x()), int(self._window.y())
            state.save_default_position(x, y)
            self._set_status(f"已把当前位置设为默认 · ({x}, {y})")
            self.syncTray()

        @Slot()
        def trayClearPosition(self) -> None:
            """托盘：清除自定义默认位置，恢复"工作区右侧偏下"的自动摆放。"""
            state.clear_default_position()
            self._set_status("已清除默认位置 · 下次启动自动摆放")
            self.syncTray()

        @Slot(str)
        def traySetSizeTier(self, tier: str) -> None:
            """托盘：直接切到指定档位（与桌宠上的 S/M/L 按钮共用同一套状态）。"""
            if tier not in PET_SIZES:
                return
            if tier == self._size_tier and self._window is not None:
                self.syncTray()
                return
            #复用 cycleSize 的落盘逻辑，但直接指明目标档位。
            while self._size_tier != tier:
                self.cycleSize()
            self.syncTray()

        @Slot()
        def trayQuit(self) -> None:
            """托盘：退出桌宠（与窗口上的「×」同一条路径，保证落盘）。"""
            if self._window is not None:
                state.save(int(self._window.x()), int(self._window.y()),
                           int(self._window.width()), int(self._window.height()),
                           self._current_id(), self._size_tier)
            self.shutdown_tray()
            QGuiApplication.quit()

        @Slot()
        def syncTray(self) -> None:
            """通过状态文件同步独立托盘进程的可见性与档位。"""
            if self._window is None:
                return
            from PySide6.QtQuick import QQuickWindow

            visible = self._window.isVisible() and \
                self._window.visibility() != QQuickWindow.Visibility.Minimized
            pet_tray.write_state(self._tray_dir, visible, self._size_tier, os.getpid())

        def start_tray_process(self) -> None:
            """拉起托盘进程。失败不影响桌宠本身（托盘只是"找回入口"）。"""
            #brand-assets/app.ico 是主程序的品牌徽章，缩到 16px 在托盘里认不出来。
            icon = app_paths.resource_root() / "ui" / "avatar-fox-round.png"
            if not icon.is_file():
                icon = app_paths.resource_root() / "brand-assets" / "app.ico"
            #真正的启动逻辑在模块级 `launch_tray_process()`
            self._tray_process = launch_tray_process(self._tray_dir, icon)
            if self._tray_process is None:
                return
            self.syncTray()

        def poll_tray_command(self) -> None:
            """轮询托盘下发的命令并执行（没有命令时就是一次失败的文件读取）。"""
            payload = pet_tray.take_command(self._tray_dir)
            if not payload:
                return
            command = payload.get("command")
            if command == "toggle":
                self.trayTogglePet()
            elif command == "pin":
                self.trayPinPosition()
            elif command == "clear-position":
                self.trayClearPosition()
            elif command == "size":
                self.traySetSizeTier(str(payload.get("tier") or ""))
            elif command == "quit":
                self.trayQuit()

        def shutdown_tray(self) -> None:
            """清除状态文件并结束本次启动的托盘进程。"""
            pet_tray.clear_state(self._tray_dir)
            process = getattr(self, "_tray_process", None)
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
                self._tray_process = None

        def _current_id(self) -> str:
            item = self._current()
            return item["id"] if item else ""

        @Slot(result=str)
        def cycleSize(self) -> str:
            self._size_tier = cycle_size_tier(self._size_tier)
            self.sizeTierChanged.emit()
            width, height = PET_SIZES[self._size_tier]
            #即时落盘 sizeTier；位置沿用上次保存值，500ms 防抖 / onClosing 会再校正坐标。
            saved = state.load()
            x = int(saved["x"]) if saved["x"] is not None else 0
            y = int(saved["y"]) if saved["y"] is not None else 0
            item = self._current()
            state.save(x, y, width, height, item["id"] if item else "", self._size_tier)
            self._set_status(f"已切换为 {self._size_tier} 档 · {width}×{height}")
            return self._size_tier

        @Slot(str, bool, int, str, str, str, result=str)
        def queryGallery(self, search: str, favorites: bool, offset: int,
                         tag: str = "", game: str = "", character: str = "") -> str:
            """返回总览分页数据与级联筛选项；优先使用缩略图。"""
            result = build_gallery_page(library, search, favorites, offset,
                                        tag=tag, game=game, character=character)
            items = []
            for row in result["items"]:
                item = row["item"]
                image_path = row["imagePath"]
                url = QUrl.fromLocalFile(str(image_path)).toString()
                #头部特写 URL：读后端缓存好的文件（`thumbs/<id>.head.png`）。
                head_url = url
                try:
                    is_special = bool(item.get("category") not in (None, "", "normal"))
                    head_file = library.head_path(item["id"], is_special, False)
                    if head_file is not None:
                        head_url = QUrl.fromLocalFile(str(head_file)).toString()
                except Exception:
                    head_url = url
                items.append({
                    "id": item["id"],
                    "title": item["displayName"] or item["character"],
                    "detail": f"{item['game']} · {item['face']}",
                    "favorite": bool(item["favorite"]),
                    "imageUrl": url,
                    "headUrl": head_url,
                    #面部小头像：同一张图，界面自己裁右上角圆形区域，零额外磁盘开销。
                    "faceUrl": url,
                    "tags": list(item.get("tags") or []),
                    "game": item["game"],
                    "selected": bool(self._current() and self._current()["id"] == item["id"]),
                })
            return json.dumps({"items": items, "total": result["total"],
                               "hasMore": result["hasMore"],
                               "nextOffset": result["nextOffset"],
                               "tags": result["tags"], "games": result["games"],
                               "characters": result["characters"],
                               "scopedGames": result["scopedGames"],
                               "gameCharacters": result["gameCharacters"]},
                              ensure_ascii=False)

        @Slot(int, int, int, int, int, int, result=str)
        def galleryPosition(self, pet_x: int, pet_y: int, pet_w: int, pet_h: int,
                            gallery_w: int, gallery_h: int) -> str:
            """由 Qt/Python 读取 QScreen，避免 QML 平台差异导致 availableGeometry 为空。"""
            center = QPoint(pet_x + pet_w // 2, pet_y + pet_h // 2)
            screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
            area = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
            x, y = gallery_window_position(
                pet_x, pet_y, pet_w, pet_h, gallery_w, gallery_h,
                area.x(), area.y(), area.width(), area.height(),
            )
            return json.dumps({"x": x, "y": y})

        @Slot(result=str)
        def galleryRect(self) -> str:
            """上次保存的总览窗口位置尺寸（没有就返回 {}，界面用默认值）。"""
            saved = state.load().get("galleryRect")
            return json.dumps(saved or {}, ensure_ascii=False)

        @Slot(int, int, int, int)
        def saveGalleryRect(self, x: int, y: int, width: int, height: int) -> None:
            """记住总览窗口的位置尺寸（跨屏记忆；越界由界面侧 restoreGeometry 校正）。"""
            try:
                state.save_gallery_rect(x, y, width, height)
            except Exception:
                pass

        @Slot(str, result=bool)
        def selectFromGallery(self, item_id: str) -> bool:
            for index, item in enumerate(self._roster):
                if item["id"] == item_id:
                    self._select(index)
                    self._set_status(f"已切换：{item['displayName'] or item['character']}")
                    return True
            self.reload()
            for index, item in enumerate(self._roster):
                if item["id"] == item_id:
                    self._select(index)
                    return True
            return False

        @Slot(result=bool)
        def dragCurrent(self) -> bool:
            """在 GUI 线程执行原生拖放，临时隐藏窗口并在结束后恢复。"""
            if self._dragging:
                return False
            item = self._current()
            if not item:
                return False
            path = library.file(item["id"], False)
            if path is None:
                self._set_status("无法拖动：图片文件已丢失")
                return False
            self._dragging = True
            self.dragStateChanged.emit()
            self._set_status(f"正在拖动：{item['displayName'] or item['character']}…")
            #拖放开始时隐藏总览，并记录状态以便恢复。
            gallery_window = getattr(self, "_gallery_window", None)
            hid_gallery = False
            if gallery_window is not None:
                try:
                    hid_gallery = bool(gallery_window.property("visible"))
                except Exception:
                    hid_gallery = False
            self._gallery_hidden_for_drag = hid_gallery
            if hid_gallery:
                self._apply_topmost(gallery_window, False)
                self._set_gallery_dragging(gallery_window, True)
                try:
                    gallery_window.setProperty("visible", False)
                except Exception:
                    pass
            target = None
            dropped = False
            forbidden = False
            try:
                target = make_draggable_copy(path, sprite_filename(item))
                dropped = drag_file(target)
            except DroppedOnForbiddenTarget:
                #拖放完成后立即解锁，副本清理交给后台线程。
                self._set_status("已取消：不能拖到桌面或文件夹，请拖到剪映素材区")
                forbidden = True
            except Exception as error:  #pragma: no cover - 依赖 Windows 实机
                self._set_status(f"拖动失败：{error}")
            finally:
                #先解锁再收尾：收尾可能起延迟删除线程，不能让它挡住下一次拖动
                self._dragging = False
                self.dragStateChanged.emit()
                cleanup_drag_copy(target, dropped)
                #归位：稍等一下再恢复置顶。
                QTimer.singleShot(320, self._restore_gallery_topmost)
            if not forbidden:
                self._set_status("已拖到剪映/PR（文件保留在 DragOut，工程随时可读）" if dropped
                                 else "已取消拖动")
            return dropped

        def _set_gallery_dragging(self, gallery_window, value: bool) -> None:
            """记录拖放状态，防止临时隐藏总览时错误显示桌宠。"""
            if gallery_window is None:
                return
            try:
                gallery_window.setProperty("dragging", bool(value))
            except Exception:
                pass

        def _restore_gallery_topmost(self) -> None:
            """延迟恢复本次拖放隐藏的总览，避免抢占目标应用的激活时机。"""
            if not getattr(self, "_gallery_hidden_for_drag", False):
                return
            self._gallery_hidden_for_drag = False
            gallery_window = getattr(self, "_gallery_window", None)
            if gallery_window is None:
                return
            try:
                gallery_window.setProperty("visible", True)
            except Exception:
                pass
            #清掉"正在拖放"标志：此后 pet.qml 的派生绑定（visible: !总览可见 && !拖拽中）
            #会自己把桌宠藏好，这里不需要再手动压底。
            self._set_gallery_dragging(gallery_window, False)
            self._apply_topmost(gallery_window, True)

        @Slot(int, int, int, int, str)
        def saveGeometry(self, x: int, y: int, width: int, height: int,
                         size_tier: str = "M") -> None:
            item = self._current()
            self._size_tier = size_tier if size_tier in PET_SIZES else self._size_tier
            state.save(x, y, width, height, item["id"] if item else "", self._size_tier)

        def set_window(self, window) -> None:
            """由 run_desktop_pet 注入 QML 根窗口，供 setPetTopmost 取原生句柄。"""
            self._window = window

        def _apply_topmost(self, window, topmost: bool) -> None:
            """通过 SetWindowPos 调整置顶；回读实际状态并执行有界重试。"""
            if window is None or os.name != "nt":
                _topmost_log(f"跳过：window={window!r} os={os.name}")
                return
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
                user32.SetWindowPos.restype = wintypes.BOOL
                if hasattr(user32, "GetWindowLongPtrW"):
                    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
                    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
                hwnd = int(window.winId())
                if not hwnd:
                    _topmost_log("winId() 为 0：原生窗口还没建好，本次请求丢弃")
                    return
                GWL_EXSTYLE = -20
                WS_EX_TOPMOST = 0x00000008
                flags = 0x0001 | 0x0002 | 0x0010  #SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE

                def is_topmost() -> bool:
                    return bool(user32.GetWindowLongPtrW(wintypes.HWND(hwnd), GWL_EXSTYLE) & WS_EX_TOPMOST)

                before = is_topmost()
                if before == bool(topmost):
                    _topmost_log(f"hwnd={hwnd} 目标={topmost} 已经是该状态，无需改动")
                    return
                insert_after = wintypes.HWND(-1 if topmost else -2)  #HWND_TOPMOST / HWND_NOTOPMOST
                for attempt in (1, 2):
                    ok = user32.SetWindowPos(wintypes.HWND(hwnd), insert_after, 0, 0, 0, 0, flags)
                    error = ctypes.get_last_error() if hasattr(ctypes, "get_last_error") else 0
                    after = is_topmost()
                    _topmost_log(
                        f"hwnd={hwnd} 目标={topmost} 改前={before} 第{attempt}次: "
                        f"SetWindowPos={ok} GetLastError={error} 改后={after}"
                        + ("  ✓生效" if after == bool(topmost) else "  ✗未生效")
                    )
                    if after == bool(topmost):
                        return
                    #回读没变 → 很可能是"非前台窗口，排序请求被忽略"。
                    #先把它抬到前台（不用 SWP_NOACTIVATE 的那一套），再试一次。
                    try:
                        user32.SetForegroundWindow(wintypes.HWND(hwnd))
                    except Exception:
                        pass
                _topmost_log(f"hwnd={hwnd} 两次都没生效，放弃（界面会显示真实状态）")
            except Exception as error:
                _topmost_log(f"异常：{error!r}")

        def set_gallery_window(self, window) -> None:
            """由 run_desktop_pet 注入总览窗口（GalleryWindow），供「钉住」开关使用。"""
            self._gallery_window = window

        @Slot(bool)
        def setGalleryTopmost(self, topmost: bool) -> None:
            """调整总览窗口的原生置顶状态。"""
            window = getattr(self, "_gallery_window", None)
            _topmost_log(f"  ↑ setGalleryTopmost({topmost}) 窗口={'有' if window is not None else '无(None!)'}")
            self._apply_topmost(window, topmost)

        @Slot(result=bool)
        def galleryTopmostActual(self) -> bool:
            """回读原生窗口的实际置顶标志。"""
            window = getattr(self, "_gallery_window", None)
            if window is None or os.name != "nt":
                return False
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                if hasattr(user32, "GetWindowLongPtrW"):
                    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
                    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
                hwnd = int(window.winId())
                if not hwnd:
                    return False
                return bool(user32.GetWindowLongPtrW(wintypes.HWND(hwnd), -20) & 0x00000008)
            except Exception as error:
                _topmost_log(f"  galleryTopmostActual 异常：{error!r}")
                return False

        @Slot(bool)
        def setPetTopmost(self, topmost: bool) -> None:
            """开总览时取消桌宠置顶，关闭总览恢复置顶（不重建窗口，避免闪烁）。"""
            self._apply_topmost(getattr(self, "_window", None), topmost)

        @Slot()
        def sinkPetWindow(self) -> None:
            """降低桌宠窗口层级而不隐藏，避免连带隐藏其总览窗口。"""
            window = getattr(self, "_window", None)
            if window is None or os.name != "nt":
                return
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
                user32.SetWindowPos.restype = wintypes.BOOL
                hwnd = int(window.winId())
                if not hwnd:
                    return
                HWND_BOTTOM = wintypes.HWND(1)
                flags = 0x0001 | 0x0002 | 0x0010  #NOSIZE | NOMOVE | NOACTIVATE
                ok = user32.SetWindowPos(wintypes.HWND(hwnd), HWND_BOTTOM, 0, 0, 0, 0, flags)
                _topmost_log(f"sinkPetWindow hwnd={hwnd} -> {ok}")
            except Exception as error:
                _topmost_log(f"sinkPetWindow 异常：{error!r}")

        @Slot()
        def restorePetWindow(self) -> None:
            """关总览时把桌宠恢复成置顶（回到它原本的样子）。"""
            self._apply_topmost(getattr(self, "_window", None), True)

    apply_qml_style()
    app = QGuiApplication([])
    apply_render_backend(app)
    app.setApplicationName("冰翼取用精灵")
    app.setOrganizationName("冰翼逆时光")
    icon_path = app_paths.resource_root() / "brand-assets" / "app.ico"
    if not icon_path.is_file():
        icon_path = app_paths.resource_root() / "ui" / "favicon.png"
    app.setWindowIcon(QIcon(str(icon_path)))
    engine = QQmlApplicationEngine()
    bridge = DesktopPetBridge()
    engine.rootContext().setContextProperty("pet", bridge)

    qml_file = code_dir / "ui" / "pet.qml"
    engine.load(QUrl.fromLocalFile(str(qml_file)))
    if not engine.rootObjects():
        raise RuntimeError("无法加载桌宠界面 ui/pet.qml")

    window = engine.rootObjects()[0]
    #通过 QGuiApplication 设置图标；QML Window 不提供 icon.source。
    fox_icon = app_paths.resource_root() / "ui" / "avatar-fox-round.png"
    if fox_icon.is_file():
        try:
            window.setIcon(QIcon(str(fox_icon)))
        except Exception:
            pass
    bridge.set_window(window)
    #pet.qml 里内联的 GalleryWindow 实例：注入给桥，供「钉住」开关切换它的置顶
    gallery_root = window.findChild(QObject, "galleryWindow")
    if gallery_root is not None:
        bridge.set_gallery_window(gallery_root)
        #为总览单独设置图标，覆盖应用级默认图标。
        if fox_icon.is_file():
            try:
                gallery_root.setIcon(QIcon(str(fox_icon)))
            except Exception:
                pass

    #命令轮询（托盘 → 桌宠）
    app.aboutToQuit.connect(bridge.shutdown_tray)

    command_timer = QTimer()
    command_timer.setInterval(400)
    command_timer.timeout.connect(bridge.poll_tray_command)
    command_timer.start()

    #恢复窗口位置，并夹紧到当前可用屏幕区域，异常退出后也能安全找回。
    saved = state.load()
    screen = window.screen() or QGuiApplication.primaryScreen()
    available = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
    width = int(saved["width"] or DesktopPetState.DEFAULT_WIDTH)
    height = int(saved["height"] or DesktopPetState.DEFAULT_HEIGHT)

    x = y = None
    if saved.get("defaultX") is not None and saved.get("defaultY") is not None:
        #默认位置先限制在当前工作区，无法容纳时恢复自动摆放。
        candidate_x, candidate_y = clamp_to_area(
            int(saved["defaultX"]), int(saved["defaultY"]), width, height,
            available.x(), available.y(), available.width(), available.height())
        fits = (available.width() >= width and available.height() >= height)
        if fits:
            x, y = candidate_x, candidate_y
    if x is None and saved["x"] is not None and saved["y"] is not None:
        x, y = int(saved["x"]), int(saved["y"])
    if x is None:
        x, y = default_pet_position(width, height, available.x(), available.y(),
                                    available.width(), available.height())
    x, y = clamp_to_area(x, y, width, height,
                         available.x(), available.y(),
                         available.width(), available.height())
    window.setProperty("x", x)
    window.setProperty("y", y)
    #窗口就位后启动托盘，提供隐藏后的恢复入口。
    bridge.setScreenArea()
    bridge.start_tray_process()
    #窗口显示后再同步托盘，避免记录事件循环前的不可见状态。
    QTimer.singleShot(0, bridge.syncTray)
    QTimer.singleShot(0, lambda: _topmost_log(
        f"PET_READY hwnd={int(window.winId())} visible={window.isVisible()}"))
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="冰翼取用精灵：桌宠与立绘总览合一的取用工具。")
    parser.add_argument("--library-root", type=Path, help="测试用立绘库目录。")
    parser.add_argument("--tray", action="store_true",
                        help="只启动系统托盘（冻结 exe 的托盘模式，由桌宠自动拉起）")
    parser.add_argument("--data-dir", type=Path, help="--tray 模式使用的数据目录")
    parser.add_argument("--icon", type=Path, help="--tray 模式使用的图标")
    arguments = parser.parse_args(argv)
    if arguments.tray:
        import pet_tray

        data_dir = arguments.data_dir or app_paths.resolve_data_dir()
        icon = arguments.icon
        if icon is None:
            icon = app_paths.resource_root() / "ui" / "avatar-fox-round.png"
            if not icon.is_file():
                icon = app_paths.resource_root() / "brand-assets" / "app.ico"
        return pet_tray.tray_entry(data_dir, icon)
    return run_desktop_pet(arguments.library_root)


if __name__ == "__main__":
    raise SystemExit(main())
