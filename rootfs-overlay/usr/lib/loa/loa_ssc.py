#!/usr/bin/env python3
"""Minimal Qualcomm Sensor Core (SSC/SEE) client for the LoA native port.

Transport: libqmi's SSC service over QRTR (GObject introspection), the same
route libssc uses. Payloads: the handful of SSC protobuf messages needed here,
hand-encoded (field numbers from libssc's data/ssc-*.proto definitions).

Flow per sensor:
  SUID lookup (data type -> sensor UID) on the well-known SUID sensor
  (uid 0xABAB...AB), msg 512 -> response 768;
  enable streaming: msg 513 (continuous, SscEnableConfigRequest sample_rate)
  or 514 (on-change, empty); measurements arrive as msg 1025 events with
  `repeated float` in field 1.
"""
import struct
import gi
gi.require_version("Qmi", "1.0")
gi.require_version("Qrtr", "1.0")
from gi.repository import GLib, Qmi, Qrtr

SUID_UID = (0xABABABABABABABAB, 0xABABABABABABABAB)  # (low, high)
MSG_SUID_REQ, MSG_SUID_RESP = 512, 768
MSG_ENABLE_CONT, MSG_ENABLE_ONCHANGE, MSG_DISABLE = 513, 514, 10
MSG_MEASUREMENT, MSG_MEASUREMENT_PROX = 1025, 769
QMI_SERVICE_SSC = 400

# --- tiny protobuf codec ---------------------------------------------------
def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)

def _key(field, wt):
    return _varint((field << 3) | wt)

def pb_varint(field, v):
    return _key(field, 0) + _varint(v)

def pb_fixed64(field, v):
    return _key(field, 1) + struct.pack("<Q", v)

def pb_fixed32(field, v):
    return _key(field, 5) + struct.pack("<I", v)

def pb_float(field, v):
    return _key(field, 5) + struct.pack("<f", v)

def pb_bytes(field, b):
    return _key(field, 2) + _varint(len(b)) + b

def pb_decode(buf):
    """-> list of (field, wiretype, value); value = int or bytes."""
    out, i = [], 0
    while i < len(buf):
        k, sh = 0, 0
        while True:
            b = buf[i]; i += 1
            k |= (b & 0x7F) << sh; sh += 7
            if not b & 0x80:
                break
        field, wt = k >> 3, k & 7
        if wt == 0:
            v, sh = 0, 0
            while True:
                b = buf[i]; i += 1
                v |= (b & 0x7F) << sh; sh += 7
                if not b & 0x80:
                    break
        elif wt == 1:
            v = struct.unpack_from("<Q", buf, i)[0]; i += 8
        elif wt == 5:
            v = struct.unpack_from("<I", buf, i)[0]; i += 4
        elif wt == 2:
            n, sh = 0, 0
            while True:
                b = buf[i]; i += 1
                n |= (b & 0x7F) << sh; sh += 7
                if not b & 0x80:
                    break
            v = bytes(buf[i:i + n]); i += n
        else:
            raise ValueError("unsupported wire type %d" % wt)
        out.append((field, wt, v))
    return out

