import tempfile
import unittest
from pathlib import Path

from PIL import Image

from desktop_pet import (DesktopPetState, PET_SIZES, build_gallery_page,
                         build_roster, clamp_to_area, cycle_size_tier,
                         default_pet_position, gallery_window_position,
                         next_index, prev_index, size_tier_label,
                         tier_for_size)
from sprite_library import SpriteLibrary


def _make_library(directory: str) -> SpriteLibrary:
    library = SpriteLibrary(Path(directory) / "Library")
    image = Image.new("RGBA", (40, 80), (0, 0, 0, 0))
    image.putpixel((20, 40), (30, 40, 50, 255))
    library.save("作品", "角色A", "校服", "a0001", "normal", image)
    library.save("作品", "角色B", "校服", "a0002", "normal", image)
    library.save("作品", "特殊角色", "泳衣", "a0001", "swimwear", image)
    return library


class RosterTest(unittest.TestCase):
    def test_build_roster_only_normal_and_sorted(self):
        with tempfile.TemporaryDirectory() as directory:
            library = _make_library(directory)
            roster = build_roster(library)
            #特殊分区不进入桌宠列表
            self.assertEqual(len(roster), 2)
            self.assertTrue(all(item["category"] == "normal" for item in roster))
            self.assertFalse(any(item["missing"] for item in roster))

    def test_gallery_page_search_favorite_and_thumbnails(self):
        with tempfile.TemporaryDirectory() as directory:
            library = _make_library(directory)
            first = build_roster(library)[0]
            library.update(first["id"], False, "我的收藏", "", True, ["开心"])

            page = build_gallery_page(library, "开心", True, 0, 60)
            self.assertEqual(page["total"], 1)
            self.assertEqual(len(page["items"]), 1)
            self.assertTrue(page["items"][0]["imagePath"].is_file())
            self.assertLessEqual(page["limit"], 100)

    def test_cycle_wraps_around(self):
        self.assertEqual(next_index(3, 0), 1)
        self.assertEqual(next_index(3, 2), 0)  #到最后一张后回到第一张
        self.assertEqual(prev_index(3, 0), 2)  #第一张再上一张到最后一张
        self.assertEqual(prev_index(3, 2), 1)
        self.assertEqual(next_index(0, 0), -1)  #空列表安全
        self.assertEqual(prev_index(1, 0), 0)  #单张原地循环


