"""拖出文件必须落到稳定目录，而且默认永不自动清理。"""
from __future__ import annotations

from pathlib import Path

import pytest

import app_paths
import windows_file_drag


@pytest.fixture
def drag_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "工作数据"
    data_dir.mkdir()

    monkeypatch.setattr(app_paths, "resolve_data_dir", lambda: data_dir, raising=False)
    previous = windows_file_drag.DRAG_COPY_DIR
    yield data_dir, tmp_path
    windows_file_drag.set_drag_dir(previous)


def _source_png(tmp_path: Path, name: str = "sprite.png") -> Path:
    from PIL import Image

    path = tmp_path / "src" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (12, 20), (10, 20, 30, 255)).save(path)
    return path


def test_default_dir_is_stable_dragout_folder(drag_env):
    data_dir, _ = drag_env
    directory = windows_file_drag.set_drag_dir(None)
    assert directory == data_dir / "exports" / "DragOut"

    assert directory.parts[-2:] == ("exports", "DragOut")
    assert "冰翼立绘拖出" not in str(directory)


def test_copy_lands_in_dragout_and_stays_after_successful_drop(drag_env, tmp_path):
    windows_file_drag.set_drag_dir(None)
    source = _source_png(tmp_path)
    target = windows_file_drag.make_draggable_copy(source, "华乃_校服_a0001")
    assert target.name == "华乃_校服_a0001.png"
    assert target.parent == windows_file_drag.DRAG_COPY_DIR
    assert target.is_file()


    windows_file_drag.cleanup_drag_copy(target, dropped=True, delay_seconds=0)
    assert target.is_file(), "投放成功后不能删除拖出文件，否则剪映工程会变成媒体丢失"


def test_cancelled_drop_cleans_up(drag_env, tmp_path):
    windows_file_drag.set_drag_dir(None)
    source = _source_png(tmp_path)
    target = windows_file_drag.make_draggable_copy(source, "取消的立绘")
    windows_file_drag.cleanup_drag_copy(target, dropped=False, delay_seconds=0)

    assert not target.exists(), "取消的拖放没有投出去，副本应当被清掉"


def test_no_time_based_auto_cleanup(drag_env, tmp_path):
    windows_file_drag.set_drag_dir(None)
    source = _source_png(tmp_path)
    target = windows_file_drag.make_draggable_copy(source, "很旧的立绘")
    import os
    import time

    old = time.time() - 48 * 60 * 60
    os.utime(target, (old, old))

    windows_file_drag.make_draggable_copy(source, "新的立绘")
    assert target.is_file(), "拖出目录不允许按时间自动清理（会毁掉剪映工程）"


def test_clear_drag_dir_is_manual_only(drag_env, tmp_path):
    windows_file_drag.set_drag_dir(None)
    source = _source_png(tmp_path)
    first = windows_file_drag.make_draggable_copy(source, "甲")
    second = windows_file_drag.make_draggable_copy(source, "乙")
    assert first.is_file() and second.is_file()

    removed = windows_file_drag.clear_drag_dir()
    assert removed == 2
    assert not first.exists() and not second.exists()


def test_migrate_moves_files_and_keeps_old_dir(drag_env, tmp_path):
    old_dir = tmp_path / "old-drag"
    new_dir = tmp_path / "new-drag"
    old_dir.mkdir()
    windows_file_drag.set_drag_dir(old_dir)
    source = _source_png(tmp_path)
    target = windows_file_drag.make_draggable_copy(source, "要搬走的立绘")

    moved = windows_file_drag.migrate_drag_dir(old_dir, new_dir)

    assert moved == 1
    assert (new_dir / target.name).is_file()
    assert old_dir.is_dir(), "旧目录必须保留（软删除原则）"
    assert not target.exists(), "文件应已搬走，不留重复"
