# How to record the demo GIF

## Option A — VHS (recommended, produces clean GIFs automatically)

```bash
# Install VHS (macOS)
brew install vhs    # also needs: brew install ffmpeg ttyd

# Record
vhs assets/demo.tape
# → writes assets/demo.gif and assets/demo.mp4
```

Then put `demo.gif` in `assets/` and the README `![demo](assets/demo.gif)` line works.

---

## Option B — asciinema + agg (cross-platform)

```bash
pip install asciinema
brew install agg          # gif renderer for asciinema

# Record a session interactively
asciinema rec assets/demo.cast

# Convert to GIF
agg assets/demo.cast assets/demo.gif --theme dracula --font-size 14
```

---

## Option C — Quicktime / OBS screen capture

1. Open a terminal, set font size to 16+, dark theme
2. Run the commands manually, screen-record
3. Convert to GIF: `ffmpeg -i demo.mp4 -vf "fps=10,scale=1200:-1:flags=lanczos" assets/demo.gif`

---

## Tips for a good recording

- Use a **dark theme** (Dracula, Tokyo Night, Catppuccin Mocha)
- Font size **14–16**, terminal width **~120 columns**
- Record these commands in order:
  1. `arxiv recommend "your field" -n 4 --no-open`
  2. `arxiv direction "a hot topic" --no-open`
  3. `arxiv topic list`
- Keep it **under 90 seconds** — GitHub renders GIFs inline, people won't wait longer
- Use `--no-open` to prevent browser from popping up during recording
