#!/usr/bin/env python3
"""Feed PipeWire's pipe-tunnel source (/run/loa-audio/mic.fifo) from the stock
PAL capture (`loa-pal record 0 30` = handset-dmic-endfire). The mics only run
while PipeWire drains the FIFO: if it stays full for IDLE seconds the capture
is stopped; it restarts as soon as the FIFO has room again."""
import fcntl, os, select, subprocess, time
RUN = "/run/loa-audio"; FIFO = RUN + "/mic.fifo"; IDLE = 2.0
F_SETPIPE_SZ = 1031
os.makedirs(RUN, exist_ok=True); os.chmod(RUN, 0o755)
if not os.path.exists(FIFO): os.mkfifo(FIFO)
os.chmod(FIFO, 0o666); os.chown(FIFO, 1000, 1000)
keep_r = os.open(FIFO, os.O_RDONLY | os.O_NONBLOCK)      # lets us open for writing
out = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
fcntl.fcntl(out, F_SETPIPE_SZ, 4096)                     # ~20 ms of stale audio at most
os.close(keep_r)
rec = None; blocked_since = None
def start():
    return subprocess.Popen(["/usr/lib/loa/android-run", "/loa/bin/loa-pal", "record", "0", "30"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
def stop(p):
    p.terminate()
    try: p.wait(timeout=3)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
while True:
    if rec is None:
        select.select([], [out], [])                     # wait until PipeWire drains
        rec = start(); blocked_since = None; print("mic on", flush=True)
    r, _, _ = select.select([rec.stdout], [], [], 0.5)
    if r:
        data = os.read(rec.stdout.fileno(), 7680)
        if not data:
            rec.wait(); rec = None; print("capture exited", flush=True); time.sleep(1); continue
        try:
            os.write(out, data); blocked_since = None
        except BlockingIOError:
            blocked_since = blocked_since or time.monotonic()
    if blocked_since and time.monotonic() - blocked_since > IDLE:
        stop(rec); rec = None; print("mic off (idle)", flush=True)
