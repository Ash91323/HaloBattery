"""Barracuda X 2022, YS-Tech receiver 1532:0550.

RACE voltage query framing verified on the local receiver. Protocol reference:
https://github.com/mehdibouchami/razer-barracuda-x-battery/blob/main/src/Protocol.cs
Percentage and charging are estimates. Seven voltage samples use the reference
implementation's spread/voltage heuristic; no explicit charging flag is available.
"""
import binascii
import time
import hid
from . import hidlist
from .base import DeviceStatus, Provider

VID, PID = 0x1532, 0x0550
CURVE = (3300, 3680, 3750, 3790, 3830, 3870, 3910, 3960, 4020, 4080, 4150)
CHARGE_SAMPLES = 7
CHARGE_SAMPLE_DELAY = 0.35
CHARGE_JITTER_MV = 12
CHARGE_VOLTAGE_MV = 4180


def estimate(mv):
    if mv <= CURVE[0]:
        return 0
    for i in range(1, len(CURVE)):
        if mv < CURVE[i]:
            return (i - 1) * 10 + (mv - CURVE[i - 1]) * 10 // (CURVE[i] - CURVE[i - 1])
    return 100


def frame(seq, group, body):
    race = bytes((0x50, 0x41, group, seq)) + bytes(body)
    report = bytearray(64)
    report[:3] = bytes((2, 0x80, len(race)))
    report[5:5 + len(race)] = race
    report[3:5] = binascii.crc_hqx(report, 0).to_bytes(2, 'little')
    return bytes(report)


def parse_reply(report, seq, group):
    data = bytes(report)
    if len(data) < 2 or data[0] != 2 or data[1] > len(data) - 2:
        return None
    end, pos = data[1] + 2, 2
    while pos + 10 <= end:
        if data[pos:pos + 2] != b'PI':
            return None
        stop = pos + 10 + int.from_bytes(data[pos + 8:pos + 10], 'little')
        if stop > end:
            return None
        payload = data[pos + 10:stop]
        if data[pos + 2] == 1 and len(payload) >= 3 and payload[:2] == bytes((group, seq | 0x80)):
            return payload[2:]
        pos = stop
    return None


class Session:
    def __init__(self, dev):
        self.dev, self.seq = dev, 0

    def query(self, group, body):
        self.seq = self.seq % 127 + 1
        report = frame(self.seq, group, body)
        for attempt in range(5):
            if attempt:
                time.sleep(0.05)
            if self.dev.write(report) != len(report):
                return None
            ack = self.dev.get_input_report(2, 64)
            if len(ack) < 2 or ack[0] != 2:
                return None
            if ack[1] == 0x4f:
                break
            if ack[1] != 0x46:
                return None
        else:
            return None
        deadline = time.monotonic() + 0.8
        while time.monotonic() < deadline:
            data = self.dev.read(64, max(1, int((deadline - time.monotonic()) * 1000)))
            reply = parse_reply(data, self.seq, group)
            if reply is not None:
                return reply
        return None


def charging_from_samples(samples):
    """Conservative voltage estimate, never an explicit device charging flag.

    Require a complete sample window: one failed query must not turn a single
    noisy/raised reading into a charging claim. Never reuse an earlier window.
    """
    return (len(samples) == CHARGE_SAMPLES
            and (max(samples) - min(samples) >= CHARGE_JITTER_MV
                 or min(samples) >= CHARGE_VOLTAGE_MV))


def read_battery(path, diag, sample_count=CHARGE_SAMPLES):
    dev = hid.device()
    try:
        dev.open_path(path)
        session = Session(dev)
        # Restore local routing even if the remote acknowledgement is lost.
        try:
            reply = session.query(0x0e, (2, 0xe1, 1))
            if not reply or reply[0] != 0:
                return None, False
            samples = []
            for i in range(sample_count):
                if i:
                    time.sleep(CHARGE_SAMPLE_DELAY)
                reply = session.query(6, (1, 0, 0x31))
                if not reply or len(reply) < 3 or reply[0] != 0:
                    continue
                mv = int.from_bytes(reply[1:3], 'little')
                if 2500 <= mv <= 4500:
                    samples.append(mv)
                else:
                    diag.append(f"  invalid battery voltage: {mv}")
            if samples:
                mv = min(samples)
                charging = charging_from_samples(samples)
                diag.append(f"  battery voltage: {mv} mV (estimated percentage)")
                if sample_count == CHARGE_SAMPLES:
                    state = ('charging' if charging else 'on battery') if len(samples) == CHARGE_SAMPLES else 'unknown'
                    diag.append(f"  voltage samples: {samples}; spread {max(samples) - mv} mV; "
                                f"charging estimate: {state}")
                return mv, charging
        finally:
            reply = session.query(0x0e, (2, 0xe1, 0))
            if not reply or reply[0] != 0:
                diag.append("  local route restoration was not acknowledged")
    except (OSError, ValueError) as exc:
        diag.append(f"  query failed: {exc}")
    finally:
        dev.close()
    return None, False


def read_voltage(path, diag):
    """Single-sample compatibility query for diagnostics/tools."""
    return read_battery(path, diag, sample_count=1)[0]


class BarracudaXProvider(Provider):
    name = 'barracuda_x'

    def __init__(self):
        self._diag = []

    def poll(self):
        self._diag = []
        out = []
        for info in hidlist.enumerate(VID):
            if (info.get('product_id') != PID or info.get('usage_page') != 0xff00
                    or info.get('interface_number') != 3):
                continue
            mv, charging = read_battery(info['path'], self._diag)
            level = estimate(mv) if mv is not None else None
            serial = info.get('serial_number') or info['path'].decode(errors='replace')
            out.append(DeviceStatus(f'barracuda_x:0550:{serial}',
                                    'Razer Barracuda X (2.4 GHz)', level,
                                    charging, mv is not None, self.name,
                                    approx=f'~{level}% ({mv / 1000:.2f} V)' if mv is not None else '',
                                    kind='headset', charging_estimated=True))
        return out

    def diagnostics(self):
        return list(self._diag)
