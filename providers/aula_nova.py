"""AULA NOVA75 battery over its 05AC:024F 2.4 GHz dongle.

Receiver matching: NOVA75 official driver Beta 1.0.0.2, config.xml.
Battery command: VitalyArt/Aula-F75-Max-Driver, WirelessAulaDevice.swift,
sendBatteryQuery and BatteryInputPipe (links and captures in docs/protocols.md).
Confirmed on NOVA75 on Windows, 2026-10-07: 20 01 00 4D ... 6E = 77%.
This is a different protocol from the F87 Pro's Compx receiver.

Only interface 3, vendor collection FF60:0061, is queried. hidapi needs a
zero report-id prefix on the 32-byte output, but returns 32-byte input frames.
Charging/status bits are not decoded. No configuration commands are sent.
The OEM receiver match is not a unique hardware model identifier.
"""
from __future__ import annotations

import hashlib
import time
from typing import Dict, List, Optional, Tuple

import hid

from . import hidlist
from .base import DeviceStatus, Provider, hexdump, log

VID, PID = 0x05AC, 0x024F
INTERFACE, USAGE_PAGE, USAGE = 3, 0xFF60, 0x0061
PRODUCT = "2.4G Dongle"
DEVICE_NAME = "AULA NOVA75"
FRAME_LEN = 32
TIMEOUT, READ_MS, DRAIN_LIMIT = 1.5, 100, 16
ASLEEP_KEEP = 300.0


def battery_request() -> List[int]:
    frame = [0x20, 0x01] + [0] * 29
    return [0] + frame + [sum(frame) & 0xFF]


def parse_battery(reply) -> Optional[int]:
    if not reply or len(reply) != FRAME_LEN or list(reply[:2]) != [0x20, 0x01]:
        return None
    if sum(reply[:31]) & 0xFF != reply[31] or not 0 <= reply[3] <= 100:
        return None
    # An echoed request has no battery information; do not invent a 0% reading.
    if list(reply) == battery_request()[1:]:
        return None
    return reply[3]


def matches(info) -> bool:
    return (info.get("vendor_id"), info.get("product_id"),
            info.get("interface_number"), info.get("usage_page"),
            info.get("usage"), info.get("product_string")) == (
                VID, PID, INTERFACE, USAGE_PAGE, USAGE, PRODUCT)


def device_key(path) -> str:
    raw = path if isinstance(path, bytes) else str(path).encode("utf-8")
    return "aula_nova:" + hashlib.sha256(raw.lower()).hexdigest()[:16]


class AulaNovaProvider(Provider):
    name = "aula_nova"

    def __init__(self):
        self._diag: List[str] = []
        self._last: Dict[str, Tuple[int, float]] = {}

    def _read(self, path) -> Optional[int]:
        dev = hid.device()
        try:
            dev.open_path(path)
            for _ in range(DRAIN_LIMIT):
                if not dev.read(FRAME_LEN, 1):
                    break
            else:
                self._diag.append("    queued reports did not drain; query deferred")
                return None
            request = battery_request()
            if dev.write(request) != len(request):
                self._diag.append("    battery request was not accepted")
                return None
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline:
                ms = max(1, min(READ_MS, int((deadline - time.monotonic()) * 1000)))
                reply = dev.read(FRAME_LEN, ms)
                level = parse_battery(reply)
                if level is not None:
                    self._diag.append(f"    battery reply: {hexdump(reply)}")
                    self._diag.append(f"    {level}% (charging unknown)")
                    return level
            self._diag.append("    no valid battery reply (off, asleep, or unsupported)")
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
            log.warning("hid.enumerate(aula_nova): %s", e)
            return []
        present, out = set(), []
        for info in infos:
            if not matches(info) or not info.get("path"):
                continue
            path = info["path"]
            key = device_key(path)
            if key in present:
                continue
            present.add(key)
            self._diag.append(f"[AULA NOVA75] receiver {VID:04x}:{PID:04x} [{key}]")
            level = self._read(path)
            now = time.monotonic()
            if level is not None:
                self._last[key] = (level, now)
                out.append(DeviceStatus(key, DEVICE_NAME, level, False, True,
                                        self.name, kind="keyboard"))
            elif key in self._last:
                last_level, seen = self._last[key]
                if now - seen < ASLEEP_KEEP:
                    self._diag.append(f"    keeping last {last_level}% greyed out")
                    out.append(DeviceStatus(key, DEVICE_NAME, last_level, False,
                                            False, self.name, kind="keyboard"))
                else:
                    del self._last[key]
        for key in list(self._last):
            if key not in present:
                del self._last[key]
        return out

    def diagnostics(self) -> List[str]:
        return list(self._diag)
