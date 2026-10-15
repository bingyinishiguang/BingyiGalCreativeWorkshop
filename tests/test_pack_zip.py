"""packs zip 导入的回归测试。"""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

import pack_import


def _make_zip(path: Path, entries: list[tuple[str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return path


def _pack_entries(prefix: str = "pack-lite") -> list[tuple[str, bytes]]:
    return [
        (f"{prefix}/pack.json", '{"formatVersion": 1}'.encode("utf-8")),
        (f"{prefix}/games/某作品/角色A/角色A.txt", b"canvas 1280 1280\n"),
        (f"{prefix}/games/某作品/角色A/角色A_1.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 300),
    ]


def test_valid_zip_is_analyzed(tmp_path):
    archive = _make_zip(tmp_path / "pack-lite.zip", _pack_entries())
    result = pack_import.analyze(str(archive), tmp_path / "packs")
    assert result.ok, result.errors
    assert result.pack_name == "pack-lite"
    assert result.txt_count == 1
    assert result.file_count == 3


def test_extract_normalizes_single_top_level_directory(tmp_path):
    packs = tmp_path / "packs"
    archive = _make_zip(tmp_path / "pack-lite.zip", _pack_entries())
    target = pack_import.extract_zip(archive, packs, "pack-lite")

    assert (target / "games").is_dir()
    assert (target / "pack.json").is_file()
    assert not (target / "pack-lite").exists(), "多套了一层，扫描器会找不到素材"


def test_extract_refuses_existing_pack_name(tmp_path):
    packs = tmp_path / "packs"
    archive = _make_zip(tmp_path / "pack-lite.zip", _pack_entries())
    pack_import.extract_zip(archive, packs, "pack-lite")
    with pytest.raises(FileExistsError):
        pack_import.extract_zip(archive, packs, "pack-lite")


def test_analyze_refuses_duplicate_name(tmp_path):
    packs = tmp_path / "packs"
    archive = _make_zip(tmp_path / "pack-lite.zip", _pack_entries())
    pack_import.extract_zip(archive, packs, "pack-lite")
    again = pack_import.analyze(str(archive), packs)
    assert not again.ok
    assert "已存在同名目录" in again.errors[0]


@pytest.mark.parametrize("member", [
    "../../../../被写坏了.txt",
    f"../逃出去.txt",
    "C:/Windows/坏.dll",
    "包/子目录/名字:带冒号.png",
    "包/CON/games/作品/角色/角色.txt",
    "包/COM1.txt",
    "包/NUL",
])
def test_unsafe_members_are_refused(tmp_path, member):
    archive = _make_zip(tmp_path / "恶意.zip", [(member, b"x"), ("好/games/作品/角色/角色.txt", b"canvas 1 1\n")])
    result = pack_import.analyze(str(archive), tmp_path / "packs")
    assert not result.ok
    assert "不安全路径" in result.errors[0], result.errors


def test_unsafe_member_is_not_written(tmp_path):
    packs = tmp_path / "packs"
    packs.mkdir()
    escape = tmp_path / "逃出去.txt"
    archive = _make_zip(tmp_path / "恶意.zip", [
        ("../../逃出去.txt", b"x"),
        ("好/games/作品/角色/角色.txt", b"canvas 1 1\n"),
    ])
    with pytest.raises(ValueError):
        pack_import.extract_zip(archive, packs, "好")
    assert not escape.exists(), "解压逃出了目标目录！"

    assert [p.name for p in packs.iterdir()] == []


def test_zip_without_media_is_refused(tmp_path):
    archive = _make_zip(tmp_path / "不是packs.zip", [("只有歌/歌.mp3", b"ID3" + b"\x00" * 400)])
    result = pack_import.analyze(str(archive), tmp_path / "packs")
    assert not result.ok
    assert "没有任何 .pbd / .txt" in result.errors[0]


def test_corrupt_zip_is_refused_with_plain_language(tmp_path):
    broken = tmp_path / "下载一半.zip"
    broken.write_bytes(b"PK\x03\x04" + b"garbage" * 200)
    result = pack_import.analyze(str(broken), tmp_path / "packs")
    assert not result.ok
    assert "不是有效的 zip" in result.errors[0]


def test_zip_bomb_total_size_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pack_import, "MAX_ZIP_TOTAL_BYTES", 1024)
    archive = _make_zip(tmp_path / "巨型.zip", [
        ("大/games/作品/角色/角色.txt", b"canvas 1 1\n"),
        ("大/games/作品/角色/大文件.bin", b"\x00" * 5000),
    ])
    result = pack_import.analyze(str(archive), tmp_path / "packs")
    assert not result.ok
    assert "过大" in result.errors[0]


def test_bad_pack_name_is_refused(tmp_path):
    archive = _make_zip(tmp_path / "pack-lite.zip", _pack_entries())
    for bad in ("../坏", "带/斜杠", "CON", "NUL", "名字:带冒号"):
        with pytest.raises(ValueError):
            pack_import.extract_zip(archive, tmp_path / "packs", bad)


def test_empty_pack_name_falls_back_to_file_name(tmp_path):
    archive = _make_zip(tmp_path / "pack-lite.zip", _pack_entries())
    target = pack_import.extract_zip(archive, tmp_path / "packs", "")
    assert target.name == "pack-lite"


def test_directory_import_still_works(tmp_path):
    source = tmp_path / "我的作品包" / "某作品" / "角色A"
    source.mkdir(parents=True)
    (source / "角色A.txt").write_text("canvas 1280 1280\n", encoding="utf-8")
    result = pack_import.analyze(str(tmp_path / "我的作品包"), tmp_path / "packs")
    assert result.ok, result.errors
    assert result.txt_count == 1
    target = pack_import.copy_pack(Path(result.source_root), tmp_path / "packs")
    assert (target / "某作品" / "角色A" / "角色A.txt").is_file()
