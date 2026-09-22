---
name: watchface-from-image
description: Turn a picture of a watch face -- a screenshot, a photo, a mockup, or a crude hand drawing -- into a buildable Garmin Connect IQ watch face that looks as close to it as possible, by iterating preview-against-target comparisons. Use when someone shares an image and wants a watch face like it, says "build me this watch face", "make a face that looks like this", "copy this style", or asks to design a Garmin watch face at all.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
---

# Build a Garmin watch face from a picture

**Read `skills/watchface-builder.md` from the repository root and follow it.**
That is the whole procedure. It is kept model-agnostic on purpose so the same
instructions work outside Claude Code; this file only makes it discoverable
here and adds what is specific to this environment.

If you cannot find that file, look for it:

```sh
find . ~ /workspace -maxdepth 6 -name watchface-builder.md 2>/dev/null | head
```

## Specific to Claude Code

- **You can see images.** The "if you cannot see images" branches do not
  apply: look at what the person shared, and genuinely compare each compare
  sheet against it before saying the design matches.
- **Open every compare sheet with the Read tool.** `skills/face-compare.py`
  writes a PNG with target, preview, overlay and difference side by side;
  Read renders it inline. Looking at it is the step that catches everything
  validation cannot. Do not run a round without looking at its sheet.
- **Measure the picture with Python.** `./.venv/bin/python` has Pillow.
  A few lines that find the dial circle, sample colours and scan for where
  ticks, hands and text start and stop give you `%r` values directly.
- **`wfb` is this repository's own tool.** From the repository root,
  `./wfb.py <command>` always works; `./wfb.py doctor` confirms the setup.
- **Where to write the face:** in a new directory the person names, or
  `build/faces/<name>/face.yaml` if they name none. Never edit
  `examples/dashboard/face.yaml` (the user's playground) or the other
  examples unless asked.
- **Show the person the last compare sheet** when you report, rather than
  only describing it.
