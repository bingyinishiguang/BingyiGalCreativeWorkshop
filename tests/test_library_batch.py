"""批量保存到立绘库 + 入库自动打标签 + 千张级吞吐。"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from library_tags import MAX_AUTO_TAGS, build_auto_tags
from sprite_library import SpriteLibrary

STRESS_COUNT = int(os.environ.get("BINGYI_STRESS_COUNT", "200"))
#只衡量入库耗时，不把合成时间计入图库性能指标。
#否则"千张压测"的瓶颈就会从合成变成写库。
MIN_SAVES_PER_SECOND = 8.0


def _sprite(seed: int) -> Image.Image:
    """造一张可区分的透明 PNG（不同 seed 内容不同，避免被判重复）。"""
    image = Image.new("RGBA", (48, 96), (0, 0, 0, 0))
    for x in range(8):
        for y in range(8):
            image.putpixel(((seed * 7 + x) % 48, (seed * 11 + y) % 96),
                           ((seed * 13) % 255, (seed * 29) % 255, (seed * 47) % 255, 255))
    return image


class AutoTagTest(unittest.TestCase):
    def test_builds_tags_from_metadata(self):
        tags = build_auto_tags({"game": "LimeLightLemonadeJam", "character": "卫哉",
                                "body": "制服｜动作1", "face": "21", "category": "normal"},
                               batch_label="千张压测")
        for expected in ("作品:LimeLightLemonadeJam", "角色:卫哉", "姿势:制服｜动作1",
                         "表情:21", "分区:普通", "千张压测", "批量入库"):
            self.assertIn(expected, tags, expected)
        self.assertLessEqual(len(tags), MAX_AUTO_TAGS)

    def test_special_category_and_dedup(self):
        tags = build_auto_tags({"game": "夜宴", "character": "七绪", "body": "泳衣", "face": "01",
                                "category": "swimwear"},
                               batch_label="角色:七绪", source="批量入库")
        self.assertIn("分区:特殊", tags)
        #重复标签只保留一份
        self.assertEqual(tags.count("角色:七绪"), 1)

    def test_does_not_invent_emotion_tags(self):
        tags = build_auto_tags({"game": "G", "character": "C", "body": "B", "face": "01"})
        for guess in ("微笑", "生气", "难过", "害羞"):
            self.assertNotIn(guess, tags)


class LibraryBatchSaveTest(unittest.TestCase):
    def test_save_with_tags_writes_and_reads_back(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            item = library.save("作品", "角色A", "校服", "a0001", "normal", _sprite(1),
                                ["作品:作品", "角色:角色A", "批量入库"])
            self.assertTrue(item["created"])
            self.assertIn("角色:角色A", item["tags"])

            listed = library.list(False, tag="角色:角色A")
            self.assertEqual(listed["total"], 1)
            self.assertIn("角色:角色A", listed["tags"])

    def test_duplicate_save_merges_new_tags(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            first = library.save("作品", "角色A", "校服", "a0001", "normal", _sprite(2), ["标签A"])
            again = library.save("作品", "角色A", "校服", "a0001", "normal", _sprite(2), ["标签B"])
            self.assertFalse(again["created"])
            self.assertTrue(again["duplicate"])
            self.assertIn("标签A", again["tags"])
            self.assertIn("标签B", again["tags"])

    def test_missing_tags_argument_still_works(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            item = library.save("作品", "角色A", "校服", "a0001", "normal", _sprite(3))
            self.assertEqual(item["tags"], [])


class StressTest(unittest.TestCase):
    def test_thousand_scale_throughput(self):
        with tempfile.TemporaryDirectory() as directory:
            library = SpriteLibrary(Path(directory) / "Library")
            started = time.perf_counter()
            for index in range(STRESS_COUNT):
                item = library.save("压测作品", f"角色{index % 7}", "校服",
                                    f"a{index:04d}", "normal", _sprite(index + 100),
                                    build_auto_tags({"game": "压测作品", "character": f"角色{index % 7}",
                                                     "body": "校服", "face": f"a{index:04d}"},
                                                    batch_label="千张压测"))
                self.assertTrue(item["created"], index)
            elapsed = time.perf_counter() - started
            rate = STRESS_COUNT / max(elapsed, 1e-6)
            projected = 1000 / rate
            print(f"\n[批次8 压测] 入库 {STRESS_COUNT} 张耗时 {elapsed:.2f}s "
                  f"= {rate:.1f} 张/秒；1000 张约 {projected:.1f}s")
            self.assertGreaterEqual(rate, MIN_SAVES_PER_SECOND,
                                    f"入库太慢：{rate:.1f} 张/秒，千张会拖到 {projected:.0f}s")

            total = library.list(False, limit=1)["total"]
            self.assertEqual(total, STRESS_COUNT)
            by_tag = library.list(False, tag="千张压测", limit=1)["total"]
            self.assertEqual(by_tag, STRESS_COUNT, "批量入库的标签要能一次找回整批")


if __name__ == "__main__":
    unittest.main()

def test_concurrent_save_merges_all_tags(tmp_path):
    import threading
    from PIL import Image

    library = SpriteLibrary(tmp_path / "Library")
    image = Image.new("RGBA", (60, 120), (10, 200, 30, 255))
    errors: list[str] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        try:
            library.save("作品并发", "角色并发", "校服", "a0001", "normal", image, [f"tag{index}"])
        except Exception as error:  #noqa: BLE001 - 测试要记录任何异常
            with lock:
                errors.append(f"{type(error).__name__}: {error}")

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    result = library.list(False, limit=10)
    assert errors == [], f"并发保存不应抛异常，实际: {errors}"
    assert result["total"] == 1, "同一张图并发保存只应留下 1 条记录"
    tags = result["items"][0].get("tags") or []
    assert len(tags) == 12, f"12 个并发标签必须全部保留，实际只有 {len(tags)}: {tags}"
    #不能留下孤儿 PNG（兜底分支删过自己写的那份）
    pngs = list((tmp_path / "Library" / "images").rglob("*.png"))
    assert len(pngs) == 1, f"磁盘上应只有 1 个 PNG，实际 {len(pngs)}"
