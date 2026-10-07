"""AULA F87 Pro: captured 95% reply, strict parsing, bounded HID queries and sleep.
No hardware needed. Fake HID traffic stays on the receiver's vendor collection.
"""
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from providers import aula as A

CAPTURE = bytes.fromhex("13 4A 01 00 02 5F 01 00 00 00 00 00 00 00 00 00 00 00 00 C0")
REQUEST = bytes.fromhex("13 4A 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 5E")
MODEL_CAPTURE = bytes.fromhex("13 05 01 00 0A 03 00 00 00 01 0B 01 00 00 00 00 00 00 00 33")
MODEL_REQUEST = bytes.fromhex("13 05 01 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 19")


def model_reply(psd="03 00 00 00 01 0b", length=10):
    data = list(MODEL_CAPTURE)
    data[4] = length
    data[5:11] = bytes.fromhex(psd)
    if length == 6:
        data[11:19] = [0] * 8
    data[19] = sum(data[:19]) & 255
    return data


def reply(level=95, status=1, **fields):
    data = list(CAPTURE)
    data[5], data[6] = level, status
    for offset, value in fields.items():
        data[int(offset)] = value
    data[19] = sum(data[:19]) & 255
    return data


def entries(prefix=b"receiver", **fields):
    # The seven collections from the user's F87 Pro diagnostics. Only FF02:0002
    # carries the 20-byte battery reports; FF04:0002 is a different interface.
    shape = [(0, 1, 6), (1, 0x0C, 1), (1, 1, 0x80), (1, 1, 6),
             (1, 1, 2), (1, 0xFF04, 2), (1, 0xFF02, 2)]
    return [dict(vendor_id=A.VID, product_id=A.PID, interface_number=i,
                 usage_page=p, usage=u, path=prefix + b"-" + str(n).encode(),
                 product_string="2.4G Wireless Receiver", **fields)
            for n, (i, p, u) in enumerate(shape)]


class FakeDevice:
    def __init__(self, clock, replies=(), stale=(), error=None, write_count=20, noise=False,
                 model_replies=()):
        self.clock, self.replies, self.queue = clock, list(replies), list(stale)
        self.error, self.write_count, self.noise = error, write_count, noise
        self.opened, self.closed, self.writes, self.reads = [], 0, [], 0
        self.model_replies = list(model_replies)

    def open_path(self, path):
        self.opened.append(path)
        if self.error == "open":
            raise OSError("open failed")

    def write(self, data):
        self.writes.append(list(data))
        if self.error == "write":
            raise OSError("write failed")
        if data[1] == A.CMD_MODEL:
            if self.error == "model":
                raise OSError("model query failed")
            self.queue.extend(self.model_replies)
        else:
            self.queue.extend(self.replies)
        return self.write_count

    def read(self, n, timeout):
        self.reads += 1
        self.clock[0] += timeout / 1000
        if self.error == "read":
            raise OSError("read failed")
        if self.queue:
            return self.queue.pop(0)
        return [0] * 20 if self.noise else []

    def close(self):
        self.closed += 1


class ParseTests(unittest.TestCase):
    def test_model_capture_and_oem_six_byte_layout(self):
        self.assertEqual(bytes(A.model_request()), MODEL_REQUEST)
        for data in (MODEL_CAPTURE, model_reply(length=6)):
            self.assertEqual(A.parse_model(data), bytes.fromhex("03 00 00 00 01 0b"))

    def test_invalid_model_frames_are_rejected(self):
        for data in (None, [], MODEL_CAPTURE[:-1], MODEL_CAPTURE + b"\0", REQUEST,
                     MODEL_REQUEST, CAPTURE, bytes(20)):
            self.assertIsNone(A.parse_model(data))
        for offset, value in [(0, 0x08), (1, 0x85), (2, 2), (3, 1),
                              (4, 0), (4, 5), (4, 7), (4, 14), (4, 0x1a)]:
            data = list(MODEL_CAPTURE)
            data[offset] = value
            data[19] = sum(data[:19]) & 255
            self.assertIsNone(A.parse_model(data))
        corrupt = list(MODEL_CAPTURE)
        corrupt[5] ^= 1
        self.assertIsNone(A.parse_model(corrupt))

    def test_captured_f87_pro_reply(self):
        self.assertEqual(A.parse_battery(CAPTURE), (95, 1))

    def test_empty_truncated_and_extra_bytes_are_rejected(self):
        for data in (None, [], CAPTURE[:7], CAPTURE[:-1], CAPTURE + b"\0"):
            with self.subTest(data=data):
                self.assertIsNone(A.parse_battery(data))

    def test_invalid_header_command_fragment_or_payload_length(self):
        for offset, value in [(0, 0x08), (1, 0x44), (1, 0xCA), (2, 0), (2, 2),
                              (3, 1), (4, 0), (4, 1), (4, 3), (4, 0x12)]:
            with self.subTest(offset=offset, value=value):
                self.assertIsNone(A.parse_battery(reply(**{str(offset): value})))

    def test_corrupt_checksum_and_out_of_range_levels(self):
        corrupt = list(CAPTURE)
        corrupt[5] = 90
        for data in (corrupt, reply(101), reply(255), [0] * 20):
            self.assertIsNone(A.parse_battery(data))

    def test_zero_and_full_are_valid_levels(self):
        for level in (0, 100):
            self.assertEqual(A.parse_battery(reply(level)), (level, 1))


