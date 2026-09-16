import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .radio import Radio
from .scene import Scene, hit
from .state import World
from .terminal import Terminal


class Awake:
    def __init__(self):
        self.process = None

    def __enter__(self):
        binary = shutil.which("caffeinate")
        if not binary:
            raise RuntimeError("caf requires macOS caffeinate to keep your Mac awake.")
        # -w also releases the assertions if this app is killed without cleanup.
        self.process = subprocess.Popen(
            [binary, "-di", "-w", str(os.getpid())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None

    def __exit__(self, *args):
        if self.alive:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


def handle(event, world, radio, terminal):
    if event.kind == "cell":
        terminal.cell = event.value
        return
    if event.kind == "graphics":
        if "i=31;OK" in event.value:
            terminal.supported = True
        return
    if event.kind == "key":
        key = event.value
        if key in ("q", "Q", "\x03", "\x04"):
            world.running = False
        elif key in ("?", "h"):
            world.help = not world.help
        elif key == " ":
            radio.command("toggle")
        elif key in ("right", "]", "."):
            radio.command("next", 1)
        elif key in ("left", "[", ","):
            radio.command("next", -1)
        elif key in ("+", "=", "up"):
            radio.command("volume", 5)
        elif key in ("-", "_", "down"):
            radio.command("volume", -5)
        elif key in ("1", "2", "3", "4"):
            radio.command("station", int(key) - 1)
        elif key in ("w", "W"):
            world.cycle_weather()
        elif key in ("l", "L"):
            world.cycle_lamp()
        elif key in ("c", "C"):
            world.pet()
        elif key in ("b", "B"):
            world.brew()
        elif key == "focus":
            world.focused = True
        elif key == "blur":
            world.focused = False
        return
    x, y = terminal.point(event.x, event.y)
    target = hit(x, y)
    world.hover = target
    if world.help and event.kind == "click":
        world.help = False
        return
    if event.kind == "scroll" and target in (
        "radio",
        "volume",
        "power",
        "previous",
        "next",
    ):
        radio.command("volume", 5 if event.value & 1 == 0 else -5)
    if event.kind != "click" or event.value & 3 != 0:
        return
    if target in ("power", "radio"):
        radio.command("toggle")
    elif target == "previous":
        radio.command("next", -1)
    elif target == "next":
        radio.command("next", 1)
    elif target.startswith("preset"):
        radio.command("station", int(target[-1]))
    elif target == "cat":
        world.pet()
    elif target == "coffee":
        world.brew()
    elif target == "lamp":
        world.cycle_lamp()
    elif target == "window":
        world.cycle_weather()


def parse_hour(text):
    try:
        h, m = text.split(":")
        h, m = int(h), int(m)
        if not 0 <= h < 24 or not 0 <= m < 60:
            raise ValueError
        return h + m / 60
    except ValueError:
        raise argparse.ArgumentTypeError("Use local time HH:MM, for example 21:30.")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="caf — a living pixel-art café. Stay a little longer."
    )
    parser.add_argument(
        "--weather", choices=["auto", "clear", "cloudy", "rain"], default="auto"
    )
    parser.add_argument(
        "--fps", type=int, default=12, choices=range(1, 31), metavar="1-30"
    )
    parser.add_argument(
        "--render",
        type=Path,
        help="Save a still preview; no audio or keep-awake process.",
    )
    parser.add_argument(
        "--time",
        type=parse_hour,
        help="Preview lighting at HH:MM (wall clock always shows real time).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Preview a full lighting day every 144 seconds.",
    )
    parser.add_argument(
        "--seconds", type=float, help="Close automatically after this duration."
    )
    parser.add_argument(
        "--diagnostics", type=Path, help="Write runtime state for local verification."
    )
    parser.add_argument(
        "--check", action="store_true", help="Check local dependencies."
    )
    args = parser.parse_args(argv)
    if args.check:
        from PIL import __version__

        print("Pillow:", __version__)
        print("caffeinate:", shutil.which("caffeinate") or "MISSING")
        print("mpv:", shutil.which("mpv") or "MISSING (brew install mpv)")
        print("Graphics: Ghostty / Kitty graphics protocol; run ./caf to negotiate.")
        return
    world = World(hour_override=args.time, demo=args.demo, weather_mode=args.weather)
    scene = Scene()
    if args.render:
        args.render.parent.mkdir(parents=True, exist_ok=True)
        scene.render(world, t=12).save(args.render)
        print(args.render)
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error(
            "Run caf in an interactive Ghostty terminal, or use --render PATH."
        )
    radio = Radio()
    old_handlers = {}

    def shutdown(signum, frame):
        world.running = False

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        old_handlers[sig] = signal.signal(sig, shutdown)
    try:
        with Terminal() as terminal:
            deadline = time.monotonic() + 1.2
            while (
                not terminal.supported and time.monotonic() < deadline and world.running
            ):
                for event in terminal.read(0.05):
                    handle(event, world, radio, terminal)
            if not world.running:
                return 0
            if not terminal.supported:
                raise RuntimeError(
                    "This terminal did not accept Kitty graphics. Open caf directly in Ghostty (outside tmux)."
                )
            with Awake() as awake:
                last_diagnostic = 0
                frames = 0
                was_playing = False
                while world.running:
                    start = time.monotonic()
                    for event in terminal.read():
                        handle(event, world, radio, terminal)
                    if not world.running:
                        break
                    world.awake = awake.alive
                    if not world.awake:
                        raise RuntimeError(
                            "caffeinate stopped unexpectedly; caf has closed so it cannot claim to keep you awake."
                        )
                    state = radio.snapshot()
                    if state.playing and not was_playing and world.lighting()[3] > 0.5:
                        world.cat_watch_until = world.elapsed() + 3
                    was_playing = state.playing
                    terminal.draw(scene.render(world, state))
                    frames += 1
                    if args.diagnostics and start - last_diagnostic >= 1:
                        args.diagnostics.parent.mkdir(parents=True, exist_ok=True)
                        report = {
                            "pid": os.getpid(),
                            "caffeinate_pid": awake.process.pid,
                            "awake": world.awake,
                            "radio": vars(state),
                            "mpv_pid": radio.process.pid if radio.process else None,
                            "frames": frames,
                            "elapsed": world.elapsed(),
                            "bounds": terminal.bounds,
                            "cell": terminal.cell,
                            "weather": world.weather()[3],
                            "lamp": world.lamp,
                            "hover": world.hover,
                            "help": world.help,
                            "focused": world.focused,
                        }
                        pending = args.diagnostics.with_suffix(".tmp")
                        pending.write_text(json.dumps(report, indent=2))
                        pending.replace(args.diagnostics)
                        last_diagnostic = start
                    if args.seconds is not None and world.elapsed() >= args.seconds:
                        break
                    while world.running:
                        fps = args.fps if world.focused else min(args.fps, 6)
                        delay = start + 1 / fps - time.monotonic()
                        if delay <= 0:
                            break
                        for event in terminal.read(delay):
                            handle(event, world, radio, terminal)
    except (RuntimeError, OSError) as exc:
        print(f"caf: {exc}", file=sys.stderr)
        return 1
    finally:
        radio.close()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
    print("☕ Café closed. Music off, keep-awake released. See you soon.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
