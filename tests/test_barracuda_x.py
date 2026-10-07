import unittest
from unittest import mock
from providers import barracuda_x as B

CAPTURE = bytes.fromhex('02 11 50 49 01 d8 fb f2 10 00 07 00 06 82 00 af 0e 00 00')

class ProtocolTests(unittest.TestCase):
    def test_real_capture(self):
        r = B.parse_reply(CAPTURE, 2, 6)
        self.assertEqual(int.from_bytes(r[1:3], 'little'), 3759)
        self.assertEqual(B.estimate(3759), 22)

    def test_reject_foreign_and_truncated(self):
        for packet in (CAPTURE[:-1], b'', b'\x01' + CAPTURE[1:]):
            self.assertIsNone(B.parse_reply(packet, 2, 6))
        self.assertIsNone(B.parse_reply(CAPTURE, 3, 6))
        self.assertIsNone(B.parse_reply(CAPTURE, 2, 14))

    def test_crc_frame(self):
        report = bytearray(B.frame(2, 6, (1, 0, 49)))
        checksum = int.from_bytes(report[3:5], 'little')
        report[3:5] = b'\0\0'
        self.assertEqual(checksum, B.binascii.crc_hqx(report, 0))
        self.assertEqual(report[5:12], bytes.fromhex('50 41 06 02 01 00 31'))

    def test_restore_after_timeout_and_exception(self):
        for answers in ([None, b'\0'], [b'\0', OSError('read'), b'\0']):
            with mock.patch.object(B.hid, 'device'), mock.patch.object(B.Session, 'query', side_effect=answers) as query:
                self.assertIsNone(B.read_voltage(b'path', []))
                self.assertEqual(query.call_args, mock.call(14, (2, 225, 0)))

    def test_invalid_voltage(self):
        with mock.patch.object(B.hid, 'device'), mock.patch.object(B.Session, 'query', side_effect=[b'\0', b'\0\xff\xff', b'\0']):
            self.assertIsNone(B.read_voltage(b'path', []))

    def test_provider_identity_and_offline(self):
        info = dict(product_id=B.PID, usage_page=0xff00, interface_number=3, path=b'path', serial_number='test')
        p = B.BarracudaXProvider()
        with mock.patch.object(B.hidlist, 'enumerate', return_value=[info]), mock.patch.object(B, 'read_battery', side_effect=[(3759, False), (None, False)]):
            status, = p.poll()
            self.assertEqual((status.level, status.kind, status.source), (22, 'headset', 'barracuda_x'))
            self.assertTrue(status.approx.startswith('~22%'))
            offline, = p.poll()
            self.assertFalse(offline.online)
            self.assertIsNone(offline.level)
        with mock.patch.object(B.hidlist, 'enumerate', return_value=[dict(info, product_id=0x053a)]), mock.patch.object(B, 'read_battery') as read:
            self.assertEqual(p.poll(), [])
            read.assert_not_called()

    def test_busy_is_bounded(self):
        dev = mock.Mock()
        dev.write.return_value = 64
        dev.get_input_report.return_value = [2, 0x46]
        with mock.patch.object(B.time, 'sleep'):
            self.assertIsNone(B.Session(dev).query(6, (1, 0, 49)))
        self.assertEqual(dev.write.call_count, 5)


class ChargingTests(unittest.TestCase):
    # Same local unit, user-confirmed cable states on 2026-10-08.
    CHARGING = [3837, 3840, 3870, 4110, 4107, 4098, 4077]
    UNPLUGGED = [3762, 3762, 3762, 3762, 3765, 3762, 3765]

    def read_samples(self, samples):
        replies = [b'\0'] + [b'\0' + mv.to_bytes(2, 'little') if mv is not None else None
                              for mv in samples] + [b'\0']
        diag = []
        with mock.patch.object(B.hid, 'device') as dev, \
                mock.patch.object(B.Session, 'query', side_effect=replies) as query, \
                mock.patch.object(B.time, 'sleep'):
            reading = B.read_battery(b'path', diag)
            self.assertEqual(query.call_args, mock.call(14, (2, 225, 0)))
            dev.return_value.close.assert_called_once()
        return reading, diag

    def test_captured_cable_states_and_minimum_voltage(self):
        self.assertEqual(self.read_samples(self.CHARGING)[0], (3837, True))
        self.assertEqual(self.read_samples(self.UNPLUGGED)[0], (3762, False))

    def test_incomplete_invalid_or_missing_samples_do_not_claim_charging(self):
        for samples in ([None] * 7, [4200] + [None] * 6,
                        [3762, 65535, 4110, 3762, 3762, 3762, 3762]):
            with self.subTest(samples=samples):
                self.assertFalse(self.read_samples(samples)[0][1])

    def test_full_charge_voltage_and_thresholds(self):
        self.assertTrue(B.charging_from_samples([4180] * 7))
        self.assertFalse(B.charging_from_samples([4179] * 7))
        self.assertFalse(B.charging_from_samples([3762] * 6 + [3773]))
        self.assertTrue(B.charging_from_samples([3762] * 6 + [3774]))

    def test_query_error_restores_local_routing(self):
        with mock.patch.object(B.hid, 'device'), \
                mock.patch.object(B.Session, 'query', side_effect=[b'\0', OSError('read'), b'\0']) as query:
            self.assertEqual(B.read_battery(b'path', []), (None, False))
            self.assertEqual(query.call_args, mock.call(14, (2, 225, 0)))

    def test_provider_clears_charging_after_unplug_and_lost_link(self):
        info = dict(product_id=B.PID, usage_page=0xff00, interface_number=3,
                    path=b'path', serial_number='test')
        p = B.BarracudaXProvider()
        with mock.patch.object(B.hidlist, 'enumerate', return_value=[info]), \
                mock.patch.object(B, 'read_battery', side_effect=[(3837, True), (3762, False), (None, False)]):
            states = [p.poll()[0] for _ in range(3)]
        self.assertEqual([s.charging for s in states], [True, False, False])
        self.assertTrue(all(s.charging_estimated for s in states))
        self.assertFalse(states[-1].online)

if __name__ == '__main__':
    unittest.main()
