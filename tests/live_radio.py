import json
import tempfile
import time
from pathlib import Path

from caf_app.radio import STATIONS, Radio

Path("work").mkdir(exist_ok=True)
results = []
with tempfile.TemporaryDirectory() as temp:
    player = Radio(config=Path(temp) / "radio.json", silent=True)
    try:
        for i, station in enumerate(STATIONS):
            player.command("station", i)
            if i == 0:
                player.command("toggle")
            started = time.monotonic()
            time.sleep(0.3)
            while time.monotonic() - started < 22:
                s = player.snapshot()
                if s.station == i and s.playing:
                    break
                time.sleep(0.2)
            s = player.snapshot()
            row = {
                "station": station[0],
                "elapsed": round(time.monotonic() - started, 1),
                **vars(s),
            }
            results.append(row)
            print(json.dumps(row), flush=True)
        player.command("toggle")
        time.sleep(0.5)
        assert not player.snapshot().enabled
        proc = player.process
    finally:
        player.close()
    assert proc.poll() is not None
Path("work/radio-results.json").write_text(json.dumps(results, indent=2))
assert all(r["playing"] for r in results), (
    "A station did not reach real decoded playback"
)
