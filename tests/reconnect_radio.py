import tempfile
import time
from pathlib import Path

from caf_app.radio import Radio

Path("work").mkdir(exist_ok=True)
with tempfile.TemporaryDirectory() as temp:
    radio = Radio(config=Path(temp) / "radio.json", silent=True)
    try:
        radio.command("station", 1)
        radio.command("toggle")
        deadline = time.monotonic() + 20
        while not radio.snapshot().playing and time.monotonic() < deadline:
            time.sleep(0.2)
        assert radio.snapshot().playing, vars(radio.snapshot())
        original = radio.process.pid
        radio.process.kill()
        radio.process.wait()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            time.sleep(0.2)
            if (
                radio.snapshot().playing
                and radio.process
                and radio.process.pid != original
            ):
                print(
                    "Recovered decoded live playback after player death:",
                    original,
                    "->",
                    radio.process.pid,
                )
                break
        else:
            raise AssertionError(vars(radio.snapshot()))
    finally:
        radio.close()
