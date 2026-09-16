import json
import os
import subprocess
import time
from pathlib import Path

Path("work").mkdir(exist_ok=True)
child = """
from caf_app.app import Awake
from caf_app.radio import Radio
from pathlib import Path
Path("work").mkdir(exist_ok=True)
import json,time
with Awake() as awake:
 radio=Radio(config='work/crash-radio.json',silent=True)
 radio.command('station',1);radio.command('toggle')
 deadline=time.monotonic()+20
 while not radio.snapshot().playing and time.monotonic()<deadline:time.sleep(.1)
 assert radio.snapshot().playing
 Path('work/crash-pids.json').write_text(json.dumps([awake.process.pid,radio.process.pid]))
 time.sleep(30)
"""
path = Path("work/crash-pids.json")
path.unlink(missing_ok=True)
p = subprocess.Popen(["./.venv/bin/python", "-c", child])
try:
    deadline = time.monotonic() + 25
    while not path.exists() and time.monotonic() < deadline:
        assert p.poll() is None
        time.sleep(0.1)
    assert path.exists()
    pids = json.loads(path.read_text())
    p.kill()
    p.wait()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        alive = []
        for pid in pids:
            try:
                os.kill(pid, 0)
                alive.append(pid)
            except ProcessLookupError:
                pass
        if not alive:
            break
        time.sleep(0.1)
    assert not alive, alive
    print("SIGKILL parent: caffeinate and mpv both exited automatically.", pids)
finally:
    if p.poll() is None:
        p.terminate()
        p.wait(timeout=5)