class GalleryFilterTest(unittest.TestCase):
    """回归检查：GalleryFilterTest。"""

    def test_filters_by_tag_game_and_character(self):
        with tempfile.TemporaryDirectory() as directory:
            library = _make_library(directory)
            first = build_roster(library)[0]
            library.update(first["id"], False, "带标签的", "", True, ["开心", "开场"])

            by_tag = build_gallery_page(library, "", False, 0, tag="开心")
            self.assertEqual(by_tag["total"], 1)
            self.assertEqual(by_tag["items"][0]["item"]["character"], first["character"])

            by_game = build_gallery_page(library, "", False, 0, game="作品")
            self.assertEqual(by_game["total"], 2)

            by_character = build_gallery_page(library, "", False, 0, character="角色A")
            self.assertEqual(by_character["total"], 1)

            #界面要靠这三份清单填下拉框与标签芯片
            self.assertIn("开心", by_tag["tags"])
            self.assertIn("作品", by_tag["games"])
            self.assertIn("角色A", by_tag["characters"])

    def test_page_carries_face_url_for_the_round_badge(self):
        with tempfile.TemporaryDirectory() as directory:
            library = _make_library(directory)
            page = build_gallery_page(library, "", False, 0)
            self.assertTrue(page["items"])
            #分页只返回图片路径，Qt 桥按相同图片生成头部特写。
            #这里锁住"每张卡片都有图可裁"这个前提。
            for row in page["items"]:
                self.assertTrue(row["imagePath"].is_file())

    def test_gallery_rect_is_remembered_and_survives_pet_save(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            self.assertIsNone(state.load()["galleryRect"])
            state.save_gallery_rect(1200, 40, 460, 640)
            self.assertEqual(state.load()["galleryRect"],
                             {"x": 1200, "y": 40, "width": 460, "height": 640})
            #桌宠自己保存几何时不能把总览那份弄丢
            state.save(100, 100, 240, 345, "abc", "M")
            self.assertEqual(state.load()["galleryRect"]["width"], 460)

    def test_gallery_rect_rejects_nonsense(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            state.file.write_text('{"galleryRect": {"x": 0, "y": 0, "width": 5, "height": 5}}',
                                  encoding="utf-8")
            self.assertIsNone(state.load()["galleryRect"], "过小尺寸应被拒绝")
            state.file.write_text('{"galleryRect": "nonsense"}', encoding="utf-8")
            self.assertIsNone(state.load()["galleryRect"], "非对象应被拒绝")


class DefaultPositionTest(unittest.TestCase):
    """回归检查：DefaultPositionTest。"""

    def test_default_position_absent_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            loaded = state.load()
            self.assertIsNone(loaded["defaultX"])
            self.assertIsNone(loaded["defaultY"])

    def test_pin_then_survives_pet_geometry_save(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            state.save_default_position(700, 300)
            self.assertEqual((state.load()["defaultX"], state.load()["defaultY"]), (700, 300))
            #模拟用户又拖了桌宠：save() 会整份覆写状态文件
            state.save(999, 888, 240, 345, "abc", "M")
            loaded = state.load()
            self.assertEqual((loaded["defaultX"], loaded["defaultY"]), (700, 300),
                             "拖动桌宠不应清掉用户钉住的默认位置")
            self.assertEqual((loaded["x"], loaded["y"]), (999, 888))

    def test_clear_restores_auto_placement(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            state.save_default_position(700, 300)
            state.save(700, 300, 240, 345, "abc", "M")
            state.clear_default_position()
            loaded = state.load()
            self.assertIsNone(loaded["defaultX"])
            self.assertIsNone(loaded["defaultY"])
            self.assertIsNone(loaded["x"], "上次位置也要清，否则不会走自动摆放")
            self.assertIsNone(loaded["y"])

    def test_clear_default_only_keeps_last_position(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            state.save_default_position(700, 300)
            state.save(700, 300, 240, 345, "abc", "M")
            state.clear_default_only()
            loaded = state.load()
            self.assertIsNone(loaded["defaultX"])
            self.assertEqual((loaded["x"], loaded["y"]), (700, 300),
                             "clear_default_only 应保留上次位置")

    def test_corrupt_default_position_falls_back_to_none(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            state.file.write_text('{"defaultX": "左边", "defaultY": null}', encoding="utf-8")
            loaded = state.load()
            self.assertIsNone(loaded["defaultX"], "非数字应被忽略")
            self.assertIsNone(loaded["defaultY"])


class SizeTierLabelTest(unittest.TestCase):
    def test_labels_cover_all_tiers(self):
        for tier in PET_SIZES:
            self.assertTrue(size_tier_label(tier))
        self.assertEqual(size_tier_label("S"), "小")
        self.assertEqual(size_tier_label("M"), "中")
        self.assertEqual(size_tier_label("L"), "大")

    def test_tier_for_size_roundtrip(self):
        for tier, (width, height) in PET_SIZES.items():
            self.assertEqual(tier_for_size(width, height), tier)
        self.assertIsNone(tier_for_size(123, 456), "非标准尺寸应返回 None")


class StateTest(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            state.save(120, 240, 320, 460, "abc123", "L")
            loaded = state.load()
            self.assertEqual(loaded["x"], 120)
            self.assertEqual(loaded["y"], 240)
            self.assertEqual(loaded["width"], 320)
            self.assertEqual(loaded["height"], 460)
            self.assertEqual(loaded["sizeTier"], "L")
            self.assertEqual(loaded["spriteId"], "abc123")

    def test_load_missing_or_corrupt_returns_default(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            default = state.load()
            self.assertIsNone(default["x"])
            self.assertEqual(default["width"], DesktopPetState.DEFAULT_WIDTH)
            self.assertEqual(default["sizeTier"], "M")
            #写坏状态文件后仍回退默认，不抛异常
            state.file.write_text("{不是合法JSON", encoding="utf-8")
            self.assertEqual(state.load(), default)

    def test_legacy_large_state_migrates_to_new_medium_default(self):
        with tempfile.TemporaryDirectory() as directory:
            state = DesktopPetState(Path(directory))
            state.file.write_text('{"x": 10, "y": 20, "width": 320, "height": 460}',
                                  encoding="utf-8")
            loaded = state.load()
            self.assertEqual(loaded["sizeTier"], "M")
            self.assertEqual((loaded["width"], loaded["height"]), PET_SIZES["M"])

    def test_clamp_keeps_window_on_screen(self):
        #完全跑出右下会被拉回
        self.assertEqual(clamp_to_area(5000, 5000, 320, 460, 0, 0, 1920, 1080),
                         (1600, 620))
        #完全跑出左上会被拉回
        self.assertEqual(clamp_to_area(-500, -500, 320, 460, 0, 0, 1920, 1080),
                         (0, 0))
        #正常位置保持不变
        self.assertEqual(clamp_to_area(100, 100, 320, 460, 0, 0, 1920, 1080),
                         (100, 100))

    def test_default_position_is_right_and_lower_with_taskbar_margin(self):
        x, y = default_pet_position(240, 345, 0, 0, 1920, 1040)
        self.assertEqual(x, 1642)
        self.assertEqual(y, 645)
        self.assertLessEqual(y + 345, 1040 - 16)

    def test_gallery_center_matches_pet_center(self):
        pet_x, pet_y, pet_w, pet_h = 1500, 600, 240, 345
        gallery_w, gallery_h = 480, 640
        x, y = gallery_window_position(pet_x, pet_y, pet_w, pet_h,
                                       gallery_w, gallery_h, 0, 0, 1920, 1040)
        assert x == pet_x + pet_w // 2 - gallery_w // 2, "中心 x 应对齐桌宠中心"
        #y 会被夹进工作区，所以验"未夹紧时同心、夹紧后不越界"
        ideal_y = pet_y + pet_h // 2 - gallery_h // 2
        assert y == max(10, min(ideal_y, 1040 - 10 - gallery_h))
        assert y >= 10 and y + gallery_h <= 1040 - 10
        #桌宠贴左边缘：同心位置会跑出屏幕（20+120-240 = -100），所以被夹到左边界
        x2, y2 = gallery_window_position(20, 850, 240, 345, 480, 640, 0, 0, 1920, 1040)
        assert x2 == 10, "越界时必须夹到工作区左边"
        assert y2 + 640 <= 1040 - 10

    def test_size_tiers_cycle_and_default_to_medium(self):
        self.assertEqual(cycle_size_tier("S"), "M")
        self.assertEqual(cycle_size_tier("M"), "L")
        self.assertEqual(cycle_size_tier("L"), "S")
        self.assertEqual(cycle_size_tier("bad"), "M")
        self.assertEqual(PET_SIZES[DesktopPetState.DEFAULT_TIER], (240, 345))


class MalformedStateTest(unittest.TestCase):
    """状态文件被写坏时桌宠必须照常启动。"""

    CASES = (
        '{"x": 1e309, "y": 1, "width": 300, "height": 400}',
        '{"x": NaN, "y": Infinity, "width": 300, "height": 400}',
        '{"x": -Infinity, "y": 5, "width": 300, "height": 400}',
        '{"width": Infinity, "height": NaN}',
        '{"galleryRect": {"x": Infinity, "y": 0, "width": 400, "height": 500}}',
        '{"galleryRect": {"x": 0, "y": 0, "width": NaN, "height": 500}}',
        '{"defaultX": 1e309, "defaultY": NaN}',
        "not json at all",
        "[1, 2, 3]",
        '{"x": "左", "y": {}}',
        "",
    )

    def test_malformed_state_files_never_raise(self):
        import app_paths

        for payload in self.CASES:
            with self.subTest(payload=payload[:40]):
                with tempfile.TemporaryDirectory() as directory:
                    (Path(directory) / app_paths.PET_STATE_NAME).write_text(payload, encoding="utf-8")
                    loaded = DesktopPetState(Path(directory)).load()  #不应抛异常
                    #至少要落回可用的默认几何
                    self.assertGreaterEqual(loaded["width"], 80)
                    self.assertGreaterEqual(loaded["height"], 80)
                    self.assertIn(loaded["sizeTier"], PET_SIZES)


if __name__ == "__main__":
    unittest.main()
