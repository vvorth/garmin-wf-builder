# The editor: `wfb studio`

`wfb studio` is a visual editor for a face, run as a small web app on your
own computer and used from a browser. You place and size elements on the
watch's screen, set their properties, arrange them in layers and edit the
face's colours, styles and fonts. Every change is written into the face's
YAML, in your own units and spelling, so the file you download is the
same kind of design file you would write by hand, with your comments and
layout kept.

**Build…** compiles the face for one watch and downloads its `.prg`, ready
to copy to the watch; **Download** saves the face itself.

## Starting it

```sh
wfb studio                      # then open http://127.0.0.1:8765/
wfb studio examples/showcase/face.yaml   # opens that face first
```

| Flag | What it does |
|---|---|
| `-p`, `--port` | the port (default 8765) |
| `--host` | the address to listen on (default `127.0.0.1`, this computer only); anything else warns, since the editor writes files |
| `--state-dir` | where every face's history is kept (default `~/.local/state/wfb/studio`, or `$XDG_STATE_HOME/wfb/studio`) |
| `--snapshot-minutes` | how often a changed face is snapshotted (default 5) |
| `--keep-days`, `--keep-snapshots` | on start, faces untouched this many days are deleted, and each keeps its newest snapshots (defaults 30 and 50) |

A face named on the command line is copied into the editor, with the font
files it names. The editor never writes back to it: you save by
downloading.

