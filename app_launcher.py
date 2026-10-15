#!/usr/bin/env python3
"""冰翼Gal创作工坊 桌面启动器（PyInstaller 打包入口）。

起本地 HTTP 服务，优先用 pywebview 套壳为桌面窗口；无 pywebview / 无 GUI 时回退浏览器。"""
from __future__ import annotations

import os
import math
import sys
import threading
import time
import traceback
import ctypes
from ctypes import byref, c_int, c_long, c_void_p
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import app_paths
import sprite_composer


def _append_shell_flag(url: str) -> str:
    """给桌面壳 URL 追加 shell=desktop 查询参数，供前端无条件启用无边框标题栏。"""
    parts = urlparse(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["shell"] = ["desktop"]
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))


WINDOW_WIDTH = 1564
WINDOW_HEIGHT = 912


WINDOW_MARGIN = 24
MIN_WINDOW_WIDTH = 960
MIN_WINDOW_HEIGHT = 640


def _dpi_scale() -> float:
    """当前主屏 DPI 缩放（96dpi = 1.0）。pywebview 会用它乘 create_window 的坐标。"""
    if sys.platform != "win32":
        return 1.0
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        if dpi:
            return dpi / 96.0
    except Exception:
        pass
    return 1.0


def _work_area() -> tuple[int, int, int, int]:
    """主屏工作区 (left, top, width, height)，即扣除任务栏后的可用区域。"""
    if sys.platform == "win32":
        try:
            class Rect(ctypes.Structure):
                _fields_ = (("left", c_long), ("top", c_long), ("right", c_long), ("bottom", c_long))

            rect = Rect()
            user32 = ctypes.windll.user32
            user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
            user32.SystemParametersInfoW.restype = ctypes.c_int
            if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  #SPI_GETWORKAREA
                return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            pass
    return 0, 0, WINDOW_WIDTH, WINDOW_HEIGHT


