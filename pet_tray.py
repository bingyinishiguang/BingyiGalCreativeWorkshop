"""取用精灵的独立 QtWidgets 托盘进程，通过状态文件与桌宠通信。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

#状态/命令文件名集中在此，桌宠那边从本模块导入，避免两处各写一份字符串。
TRAY_STATE_NAME = "pet-tray-state.json"
TRAY_CMD_NAME = "pet-tray-cmd.json"

POLL_MS = 400


def write_command(data_dir: Path, command: str, tier: str = "") -> None:
    """写一条命令给桌宠（托盘进程调用）。"""
    payload = {"command": command, "tier": tier, "at": time.time()}
    target = Path(data_dir) / TRAY_CMD_NAME
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


def take_command(data_dir: Path) -> dict | None:
    """读取并**消费**一条命令（桌宠进程调用）；没有则返回 None。"""
    target = Path(data_dir) / TRAY_CMD_NAME
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        target.unlink()
    except OSError:
        pass
    if not isinstance(payload, dict) or not isinstance(payload.get("command"), str):
        return None
    return payload


def write_state(data_dir: Path, visible: bool, size_tier: str, pid: int) -> None:
    """把桌宠的当前状态写给托盘（桌宠进程调用）。"""
    target = Path(data_dir) / TRAY_STATE_NAME
    payload = {"visible": bool(visible), "sizeTier": str(size_tier), "pid": int(pid)}
    temporary = target.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, target)
    except OSError:
        pass


def read_state(data_dir: Path) -> dict | None:
    try:
        payload = json.loads((Path(data_dir) / TRAY_STATE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def clear_state(data_dir: Path) -> None:
    """退出桌宠时删除状态文件，让独立托盘进程停止。"""
    for suffix in ("", ".tmp"):
        try:
            (Path(data_dir) / (TRAY_STATE_NAME + suffix)).unlink()
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == 259  #STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        #查不了就当作还活着，避免把用户正在用的桌宠误判掉。
        return True


def run_tray(data_dir: Path, icon_path: Path) -> int:
    """托盘进程主入口（需要 QtWidgets）。"""
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QAction, QActionGroup, QIcon
        from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    except ImportError as error:
        raise RuntimeError("托盘需要 PySide6 的 QtWidgets") from error

    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("冰翼取用精灵 · 托盘")

    icon = QIcon(str(icon_path)) if Path(icon_path).is_file() else QIcon()
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("冰翼取用精灵")

    menu = QMenu()
    toggle_action = QAction("显示桌宠", menu)
    toggle_action.triggered.connect(lambda: write_command(data_dir, "toggle"))
    menu.addAction(toggle_action)

    pin_action = QAction("把当前位置设为默认", menu)
    pin_action.triggered.connect(lambda: write_command(data_dir, "pin"))
    menu.addAction(pin_action)

    clear_action = QAction("恢复自动摆放", menu)
    clear_action.triggered.connect(lambda: write_command(data_dir, "clear-position"))
    menu.addAction(clear_action)

    menu.addSeparator()
    size_menu = menu.addMenu("桌宠大小")
    group = QActionGroup(menu)
    group.setExclusive(True)
    #档位文字在这里写死与 PET_SIZES 对应；托盘进程不导入 desktop_pet，
    #以免为了三个数字把整个 QtQuick 依赖拖进来。
    size_actions = {}
    for tier, label in (("S", "小 160×230"), ("M", "中 240×345"), ("L", "大 320×460")):
        action = QAction(label, menu)
        action.setCheckable(True)
        action.triggered.connect(lambda _checked=False, t=tier: write_command(data_dir, "size", t))
        group.addAction(action)
        size_menu.addAction(action)
        size_actions[tier] = action
    menu.addSeparator()

    quit_action = QAction("退出", menu)
    quit_action.triggered.connect(lambda: write_command(data_dir, "quit"))
    menu.addAction(quit_action)

    tray.setContextMenu(menu)

    def on_activated(reason):
        #左键单击 = 显示/隐藏开关（用户直觉）。双击在 Windows 上也会先来一个 Trigger。
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            write_command(data_dir, "toggle")

    tray.activated.connect(on_activated)
    tray.show()

    last_seen = {"state": None}

    def poll() -> None:
        state = read_state(data_dir)
        if state != last_seen["state"]:
            last_seen["state"] = state
            visible = bool(state.get("visible")) if state else True
            tier = str(state.get("sizeTier") or "M") if state else "M"
            toggle_action.setText("隐藏桌宠" if visible else "显示桌宠")
            action = size_actions.get(tier)
            if action is not None and not action.isChecked():
                action.setChecked(True)
        #桌宠没了就一起退出，别在托盘里留个孤儿图标。
        if state and not _pid_alive(int(state.get("pid") or 0)):
            tray.hide()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(POLL_MS)
    poll()

    return app.exec()


def tray_entry(data_dir: Path | None = None, icon: Path | None = None) -> int:
    """接收显式状态路径；冻结态无需重复解析桌宠的命令行。"""
    if data_dir is None or icon is None:
        raise SystemExit(2)
    return run_tray(Path(data_dir), Path(icon))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="冰翼取用精灵托盘（由桌宠自动拉起）")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--icon", type=Path, required=True)
    arguments = parser.parse_args()
    raise SystemExit(tray_entry(arguments.data_dir, arguments.icon))
