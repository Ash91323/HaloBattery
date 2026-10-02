"""AULA F87 Pro battery over the Compx 3554:FA09 2.4 GHz receiver.

Protocol source: deepan-alve/womier-l65-linux, linux/l65ctl.py,
WirelessTransport._packet() and WirelessTransport.battery():
https://github.com/deepan-alve/womier-l65-linux/blob/main/linux/l65ctl.py#L185-L293

Only the vendor collection FF02:0002 is opened. A 20-byte output report
13 4A 01 00 00 ... 5E asks for the battery (operation 0 = read). The reply
has the same report/command, one packet, index 0 and two payload bytes:
byte 5 = percent, byte 6 = status flags, byte 19 = sum(bytes 0..18) & 0xFF.
Confirmed on an AULA F87 Pro on Windows, 2026-10-02:
13 4A 01 00 02 5F 01 00 00 00 00 00 00 00 00 00 00 00 00 C0 -> 95%.

The status flags are not decoded: a nonzero byte does NOT prove charging.
No settings, lighting, pairing or firmware commands are sent. Wired USB and
Bluetooth use different paths and are not probed by this provider.

Several keyboards share this receiver id and its generic USB product name,
so the icon uses a family name rather than claiming all of them are F87 Pros.
An unresponsive keyboard keeps its last reading greyed out for five minutes.
"""
from __future__ import annotations

import hashlib
import time
from typing import Dict, List, Optional, Tuple

import hid

from . import hidlist
from .base import DeviceStatus, Provider, hexdump, log

VID, PID = 0x3554, 0xFA09
USAGE_PAGE, USAGE = 0xFF02, 0x0002
REPORT_ID, CMD_BATTERY, REPORT_LEN = 0x13, 0x4A, 20
TIMEOUT = 1.5
READ_MS = 100
DRAIN_LIMIT = 16
ASLEEP_KEEP = 300.0
DEVICE_NAME = "AULA / Compx keyboard"


def battery_request() -> List[int]:
    packet = [REPORT_ID, CMD_BATTERY, 1, 0, 0] + [0] * 14
    return packet + [sum(packet) & 0xFF]


def parse_battery(r) -> Optional[Tuple[int, int]]:
    """(percentage, raw status), only for a complete, checksummed battery reply."""
    if not r or len(r) != REPORT_LEN:
        return None
    if list(r[:5]) != [REPORT_ID, CMD_BATTERY, 1, 0, 2]:
        return None
    if (sum(r[:19]) & 0xFF) != r[19] or not 0 <= r[5] <= 100:
        return None
    return r[5], r[6]


def device_key(path) -> str:
    """Stable across restarts on the same USB port, distinct for two receivers.
    The generic product name/serial cannot identify the paired keyboard."""
    raw = path if isinstance(path, bytes) else str(path).encode("utf-8")
    return "aula:" + hashlib.sha256(raw.lower()).hexdigest()[:16]


class AulaProvider(Provider):
    name = "aula"

    def __init__(self):
        self._diag: List[str] = []
        self._last: Dict[str, Tuple[int, float]] = {}

    def _read(self, path) -> Optional[int]:
        dev = hid.device()
        try:
            dev.open_path(path)
            # Discard queued reports before asking, but bound the drain even
            # while another app is sending traffic on this vendor collection.
            for _ in range(DRAIN_LIMIT):
                if not dev.read(REPORT_LEN, 1):
                    break
            else:
                self._diag.append("    queued reports did not drain; battery query deferred")
                return None
            request = battery_request()
            if dev.write(request) != len(request):
                self._diag.append("    battery request was not accepted")
                return None
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline:
                ms = max(1, min(READ_MS, int((deadline - time.monotonic()) * 1000)))
                reply = dev.read(REPORT_LEN, ms)
                parsed = parse_battery(reply)
                if parsed is not None:
                    level, status = parsed
                    self._diag.append(f"    reply: {hexdump(reply)} -> {level}% "
                                      f"(status 0x{status:02x}, charging unknown)")
                    return level
            self._diag.append("    no valid battery reply (keyboard off or asleep, or unsupported)")
        except (OSError, ValueError) as e:
            self._diag.append(f"    HID: {e}")
        finally:
            try:
                dev.close()
            except Exception:
                pass
        return None

    def poll(self) -> List[DeviceStatus]:
        self._diag = []
        try:
            infos = hidlist.enumerate(VID)
        except Exception as e:  # pragma: no cover
            log.warning("hid.enumerate(aula): %s", e)
            return []
        present = set()
        out: List[DeviceStatus] = []
        for d in infos:
            if d.get("vendor_id") != VID or d.get("product_id") != PID:
                continue
            if (d.get("usage_page"), d.get("usage")) != (USAGE_PAGE, USAGE):
                continue
            path = d.get("path")
            if not path:
                continue
            key = device_key(path)
            if key in present:
                continue
            present.add(key)
            self._diag.append(f"[AULA / Compx] receiver {VID:04x}:{PID:04x} [{key}]")
            level = self._read(path)
            now = time.monotonic()
            if level is not None:
                self._last[key] = (level, now)
                out.append(DeviceStatus(key, DEVICE_NAME, level, False, True, self.name,
                                        kind="keyboard"))
            elif key in self._last:
                last_level, seen = self._last[key]
                if now - seen < ASLEEP_KEEP:
                    self._diag.append(f"    keeping last {last_level}% greyed out")
                    out.append(DeviceStatus(key, DEVICE_NAME, last_level, False, False,
                                            self.name, kind="keyboard"))
                else:
                    del self._last[key]
        # An unplugged receiver must not leave a stale reading behind.
        for key in list(self._last):
            if key not in present:
                del self._last[key]
        return out

    def diagnostics(self) -> List[str]:
        return list(self._diag)
