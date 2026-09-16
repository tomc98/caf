import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

STATIONS = [
    ("LOFI", "lofi hip-hop", "https://stream.laut.fm/lofi"),
    ("FLUID", "instrumental beats", "https://somafm.com/m3u/fluid130.m3u"),
    ("GROOVE SALAD", "downtempo", "https://somafm.com/m3u/groovesalad130.m3u"),
    ("DRONE ZONE", "deep ambient", "https://somafm.com/m3u/dronezone130.m3u"),
]


@dataclass
class RadioState:
    station: int = 0
    volume: int = 35
    enabled: bool = False
    status: str = "OFF"
    title: str = "A LITTLE MUSIC, WHEN YOU WANT IT."
    playing: bool = False
    error: str = ""


class Radio:
    def __init__(self, config=None, silent=False):
        self.config = (
            Path(config)
            if config
            else Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            / "caf"
            / "radio.json"
        )
        self.state = RadioState()
        try:
            saved = json.loads(self.config.read_text())
            self.state.station = int(saved.get("station", 0)) % len(STATIONS)
            self.state.volume = max(0, min(100, int(saved.get("volume", 35))))
        except (OSError, ValueError, TypeError):
            pass
        self.silent = silent
        self.commands = queue.Queue()
        self.lock = threading.Lock()
        self.process = None
        self.sock = None
        self.buffer = b""
        self.request_id = 0
        self.retry_at = 0
        self.attempts = 0
        self.loaded_at = 0
        self.stopping = False
        self.streams = {}
        self.ready = False
        self.playing_url = None
        self.fade_started = 0
        self.actual_volume = 0
        self.thread = threading.Thread(
            target=self._worker, name="caf-radio", daemon=True
        )
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return RadioState(**asdict(self.state))

    def command(self, action, value=None):
        self.commands.put((action, value))

    def _update(self, **values):
        with self.lock:
            for key, value in values.items():
                setattr(self.state, key, value)

    def _save(self):
        try:
            self.config.parent.mkdir(parents=True, exist_ok=True)
            temp = self.config.with_suffix(f".{os.getpid()}.tmp")
            temp.write_text(
                json.dumps({"station": self.state.station, "volume": self.state.volume})
                + "\n"
            )
            temp.replace(self.config)
        except OSError:
            pass

    def _launch(self):
        if self.process and self.process.poll() is None and self.sock:
            return True
        self._dispose()
        mpv = shutil.which("mpv")
        if not mpv:
            self._update(
                status="NEEDS MPV",
                title="INSTALL AUDIO: BREW INSTALL MPV",
                error="Install audio: brew install mpv",
                enabled=False,
            )
            return False
        parent, child = socket.socketpair()
        args = [
            mpv,
            "--no-config",
            "--idle=yes",
            "--no-video",
            "--no-terminal",
            "--input-media-keys=no",
            "--really-quiet",
            "--input-ipc-client=fd://" + str(child.fileno()),
            "--volume=0",
            "--network-timeout=10",
            "--cache=yes",
            "--demuxer-max-bytes=4MiB",
        ]
        if self.silent:
            args.append("--ao=null")
        try:
            self.process = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=(child.fileno(),),
            )
        except OSError:
            parent.close()
            raise
        finally:
            child.close()
        self.sock = parent
        self.sock.settimeout(2)
        self.buffer = b""
        return True

    def _request(self, command):
        if not self.sock:
            return None
        self.request_id += 1
        ident = self.request_id
        self.sock.sendall(
            (json.dumps({"command": command, "request_id": ident}) + "\n").encode()
        )
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            if b"\n" not in self.buffer:
                block = self.sock.recv(65536)
                if not block:
                    raise ConnectionError("Audio player closed")
                self.buffer += block
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                msg = json.loads(line)
                if msg.get("event") == "file-loaded":
                    self.ready = True
                if (
                    msg.get("event") == "end-file"
                    and msg.get("reason") == "error"
                    and self.state.enabled
                ):
                    self._schedule_retry()
                if msg.get("request_id") == ident:
                    self.sock.settimeout(0.3)
                    return msg.get("data") if msg.get("error") == "success" else None
        return None

    def _stream_url(self):
        index = self.state.station
        if index not in self.streams:
            url = STATIONS[index][2]
            if url.endswith(".m3u"):
                with urllib.request.urlopen(url, timeout=5) as response:
                    text = response.read(16384).decode()
                urls = []
                for line in text.splitlines():
                    line = line.strip()
                    parsed = urlparse(line)
                    if parsed.scheme in ("http", "https") and (
                        parsed.hostname or ""
                    ).endswith(".somafm.com"):
                        urls.append(line.replace("http://", "https://", 1))
                if not urls:
                    raise ValueError("Station playlist has no usable streams")
                self.streams[index] = urls
            else:
                self.streams[index] = [url]
        urls = self.streams[index]
        return urls[self.attempts % len(urls)]

    def _load(self):
        if self._launch():
            self._update(
                status="TUNING",
                playing=False,
                title="FINDING YOUR FREQUENCY...",
                error="",
            )
            self._request(["stop"])
            self._request(["set_property", "volume", 0])
            self.actual_volume = 0
            self.fade_started = 0
            self.ready = False
            self.playing_url = self._stream_url()
            self.loaded_at = time.monotonic()
            self.retry_at = 0
            self._request(["loadfile", self.playing_url, "replace"])
            self._request(["set_property", "pause", False])

    def _schedule_retry(self):
        if not self.retry_at:
            self.attempts += 1
            self.retry_at = time.monotonic() + min(30, 2 ** min(self.attempts, 5))
        self._update(
            playing=False, status="RECONNECTING", title="SIGNAL LOST. TUNING BACK IN..."
        )

    def _worker(self):
        next_poll = 0
        while not self.stopping:
            try:
                try:
                    action, value = self.commands.get(timeout=0.1)
                except queue.Empty:
                    action, value = None, None
                if action == "close":
                    break
                if action == "toggle":
                    self._update(enabled=not self.state.enabled)
                    if self.state.enabled:
                        self.attempts = 0
                        self._load()
                    else:
                        self.retry_at = 0
                        initial = self.actual_volume
                        for step in (3, 2, 1, 0):
                            self._request(
                                ["set_property", "volume", initial * step / 4]
                            )
                            time.sleep(0.04)
                        self._request(["stop"])
                        self.actual_volume = 0
                        self._update(
                            playing=False,
                            status="OFF",
                            title="A LITTLE MUSIC, WHEN YOU WANT IT.",
                        )
                if action in ("station", "next"):
                    idx = value if action == "station" else self.state.station + value
                    self._update(station=idx % len(STATIONS))
                    self.attempts = 0
                    if self.state.enabled:
                        self._load()
                    self._save()
                if action == "volume":
                    self._update(volume=max(0, min(100, self.state.volume + value)))
                    self._request(["set_property", "volume", self.state.volume])
                    self.actual_volume = self.state.volume
                    self._save()
                now = time.monotonic()
                if self.state.enabled and self.retry_at and now >= self.retry_at:
                    self._load()
                if self.state.enabled and self.sock and now >= next_poll:
                    idle = self._request(["get_property", "core-idle"])
                    audio = self._request(["get_property", "audio-params"])
                    path = self._request(["get_property", "path"])
                    if (
                        self.ready
                        and path == self.playing_url
                        and audio
                        and idle is False
                    ):
                        meta = self._request(["get_property", "metadata"]) or {}
                        title = (
                            meta.get("icy-title")
                            or meta.get("title")
                            or meta.get("TITLE")
                            or STATIONS[self.state.station][1]
                        )
                        if meta.get("artist") and not meta.get("icy-title"):
                            title = meta["artist"] + " - " + title
                        if not self.state.playing:
                            self.fade_started = now
                        self._update(
                            playing=True,
                            status="LIVE",
                            title=str(title)[:300],
                            error="",
                        )
                        self.attempts = 0
                        self.retry_at = 0
                    elif now - self.loaded_at > 15:
                        self._schedule_retry()
                    next_poll = now + 0.75
                if self.state.playing and self.state.enabled and self.fade_started:
                    fraction = min(1, (now - self.fade_started) / 0.8)
                    volume = round(self.state.volume * fraction)
                    if volume != self.actual_volume:
                        self._request(["set_property", "volume", volume])
                        self.actual_volume = volume
                    if fraction >= 1:
                        self.fade_started = 0
            except (OSError, ValueError, ConnectionError) as exc:
                self._update(error=str(exc)[:120])
                if self.state.enabled:
                    self._schedule_retry()
                else:
                    self._update(
                        playing=False,
                        status="OFF",
                        title="A LITTLE MUSIC, WHEN YOU WANT IT.",
                    )
                if self.sock:
                    self.sock.close()
                    self.sock = None
        self._dispose()

    def _dispose(self):
        if self.sock:
            self.sock.close()
            self.sock = None
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None

    def close(self):
        self.stopping = True
        self.commands.put(("close", None))
        self.thread.join(timeout=8)
        self._dispose()
