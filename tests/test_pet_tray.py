"""托盘与桌宠之间的文件协议测试。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pet_tray import (TRAY_CMD_NAME, TRAY_STATE_NAME, clear_state, read_state,
                      take_command, write_command, write_state)


class CommandProtocolTest(unittest.TestCase):
    def test_write_then_take_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            write_command(data, "toggle")
            payload = take_command(data)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["command"], "toggle")

    def test_take_is_destructive(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            write_command(data, "pin")
            self.assertIsNotNone(take_command(data))
            self.assertIsNone(take_command(data), "同一条命令不应被执行两次")
            self.assertFalse((data / TRAY_CMD_NAME).exists())

    def test_take_without_file_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(take_command(Path(directory)))

    def test_take_rejects_corrupt_or_unknown_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            target = data / TRAY_CMD_NAME
            target.write_text("{不是合法JSON", encoding="utf-8")
            self.assertIsNone(take_command(data))
            target.write_text(json.dumps({"command": 123}), encoding="utf-8")
            self.assertIsNone(take_command(data), "命令必须是字符串")
            target.write_text(json.dumps("just-a-string"), encoding="utf-8")
            self.assertIsNone(take_command(data), "顶层必须是对象")

    def test_size_command_carries_tier(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            write_command(data, "size", "L")
            payload = take_command(data)
            self.assertEqual(payload["command"], "size")
            self.assertEqual(payload["tier"], "L")


class StateProtocolTest(unittest.TestCase):
    def test_write_then_read_state(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            write_state(data, True, "M", 4242)
            state = read_state(data)
            self.assertEqual(state, {"visible": True, "sizeTier": "M", "pid": 4242})

    def test_state_reflects_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            write_state(data, False, "S", 7)
            state = read_state(data)
            self.assertFalse(state["visible"])
            self.assertEqual(state["sizeTier"], "S")

    def test_read_missing_or_corrupt_state_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            self.assertIsNone(read_state(data))
            (data / TRAY_STATE_NAME).write_text("坏文件", encoding="utf-8")
            self.assertIsNone(read_state(data))

    def test_clear_state_removes_file(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            write_state(data, False, "L", 999)
            self.assertIsNotNone(read_state(data))
            clear_state(data)
            self.assertIsNone(read_state(data), "清理后不应还能读到状态")

    def test_clear_state_is_safe_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            clear_state(Path(directory))  #不应抛异常

    def test_state_file_is_atomic_no_tmp_left_behind(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            for _ in range(3):
                write_state(data, True, "L", 1)
            leftovers = [p.name for p in data.iterdir() if p.suffix == ".tmp"]
            self.assertEqual(leftovers, [], f"留下了临时文件：{leftovers}")


class FrozenTrayLaunchTest(unittest.TestCase):
    """冻结态拉起托盘的代码路径必须真的能走通。"""

    def test_frozen_branch_start_tray_process_does_not_raise(self):
        root = Path(__file__).resolve().parent.parent
        script = r'''
import os, sys, tempfile
from pathlib import Path
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, sys.argv[1])
import desktop_pet

tray_dir = Path(tempfile.mkdtemp()) / "tray"
tray_dir.mkdir(parents=True, exist_ok=True)
icon = Path(sys.argv[1]) / "ui" / "avatar-fox-round.png"
if not icon.is_file():
    icon = Path(sys.argv[1]) / "brand-assets" / "app.ico"

# ── 关键：伪造冻结态，强制走 `getattr(sys, "frozen", False)` 为真的分支 ──
sys.frozen = True

logs = []
desktop_pet._topmost_log = lambda message: logs.append(str(message))

try:
    process = desktop_pet.launch_tray_process(tray_dir, icon)
except UnboundLocalError as error:
    print("RAISED_UNBOUND:" + str(error))
    raise SystemExit(3)

print("OK")
for line in logs:
    print("LOG:" + line)
if process is not None:
    process.terminate()
'''
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "frozen_probe.py"
            probe.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(probe), str(root)],
                capture_output=True, text=True, timeout=120, cwd=str(root),
                #子进程输出显式使用 UTF-8，避免 Windows 默认编码差异。
                encoding="utf-8", errors="replace")
        combined = (result.stdout or "") + (result.stderr or "")
        self.assertNotIn(
            "UnboundLocalError", combined,
            f"冻结态拉起托盘时抛了 UnboundLocalError（就是这次修的 bug）：\n{combined}")
        self.assertIn(
            "OK", (result.stdout or ""),
            f"探针没跑完（说明真的抛了异常）：\nstdout={result.stdout}\nstderr={result.stderr}")
        #日志里应能看到冻结态的目标（证明走的是 --tray 分支）
        self.assertIn("--tray", (result.stdout or ""),
                      f"冻结态应启动 `exe --tray`，日志：\n{result.stdout}")


if __name__ == "__main__":
    unittest.main()
