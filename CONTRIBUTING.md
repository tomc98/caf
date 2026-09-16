# Contributing

Keep caf small, quiet, and easy to run. Bug fixes, terminal compatibility reports, performance improvements, and carefully paced animation details are welcome. Discuss large features in an issue first.

## Local development

Use macOS, Python 3.11+, and uv. Install mpv only if you want to test music.

```sh
uv sync --locked
uv run --no-sync ruff check caf_app tests
uv run --no-sync python -m unittest discover -s tests -v
sh -n caf install.sh
```

Run `./caf` directly in Ghostty for visual work. `./caf --render work/preview.png --time 18:00 --weather rain` renders a still without starting music or keeping the machine awake. The wall clock always uses real local time, even in previews.

## Terminal and package checks

```sh
uv run --no-sync python tests/signals.py
uv run --no-sync python tests/input_burst.py
uv run --no-sync python tests/tmux_session.py  # requires tmux
uv build
uv run --no-sync python tests/package_smoke.py dist/*.whl
```

The core and terminal tests briefly start their own caffeinate processes and check cleanup. The package check installs the built wheel in a temporary environment outside the checkout, then renders day, dusk, and night using the bundled assets. It may download dependencies.

CI runs these checks on macOS with Python 3.11 and 3.14. The tmux integration test creates its own server and simulated outer Kitty terminal. It checks decoded pixels, multiple panes, zoom, window switching, mouse and keyboard routing, disabled passthrough, and cleanup. It does not access existing tmux sessions or open a native terminal window. CI does not require live radio stations to be available.

Optional network checks require mpv:

```sh
uv run --no-sync python tests/live_radio.py
uv run --no-sync python tests/reconnect_radio.py
uv run --no-sync python tests/parent_death.py
uv run --no-sync python tests/terminal_session.py
```

The first three use muted output. `terminal_session.py` plays brief audible music. Scripts use their own processes, store diagnostics in ignored `work/`, and do not control an existing terminal window.

## Before opening a pull request

- Run checks relevant to your change and describe what you tested.
- For visual changes, include a screenshot or short clip and test window resizing, mouse targets, and exit cleanup in Ghostty.
- Include provenance and an appropriate license for new artwork or fonts. Do not add music files or recorded broadcasts.
- Keep personal paths, preferences, `.env` files, logs, and generated build files out of commits.

Bug reports should include the macOS and Ghostty versions, the output of `./caf --check`, how caf was launched, and steps to reproduce. Review diagnostics before sharing them; they include local process IDs and station metadata.
