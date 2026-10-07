"""Captured charge states reach the real breathing animation and clear on unplug."""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_hide_rename import hb, make_app
from providers import barracuda_x as B


class ChargingTrayTests(unittest.TestCase):
    def test_sampled_charge_and_unplug_start_and_stop_breathing(self):
        info = dict(product_id=B.PID, usage_page=0xff00, interface_number=3,
                    path=b'path', serial_number='test')
        app = make_app()
        app.anim_tick = 0
        icon = hb.DeviceIcon.__new__(hb.DeviceIcon)
        icon.app = app
        icon.key = 'barracuda_x:0550:test'
        icon.status, icon.frames, icon._state = None, None, None
        icon._images = {}
        icon.icon = types.SimpleNamespace(title='', icon=None, visible=True,
                                         update_menu=lambda: None)
        p = B.BarracudaXProvider()
        with mock.patch.object(B.hidlist, 'enumerate', return_value=[info]), \
                mock.patch.object(B, 'read_battery', side_effect=[(3837, True), (3762, False)]):
            icon.update(p.poll()[0])
            self.assertEqual(len(icon.frames), hb.icons.BREATH_FRAMES)
            self.assertIn('charging (estimated)', icon.icon.title)
            self.assertTrue(app.status_data([icon.status])['devices'][0]['charging_estimated'])
            first = icon.icon.icon.tobytes()
            icon.tick(len(icon.frames) // 2)
            self.assertNotEqual(icon.icon.icon.tobytes(), first)
            icon.update(p.poll()[0])
            self.assertIsNone(icon.frames)
            self.assertNotIn('charging (estimated)', icon.icon.title)
            unplugged = icon.icon.icon.tobytes()
            icon.tick(0)
            self.assertEqual(icon.icon.icon.tobytes(), unplugged)
