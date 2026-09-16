import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path

Path("work").mkdir(exist_ok=True)
for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 800, 480))
    old = termios.tcgetattr(slave)
    diag = Path("work/signal-" + sig.name + ".json")
    diag.unlink(missing_ok=True)
    command = f"./caf --diagnostics {diag}; result=$?; echo CAF_TEST_WAIT; read reply; exit $result"
    process = subprocess.Popen(
        ["/bin/bash", "-c", command],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    started = time.monotonic()
    sent = False
    restored = False
    buf = b""
    try:
        while process.poll() is None:
            if time.monotonic() - started > 7:
                raise AssertionError("Signal shutdown hung")
            if select.select([master], [], [], 0.1)[0]:
                data = os.read(master, 1048576)
                buf = (buf + data)[-1048576:]
                if b"\x1b[16t" in data:
                    os.write(master, b"\x1b[6;20;10t")
                if b"i=31,a=q" in buf:
                    os.write(master, b"\x1b_Gi=31;OK\x1b\\")
                    buf = b""
                if b"CAF_TEST_WAIT" in data:
                    assert termios.tcgetattr(slave) == old
                    restored = True
                    os.write(master, b"finished\n")
            if diag.exists() and not sent and time.monotonic() - started > 1:
                info = json.loads(diag.read_text())
                os.kill(info["pid"], sig)
                sent = True
        process.wait()
        assert process.returncode == 0 and sent and restored
        try:
            os.kill(info["caffeinate_pid"], 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("Leaked caffeinate")
        print(sig.name, "restores the terminal and releases keep-awake", flush=True)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        os.close(master)
        os.close(slave)
