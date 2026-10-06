"""app_paths 路径解析测试：开发态锚定项目目录，冻结态走 AppData + 指针文件。"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import app_paths


class AppPathsTest(unittest.TestCase):
    def test_dev_mode_data_dir_is_project_workdir(self):
        with patch.object(app_paths, "is_frozen", return_value=False):
            data = app_paths.resolve_data_dir()
            self.assertEqual(data.name, "工作数据")
            self.assertEqual(data.parent, app_paths.project_root())

    def test_brand_reads_ui_brand_json(self):
        brand = app_paths.brand()
        self.assertEqual(brand.get("appName"), "冰翼Gal创作工坊")
        self.assertEqual(brand.get("appNameEn"), "BingyiGalCreativeWorkshop")

    def test_frozen_data_dir_prefers_existing_new_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            current = base / "BingyiGalCreativeWorkshop"
            legacy = base / "BingyiGalWorkshop"
            current.mkdir()
            legacy.mkdir()
            with patch.object(app_paths, "is_frozen", return_value=True), \
                 patch.dict(app_paths.os.environ, {"APPDATA": tmp}), \
                 patch.object(app_paths, "brand", return_value={"dataDirName": "BingyiGalCreativeWorkshop"}):
                self.assertEqual(app_paths.default_data_dir(), current)

    def test_frozen_data_dir_reuses_legacy_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "BingyiGalWorkshop"
            legacy.mkdir()
            (legacy / app_paths.POINTER_NAME).write_text("kept", encoding="utf-8")
            with patch.object(app_paths, "is_frozen", return_value=True), \
                 patch.dict(app_paths.os.environ, {"APPDATA": tmp}), \
                 patch.object(app_paths, "brand", return_value={"dataDirName": "BingyiGalCreativeWorkshop"}):
                self.assertEqual(app_paths.default_data_dir(), legacy)
                self.assertEqual(app_paths.pointer_file(), legacy / app_paths.POINTER_NAME)

    def test_frozen_data_dir_respects_configured_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "BingyiGalWorkshop").mkdir()
            with patch.object(app_paths, "is_frozen", return_value=True), \
                 patch.dict(app_paths.os.environ, {"APPDATA": tmp}), \
                 patch.object(app_paths, "brand", return_value={"dataDirName": "CustomWorkshop"}):
                self.assertEqual(app_paths.default_data_dir(), Path(tmp) / "CustomWorkshop")

    def test_pointer_round_trip_in_frozen_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_default = Path(tmp) / "appdata-default"
            custom = Path(tmp) / "custom-data"
            #会被悄悄重建出来并当成合法数据目录 —— 用户看到空库，新数据又写进这个空目录。
            custom.mkdir(parents=True)
            with patch.object(app_paths, "is_frozen", return_value=True), \
                 patch.object(app_paths, "default_data_dir", return_value=fake_default):
                self.assertEqual(app_paths.resolve_data_dir(), fake_default)
                app_paths.set_custom_data_dir(custom)
                self.assertEqual(app_paths.resolve_data_dir(), custom)
                app_paths.clear_custom_data_dir()
                self.assertEqual(app_paths.resolve_data_dir(), fake_default)

    def test_missing_pointer_target_is_not_created_and_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_default = Path(tmp) / "appdata-default"
            missing = Path(tmp) / "gone-drive" / "BingyiData"
            with patch.object(app_paths, "is_frozen", return_value=True), \
                 patch.object(app_paths, "default_data_dir", return_value=fake_default):
                app_paths.set_custom_data_dir(missing)
                self.assertEqual(app_paths.resolve_data_dir(), fake_default)
                self.assertFalse(missing.is_dir(), "不存在的指针目标不应被创建")
                self.assertTrue(app_paths.last_fallback_reason(), "回退必须给出原因，便于界面提示")

    def test_blank_or_relative_pointer_falls_back(self):
        for content in ("", "   \n ", "relative-data"):
            with tempfile.TemporaryDirectory() as tmp:
                fake_default = Path(tmp) / "appdata-default"
                pointer = Path(tmp) / "data-location.txt"
                pointer.write_text(content, encoding="utf-8")
                with patch.object(app_paths, "is_frozen", return_value=True), \
                     patch.object(app_paths, "default_data_dir", return_value=fake_default), \
                     patch.object(app_paths, "pointer_file", return_value=pointer):
                    self.assertEqual(app_paths.resolve_data_dir(), fake_default,
                                     f"指针内容 {content!r} 应回退默认目录")

    def test_packs_dir_dev_anchors_project(self):
        with patch.object(app_paths, "is_frozen", return_value=False):
            self.assertEqual(app_paths.packs_dir(), app_paths.project_root() / "sprite-packs")


class BetaDeadlineTest(unittest.TestCase):
    """内测期限。"""

    def _stamp(self, deadline, warn_days=7, message="内测期已结束"):
        with patch.object(app_paths, "brand", return_value={
                "appName": "冰翼Gal创作工坊", "betaDeadline": deadline,
                "betaWarnDays": warn_days, "betaMessage": message}):
            return app_paths.build_stamp()

    def test_no_deadline_configured(self):
        info = self._stamp("")
        self.assertFalse(info["configured"])
        self.assertFalse(info["expired"])
        self.assertFalse(info["warn"])
        self.assertIsNone(info["daysLeft"])

    def test_broken_deadline_is_treated_as_unconfigured(self):
        for bad in ("2026/10/31", "不是日期", "2026-13-45", "   "):
            info = self._stamp(bad)
            self.assertFalse(info["configured"], f"{bad!r} 应视为未配置")
            self.assertFalse(info["expired"], f"{bad!r} 不应被判为过期")

    def test_far_future_is_silent(self):
        info = self._stamp("2099-12-31")
        self.assertTrue(info["configured"])
        self.assertFalse(info["expired"])
        self.assertFalse(info["warn"], "还早的时候不该打扰用户")
        self.assertGreater(info["daysLeft"], 100)

    def test_within_warn_window(self):
        today = date.today()
        info = self._stamp((today + timedelta(days=3)).isoformat(), warn_days=7)
        self.assertFalse(info["expired"])
        self.assertTrue(info["warn"], "进入提醒窗口应给出提示")
        self.assertEqual(info["daysLeft"], 3)

    def test_expired(self):
        today = date.today()
        info = self._stamp((today - timedelta(days=5)).isoformat())
        self.assertTrue(info["expired"])
        self.assertFalse(info["warn"], "已过期就不再是警告窗口")
        self.assertEqual(info["daysLeft"], -5)

    def test_boundary_today_is_last_warning_day(self):
        today = date.today()
        info = self._stamp(today.isoformat(), warn_days=7)
        self.assertFalse(info["expired"])
        self.assertTrue(info["warn"])
        self.assertEqual(info["daysLeft"], 0)

    def test_message_is_passed_through_and_config_is_not_a_gate(self):
        info = self._stamp("2020-01-01", message="请找作者拿新包")
        self.assertEqual(info["message"], "请找作者拿新包")
        self.assertTrue(info["expired"])
        #期限配置仅用于提醒，不阻止使用。
        for forbidden in ("block", "blocked", "deny", "lock", "disabled"):
            self.assertNotIn(forbidden, info,
                             "内测期限是提醒不是拦截，不该出现阻止使用的字段")

    def test_public_brand_has_no_beta_deadline(self):
        info = app_paths.build_stamp()
        self.assertFalse(info["configured"])
        self.assertFalse(info["expired"])
        self.assertFalse(info["warn"])
        self.assertIsNone(info["daysLeft"])



if __name__ == "__main__":
    unittest.main()
