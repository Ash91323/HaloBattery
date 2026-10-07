"""NOVA75 captured exchange and bounded polling, without hardware access."""
import unittest
from unittest import mock

from providers import aula_nova as N

CAPTURE = bytes.fromhex("20 01 00 4d " + "00 " * 27 + "6e")
REQUEST = bytes.fromhex("00 20 01 " + "00 " * 29 + "21")


def reply(level=77, status=0):
    frame = list(CAPTURE)
    frame[2], frame[3] = status, level
    frame[31] = sum(frame[:31]) & 255
    return frame


def entry(**changes):
    info = dict(vendor_id=N.VID, product_id=N.PID, interface_number=3,
                usage_page=0xFF60, usage=0x61, product_string="2.4G Dongle",
                path=b"nova-receiver")
    return dict(info, **changes)


class FakeDevice:
    def __init__(self, clock, replies=(), stale=(), error=None, written=33):
        self.clock, self.replies, self.queue = clock, list(replies), list(stale)
        self.error, self.written = error, written
        self.opened, self.writes, self.closed = [], [], False

    def open_path(self, path):
        self.opened.append(path)
        if self.error == "open":
            raise OSError("open failed")

    def write(self, data):
        self.writes.append(bytes(data))
        if self.error == "write":
            raise OSError("write failed")
        self.queue.extend(self.replies)
        return self.written

    def read(self, size, ms):
        self.clock[0] += ms / 1000
        if self.error == "read":
            raise OSError("read failed")
        return self.queue.pop(0) if self.queue else []

    def close(self):
        self.closed = True


class PacketTests(unittest.TestCase):
    def test_hardware_capture_and_report_id_framing(self):
        self.assertEqual(bytes(N.battery_request()), REQUEST)
        self.assertEqual(N.parse_battery(CAPTURE), 77)

    def test_bad_length_checksum_command_and_percentage(self):
        bad_checksum = list(CAPTURE)
        bad_checksum[-1] ^= 1
        frames = [None, [], CAPTURE[:-1], CAPTURE + b"\0", b"\0" + CAPTURE,
                  REQUEST, REQUEST[1:], bad_checksum, reply(101), reply(255)]
        for offset in (0, 1):
            frame = list(CAPTURE)
            frame[offset] ^= 1
            frame[-1] = sum(frame[:-1]) & 255
            frames.append(frame)
        for frame in frames:
            with self.subTest(frame=frame):
                self.assertIsNone(N.parse_battery(frame))

    def test_full_battery_and_non_echo_zero(self):
        self.assertEqual(N.parse_battery(reply(100)), 100)
        self.assertEqual(N.parse_battery(reply(0, status=1)), 0)
        # All-zero payload is indistinguishable from an echo, so no fake 0%.
        self.assertIsNone(N.parse_battery(reply(0)))


class PollTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.devices, self.infos = [1000.0], [], [entry()]
        self.provider = N.AulaNovaProvider()
        for patch in (
            mock.patch.object(N.time, "monotonic", side_effect=lambda: self.clock[0]),
            mock.patch.object(N.hid, "device", side_effect=lambda: self.devices.pop(0)),
            mock.patch.object(N.hidlist, "enumerate", side_effect=lambda vid: self.infos),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def device(self, **kwargs):
        dev = FakeDevice(self.clock, **kwargs)
        self.devices.append(dev)
        return dev

    def test_capture_becomes_named_keyboard_status(self):
        dev = self.device(replies=[CAPTURE])
        status, = self.provider.poll()
        self.assertEqual((status.name, status.level, status.kind, status.source,
                          status.online, status.charging),
                         ("AULA NOVA75", 77, "keyboard", "aula_nova", True, False))
        self.assertEqual(dev.writes, [REQUEST])
        self.assertTrue(dev.closed)

    def test_only_oem_receiver_and_vendor_collection_are_opened(self):
        for field, value in [("vendor_id", 0x3554), ("product_id", 0xFA09),
                             ("interface_number", 4), ("usage_page", 0xFF59),
                             ("usage", 1), ("product_string", "Apple Keyboard"),
                             ("product_string", None), ("path", None)]:
            with self.subTest(field=field):
                self.infos = [entry(**{field: value})]
                self.assertEqual(self.provider.poll(), [])

    def test_receivers_are_distinct_and_duplicates_are_skipped(self):
        self.infos += [entry(), entry(path=b"second-receiver")]
        self.device(replies=[CAPTURE])
        self.device(replies=[reply(30)])
        first, second = self.provider.poll()
        self.assertNotEqual(first.key, second.key)
        self.assertEqual((first.level, second.level), (77, 30))
        self.assertEqual(N.device_key(b"PATH"), N.device_key(b"path"))

    def test_stale_echo_and_bad_frames_do_not_supply_a_reading(self):
        self.device(stale=[CAPTURE], replies=[REQUEST[1:], [0] * 32, reply(101), reply(60)])
        self.assertEqual(self.provider.poll()[0].level, 60)

    def test_silence_and_noise_are_bounded(self):
        for frames in ([], [[0] * 32] * 100):
            start = self.clock[0]
            dev = self.device(replies=frames)
            self.assertEqual(self.provider.poll(), [])
            self.assertLessEqual(self.clock[0] - start, N.TIMEOUT + 0.01)
            self.assertTrue(dev.closed)

    def test_saturated_queue_defers_query(self):
        dev = self.device(stale=[CAPTURE] * (N.DRAIN_LIMIT + 1))
        self.assertEqual(self.provider.poll(), [])
        self.assertEqual(dev.writes, [])

    def test_failed_or_short_write_does_not_read_queued_reply(self):
        for written in (-1, 0, 32):
            dev = self.device(replies=[CAPTURE], written=written)
            self.assertEqual(self.provider.poll(), [])
            self.assertTrue(dev.closed)

    def test_io_errors_close_device(self):
        for error in ("open", "write", "read"):
            dev = self.device(error=error)
            self.assertEqual(self.provider.poll(), [])
            self.assertTrue(dev.closed)

    def test_sleep_expires_without_refreshing_last_seen_and_wakes(self):
        self.device(replies=[CAPTURE])
        self.provider.poll()
        self.clock[0] += 60
        self.device()
        status, = self.provider.poll()
        self.assertEqual((status.name, status.level, status.online), ("AULA NOVA75", 77, False))
        self.clock[0] += N.ASLEEP_KEEP
        self.device()
        self.assertEqual(self.provider.poll(), [])
        self.device(replies=[reply(65)])
        self.assertTrue(self.provider.poll()[0].online)

    def test_unplug_clears_cached_battery(self):
        self.device(replies=[CAPTURE])
        self.provider.poll()
        self.infos = []
        self.assertEqual(self.provider.poll(), [])
        self.infos = [entry()]
        self.device()
        self.assertEqual(self.provider.poll(), [])

    def test_unknown_status_does_not_claim_charging(self):
        self.device(replies=[reply(status=0xFF)])
        self.assertFalse(self.provider.poll()[0].charging)