def _target_size() -> tuple[int, int]:
    """将默认窗口尺寸限制在当前屏幕工作区内。"""
    _left, _top, work_w, work_h = _work_area()
    width = min(WINDOW_WIDTH, max(MIN_WINDOW_WIDTH, work_w - WINDOW_MARGIN))
    height = min(WINDOW_HEIGHT, max(MIN_WINDOW_HEIGHT, work_h - WINDOW_MARGIN))

    width = max(MIN_WINDOW_WIDTH // 2, min(width, work_w))
    height = max(MIN_WINDOW_HEIGHT // 2, min(height, work_h))
    return int(width), int(height)


def _layout_limits(work_width: int, work_height: int, dpi: float,
                   css_width: float = 1160, css_height: float = 740,
                   frame_width: int | None = None, frame_height: int | None = None) -> dict:
    """Fit the usable CSS layout inside the monitor, returning physical limits."""
    available_w = max(1, work_width - WINDOW_MARGIN)
    available_h = max(1, work_height - WINDOW_MARGIN)
    frame_w = math.ceil(16 * dpi) if frame_width is None else max(0, frame_width)
    frame_h = math.ceil(16 * dpi) if frame_height is None else max(0, frame_height)
    fit = min(1.0, max(1, available_w - frame_w) / (css_width * dpi),
              max(1, available_h - frame_h) / (css_height * dpi))
    return {"fit": fit, "frame_width": frame_w, "frame_height": frame_h,
            "width": min(available_w, math.ceil(css_width * dpi * fit) + frame_w),
            "height": min(available_h, math.ceil(css_height * dpi * fit) + frame_h)}


def _centered_position(width: int, height: int) -> tuple[int, int] | None:
    """返回主屏工作区居中坐标（DPI awareness 已开，返回物理像素）；失败返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        class Rect(ctypes.Structure):
            _fields_ = (("left", c_long), ("top", c_long), ("right", c_long), ("bottom", c_long))

        SPI_GETWORKAREA = 0x0030
        user32 = ctypes.windll.user32
        user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        user32.SystemParametersInfoW.restype = ctypes.c_int

        rect = Rect()
        if user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            work_w = rect.right - rect.left
            work_h = rect.bottom - rect.top
            return rect.left + max(0, (work_w - width) // 2), rect.top + max(0, (work_h - height) // 2)
    except Exception:
        pass
    return None


class WindowChromeApi:
    """将网页标题栏操作桥接到原生窗口，Windows 下保留缩放与贴靠。"""

    _RESIZE_HIT_TEST = {
        "left": 10,
        "right": 11,
        "top": 12,
        "top-left": 13,
        "top-right": 14,
        "bottom": 15,
        "bottom-left": 16,
        "bottom-right": 17,
    }

    def __init__(self, log_path: Path | None = None) -> None:
        self._window = None

        self._log_path = Path(log_path) if log_path is not None else None

        self._debug = str(os.environ.get("BINGYI_DEBUG", "")).strip() not in ("", "0", "false")

    def bind(self, window) -> None:

        self._window = window

    def _log(self, message: str, level: str = "info") -> None:
        """追加窗口状态日志；写入失败不影响界面操作。"""
        if self._log_path is None and "pytest" in sys.modules:
            return
        if level == "debug" and not getattr(self, "_debug", False):
            return
        try:
            log_path = self._log_path or (app_paths.resolve_data_dir() / app_paths.STARTUP_LOG_NAME)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            tag = "chrome:debug" if level == "debug" else "chrome"
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{tag} {datetime.now():%Y-%m-%d %H:%M:%S}] {message}\n")
        except Exception:
            pass

    def _raw_hwnd(self) -> int | None:
        native = getattr(self._window, "native", None)
        if native is None:
            self._log("_raw_hwnd: window.native 为 None（pywebview 原生对象不可用）", level="debug")
            return None
        handle = getattr(native, "Handle", None)
        self._log(f"_raw_hwnd: native类型={type(native).__name__} Handle原始值={handle!r}", level="debug")
        if handle is None:
            return None
        try:
            return int(handle.ToInt64())
        except Exception as exc:
            self._log(f"_raw_hwnd: handle.ToInt64() 失败 → {exc}", level="debug")
            try:
                return int(handle)
            except Exception as exc2:
                self._log(f"_raw_hwnd: int(handle) 失败 → {exc2}", level="debug")
                return None

    def _find_window_by_title(self) -> int | None:
        """按唯一标题查找原生句柄；测试进程禁用此兜底，避免操作真实窗口。"""
        if sys.platform != "win32" or "pytest" in sys.modules:
            return None
        try:
            user32 = ctypes.windll.user32
            user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            user32.FindWindowW.restype = c_void_p
            found = user32.FindWindowW(None, "冰翼Gal创作工坊")
            if found:
                return int(found)
        except Exception as exc:
            self._log(f"_find_window_by_title: FindWindowW 失败 → {exc}", level="debug")
        return None

    def _hwnd(self) -> int | None:
        """返回顶层窗口句柄（GetAncestor GA_ROOT 归一，避免拿到 WebView2 子窗口）。"""
        raw = self._raw_hwnd()
        self._log(f"_hwnd: native.Handle 解析结果={raw}", level="debug")
        if raw is None:
            raw = self._find_window_by_title()
            self._log(f"_hwnd: native.Handle=None，改用 FindWindowW 兜底 → {raw}", level="debug")
            if raw is None:
                return None
        if sys.platform != "win32":
            return raw
        try:
            GA_ROOT = 2
            user32 = ctypes.windll.user32
            user32.GetAncestor.restype = c_void_p
            top = user32.GetAncestor(c_void_p(raw), GA_ROOT)
            if top:
                self._log(f"_hwnd: GetAncestor 归一 前={raw} 后={int(top)}", level="debug")
                return int(top)
        except Exception as exc:
            self._log(f"_hwnd: GetAncestor 失败 → {exc}", level="debug")
        return raw

    def _is_maximized(self) -> bool:
        hwnd = self._hwnd()
        if sys.platform == "win32" and hwnd:
            return bool(ctypes.windll.user32.IsZoomed(c_void_p(hwnd)))
        return False

    def apply_maximized_bounds(self) -> None:
        """将最大化边界设为显示器工作区，保留任务栏空间。"""
        native = getattr(self._window, "native", None)
        hwnd = self._hwnd()
        if native is None or not hwnd:
            self._log("apply_maximized_bounds: 原生窗口不可用，跳过")
            return
        try:
            from System.Drawing import Rectangle  #type: ignore  # pythonnet（pywebview Windows 后端）

            left, top, width, height = _work_area()
            native.MaximizedBounds = Rectangle(int(left), int(top), int(width), int(height))
            self._log(f"MaximizedBounds 已设 = ({left},{top}) {width}x{height}", level="debug")
            ctypes.windll.user32.SetWindowPos(c_void_p(hwnd), None, 0, 0, 0, 0, 0x0027)
        except Exception as exc:
            self._log(f"设置 MaximizedBounds 失败（最大化可能仍会盖住任务栏）: {exc}")

    def _refresh_webview_layout(self) -> None:
        """样式/DPI 重算后同步客户区，避免 WebView 留下旧的顶部或左侧偏移。"""
        native = getattr(self._window, "native", None)
        if native is None:
            return

        def apply():
            from System.Windows.Forms import DockStyle, Padding  #type: ignore

            view = getattr(native, "webview", None)
            if view is None:
                return
            native.SuspendLayout()
            try:
                native.Padding = Padding(0)
                view.Margin = Padding(0)
                view.Dock = DockStyle.Fill
                view.Bounds = native.ClientRectangle
            finally:
                native.ResumeLayout(True)
            native.PerformLayout()
            view.Invalidate()
            self._log(f"WebView 客户区同步: client={native.ClientRectangle} bounds={view.Bounds}",
                      level="debug")

        self._run_on_ui_thread(apply)

    def configure_native_window(self) -> None:


        if sys.platform == "win32":
            self._run_on_ui_thread(self._configure_native_window)

    def _configure_native_window(self) -> None:
        """恢复无边框窗口的缩放、贴靠与系统菜单，重新同步客户区尺寸。"""
        if sys.platform != "win32":
            return
        hwnd = self._hwnd()
        if not hwnd:
            self._log("configure_native_window: hwnd=None，跳过")
            return
        self.apply_maximized_bounds()
        self.fit_workspace()
        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        user32.SetWindowPos.restype = ctypes.c_int

        try:
            version = sys.getwindowsversion()
            self._log(f"Windows 版本: {version.major}.{version.minor}.{getattr(version, 'build', 0)}")
        except Exception as exc:
            self._log(f"读取 Windows 版本失败: {exc}")

        WS_CAPTION = 0x00C00000
        WS_SIZEBOX = 0x00040000
        WS_MINIMIZEBOX = 0x00020000
        WS_MAXIMIZEBOX = 0x00010000
        WS_SYSMENU = 0x00080000
        before = user32.GetWindowLongW(c_void_p(hwnd), -16)
        style = (before | WS_SIZEBOX | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU) & ~WS_CAPTION
        user32.SetWindowLongW(c_void_p(hwnd), -16, style)
        after = user32.GetWindowLongW(c_void_p(hwnd), -16)
        self._log(f"style 归一: before=0x{before & 0xFFFFFFFF:08X} after=0x{after & 0xFFFFFFFF:08X}", level="debug")
        user32.SetWindowPos(c_void_p(hwnd), None, 0, 0, 0, 0, 0x0027)

        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


        try:
            extend = dwmapi.DwmExtendFrameIntoClientArea
            extend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            extend.restype = ctypes.c_long

            class Margins(ctypes.Structure):
                _fields_ = (("cxLeftWidth", c_int), ("cxRightWidth", c_int),
                            ("cyTopHeight", c_int), ("cyBottomHeight", c_int))

            margins = Margins(1, 1, 1, 1)
            hr = extend(c_void_p(hwnd), byref(margins))
            self._log(f"DwmExtendFrameIntoClientArea(1px×4) hr=0x{hr & 0xFFFFFFFF:08X}", level="debug")
            DWMWA_NCRENDERING_POLICY = 2
            DWMNCRP_ENABLED = 2
            policy = c_int(DWMNCRP_ENABLED)
            hr = dwmapi.DwmSetWindowAttribute(c_void_p(hwnd), DWMWA_NCRENDERING_POLICY, byref(policy), 4)
            self._log(f"DwmSetWindowAttribute(NCRENDERING=ENABLED) hr=0x{hr & 0xFFFFFFFF:08X}", level="debug")

            user32.SetWindowPos(c_void_p(hwnd), None, 0, 0, 0, 0, 0x0027)
            self._log("扩框后已重触发 SWP_FRAMECHANGED", level="debug")
        except Exception as exc:
            self._log(f"扩框消除黑边失败: {exc}")

        try:


            hr = _set_caption_color(hwnd, DARK_CAPTION_COLOR)
            self._log(f"DwmSetWindowAttribute(标题栏色35={DARK_CAPTION_COLOR}) hr=0x{hr & 0xFFFFFFFF:08X}", level="debug")
        except Exception as exc:
            self._log(f"设置标题栏色失败: {exc}")


        target_w, target_h = _target_size()
        limits = self.fit_workspace()
        target_w, target_h = max(target_w, limits["width"]), max(target_h, limits["height"])
        target = _centered_position(target_w, target_h)
        if target:
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            user32.SetWindowPos(c_void_p(hwnd), None, target[0], target[1],
                                target_w, target_h, SWP_NOZORDER | SWP_NOACTIVATE)
            age = app_paths.process_age_seconds()
            age_text = f"{age * 1000:.0f} ms" if age is not None else "?"
            self._log(f"[boot] 原生窗口就绪：进程创建后 {age_text}")
            self._log(f"窗口几何钉死: pos={target} size={target_w}x{target_h}"
                      f"（用户目标 {WINDOW_WIDTH}x{WINDOW_HEIGHT}，工作区自适应）")

        try:
            corner = c_int(2)
            hr = dwmapi.DwmSetWindowAttribute(c_void_p(hwnd), 33, byref(corner), 4)
            self._log(f"DwmSetWindowAttribute(圆角33=2) hr=0x{hr & 0xFFFFFFFF:08X}", level="debug")
        except Exception as exc:
            self._log(f"DwmSetWindowAttribute(圆角) 异常: {exc}", level="debug")
        try:
            border = c_long(0x00EAB87E)
            hr = dwmapi.DwmSetWindowAttribute(c_void_p(hwnd), 34, byref(border), 4)
            self._log(f"DwmSetWindowAttribute(边框色34) hr=0x{hr & 0xFFFFFFFF:08X}", level="debug")
        except Exception as exc:
            self._log(f"DwmSetWindowAttribute(边框色) 异常: {exc}", level="debug")

        self._refresh_webview_layout()

    def fit_workspace(self, css_width: float = 1160, css_height: float = 740) -> dict:
        """Apply a monitor/DPI-aware native resize floor on the UI thread."""
        css_width = max(1160, min(2400, float(css_width)))
        css_height = max(740, min(1600, float(css_height)))
        result = {}
        def apply():
            from System.Drawing import Size  #type: ignore
            from System.Windows.Forms import Screen  #type: ignore
            native = self._window.native
            area = Screen.FromControl(native).WorkingArea
            hwnd = self._hwnd()
            dpi = ctypes.windll.user32.GetDpiForWindow(c_void_p(hwnd)) / 96.0 if hwnd else _dpi_scale()
            limits = _layout_limits(area.Width, area.Height, dpi or 1.0, css_width, css_height,
                                    native.Width - native.ClientSize.Width,
                                    native.Height - native.ClientSize.Height)
            #Form.MinimumSize constrains WM_GETMINMAXINFO and the OS resize loop.
            native.MinimumSize = Size(limits["width"], limits["height"])
            result.update(limits)
        if sys.platform == "win32" and self._run_on_ui_thread(apply):
            return result
        _x, _y, width, height = _work_area()
        return _layout_limits(width, height, _dpi_scale(), css_width, css_height)

    def get_state(self) -> dict:
        return {"desktop": True, "maximized": self._is_maximized()}

    def minimize(self) -> dict:
        if self._window is not None:
            self._window.minimize()
        return self.get_state()

    def toggle_maximize(self) -> dict:
        if self._window is not None:
            if self._is_maximized():
                self._window.restore()
            else:
                self._window.maximize()
        return self.get_state()

    def toggle_fullscreen(self) -> None:
        if self._window is not None:
            self._window.toggle_fullscreen()

    def close(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def log_frontend(self, message: str) -> dict:
        """前端诊断日志入口：把 app.js 侧关键状态追加写入启动日志。"""
        self._log(f"[frontend] {message}")
        return {"ok": True}

    def set_caption_color(self, color: str) -> dict:
        """同步 DWM 标题栏颜色，避免无边框窗口残留异色边缘。"""
        if sys.platform != "win32":
            return {"ok": False, "reason": "仅 Windows 支持"}
        raw = str(color or "").lstrip("#")
        if len(raw) != 6:
            return {"ok": False, "reason": "颜色格式应为 #RRGGBB"}
        try:
            int(raw, 16)
        except ValueError:
            return {"ok": False, "reason": "颜色格式应为 #RRGGBB"}
        hwnd = self._hwnd()
        if not hwnd:
            return {"ok": False, "reason": "窗口句柄不可用"}
        try:
            hr = _set_caption_color(hwnd, raw)
            self._log(f"set_caption_color(#{raw}) hwnd={hwnd} hr=0x{hr & 0xFFFFFFFF:08X}", level="debug")
            return {"ok": hr == 0}
        except Exception as exc:
            self._log(f"set_caption_color 失败: {exc}")
            return {"ok": False, "reason": str(exc)}

    def _run_on_ui_thread(self, action) -> bool:
        """同步封送到原生 UI 线程；无法封送时返回 False。"""
        native = getattr(self._window, "native", None)
        if native is None:
            self._log("_run_on_ui_thread: native=None，无法封送到 UI 线程", level="debug")
            return False
        try:
            invoke_required = bool(getattr(native, "InvokeRequired", False))
        except Exception:
            invoke_required = False
        try:
            if invoke_required:
                from System import Action
                native.Invoke(Action(action))
                self._log(f"_run_on_ui_thread: Form.Invoke 成功 (InvokeRequired={invoke_required})", level="debug")
            else:
                action()
                self._log(f"_run_on_ui_thread: 已在 UI 线程直接执行 (InvokeRequired={invoke_required})", level="debug")
            return True
        except Exception as exc:
            self._log(f"_run_on_ui_thread: Invoke/执行失败 → {exc}", level="debug")
            return False

    def _post_non_client_action(self, hwnd: int, hit_test: int) -> bool:
        """纯 Win32 备选：PostMessageW 跨线程投递 WM_NCLBUTTONDOWN，由 UI 线程处理，不依赖 pythonnet。"""
        try:
            user32 = ctypes.windll.user32
            posted = user32.PostMessageW(c_void_p(hwnd), 0x00A1, hit_test, 0)
            self._log(f"PostMessageW(WM_NCLBUTTONDOWN,{hit_test}) posted={bool(posted)}", level="debug")
            return bool(posted)
        except Exception as exc:
            self._log(f"PostMessageW 异常: {exc}", level="debug")
            return False

    def _begin_non_client_action(self, hit_test: int) -> bool:
        hwnd = self._hwnd()
        if sys.platform != "win32" or not hwnd:
            self._log(f"begin_non_client_action({hit_test}) 失败: win32={sys.platform == 'win32'} hwnd={hwnd}")
            return False
        self._log(f"begin_non_client_action({hit_test}) 顶层hwnd={hwnd} thread={threading.current_thread().name}")

        def action() -> None:
            ctypes.windll.user32.ReleaseCapture()
            ctypes.windll.user32.SendMessageW(c_void_p(hwnd), 0x00A1, hit_test, 0)

        if self._run_on_ui_thread(action):
            return True
        return self._post_non_client_action(hwnd, hit_test)

    def begin_move(self) -> bool:
        return self._begin_non_client_action(2)  #HTCAPTION

    def begin_resize(self, edge: str) -> bool:
        hit_test = self._RESIZE_HIT_TEST.get(str(edge))
        return bool(hit_test and self._begin_non_client_action(hit_test))

    def show_system_menu(self, x: int, y: int) -> bool:
        hwnd = self._hwnd()
        if sys.platform != "win32" or not hwnd:
            self._log(f"show_system_menu 失败: win32={sys.platform == 'win32'} hwnd={hwnd}")
            return False
        self._log(f"show_system_menu 顶层hwnd={hwnd} 坐标=({x},{y})")
        opened: list[bool] = []

        def action() -> None:
            user32 = ctypes.windll.user32
            user32.GetSystemMenu.restype = c_void_p
            menu = user32.GetSystemMenu(c_void_p(hwnd), False)
            if not menu:
                return
            opened.append(True)
            command = user32.TrackPopupMenu(c_void_p(menu), 0x0100, int(x), int(y), 0, c_void_p(hwnd), None)
            if command:
                user32.PostMessageW(c_void_p(hwnd), 0x0112, command, 0)

        if self._run_on_ui_thread(action):
            return bool(opened)

        try:
            lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
            posted = ctypes.windll.user32.PostMessageW(c_void_p(hwnd), 0x0112, 0xF090, lparam)
            self._log(f"show_system_menu 回退 PostMessageW(SC_MOUSEMENU) posted={bool(posted)}", level="debug")
            return bool(posted)
        except Exception as exc:
            self._log(f"show_system_menu 回退异常: {exc}", level="debug")
            return False


def _start_server(open_browser: bool) -> int:
    return sprite_composer.main(["--no-browser"] if not open_browser else [])



DARK_CAPTION_COLOR = "#102136"
LIGHT_CAPTION_COLOR = "#ffffff"
DWMWA_CAPTION_COLOR = 35


def _set_caption_color(hwnd: int, color: str) -> int:
    """把窗口标题栏（DWM 残条）颜色设为给定 #RRGGBB，返回 DWM 的 HRESULT。"""
    raw = str(color).lstrip("#")
    r, g, b = int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    colorref = c_long((b << 16) | (g << 8) | r)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(
        c_void_p(hwnd), DWMWA_CAPTION_COLOR, byref(colorref), 4)


def _enable_per_monitor_dpi_awareness() -> None:
    """在创建窗口前启用 Per-Monitor V2，避免 150%/200% 缩放时居中偏移。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass


def _log_error(exc: BaseException) -> str | None:
    """记录启动异常，优先写数据目录；失败时尝试程序目录与临时目录。"""
    candidates = []
    for factory in (app_paths.resolve_data_dir, app_paths.project_root):
        try:
            candidates.append(factory() / app_paths.STARTUP_LOG_NAME)
        except Exception:
            continue
    lines = [
        f"=== {datetime.now():%Y-%m-%d %H:%M:%S} ===",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        "",
    ]
    for log_path in candidates:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines))
            return str(log_path)
        except Exception:
            continue
    return None


def _notify_user(exc: BaseException, log_path: str | None) -> None:
    """尽量给用户可见提示，并回退到浏览器网页版保证界面可用。"""

    log_hint = f"\n\n详细日志已写入：{log_path}" if log_path else "\n\n（日志写入失败）"
    try:
        import tkinter.messagebox as messagebox

        messagebox.showerror(
            "冰翼Gal创作工坊 启动失败",
            "桌面窗口启动失败，已回退到浏览器网页版。\n\n"
            f"错误信息：{exc}" + log_hint,
        )
    except Exception:
        pass


    try:
        import webbrowser

        url = getattr(sprite_composer, "LAST_URL", None)
        if url:
            webbrowser.open(url)
        else:
            sprite_composer.main([])
    except Exception:
        pass


def _run() -> int:
    _enable_per_monitor_dpi_awareness()
    try:
        import webview  #type: ignore
    except Exception:
        webview = None

    if webview is not None:
        t = threading.Thread(target=_start_server, args=(False,), daemon=True)
        t.start()
        for _ in range(100):
            if getattr(sprite_composer, "LAST_URL", None):
                break
            time.sleep(0.1)
        url = getattr(sprite_composer, "LAST_URL", None)
        if not url:
            return _start_server(True)
        url = _append_shell_flag(url)
        #Initial limits are corrected to the active monitor after native creation.
        width, height = _target_size()
        scale = _dpi_scale()
        _left, _top, work_w, work_h = _work_area()
        limits = _layout_limits(work_w, work_h, scale)
        width, height = max(width, limits["width"]), max(height, limits["height"])
        min_w, min_h = limits["width"], limits["height"]
        options = {"width": round(width / scale), "height": round(height / scale),
                   "min_size": (int(min_w / scale), int(min_h / scale)),
                   "background_color": "#07111f", "text_select": True}

        centered = _centered_position(width, height)
        if centered:
            options["x"] = round(centered[0] / scale)
            options["y"] = round(centered[1] / scale)
        chrome_api = WindowChromeApi()
        _wl, _wt, _ww, _wh = _work_area()
        chrome_api._log(
            f"创建桌面窗口: shell已追加 url={url} 目标尺寸={width}x{height} "
            f"缩放={scale} 工作区={_ww}x{_wh} 居中逻辑坐标=({options.get('x')},{options.get('y')})"
        )
        options.update({
            "frameless": True,
            "easy_drag": False,
            "shadow": False,
            "js_api": chrome_api,
        })
        window = webview.create_window("冰翼Gal创作工坊", url, **options)
        chrome_api.bind(window)
        window.events.shown += chrome_api.configure_native_window
        window.events.loaded += chrome_api._refresh_webview_layout
        webview.start()
        return 0

    _start_server(True)
    return 0


def main() -> int:
    if sys.argv[1:2] == ['--draft-codec-worker']:
        # Run the native adapter in a child process without creating a UI.
        try:
            from draft_codec_worker import main as codec_main
            codec_main(sys.argv[2:])
            return 0
        except Exception:
            return 1
    try:
        return _run()
    except Exception as exc:
        _notify_user(exc, _log_error(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
