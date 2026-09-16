import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import termios
import time
from itertools import pairwise
from pathlib import Path

Path("work").mkdir(exist_ok=True)
diag = Path("work/input-burst.json")
diag.unlink(missing_ok=True)
master, slave = pty.openpty()
fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 800, 480))
original = termios.tcgetattr(slave)
process = subprocess.Popen(
    [
        "/bin/bash",
        "-c",
        "./caf --diagnostics work/input-burst.json --seconds 6; result=$?; echo CAF_TEST_WAIT; read reply; exit $result",
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
        "XDG_CONFIG_HOME": str(Path("work/input-config").resolve()),
    },
)
started = time.monotonic()
last_mouse = started
samples = []
buffer = b""
queried = False
blurred = False
clicked = False
restored = False
try:
    while process.poll() is None:
        elapsed = time.monotonic() - started
        assert elapsed < 10, "App failed to close after the input burst"
        if select.select([master], [], [], 0.004)[0]:
            data = os.read(master, 1048576)
            buffer = (buffer + data)[-1048576:]
            if not queried and b"i=31,a=q" in buffer:
                os.write(master, b"\x1b[6;20;10t\x1b_Gi=31;OK\x1b\\")
                queried = True
                buffer = b""
            if b"CAF_TEST_WAIT" in buffer:
                assert termios.tcgetattr(slave) == original
                restored = True
                os.write(master, b"finished\n")
                buffer = b""
        if queried and not restored and time.monotonic() - last_mouse > 0.005:
            os.write(master, b"\x1b[<35;5;5M")
            last_mouse = time.monotonic()
        if elapsed > 2 and not clicked:
            os.write(master, b"l")
            clicked = True
        if elapsed > 3 and not blurred:
            os.write(master, b"\x1b[O")
            blurred = True
        if diag.exists():
            sample = json.loads(diag.read_text())
            if not samples or sample["frames"] != samples[-1]["frames"]:
                samples.append(sample)
    process.wait(timeout=2)
    assert process.returncode == 0 and restored
    rates = []
    for a, b in pairwise(samples):
        if a["focused"] != b["focused"]:
            continue
        rate = (b["frames"] - a["frames"]) / (b["elapsed"] - a["elapsed"])
        limit = 12 if b["focused"] else 6
        assert rate < limit + 0.5, (rate, a, b)
        rates.append({"focused": b["focused"], "fps": round(rate, 2)})
    assert {row["focused"] for row in rates} == {True, False}
    assert samples[-1]["lamp"] == 2
    print(
        json.dumps(
            {
                "input_responsive": True,
                "terminal_restored": restored,
                "measured_rates": rates,
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
