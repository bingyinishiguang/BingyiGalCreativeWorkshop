"""安装包「内置packs」自动登记的回归测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

import app_paths
import pack_import
import sprite_composer


def _make_pack(root: Path, name: str = "pack-lite") -> Path:
    pack = root / name / "games" / "某作品" / "角色A"
    pack.mkdir(parents=True)
    (pack / "角色A.txt").write_text("canvas 1280 1280\n", encoding="utf-8")
    (pack / "角色A_info.txt").write_text("dress\t制服\n", encoding="utf-8")
    (root / name / "pack.json").write_text('{"formatVersion": 1}', encoding="utf-8")
    return root / name


def test_bundled_pack_is_registered_as_link(tmp_path, monkeypatch):
    bundled = tmp_path / "程序目录" / "packs"
    bundled.mkdir(parents=True)
    _make_pack(bundled)
    data_dir = tmp_path / "数据"
    data_dir.mkdir()
    monkeypatch.setattr(app_paths, "bundled_packs_dir", lambda: bundled)
    monkeypatch.setattr(sprite_composer, "_startup_log", lambda message: None)

    registered = sprite_composer.register_bundled_packs(data_dir)

    assert registered == ["pack-lite"]
    links = pack_import.load_links(app_paths.links_file(data_dir))
    assert len(links) == 1
    assert Path(links[0]["path"]) == (bundled / "pack-lite").resolve()


def test_registration_is_idempotent(tmp_path, monkeypatch):
    bundled = tmp_path / "程序目录" / "packs"
    bundled.mkdir(parents=True)
    _make_pack(bundled)
    data_dir = tmp_path / "数据"
    data_dir.mkdir()
    monkeypatch.setattr(app_paths, "bundled_packs_dir", lambda: bundled)
    monkeypatch.setattr(sprite_composer, "_startup_log", lambda message: None)

    sprite_composer.register_bundled_packs(data_dir)
    again = sprite_composer.register_bundled_packs(data_dir)

    assert again == []
    assert len(pack_import.load_links(app_paths.links_file(data_dir))) == 1


def test_empty_bundled_dir_registers_nothing(tmp_path, monkeypatch):
    bundled = tmp_path / "程序目录" / "packs"
    (bundled / "空目录").mkdir(parents=True)
    data_dir = tmp_path / "数据"
    data_dir.mkdir()
    monkeypatch.setattr(app_paths, "bundled_packs_dir", lambda: bundled)
    monkeypatch.setattr(sprite_composer, "_startup_log", lambda message: None)

    assert sprite_composer.register_bundled_packs(data_dir) == []
    assert pack_import.load_links(app_paths.links_file(data_dir)) == []


def test_missing_bundled_dir_is_harmless(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "bundled_packs_dir", lambda: tmp_path / "不存在")
    monkeypatch.setattr(sprite_composer, "_startup_log", lambda message: None)
    assert sprite_composer.register_bundled_packs(tmp_path) == []


def test_bundled_packs_dir_follows_program_root(monkeypatch, tmp_path):
    monkeypatch.setattr(app_paths, "project_root", lambda: tmp_path)
    assert app_paths.bundled_packs_dir() == tmp_path / "packs"


def test_registration_happens_before_scanning():
    source = (Path(__file__).resolve().parents[1] / "sprite_composer.py").read_text(encoding="utf-8")
    scan_body = source.split("def perform_scan(", 1)[1]

    register_at = scan_body.find("register_bundled_packs(data_dir)")
    scan_at = scan_body.find("discover_pack_game_roots(")

    assert register_at != -1, "perform_scan() 里没有调用 register_bundled_packs"
    assert scan_at != -1, "perform_scan() 里没有调用 discover_pack_game_roots"
    assert register_at < scan_at, (
        "register_bundled_packs 必须在 discover_pack_game_roots 之前调用，"
        "否则首次启动扫不到内置packs"
    )
