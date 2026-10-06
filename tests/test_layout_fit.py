"""布局回归：用真实浏览器内核量"按钮到底在不在视口内"。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
CHECKER = ROOT / "tools" / "check_layout.py"

REQUIRED_VISIBLE = ["download", "save-library", "open-custom-batch", "batch-library-quick"]
VIEWPORT = (1280, 720)


def _find_port() -> int | None:
    """找一个正在运行的开发实例端口；没有就跳过（不硬造环境）。"""
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
             "Where-Object { (Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
             "Where-Object { $_.CommandLine -like '*BingyiGalCreativeWorkshop*' }).ProcessId -contains "
             "$_.OwningProcess } | Select-Object -First 1).LocalPort"],
            capture_output=True, text=True, timeout=90)
    except Exception:
        return None
    text = (completed.stdout or "").strip()
    return int(text) if text.isdigit() else None


def test_workbench_fits_one_screen():
    port = _find_port()
    if not port:
        pytest.skip("没有正在运行的开发实例（这条用例需要一个已启动的服务）")
    if not PYTHON.is_file():
        pytest.skip("找不到项目虚拟环境的 python")

    environment = dict(os.environ)
    environment.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu --no-sandbox")
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        completed = subprocess.run(
            [str(PYTHON), str(CHECKER), f"http://127.0.0.1:{port}",
             str(VIEWPORT[0]), str(VIEWPORT[1])],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180, cwd=str(ROOT), env=environment)
    except subprocess.TimeoutExpired:
        pytest.skip("测量超时（QtWebEngine 在离屏环境偶发起不来）")

    output = completed.stdout or ""
    start = output.find("{")
    end = output.rfind("}")
    if start < 0 or end <= start:
        pytest.skip(f"没拿到测量结果，输出尾部：{output[-300:]}")

    data = json.loads(output[start:end + 1])
    measure = data.get("measure") or data

    assert measure["pageScroll"]["mustScroll"] is False, (
        f"整个页面需要滚动才能看全：scrollHeight={measure['pageScroll']['scrollH']} "
        f"> clientHeight={measure['pageScroll']['clientH']}")

    missing = [name for name in REQUIRED_VISIBLE
               if measure["items"].get(name, {}).get("inViewport") is False]
    assert not missing, f"这些按钮不在视口内：{missing}"

    rects = [measure["items"][name]["rect"] for name in REQUIRED_VISIBLE]
    assert all(rect and rect["w"] > 0 and rect["h"] > 0 for rect in rects), "按钮几何异常"
