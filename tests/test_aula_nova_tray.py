"""NOVA75 provider registration, tray percentage, alerts and preferences."""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_hide_rename import HideRenameTestCase, hb, make_app
from test_aula_nova import N, CAPTURE, FakeDevice, entry, reply
import i18n

REAL_DEVICE_ICON = hb.DeviceIcon


class NovaTrayTests(HideRenameTestCase):
    def setUp(self):
        super().setUp()
        self.app = make_app({"bluetooth": False, "percent_in_icon": True, "low": 20})
        self.app.providers = [p for p in hb.make_providers() if isinstance(p, N.AulaNovaProvider)]
        self.assertEqual(len(self.app.providers), 1)
        self.app.bt_cache, self.app._bt_dup_logged = [], set()
        self.clock = [1000.0]
        self.dev = FakeDevice(self.clock, replies=[CAPTURE])
        for patch in (
            mock.patch.object(N.hid, "device", return_value=self.dev),
            mock.patch.object(N.hidlist, "enumerate", return_value=[entry()]),
            mock.patch.object(N.time, "monotonic", side_effect=lambda: self.clock[0]),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_poll_reaches_named_keyboard_tray_icon(self):
        status, = self.app.poll_once()
        self.app.apply([status])
        title = self.app.icons[status.key].titles[-1]
        self.assertIn("AULA NOVA75", title)
        self.assertIn("77%", title)
        self.assertEqual(self.app.pictogram(status), "keyboard")

    def test_preference_stops_hardware_queries(self):
        prefs = next(i for i in self.app.build_menu(None).items if i.text == "Preferences").submenu
        kinds = next(i for i in prefs.items if i.text == "Device types").submenu
        toggle = next(i for i in kinds.items if i.text == "AULA NOVA75")
        toggle(None)
        self.assertEqual(self.app.poll_once(), [])
        self.assertEqual(self.dev.opened, [])
        toggle(None)
        self.assertEqual(self.app.poll_once()[0].level, 77)

    def test_low_battery_alert_and_sleep(self):
        self.dev.replies = [reply(10)]
        self.app.apply(self.app.poll_once())
        self.assertEqual(self.app.notes, [hb.low_battery_text("AULA NOVA75", 10, False)])
        self.dev.replies = []
        self.app.apply(self.app.poll_once())
        status = next(iter(self.app.icons.values())).status
        self.assertEqual((status.level, status.online), (10, False))
        self.assertEqual(len(self.app.notes), 1)


class NovaChargingAnimationTests(unittest.TestCase):
    def test_rises_start_real_breathing_and_expiry_stops_it(self):
        app = make_app({'percent_in_icon': True})
        app.anim_tick = 0
        icon = REAL_DEVICE_ICON.__new__(REAL_DEVICE_ICON)
        icon.app, icon.key = app, 'nova'
        icon.status, icon.frames, icon._state = None, None, None
        icon._images = {}
        icon.icon = types.SimpleNamespace(title='', icon=None, visible=True,
                                         update_menu=lambda: None)
        trend = N.ChargingTrend(77, 0)
        i18n.set_language('zh-TW')
        self.addCleanup(i18n.set_language, 'en')
        for level, now in ((78, 15), (79, 30)):
            st = hb.DeviceStatus('nova', N.DEVICE_NAME, level,
                                 trend.update(level, now), True, N.AulaNovaProvider.name,
                                 kind='keyboard', charging_estimated=True)
            icon.update(st)
        self.assertEqual(len(icon.frames), hb.icons.BREATH_FRAMES)
        self.assertIn('79%', icon.icon.title)
        self.assertIn('充電中（推估）', icon.icon.title)
        self.assertEqual(icon._state[-1], '79')
        first = icon.icon.icon.tobytes()
        icon.tick(len(icon.frames) // 2)
        self.assertNotEqual(icon.icon.icon.tobytes(), first)
        st.charging = trend.update(79, 30 + N.CHARGE_HOLD)
        icon.update(st)
        self.assertIsNone(icon.frames)
        self.assertNotIn('充電中', icon.icon.title)