class PollTests(unittest.TestCase):
    def setUp(self):
        self.clock = [1000.0]
        self.devices = []
        self.infos = entries()
        self.provider = A.AulaProvider()
        for patch in (
            mock.patch.object(A, "time", types.SimpleNamespace(monotonic=lambda: self.clock[0])),
            mock.patch.object(A, "hid", types.SimpleNamespace(device=lambda: self.devices.pop(0))),
            mock.patch.object(A, "hidlist", types.SimpleNamespace(enumerate=lambda vid: list(self.infos))),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def device(self, **kw):
        dev = FakeDevice(self.clock, **kw)
        self.devices.append(dev)
        return dev

    def test_hardware_reply_queries_battery_and_model_without_guessing_the_name(self):
        dev = self.device(replies=[CAPTURE])
        st, = self.provider.poll()
        self.assertEqual((st.name, st.level, st.source, st.kind, st.online, st.charging),
                         (A.DEVICE_NAME, 95, "aula", "keyboard", True, False))
        self.assertEqual(dev.opened, [self.infos[-1]["path"]])
        self.assertEqual(dev.writes, [list(REQUEST), list(MODEL_REQUEST)])
        self.assertEqual(dev.closed, 1)
        self.assertIn("charging unknown", "\n".join(self.provider.diagnostics()))

    def test_other_products_vendors_and_collections_are_not_opened(self):
        for field, value in (("product_id", 0xF508), ("product_id", 0xFA08),
                             ("product_id", 0x010C), ("vendor_id", 0x258A),
                             ("usage_page", 0xFF04), ("usage", 1)):
            with self.subTest(field=field, value=value):
                self.infos = [dict(d, **{field: value}) for d in entries()]
                self.assertEqual(self.provider.poll(), [])  # no fake device available to open

    def test_duplicate_enumeration_entry_is_queried_once(self):
        self.infos.append(dict(self.infos[-1]))
        dev = self.device(replies=[CAPTURE])
        self.assertEqual(len(self.provider.poll()), 1)
        self.assertEqual(dev.writes, [list(REQUEST), list(MODEL_REQUEST)])

    def test_captured_psd_automatically_identifies_f87_pro(self):
        self.device(replies=[CAPTURE], model_replies=[MODEL_CAPTURE])
        st, = self.provider.poll()
        self.assertEqual((st.name, st.level), ("AULA F87 PRO", 95))
        self.assertIn("03 00 00 00 01 0b", "\n".join(self.provider.diagnostics()))

    def test_f87_and_f87_pro_on_identical_receivers_have_distinct_names(self):
        self.infos += entries(prefix=b"receiver-two")
        self.device(replies=[CAPTURE], model_replies=[model_reply("03 00 00 00 00 8f")])
        self.device(replies=[reply(40)], model_replies=[MODEL_CAPTURE])
        first, second = self.provider.poll()
        self.assertEqual((first.name, second.name), ("AULA F87", "AULA F87 PRO"))
        self.assertNotEqual(first.key, second.key)

    def test_unknown_full_model_ids_never_inherit_f87_pro_name(self):
        for psd in ("03 00 00 00 03 66", "04 00 00 00 01 0b", "00 00 00 00 00 00"):
            self.device(replies=[CAPTURE], model_replies=[model_reply(psd)])
            self.assertEqual(self.provider.poll()[0].name, A.DEVICE_NAME)

    def test_model_timeout_or_io_error_preserves_a_valid_battery(self):
        for error in (None, "model"):
            self.device(replies=[CAPTURE], error=error)
            st, = self.provider.poll()
            self.assertEqual((st.name, st.level, st.online), (A.DEVICE_NAME, 95, True))

    def test_model_query_discards_stale_and_unrelated_reports(self):
        self.device(replies=[CAPTURE, MODEL_CAPTURE],
                    model_replies=[CAPTURE, MODEL_REQUEST, model_reply("03 00 00 00 00 8f")])
        self.assertEqual(self.provider.poll()[0].name, "AULA F87")

    def test_model_is_requeried_and_not_cached_across_receiver_pairing_changes(self):
        for model, name in ((MODEL_CAPTURE, "AULA F87 PRO"),
                            (model_reply("03 00 00 00 00 8f"), "AULA F87"),
                            (model_reply("03 00 00 00 03 66"), A.DEVICE_NAME)):
            self.device(replies=[CAPTURE], model_replies=[model])
            self.assertEqual(self.provider.poll()[0].name, name)

    def test_sleep_keeps_identified_name_but_unplug_clears_it(self):
        self.device(replies=[CAPTURE], model_replies=[MODEL_CAPTURE])
        self.provider.poll()
        self.device()
        st, = self.provider.poll()
        self.assertEqual((st.name, st.online), ("AULA F87 PRO", False))
        self.infos = []
        self.provider.poll()
        self.infos = entries()
        self.device(replies=[CAPTURE])
        self.assertEqual(self.provider.poll()[0].name, A.DEVICE_NAME)

    def test_stale_queued_battery_is_discarded_before_the_request(self):
        self.device(stale=[CAPTURE], replies=[reply(80)])
        self.assertEqual(self.provider.poll()[0].level, 80)

    def test_echo_unrelated_error_and_corrupt_reports_are_skipped(self):
        corrupt = list(CAPTURE)
        corrupt[-1] ^= 1
        self.device(replies=[REQUEST, reply(**{"1": 0x44}), reply(**{"1": 0xCA}),
                             corrupt, reply(70)])
        self.assertEqual(self.provider.poll()[0].level, 70)

    def test_silent_keyboard_has_no_fabricated_zero_and_bounded_wait(self):
        dev = self.device()
        self.assertEqual(self.provider.poll(), [])
        self.assertLessEqual(self.clock[0] - 1000, A.TIMEOUT + 0.01)
        self.assertEqual(dev.closed, 1)

    def test_continuous_noise_does_not_keep_the_drain_or_read_loop_running(self):
        dev = self.device(noise=True)
        self.assertEqual(self.provider.poll(), [])
        self.assertLess(self.clock[0] - 1000, A.TIMEOUT + 0.1)
        self.assertEqual(dev.writes, [])

    def test_saturated_queue_cannot_be_mistaken_for_a_fresh_battery_reply(self):
        dev = self.device(stale=[CAPTURE] * (A.DRAIN_LIMIT + 1))
        self.assertEqual(self.provider.poll(), [])
        self.assertEqual(dev.writes, [])
        self.assertIn("deferred", "\n".join(self.provider.diagnostics()))

    def test_noise_after_request_has_a_bounded_deadline(self):
        dev = self.device(replies=[[0] * 20] * 100)
        self.assertEqual(self.provider.poll(), [])
        self.assertLess(self.clock[0] - 1000, A.TIMEOUT + 0.01)
        self.assertEqual(dev.writes, [list(REQUEST)])

    def test_io_errors_close_handles(self):
        for error in ("open", "read", "write"):
            with self.subTest(error=error):
                dev = self.device(error=error)
                self.assertEqual(self.provider.poll(), [])
                self.assertEqual(dev.closed, 1)
                self.assertIn("failed", "\n".join(self.provider.diagnostics()))

    def test_failed_or_short_write_does_not_wait_for_a_reply(self):
        for count in (-1, 0, 19):
            with self.subTest(count=count):
                dev = self.device(write_count=count, replies=[CAPTURE])
                self.assertEqual(self.provider.poll(), [])
                self.assertEqual(dev.reads, 1)  # the initial drain only

    def test_status_bits_are_not_assumed_to_mean_charging(self):
        for status in (0, 1, 0x10, 0xFF):
            self.device(replies=[reply(status=status)])
            self.assertFalse(self.provider.poll()[0].charging)

    def test_sleep_retains_a_grey_reading_then_expires_without_extending_it(self):
        self.device(replies=[CAPTURE])
        st, = self.provider.poll()
        self.clock[0] += 60
        self.device()
        sleeping, = self.provider.poll()
        self.assertEqual((sleeping.key, sleeping.level, sleeping.online, sleeping.kind),
                         (st.key, 95, False, "keyboard"))
        self.clock[0] += A.ASLEEP_KEEP
        self.device()
        self.assertEqual(self.provider.poll(), [])
        self.assertEqual(self.provider._last, {})

    def test_waking_updates_the_same_icon(self):
        self.device(replies=[CAPTURE])
        first, = self.provider.poll()
        self.device()
        self.provider.poll()
        self.device(replies=[reply(90)])
        awake, = self.provider.poll()
        self.assertEqual((awake.key, awake.level, awake.online), (first.key, 90, True))

    def test_unplug_purges_cache_and_replug_does_not_reuse_stale_level(self):
        self.device(replies=[CAPTURE])
        self.provider.poll()
        self.infos = []
        self.assertEqual(self.provider.poll(), [])
        self.assertEqual(self.provider._last, {})
        self.infos = entries()
        self.device()
        self.assertEqual(self.provider.poll(), [])

    def test_two_identical_receivers_keep_separate_levels_and_keys(self):
        self.infos += entries(prefix=b"receiver-two")
        self.device(replies=[CAPTURE])
        self.device(replies=[reply(40)])
        first, second = self.provider.poll()
        self.assertNotEqual(first.key, second.key)
        self.assertEqual((first.level, second.level), (95, 40))
        self.assertEqual(first.key, A.device_key(entries()[-1]["path"]))
        self.assertEqual(A.device_key(b"RECEIVER-6"), A.device_key("receiver-6"))


if __name__ == "__main__":
    unittest.main()
