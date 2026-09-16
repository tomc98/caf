# Validation — 2026-09-16

## Verified locally

- `uvx ruff check caf_app tests`: passed.
- `sh -n caf install.sh`: passed.
- `python -m unittest discover -s tests -v`: 12 tests passed. Covers real clock independence from scenery previews, lighting and weather transitions including the loop boundary, fragmented terminal input, mouse targeting, image tile reconstruction and unchanged-tile suppression, real macOS assertions, configuration persistence, animated rendering, and frame-rate limits during continuous input.
- `tests/live_radio.py`: all four stations reached decoded live playback in one player session after sequential station changes. Most recent checks: Lofi 3.6 seconds, Fluid 1.5 seconds, Groove Salad 1.7 seconds, Drone Zone 1.5 seconds. Audio was sent to mpv's null output for this network test.
- `tests/terminal_session.py`: the complete executable ran through a pseudo-terminal, negotiated Kitty graphics, emitted decodable RGB images, accepted mouse and keyboard controls, resized from 100×32 to 74×24, started actual audio output, changed station and volume, and restored terminal settings. Both child processes exited on close.
- `tests/signals.py`: SIGINT, SIGTERM, and SIGHUP restored the terminal and released the caffeinate process.
- `tests/input_burst.py`: a six-second real pseudo-terminal session received continuous mouse reports, accepted the lamp control, changed focus, stayed below the 12 / 6 fps caps, and restored terminal settings. The regression test failed before the fix because mouse input could cause an immediate extra redraw; the app now processes input until the next scheduled frame.
- `tests/reconnect_radio.py`: killing the audio player caused a new player to start and live decoded playback to resume.
- `tests/parent_death.py`: after SIGKILL of the parent app, both caffeinate and mpv exited without relying on the app's cleanup handler.
- Generated daytime, dusk, rainy, and midnight scenes were visually inspected. Cloud and cat sprites were inspected in the composed scene. Clouds and celestial objects are absent from the final background layers and are animated independently.

## Performance sample

120 rendered frames at a 100×32 terminal with 10×20 pixel cells. On this Mac, rendering and encoding averaged about 8.1 ms/frame in clear weather and 11.4 ms/frame in rain, at 418 / 599 KiB per frame respectively. This is a local renderer/encoder measurement, not a measurement of Ghostty's total CPU use. The application defaults to 12 fps and reduces to at most 6 fps when unfocused.

## Native Ghostty acceptance

The maintainer launched the app in Ghostty 1.3.1 and reported that it works well on 2026-09-16. This is user-reported native acceptance. The automated checks above exercise the renderer and terminal protocol separately.

## Open-source preparation

- The 12 core tests pass on Python 3.11.14 and 3.14.2. Terminal signal cleanup and sustained input checks pass after the packaging changes.
- The built wheel includes all room art, sprites, the font, its OFL license, artwork provenance, and the project license. Isolated installs render daytime, dusk, and rainy midnight scenes outside the source checkout on both tested Python versions.
- `ruff check`, shell syntax checks, lockfile validation, and `actionlint` pass. The macOS GitHub Actions matrix is configured for Python 3.11 and 3.14; hosted CI has not run before publication.
- The publishable file set passed a credential-pattern scan and a personal-path check. PNG assets contain no embedded text or EXIF metadata. Local work, virtual environments, preferences, backups, and build outputs are excluded from Git and the source archive.
- GitHub publication, the first remote CI run, and a release tag remain separate release steps.

## Reproduce

Run from the project root with `./.venv/bin/python`:

- `-m unittest discover -s tests -v`
- `tests/live_radio.py` (network; muted output)
- `tests/terminal_session.py` (network; brief actual audio)
- `tests/signals.py`
- `tests/input_burst.py`
- `tests/reconnect_radio.py` (network; muted output)
- `tests/parent_death.py` (network; muted output)

Verification scripts write intermediates under `work/` and use isolated radio preferences. They do not control Ghostty or another terminal window.
