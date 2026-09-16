"""Exercise the distributed wheel without access to checkout-relative assets."""

import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile


def main():
    wheel = Path(sys.argv[1]).resolve()
    assets = {
        "cafe.png",
        "day.png",
        "night.png",
        "clouds.png",
        "miso.png",
        "Silkscreen-Regular.ttf",
        "FONT-LICENSE.txt",
        "ARTWORK.md",
    }
    with ZipFile(wheel) as archive:
        expected = {"caf_app/assets/" + name for name in assets}
        assert expected <= set(archive.namelist()), "Wheel is missing runtime assets"
        assert any(name.endswith("/licenses/LICENSE") for name in archive.namelist())

    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="caf-wheel-") as directory:
        root = Path(directory)
        python = root / "venv/bin/python"

        def run(*args):
            subprocess.run(args, cwd=root, env=env, check=True)

        run("uv", "venv", "--python", sys.executable, str(root / "venv"))
        run("uv", "pip", "install", "--python", str(python), str(wheel))
        run(str(root / "venv/bin/caf"), "--check")
        for hour, weather in [
            ("08:00", "clear"),
            ("18:00", "cloudy"),
            ("23:00", "rain"),
        ]:
            preview = root / (weather + ".png")
            run(
                str(root / "venv/bin/caf"),
                "--render",
                str(preview),
                "--time",
                hour,
                "--weather",
                weather,
            )
            data = preview.read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n"
            assert struct.unpack(">II", data[16:24]) == (768, 480)
        print("Installed wheel renders day, dusk, and night outside the checkout.")


if __name__ == "__main__":
    main()
