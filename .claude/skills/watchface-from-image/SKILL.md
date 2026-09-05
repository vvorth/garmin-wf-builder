---
name: watchface-from-image
description: Turn a picture of a watch face -- a photo, a mockup, or a crude hand drawing -- into a buildable Garmin Connect IQ design. Use when someone shares an image and wants a watch face like it, or says "build me this watch face", "make a face that looks like this", or asks to design a Garmin watch face at all.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
---

# Build a Garmin watch face from a picture

**Read `skills/watchface-builder.md` from the repository root and follow it.**
That is the whole procedure, and it is kept model-agnostic on purpose so the same
instructions work outside Claude Code. This file exists only to make it
discoverable here and to add what is specific to this environment.

If you cannot find that file, look for it:

```sh
find . ~ /workspace -maxdepth 6 -name watchface-builder.md 2>/dev/null | head
```

## Specific to Claude Code

- **You can see images.** So the "if you cannot see images" branches in step 2
  and step 5 do not apply: look at what the person shared, and genuinely compare
  the rendered preview against it before saying the design matches.
- **Read the preview PNG with the Read tool** — it renders inline. Comparing it
  with the source image is the step that catches everything validation cannot.
- **`wfb` is this repository's own tool.** From the repository root,
  `./.venv/bin/python wfb.py <command>` always works; `wfb doctor` will confirm.
- **Show the person the preview** as you iterate, rather than only describing it.
  A watch face is a visual artefact and they will spot in a second what would
  take a paragraph to explain.
