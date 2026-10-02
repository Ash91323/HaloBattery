"""The AULA provider's real status reaches the existing tray and preferences."""
import os
import sys
import types
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_hide_rename import HideRenameTestCase, hb, make_app
from test_aula import A, CAPTURE, FakeDevice, entries, reply

REAL_DEVICE_ICON = hb.DeviceIcon


class AulaTrayTests(HideRenameTestCase):
    def setUp(self):
        super().setUp()
        self.app = make_app({"bluetooth": False, "percent_in_icon": True, "low": 20})
        self.app.providers = [p for p in hb.make_providers() if isinstance(p, A.AulaProvider)]
        self.assertEqual(len(self.app.providers), 1)
        self.app.bt_cache, self.app._bt_dup_logged = [], set()
        self.clock = [1000.0]
        self.dev = FakeDevice(self.clock, replies=[CAPTURE])
        for patch in (
            mock.patch.object(A, "hid", types.SimpleNamespace(device=lambda: self.dev)),
            mock.patch.object(A, "hidlist", types.SimpleNamespace(enumerate=lambda vid: entries())),
            mock.patch.object(A, "time", types.SimpleNamespace(monotonic=lambda: self.clock[0])),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_poll_updates_the_icon_and_percentage_renderer(self):
        status, = self.app.poll_once()
        self.app.apply([status])
        self.assertIn("95%", self.app.icons[status.key].titles[-1])
        self.assertEqual(self.app.pictogram(status), "keyboard")
        icon = REAL_DEVICE_ICON.__new__(REAL_DEVICE_ICON)
        icon.app, icon.key = self.app, status.key
        icon.status, icon.frames, icon._state, icon._images = None, None, None, {}
        icon.icon = types.SimpleNamespace(title="", icon=None, visible=True, update_menu=lambda: None)
        with mock.patch.object(hb.icons, "render", wraps=hb.icons.render) as render:
            icon.update(status)
        self.assertTrue(render.called)
        self.assertTrue(all(c.kwargs["text"] == "95" for c in render.call_args_list))

    def test_device_type_preference_disables_hardware_queries(self):
        prefs = next(i for i in self.app.build_menu(None).items if i.text == "Preferences").submenu
        kinds = next(i for i in prefs.items if i.text == "Device types").submenu
        toggle = next(i for i in kinds.items if i.text == "AULA / Compx keyboards")
        toggle(None)
        self.assertEqual(self.app.poll_once(), [])
        self.assertEqual(self.dev.opened, [])
        toggle(None)
        self.assertEqual(self.app.poll_once()[0].level, 95)

    def test_low_battery_alert_and_sleep_use_the_existing_app_behavior(self):
        self.dev.replies = [reply(10)]
        self.app.apply(self.app.poll_once())
        self.assertEqual(self.app.notes, [hb.low_battery_text(A.DEVICE_NAME, 10, False)])
        self.dev.replies = []
        self.app.apply(self.app.poll_once())
        status = next(iter(self.app.icons.values())).status
        self.assertFalse(status.online)
        self.assertEqual(status.level, 10)
        self.assertEqual(len(self.app.notes), 1)
