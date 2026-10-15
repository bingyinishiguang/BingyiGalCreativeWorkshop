"""文件选择与解析器导入回归。"""
from __future__ import annotations

from pathlib import Path

import file_dialog

ROOT = Path(__file__).resolve().parents[1]


def test_split_multi_single_file():
    assert file_dialog._split_multi("F:\\素材\\紬_01.png\0\0") == ["F:\\素材\\紬_01.png"]


def test_split_multi_many_files():
    payload = "F:\\素材\0紬_01.png\0紬_02.png\0紬_03.png\0\0"
    assert file_dialog._split_multi(payload) == [
        str(Path("F:\\素材") / "紬_01.png"),
        str(Path("F:\\素材") / "紬_02.png"),
        str(Path("F:\\素材") / "紬_03.png"),
    ]


def test_split_multi_ignores_trailing_garbage():
    payload = "F:\\素材\0a.png\0b.png\0\0\x01\x02junk"
    assert file_dialog._split_multi(payload) == [
        str(Path("F:\\素材") / "a.png"),
        str(Path("F:\\素材") / "b.png"),
    ]


def test_split_multi_empty():
    assert file_dialog._split_multi("") == []
    assert file_dialog._split_multi("\0\0") == []


def test_browse_reads_raw_buffer_not_value():
    source = (ROOT / "file_dialog.py").read_text(encoding="utf-8")


    assert "_split_multi(buffer.value)" not in source, (
        "多选解析不能用 buffer.value（遇第一个 NUL 就截断，只会拿到目录）"
    )
    assert "ctypes.string_at" in source, "应按原始缓冲区读取"


def test_escape_html_is_defined_when_used():
    source = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    if "escapeHtml(" in source:
        assert "function escapeHtml(" in source or "const escapeHtml" in source, (
            "app.js 调用了 escapeHtml 却没有定义它——会抛 ReferenceError，"
            "并被 catch 伪装成网络故障"
        )