In the Docker image, publish the port to your computer only and keep the
history in a volume ([the container guide](../container.md#the-editor)):

```sh
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-studio:/state -v wfb-keys:/keys garmin-wf-builder studio
```

## Faces in and out

The home screen offers:

- **New face**: from one of `wfb new`'s templates, with a name; its watches
  are set in the Face tab.
- **Open**: drop or choose a `.zip` or a `.yaml`.
- **Recent**: every face the editor holds, with its history, and Delete.

A face travels as a **bundle**: a `.zip` with the design at its root
(`face.yaml` by convention) and its font files beneath it, by convention
in `assets/`. A face that uses no font file can be a plain `.yaml`. A zip
of a folder (what a desktop "compress" makes) opens too. A bundle is
refused, with the reason, when an entry would land outside it (`..`, an
absolute path, a link), when it has no `.yaml` at its root or several with
none called `face.yaml`, or when it is too large.

When a face names a font file the bundle does not hold (a bare `.yaml`
that uses one, say), it opens anyway and a banner lists the missing
files. **Add…** uploads one into `assets/` and points the face at it.

**Download** gives a `.zip` when the face uses font files and a `.yaml`
when it does not; the arrow beside it picks either. A `.yaml` of a face
that uses font files will not build on its own, and the editor says so
first.

## The editor

| Left | Centre | Right |
|---|---|---|
| **Layers**: the element tree; **Face**: targets, colours, schemes, styles, slots, fonts | the face on one watch, or its **YAML**; below it, one small frame per target | **Properties** of the selection; **Diagnostics** and **History** |

The bar above the centre picks the watch, the style, the time, asleep,
always-on and the skin, and the zoom. The faces in the strip under it
switch the watch on a click.

**Zoom** is a slider from 0.2× to 4× (screen pixels per watch pixel). **1:1**
shows the watch at its real size: its screen's pixels over its pixels per
inch, from its device files (a watch whose files give none has no 1:1).
A browser cannot measure its screen, and takes 96 of its pixels as an
inch, which is right on some screens and not others. **⚙** calibrates it:
hold a bank card to the screen and drag until the box matches; the
browser keeps the result. The editor remembers the zoom too.

**Skin** draws the watch round its screen, as the simulator does, at the
same zoom; some watches' files have no skin, and the box is then off.

### On the face

Click an element to select it; its box and handles appear. Drag it to move
it. Its handles resize it:

| Handle | Where | Changes |
|---|---|---|
| size | the edge that moves when it grows (a centred box grows both ways, so its edge moves half as far as its size) | `size:` width or height |
| radius | the circle's right | `radius:` |
| angle | an arc's two ends | `start_angle:`, `sweep:` |
| end | a line's two ends | `at:`, `to:` |

A polygon has no handles; its `points:` are edited in the YAML.

**Moving several at once.** Ctrl-, Cmd- or Shift-click more elements, on
the face or in the layers. A group, or a selection of several, shows a
**move handle** on the middle of its top edge (a disc with four arrows): drag it, or any
selected element, and they all move together, as one change that one
**Undo** takes back. A group moves with everything in it. Pressing an
element that is not selected, such as a member of a selected group, selects
it and drags it alone. A click on a selected element without a drag selects
just that one. Size and angle handles act on one element, so a selection of
several shows none.

While you drag, the moved elements are drawn where they will go. A resize
or an angle draws the element itself where the editor can be sure of the
result: a circle's or arc's radius when it is centred, an arc's angles,
and a box's edge when the box is aligned to the other edge. Otherwise it
shows the outline, since a centred box's edges round about its centre on
the watch in a way only the compiler knows. When you let go, the change is
written and the watch's own rendering replaces the preview. A change the face cannot take
snaps back, with the reason.

**Snapping.** A moved element's edges and centre snap to the screen's
centre and to other elements' centres and edges, within 4 pixels, shown as
lines; with none near, its centre snaps to a grid of 5%r about the screen
centre. An axis you did not drag along never moves. Sizes snap to the same
grid, angles to 30° within 3°, else to 6°. Hold **Alt** to place freely;
**Escape** cancels a drag.

**Units.** A drag is written in the unit the key already has: a `%r` stays
`%r`, a `%` stays `%`, rounded to the coarsest value that still lands on
the pixel you dropped it on, on the watch you are looking at. A key written
in `pt` cannot be dragged (a `pt` has no size outside its font).

### Properties

The selection's keys, every one the format offers for its type, each with
a control: a number and its unit, an angle, the 3×3 alignment picker, a
colour (a palette or role name, or your own, with a warning when a
64-colour screen would dither it), a text with **+ data** to insert a
reading, a font, an icon, a touch-and-hold target, a slot, a list of choices, on
or off. **×** removes a key, back to its default. A key no control covers,
such as a list, `aod:` or `curve:`, shows its value; edit it in the YAML.

The three buttons above the keys, **all targets**, the watch in view
(by its id) and its shape, say where `at:`, `size:`, `radius:` and
`align:` changes go ([per-device and per-shape
overrides](placement.md#per-device-and-per-shape-overrides)):

- **all targets** writes the element's own key. A drag on the face goes
  where the watch you are looking at reads the key, its override if it has
  one.
- the watch's or the shape's button writes that override, creating it
  when needed, in the unit of the value it replaces.

A key overridden on the watch in view says so under its value.

### Layers

The tree lists the face's blocks in drawing order: `static` and
`elements`, then each layout's own two, with groups as folders. A block
the face does not have yet is listed empty, as somewhere an element can
go.

- **+ add…** adds an element of any type after the selection (or at the
  end of `elements`). A graph asks for its series, a data element for its
  slot (declared in the Face tab) and hands for their set.
- With an element selected: **↑ ↓** reorder it, **Duplicate** (Ctrl+D),
  **Delete** (Del), **move to…** any block or group.
- Drag a row onto another to put it before (upper half) or after (lower
  half) it; onto a group's middle to put it inside; onto a block's name to
  put it at the end.
- **Group**: Ctrl-, Cmd- or Shift-click more elements beside the first,
  then Group. The new group has no position or size of its own, so nothing
  moves on the screen. **Ungroup** puts its children back where it was;
  it is refused for a group with other keys (`at:`, `visible:`, ...),
  whose children take something from it.

A delete that would leave something dangling is refused the same way:
the only element of a layout a style names (the layout would go with it),
or a group's only child (a group needs children; delete the group). A move
the compiler refuses, such as a live reading into `static:`, is
refused with its reason ([static content](elements.md#static--draw-it-once-then-blit-it)).

### The Face tab

- **Targets**: add any installed watch that can run a face, or remove one.
- **Colours**: click a name to rename it (every `color.<name>` in the face
  follows), set a value, add, delete (refused while something uses it). A
  ⚠ marks a colour a target's 64-colour screen would dither
  ([colours](colors.md)).
- **Schemes**: each role's colour per scheme.
- **Styles**: the default, each style's layout and scheme, add (shaped like
  the others), delete ([styles and layouts](styles-and-layouts.md)).
- **Slots**: the complication slots the wearer points at a reading on the
  watch ([the Data axis](configuration.md#the-data-axis)). **+ Slot** adds
  one, showing any complication. Click a slot's name to rename it (every
  `slot:` naming it follows); beside it is its title in the settings menu
  of a watch without the native editor. **default** is what it shows until
  the wearer picks, and what the editor draws; **choices** is **any** (the
  watch's own picker) or **a list**, each type with its own icon (a name,
  `U+XXXX` or `none`; empty keeps the type's own). The default cannot be
  taken off the list. **drawn by** lists the elements drawing it (click
  one to select it), or offers **+ data element** when nothing does yet.
  A slot is deleted only while nothing draws it.
- **Fonts**: a font's size, **Replace…** its file, **+ Font from a file…**,
  delete ([fonts](fonts.md)).

### The YAML tab

**YAML** above the face shows the design's text, with completion and
explanations from the format's schema and the compiler's diagnostics in
the gutter. What you type is saved a moment (300 ms) after you stop. Text that
is not YAML for a moment (an open bracket) is not saved, and says so under
the text, until it is YAML again. Text the compiler reports errors on is
saved, with the errors beside it: the face is not drawn until they are
mended, and the canvas waits for that.

Selecting an element on the face or in the layers selects its lines; the
cursor selects the element it is in. If the face changed elsewhere while
you were typing (another tab), your text is refused and the pane reloads
the face as it is.

## Build

**Build…** opens a dialog listing the face's own watches, and any other
installed one below them. Pick one and **Build and download**: the editor
runs `wfb build` for that watch on the face as it is now, which takes a
few seconds, and the browser downloads `<face>-<watch>.prg`. The dialog
shows the memory it uses against the watch's limit, and the build's log;
a failed build shows the log, with the reason. Copy the `.prg` to the
watch's `GARMIN/APPS` folder ([getting started](getting-started.md)).

A face that does not load is not built: mend its errors first. One build
runs at a time. The build signs with the same developer key `wfb build`
does; in the container, mount `/keys` for it.

## History

Every change is recorded as you make it, so closing the tab or stopping
the editor loses nothing, and **Undo** and **Redo** (Ctrl+Z, Ctrl+Shift+Z
or Ctrl+Y; in the YAML tab these undo your typing) work across restarts.
A change after an undo ends the redo line, as in any editor.

A **snapshot** is a point in time to go back to. One is taken every few
minutes while the face changes, on every download, and on **Snapshot
now** in the History tab. **Restore** brings one back as an ordinary
change, so it too can be undone; **Open copy** opens it as a separate
face.

The history lives under `--state-dir`, one directory per face. Deleting a
face from the home screen deletes its history.

## What it does not do

- Put the `.prg` on the watch: copy it yourself
  ([getting started](getting-started.md)).
- Edit a polygon's points, or keys no control covers, except in the YAML
  tab.
- Run in a browser on another computer: it listens on this one only,
  unless you tell it otherwise, and then warns.

The editor's checks and gestures are tested without a browser; the pages
themselves are checked by hand ([limitations](../limitations.md)).
