import base64
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time
import zlib
from pathlib import Path

from PIL import Image

Path("work").mkdir(exist_ok=True)
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 100, 1000, 640))
old = termios.tcgetattr(slave)
process = subprocess.Popen(
    [
        "/bin/bash",
        "-c",
        "./caf --diagnostics work/live.json --seconds 18; result=$?; echo CAF_TEST_WAIT; read reply; exit $result",
    ],
    stdin=slave,
    stdout=slave,
    stderr=slave,
    start_new_session=True,
    env={
        **{
            key: value
            for key, value in os.environ.items()
            if key not in ("TMUX", "TMUX_PANE")
        },
        "XDG_CONFIG_HOME": str(Path("work/terminal-config").resolve()),
    },
)
started = time.monotonic()
buffer = b""
payload = b""
frames = 0
actions = set()
stderr = b""
meta = {}
cursor = (0, 0)
canvas = Image.new("RGB", (1000, 640))
try:
    while process.poll() is None:
        if not select.select([master], [], [], 0.2)[0]:
            if time.monotonic() - started > 22:
                raise RuntimeError("app stalled")
            continue
        data = os.read(master, 1048576)
        if b"CAF_TEST_WAIT" in data:
            restored = termios.tcgetattr(slave)
            assert restored == old, "Terminal attributes were not restored"
            os.write(master, b"finished\n")
        stderr = (stderr + data)[-1024:]
        buffer += data
        if b"\x1b[16t" in data:
            os.write(master, b"\x1b[6;20;10t")
        while b"\x1b_G" in buffer:
            start = buffer.index(b"\x1b_G")
            end = buffer.find(b"\x1b\\", start)
            if end < 0:
                break
            before = buffer[:start]
            positions = list(re.finditer(rb"\x1b\[(\d+);(\d+)H", before))
            if positions:
                last = positions[-1]
                cursor = ((int(last[2]) - 1) * 10, (int(last[1]) - 1) * 20)
            if b"\x1b[2J" in before:
                canvas = Image.new("RGB", (1000, 640))
            packet = buffer[start + 3 : end]
            buffer = buffer[end + 2 :]
            header, _, body = packet.partition(b";")
            fields = dict(x.split(b"=", 1) for x in header.split(b",") if b"=" in x)
            if fields.get(b"a") == b"q":
                os.write(master, b"\x1b_Gi=31;OK\x1b\\")
                continue
            if fields.get(b"a") == b"T":
                meta = fields
                payload = b""
            if b"m" in fields:
                payload += body
                if fields[b"m"] == b"0":
                    rgb = zlib.decompress(base64.b64decode(payload))
                    im = Image.frombytes("RGB", (int(meta[b"s"]), int(meta[b"v"])), rgb)
                    frames += 1
                    canvas.paste(im, cursor)
                    if frames in (24, 140, 450, 850):
                        canvas.save(f"work/terminal-tiles-{frames}.png")
        elapsed = time.monotonic() - started
        if elapsed > 2 and "weather" not in actions:
            os.write(master, b"wwwlc?")
            actions.add("weather")
        if elapsed > 4 and "help" not in actions:
            os.write(master, b"?")
            actions.add("help")
        if elapsed > 5 and "resize" not in actions:
            fcntl.ioctl(
                slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 74, 740, 480)
            )
            os.kill(process.pid, signal.SIGWINCH)
            actions.add("resize")
        if elapsed > 7 and "music" not in actions:
            # Radio power at scene (667,341), scaled into 74x23 terminal cells.
            report = json.loads(Path("work/live.json").read_text())
            x, y, w, h = report["bounds"]
            cx = int(x + 667 / 768 * w) + 1
            cy = int(y + 341 / 480 * h) + 1
            os.write(master, f"\x1b[<0;{cx};{cy}M\x1b[<0;{cx};{cy}m".encode())
            actions.add("music")
        if elapsed > 11 and "station" not in actions:
            os.write(master, b"\x1b[C---")
            actions.add("station")
    process.wait(timeout=2)
    assert process.returncode == 0, (process.returncode, stderr)
    assert frames > 40, frames
    report = json.loads(Path("work/live.json").read_text())
    assert report["radio"]["playing"], report
    for key in ["caffeinate_pid", "mpv_pid"]:
        pid = report[key]
        if pid:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError(f"{key} leaked: {pid}")
    canvas.save("work/terminal-final.png")
    print(
        json.dumps(
            {
                "image_tiles": frames,
                "seconds": round(time.monotonic() - started, 1),
                "terminal_restored": True,
                "children_cleaned": True,
                "final": report,
            },
            indent=2,
        )
    )
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=5)
    os.close(master)
    os.close(slave)
