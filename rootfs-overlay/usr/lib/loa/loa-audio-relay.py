#!/usr/bin/env python3
"""Bridge PipeWire's pipe-tunnel sink (/run/loa-audio/speaker.fifo, S16LE 48k
stereo) to the stock AGM playback path: on first audio, enable the six Awinic
amps and start `agmplay` (inside the Android chroot) reading a streaming WAV
from a second FIFO; after IDLE seconds of silence, end the stream so the DSP
graph and amps power down."""
import os, select, struct, subprocess, time
RUN = "/run/loa-audio"; SRC = RUN + "/speaker.fifo"
R = "/opt/loa-android"; WAV_IN_CHROOT = "/data/loa-stream.wav"; WAV = R + WAV_IN_CHROOT
IDLE = 3.0
AMPS = [f"aw_dev_{i}" for i in range(6)]

def fifo(path, mode):
    if not os.path.exists(path):
        os.mkfifo(path)
    os.chmod(path, mode)

def amps_on():
    for a in AMPS:
        subprocess.run(["amixer", "-c0", "-q", "cset", f"name={a}_switch", "Enable"])
        subprocess.run(["amixer", "-c0", "-q", "cset", f"name={a}_prof", "Music"])

def wav_header():
    rate, ch, bits = 48000, 2, 16
    big = 0x7FFFFFF0
    return (b"RIFF" + struct.pack("<I", big + 36) + b"WAVE" + b"fmt " +
            struct.pack("<IHHIIHH", 16, 1, ch, rate, rate * ch * bits // 8, ch * bits // 8, bits) +
            b"data" + struct.pack("<I", big))

os.makedirs(RUN, exist_ok=True); os.chmod(RUN, 0o755)
fifo(SRC, 0o666); os.chown(SRC, 1000, 1000)
fifo(WAV, 0o600)
src = os.open(SRC, os.O_RDONLY | os.O_NONBLOCK)
keep = os.open(SRC, os.O_WRONLY | os.O_NONBLOCK)  # never see EOF when PipeWire reconnects
player = out = None; last = 0.0
while True:
    r, _, _ = select.select([src], [], [], 0.5)
    if r:
        try:
            data = os.read(src, 65536)
        except BlockingIOError:
            data = b""
        if data:
            if player is None:
                amps_on()
                player = subprocess.Popen(["/usr/lib/loa/android-run", "/vendor/bin/agmplay", WAV_IN_CHROOT,
                                           "-D", "100", "-d", "100", "-num_intf", "1", "-i", "TDM-LPAIF-RX-PRIMARY"],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                out = os.open(WAV, os.O_WRONLY)  # blocks until agmplay opens it
                os.write(out, wav_header())
                print("stream start", flush=True)
            try:
                os.write(out, data)
            except BrokenPipeError:
                os.close(out); out = None; player.wait(); player = None
                print("player exited", flush=True)
            last = time.monotonic()
    if player is not None and time.monotonic() - last > IDLE:
        os.close(out); out = None
        try: player.wait(timeout=5)
        except subprocess.TimeoutExpired: player.kill(); player.wait()
        player = None
        print("stream stop (idle)", flush=True)
