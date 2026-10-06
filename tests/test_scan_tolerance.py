"""损坏素材与缺失目录的扫描容错回归。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from sprite_composer import scan_characters, scan_lime_poses

VALID_SINFO_TEXT = "dress\t服装A\tx\t1\t默认\nface\t服装A\tx\t表情1\n"


def _lime_char(root: Path):
    character = root / "角色A"
    character.mkdir(parents=True)
    return character


def test_bad_sinfo_encoding_is_skipped_not_fatal(tmp_path):
    character = _lime_char(tmp_path)
    (character / "角色Aa.pbd").write_bytes(b"not a real pbd")
    (character / "角色Aa.sinfo").write_text(VALID_SINFO_TEXT, encoding="utf-8")

    warnings: list[str] = []
    result = scan_lime_poses(tmp_path, warnings)

    assert result == {}
    assert len(warnings) == 1
    assert "配方读取失败" in warnings[0]
    assert "UTF-16" in warnings[0]


def test_valid_utf16_sinfo_with_broken_pbd_is_skipped_not_fatal(tmp_path):
    character = _lime_char(tmp_path)
    (character / "角色Aa.pbd").write_bytes(b"garbage-not-a-pbd")
    (character / "角色Aa.sinfo").write_text(VALID_SINFO_TEXT, encoding="utf-16")

    warnings: list[str] = []
    result = scan_lime_poses(tmp_path, warnings)

    assert result == {}
    assert len(warnings) == 1
    assert "PBD 读取失败" in warnings[0]


def test_png_without_pos_metadata_is_skipped_not_fatal(tmp_path):
    root = tmp_path / "游戏A"
    character = root / "角色A"
    character.mkdir(parents=True)
    Image.new("RGBA", (8, 8)).save(character / "a0001.png")

    warnings: list[str] = []
    result = scan_characters(root, warnings)

    assert result == {}
    assert len(warnings) == 1
    assert "pos" in warnings[0]


def test_corrupt_png_is_skipped_not_fatal(tmp_path):
    root = tmp_path / "游戏A"
    character = root / "角色A"
    character.mkdir(parents=True)
    (character / "a0001.png").write_bytes(b"\x89PNG\r\n\x1a\nthis is not a decodable image")

    warnings: list[str] = []
    result = scan_characters(root, warnings)

    assert result == {}
    assert len(warnings) == 1


def test_missing_roots_are_silent(tmp_path):
    warnings: list[str] = []
    assert scan_characters(tmp_path / "不存在", warnings) == {}
    assert scan_lime_poses(tmp_path / "不存在", warnings) == {}
    assert warnings == []


def test_warnings_argument_is_optional(tmp_path):
    character = _lime_char(tmp_path)
    (character / "角色Aa.pbd").write_bytes(b"not a real pbd")
    (character / "角色Aa.sinfo").write_text(VALID_SINFO_TEXT, encoding="utf-8")

    assert scan_lime_poses(tmp_path) == {}
