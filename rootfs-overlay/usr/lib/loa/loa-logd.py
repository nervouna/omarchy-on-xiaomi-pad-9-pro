#!/usr/bin/env python3
"""Minimal stand-in for Android logd: receives liblog datagrams on
/dev/socket/logdw and writes them to stdout (journal) as `P/tag(pid): msg`."""
import os, socket, struct, sys
PATH = "/dev/socket/logdw"
os.makedirs("/dev/socket", exist_ok=True)
try: os.unlink(PATH)
except FileNotFoundError: pass
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind(PATH); os.chmod(PATH, 0o666)
PRIO = "??VDIWEF"
while True:
    d = s.recv(65536)
    # android_log_header_t: u8 id, u16 tid, u32 sec, u32 nsec  (11 bytes), then payload
    if len(d) < 12: continue
    lid, tid = d[0], struct.unpack_from("<H", d, 1)[0]
    p = d[11:]
    if lid == 2 or lid == 3:  # events/security: binary, skip
        continue
    prio = PRIO[p[0]] if p and p[0] < len(PRIO) else "?"
    rest = p[1:].split(b"\0")
    tag = rest[0].decode(errors="replace") if rest else ""
    msg = rest[1].decode(errors="replace") if len(rest) > 1 else ""
    print(f"{prio}/{tag}({tid}): {msg}", flush=True)