def floats_field1(msg):
    """repeated float field 1, packed or not."""
    vals = []
    for f, wt, v in pb_decode(msg):
        if f != 1:
            continue
        if wt == 5:
            vals.append(struct.unpack("<f", struct.pack("<I", v))[0])
        elif wt == 2:
            vals.extend(struct.unpack("<%df" % (len(v) // 4), v))
    return vals

def uid_msg(low, high):
    return pb_fixed64(1, low) + pb_fixed64(2, high)

def client_request(uid, msg_id, body=b"", wakeup=False):
    # processor APPS (1); suspend_mode: NO_WAKEUP (1) by default -- the DSP must
    # not wake the CPU for desktop-only sensors (each wakeup ends system
    # suspend); WAKEUP (0) only for events that should wake it (cover hall).
    config = pb_varint(1, 1) + pb_varint(2, 0 if wakeup else 1)
    req = (pb_bytes(2, body) if body else b"") + pb_varint(3, 0)
    return (pb_bytes(1, uid_msg(*uid)) + pb_fixed32(2, msg_id)
            + pb_bytes(3, config) + pb_bytes(4, req))

def parse_uid(b):
    d = {f: v for f, _, v in pb_decode(b)}
    return (d.get(1, 0), d.get(2, 0))

def parse_client_response(buf):
    """-> (uid, [(msg_id, timestamp, msg_bytes)])"""
    uid, events = None, []
    for f, _, v in pb_decode(buf):
        if f == 1:
            uid = parse_uid(v)
        elif f == 2:
            d = {ff: vv for ff, _, vv in pb_decode(v)}
            events.append((d.get(1), d.get(2), d.get(3, b"")))
    return uid, events

# --- SSC client over libqmi -----------------------------------------------
class SSC:
    def __init__(self, loop, on_event, on_ready):
        self.loop, self.on_event, self.on_ready = loop, on_event, on_ready
        self.client = self.device = None
        Qrtr.Bus.new(1000, None, self._bus_ready)

    def _bus_ready(self, _src, res):
        self.bus = Qrtr.Bus.new_finish(res)
        node = next((n for n in self.bus.peek_nodes() if n.lookup_port(QMI_SERVICE_SSC) >= 0), None)
        if node is None:
            raise RuntimeError("SSC QMI service not found on the QRTR bus")
        Qmi.Device.new_from_node(node, None, self._dev_new)

    def _dev_new(self, _src, res):
        self.device = Qmi.Device.new_from_node_finish(res)
        flags = Qmi.DeviceOpenFlags.AUTO | Qmi.DeviceOpenFlags.EXPECT_INDICATIONS
        self.device.open(flags, 15, None, self._dev_open)

    def _dev_open(self, dev, res):
        dev.open_finish(res)
        dev.allocate_client(Qmi.Service.SSC, 0, 10, None, self._client_ready)

    def _client_ready(self, dev, res):
        self.client = dev.allocate_client_finish(res)
        self.client.connect("report-large", self._report, "get_data")
        self.client.connect("report-small", self._report, "get_data")
        self.on_ready(self)

    def _report(self, _client, output, getter):
        # GI returns (ok, [client_id,] data); take the byte array.
        r = getattr(output, getter)()
        r = r if isinstance(r, tuple) else (True, r)
        if not r[0]:
            return
        data = next((x for x in reversed(r) if isinstance(x, (list, bytes, bytearray))), None)
        if data is None:
            return
        uid, events = parse_client_response(bytes(data))
        for msg_id, ts, msg in events:
            self.on_event(uid, msg_id, ts, msg)

    def send(self, uid, msg_id, body=b"", wakeup=False):
        inp = Qmi.MessageSscControlInput.new()
        inp.set_report_type(Qmi.SscReportType.LARGE)
        inp.set_data(list(client_request(uid, msg_id, body, wakeup)))
        self.client.control(inp, 10, None, self._sent, msg_id)

    def _sent(self, client, res, msg_id):
        try:
            client.control_finish(res)
        except GLib.Error as e:
            print("control %d failed: %s" % (msg_id, e.message), flush=True)

    def lookup(self, data_type):
        body = pb_bytes(1, data_type.encode()) + pb_varint(2, 0) + pb_varint(3, 1)
        self.send(SUID_UID, MSG_SUID_REQ, body)

    def enable(self, uid, rate=None, wakeup=False):
        if rate:
            self.send(uid, MSG_ENABLE_CONT, pb_float(1, rate), wakeup)
        else:
            self.send(uid, MSG_ENABLE_ONCHANGE, wakeup=wakeup)

def parse_suid_response(msg):
    dtype, uids = None, []
    for f, _, v in pb_decode(msg):
        if f == 1:
            dtype = v.decode(errors="replace")
        elif f == 2:
            uids.append(parse_uid(v))
    return dtype, uids

if __name__ == "__main__":
    # Probe: print a few seconds of accel / ambient_light / device_orient.
    import sys
    want = sys.argv[1:] or ["accel", "ambient_light", "device_orient"]
    loop = GLib.MainLoop()
    names = {}

    def on_event(uid, msg_id, ts, msg):
        if uid == SUID_UID and msg_id == MSG_SUID_RESP:
            dtype, uids = parse_suid_response(msg)
            print("SUID %s -> %s" % (dtype, ["%016x%016x" % (h, l) for l, h in uids]), flush=True)
            if uids:
                names[uids[0]] = dtype
                ssc.enable(uids[0], 5.0 if dtype == "accel" else None)
        elif msg_id in (MSG_MEASUREMENT, MSG_MEASUREMENT_PROX):
            print("%-14s %s" % (names.get(uid, "?"), ["%.3f" % x for x in floats_field1(msg)]), flush=True)
        else:
            print("%-14s msg %s (%d bytes)" % (names.get(uid, "?"), msg_id, len(msg)), flush=True)

    def on_ready(s):
        for t in want:
            s.lookup(t)

    ssc = SSC(loop, on_event, on_ready)
    GLib.timeout_add_seconds(int(10), loop.quit)
    loop.run()
