"""桌面窗口壳桥接测试。"""
from __future__ import annotations

import inspect
import sys

import pytest

import app_launcher
import app_paths


class FakeWindow:
    native = None

    def __init__(self):
        self.calls = []

    def minimize(self):
        self.calls.append("minimize")

    def maximize(self):
        self.calls.append("maximize")

    def restore(self):
        self.calls.append("restore")

    def destroy(self):
        self.calls.append("destroy")

    def toggle_fullscreen(self):
        self.calls.append("fullscreen")


def test_window_chrome_safe_controls_without_native_handle(tmp_path):
    window = FakeWindow()
    chrome = app_launcher.WindowChromeApi(log_path=tmp_path / "chrome.log")
    chrome.bind(window)

    assert chrome.get_state() == {"desktop": True, "maximized": False}
    chrome.minimize()
    chrome.toggle_maximize()
    chrome.toggle_fullscreen()
    chrome.close()

    assert window.calls == ["minimize", "maximize", "fullscreen", "destroy"]


def test_window_chrome_rejects_unknown_resize_edge(tmp_path):
    chrome = app_launcher.WindowChromeApi(log_path=tmp_path / "chrome.log")
    chrome.bind(FakeWindow())

    assert chrome.begin_resize("middle") is False
    assert chrome.begin_move() is False


def test_chrome_log_goes_to_injected_path(tmp_path):
    log_file = tmp_path / "chrome.log"
    chrome = app_launcher.WindowChromeApi(log_path=log_file)
    chrome.bind(FakeWindow())

    chrome.begin_move()

    assert log_file.exists()
    assert "hwnd" in log_file.read_text(encoding="utf-8")


def test_chrome_never_pollutes_real_diagnostic_log(tmp_path):
    real_log = app_paths.resolve_data_dir() / app_paths.STARTUP_LOG_NAME
    before = real_log.read_text(encoding="utf-8") if real_log.exists() else None

    #既覆盖「注入路径」，也覆盖「未注入路径」——后者在 pytest 进程内必须静默跳过。
    injected = app_launcher.WindowChromeApi(log_path=tmp_path / "chrome.log")
    injected.bind(FakeWindow())
    injected.begin_move()
    default = app_launcher.WindowChromeApi()
    default.bind(FakeWindow())
    default.begin_move()

    after = real_log.read_text(encoding="utf-8") if real_log.exists() else None
    assert after == before


def test_js_api_exposes_no_public_object_attributes(tmp_path):
    chrome = app_launcher.WindowChromeApi(log_path=tmp_path / "chrome.log")
    chrome.bind(FakeWindow())

    exposed = [
        name for name in dir(chrome)
        if not name.startswith("_")
        and not (inspect.ismethod(getattr(chrome, name)) or inspect.isfunction(getattr(chrome, name)))
    ]
    assert exposed == [], f"这些公开属性会被 pywebview 递归曝光，必须改为私有：{exposed}"


def test_centered_position_returns_real_coordinates():
    if sys.platform != "win32":
        pytest.skip("仅 Windows 有工作区概念")
    position = app_launcher._centered_position(1280, 840)
    assert position is not None, "SPI_GETWORKAREA 常量写错时这里会返回 None（窗口不居中）"
    x, y = position
    assert x >= 0 and y >= 0


@pytest.mark.parametrize("work,dpi", [((1920,1040),1), ((1920,1040),1.25),
                                    ((1366,728),1), ((1920,1040),1.5),
                                    ((1280,680),2), ((800,560),1)])
def test_layout_limits_fit_work_area_and_keep_usable_css(work, dpi):
    limits = app_launcher._layout_limits(*work, dpi)
    assert limits["width"] <= work[0] - app_launcher.WINDOW_MARGIN
    assert limits["height"] <= work[1] - app_launcher.WINDOW_MARGIN
    assert 0 < limits["fit"] <= 1
    border = app_launcher.math.ceil(16 * dpi)
    assert (limits["width"] - border) / (dpi * limits["fit"]) >= 1160 - 1e-7
    assert (limits["height"] - border) / (dpi * limits["fit"]) >= 740 - 1e-7


def test_layout_floor_tracks_measured_controls():
    base = app_launcher._layout_limits(2560, 1440, 1)
    measured = app_launcher._layout_limits(2560, 1440, 1, 1320, 800)
    assert measured["width"] > base["width"]
    assert measured["height"] > base["height"]


def test_fit_workspace_without_native_window_is_safe(tmp_path):
    chrome = app_launcher.WindowChromeApi(log_path=tmp_path / "chrome.log")
    chrome.bind(FakeWindow())
    assert chrome.fit_workspace()["width"] > 0
