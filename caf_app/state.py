import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import pairwise


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


@dataclass
class World:
    started: float = field(default_factory=time.monotonic)
    hour_override: float | None = None
    demo: bool = False
    weather_mode: str = "auto"
    lamp: int = 1
    cat_until: float = 0.0
    cat_watch_until: float = 0.0
    brew_until: float = 0.0
    toast: str = "STAY A LITTLE LONGER."
    toast_until: float = 8.0
    help: bool = False
    awake: bool = False
    running: bool = True
    focused: bool = True
    hover: str = ""
    weather_offset: float = 0.0

    def elapsed(self):
        return max(0.0, time.monotonic() - self.started)

    def clock(self, t=None):
        return datetime.now().astimezone()

    def sky_clock(self, t=None):
        t = self.elapsed() if t is None else t
        now = datetime.now().astimezone()
        if self.demo:
            return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                hours=(t / 6) % 24
            )
        if self.hour_override is not None:
            return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                hours=self.hour_override
            )
        return now

    def lighting(self, t=None):
        now = self.sky_clock(t)
        hour = now.hour + now.minute / 60 + now.second / 3600
        keys = [
            (0, "night"),
            (4.5, "night"),
            (6, "dusk"),
            (8.5, "day"),
            (15.5, "day"),
            (18, "dusk"),
            (20, "night"),
            (24, "night"),
        ]
        for (start, a), (end, b) in pairwise(keys):
            if start <= hour <= end:
                f = smooth((hour - start) / (end - start))
                night = (1 - f if a == "night" else 0) + (f if b == "night" else 0)
                return a, b, f, night
        return "night", "night", 0, 1

    def period(self, t=None):
        h = self.sky_clock(t).hour
        return (
            "AFTER HOURS"
            if h < 5 or h >= 22
            else "FIRST LIGHT"
            if h < 8
            else "SLOW MORNING"
            if h < 12
            else "GOLDEN AFTERNOON"
            if h < 17
            else "EVENING GLOW"
            if h < 20
            else "NIGHT SHIFT"
        )

    def weather(self, t=None):
        t = self.elapsed() if t is None else t
        if self.weather_mode != "auto":
            return {
                "clear": (0, 0, 0, "CLEAR"),
                "cloudy": (0.7, 0, 0, "OVERCAST"),
                "rain": (0.9, 0.85, 1, "SOFT RAIN"),
            }[self.weather_mode]
        phase = (t * (5 if self.demo else 1) + self.weather_offset) % 720
        if phase < 180:
            return 0.1, 0, 0, "CLEAR"
        if phase < 260:
            f = smooth((phase - 180) / 80)
            return 0.1 + 0.8 * f, 0, 0, "CLOUDS GATHERING"
        if phase < 300:
            f = smooth((phase - 260) / 40)
            return 0.9, 0.85 * f, f, "RAIN ARRIVING"
        if phase < 460:
            return 0.9, 0.85, 1, "SOFT RAIN"
        if phase < 520:
            f = smooth((phase - 460) / 60)
            return 0.9 - 0.2 * f, 0.85 * (1 - f), 1, "RAIN EASING"
        if phase < 620:
            f = smooth((phase - 520) / 100)
            return 0.1 + 0.6 * (1 - f), 0, 1 - f, "CLEARING SKIES"
        return 0.1, 0, 0, "CLEAR"

    def message(self, value, duration=5):
        self.toast = value
        self.toast_until = self.elapsed() + duration

    def pet(self):
        self.cat_until = self.elapsed() + 5
        self.message("MISO APPRECIATES THE COMPANY.")

    def cycle_weather(self):
        modes = ["auto", "clear", "cloudy", "rain"]
        self.weather_mode = modes[(modes.index(self.weather_mode) + 1) % len(modes)]
        self.message("WEATHER: " + self.weather_mode.upper())

    def cycle_lamp(self):
        self.lamp = (self.lamp + 1) % 3
        self.message(["LAMP: LOW", "LAMP: WARM", "LAMP: EXTRA COZY"][self.lamp])

    def brew(self):
        self.brew_until = self.elapsed() + 6
        self.message("A FRESH CUP. TAKE YOUR TIME.")


def duration(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
