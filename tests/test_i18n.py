"""Language selection, translated UI and unchanged device/config identities."""
import json
import os
import string
import tempfile
import types
import unittest
from unittest import mock

from test_hide_rename import HideRenameTestCase, hb, make_app, dev
import i18n
import flyout
import history


class CatalogueTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")

    def test_system_language_and_english_fallback(self):
        for language in ("zh_TW", "zh-HK", "zh-MO", "zh-Hant", "zh-Hant-TW"):
            with mock.patch.object(i18n, "system_language", return_value=language):
                self.assertEqual(i18n.resolve_language("auto"), "zh-TW")
        for language in ("en-US", "zh-CN", "zh-Hans", "ja-JP", None, "bogus"):
            with mock.patch.object(i18n, "system_language", return_value=language):
                self.assertEqual(i18n.resolve_language("auto"), "en")
        with mock.patch.object(i18n, "system_language", return_value="en-US"):
            self.assertEqual(i18n.resolve_language("zh-TW"), "zh-TW")

    def test_catalogue_keeps_every_format_field(self):
        formatter = string.Formatter()
        fields = lambda text: {field for _, field, _, _ in formatter.parse(text) if field}
        for english, chinese in i18n.ZH_TW.items():
            with self.subTest(message=english):
                self.assertEqual(fields(english), fields(chinese))

    def test_unknown_strings_and_braces_in_names_are_preserved(self):
        i18n.set_language("zh-TW")
        self.assertEqual(i18n.tr("AULA NOVA75 {custom}"), "AULA NOVA75 {custom}")
        self.assertEqual(i18n.tr("Show {name}", name="鍵盤 {01}"), "顯示 鍵盤 {01}")

    def test_notifications_status_and_estimates(self):
        i18n.set_language("zh-TW")
        self.assertEqual(hb.low_battery_text("NOVA75", 10, False), "NOVA75：剩餘 10% 電量，請充電。")
        self.assertEqual(hb.fully_charged_text("NOVA75"), "NOVA75 已充飽電。")
        self.assertIn("下載 v2.0…", hb.update_text("2.0"))
        status = dev(name="My NOVA75", level=77)
        status.charging = True
        self.assertEqual(hb.describe(status), "My NOVA75: 77%，充電中")
        status.charging, status.online = False, False
        self.assertIn("裝置休眠中", hb.describe(status))
        status.level = None
        self.assertIn("未連線", hb.describe(status))
        self.assertEqual(history.format_left(1800), "剩餘使用時間不到 1 小時")
        self.assertEqual(history.format_left(7200), "約可再使用 2 小時")
        self.assertEqual(history.format_left(172800), "約可再使用 2 天")

    def test_coarse_provider_status_translates_without_mutating_it(self):
        i18n.set_language("zh-TW")
        status = dev()
        for source, translated in [("about 55% (medium)", "約 55%（中）"),
                                   ("about 90% (full)", "約 90%（滿）"),
                                   ("about 25%", "約 25%"),
                                   ("connected, battery level not reported yet", "已連線，尚未回報電量")]:
            status.approx = source
            self.assertEqual(hb.device_state(status), translated)
            self.assertEqual(status.approx, source)

    def test_invalid_language_setting_falls_back_without_losing_other_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "config.json")
            with mock.patch.object(hb, "CONFIG_PATH", path):
                for value in (None, True, [], "zh-CN", "invalid"):
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump({"language": value, "interval": 120}, f)
                    cfg = hb.load_config()
                    self.assertEqual((cfg["language"], cfg["interval"]), ("auto", 120))
                hb.save_config(dict(cfg, language="zh-TW"))
                self.assertEqual(hb.load_config()["language"], "zh-TW")

    def test_chinese_header_wrap_does_not_lose_characters(self):
        text = "未顯示裝置（已隱藏十二個裝置）"
        lines = flyout.wrap(text, 40, lambda value: len(value) * 13)
        self.assertEqual("".join(lines), text)
        self.assertTrue(all(len(line) * 13 <= 40 for line in lines))


class LanguageMenuTests(HideRenameTestCase):
    def setUp(self):
        super().setUp()
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.app = make_app()

    def test_switch_rebuilds_menus_tooltips_and_persists_choice(self):
        self.app.apply([dev(name="NOVA75 {我的}")])
        owner = next(iter(self.app.icons.values()))
        owner.status.charging = True
        prefs = next(i.submenu for i in self.app.build_menu(owner).items if i.text == "Preferences")
        languages = next(i.submenu for i in prefs.items if i.text == "Language")
        next(i for i in languages.items if i.text == "繁體中文")(None)
        self.assertEqual(self.saved[-1]["language"], "zh-TW")
        self.assertIn("充電中", owner.titles[-1])
        self.assertIn("NOVA75 {我的}", owner.titles[-1])
        prefs = next(i.submenu for i in owner.icon.menu.items if i.text == "偏好設定")
        languages = next(i.submenu for i in prefs.items if i.text == "語言")
        self.assertTrue(next(i for i in languages.items if i.text == "繁體中文").checked)
        counter = next(i for i in prefs.items if i.text == "電量檢查間隔")
        self.assertEqual(counter.label(), "1 分鐘")
        next(i for i in languages.items if i.text == "English")(None)
        self.assertIn("charging", owner.titles[-1])
        self.assertTrue(any(i.text == "Preferences" for i in owner.icon.menu.items))

    def test_placeholder_and_hidden_devices_localize(self):
        self.app.apply([])
        self.app.cfg["hidden"] = {"example": "My Keyboard"}
        self.app.set_language("zh-TW")
        self.assertIn("找不到裝置", self.app.placeholder.title)
        menu = self.app.placeholder.menu
        self.assertEqual(menu.items[0].text, "未顯示裝置（已隱藏 1 個）")
        hidden = next(i.submenu for i in menu.items if i.text == "已隱藏的裝置")
        self.assertEqual(list(hidden.items)[0].text, "顯示 My Keyboard")

    def test_held_low_alert_uses_stable_kind_across_language_switch(self):
        self.app.apply([dev(level=10)])
        owner = next(iter(self.app.icons.values()))
        self.app.set_language("zh-TW")
        with mock.patch.object(self.app, "quiet", return_value=True):
            self.app.notify(owner.icon, owner.status.key, "電量不足", "Low battery")
        owner.status.charging = True
        self.app.set_language("en")
        with mock.patch.object(self.app, "notify_any") as notify:
            self.app.flush_held()
            notify.assert_not_called()

    def test_notification_title_is_translated_at_delivery(self):
        i18n.set_language("zh-TW")
        icon = types.SimpleNamespace(notify=mock.Mock())
        self.app.notify(icon, "device", "請充電", "Low battery")
        icon.notify.assert_called_once_with("請充電", "電量不足")
