# Changelog

## Unreleased

- Support tmux in Ghostty through graphics passthrough and pane-relative Unicode placeholders.
- Give concurrent cafés independent image IDs and restore static tiles after window switching or reconnecting.
- Retry graphics detection while tmux finishes its initial redraw, and explain how to enable passthrough when it is disabled.

## 1.0.0 — initial release

- A pixel-art café with local-time lighting, a real wall clock, a pour-over brewer, and Miso the cat.
- Independent drifting clouds, an ambient weather cycle, rain, stars, and small background animations.
- A clickable internet radio with four stations, remembered volume and station, and automatic reconnection.
- macOS display and idle-system keep-awake assertions that end when caf exits.
- Keyboard and mouse controls, resizing, frame-rate limits, and terminal cleanup.
- Bundled artwork and font, a local launcher, and reproducible package and lifecycle checks.
