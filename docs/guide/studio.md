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
wfb studio                      # then open the address it prints
```

Faces are opened in the editor itself, from its home screen
([faces in and out](#faces-in-and-out)), not named on the command line.

The address it prints ends in `?claim=…`: open it once, in the browser you
will use ([whose faces](#whose-faces)).

| Flag | What it does |
|---|---|
| `-p`, `--port` | the port (default 8765) |
| `--host` | the address to listen on (default `127.0.0.1`, this computer only); anything else warns, since the editor writes files |
| `--state-dir` | where every face's history is kept (default `~/.local/state/wfb/studio`, or `$XDG_STATE_HOME/wfb/studio`) |
| `--snapshot-minutes` | how often a changed face is snapshotted (default 5) |
| `--keep-days`, `--keep-snapshots` | on start, faces untouched this many days are deleted, and each keeps its newest snapshots (defaults 30 and 50); a browser unseen this long is forgotten too |
| `--single-user` | every browser sees and edits the same faces, as one person ([whose faces](#whose-faces)) |
| `--allow-host` | also answer requests addressed to this name, a proxy's or a LAN name (repeatable); see below |

In the Docker image, publish the port to your computer only and keep the
history in a volume ([the container guide](../container.md#the-editor)):

```sh
docker run --rm -it -p 127.0.0.1:8765:8765 \
  -v "$HOME/Library/Application Support/Garmin/ConnectIQ/Devices:/devices:ro" \
  -v wfb-studio:/state -v wfb-keys:/keys garmin-wf-builder studio
```

## Whose faces

Each browser has its own faces. The editor knows a browser by a cookie,
kept as long as the faces are (`--keep-days`) and renewed on every visit;
another browser, or one whose cookies were cleared, starts with none.

- **The address `wfb studio` prints** carries a one-time claim. The browser
  that opens it gets every face the editor kept from before faces
  belonged to a browser.
- **Use my faces in another browser**, on the home screen, gives a link
  for the other browser: it works once, within 10 minutes, and from then
  on both see the same faces.
- **`--single-user`** turns this off: every browser sees every face, as
  before.

The editor answers only requests addressed to `127.0.0.1`, `localhost`,
`[::1]`, the `--host` it listens on, or an `--allow-host` name. A web page
elsewhere cannot reach it by pointing its own name at this computer, and
the cookie travels only with the editor's own requests.

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

Drag the edge between a side panel and the centre to widen or narrow
the panel; a double click on the edge puts its width back. The browser
remembers both widths.

The bar above the centre picks the watch, the style, what each slot
shows, the time, asleep, always-on and the skin, and the zoom. A slot is
drawn showing its first type until you pick another of its choices there:
the watch draws whatever the wearer picks, so check each choice fits. The faces in the strip under it
switch the watch on a click.

**Time** and **Date** set the moment the face is drawn at; left empty,
it is a sample one (10:09:42 on Wed 3 Sep). **now** draws it at this
computer's time and date instead, and keeps it going: the face is drawn
again each second, once the last frame has arrived, and the strip's
faces each minute. Switched off, the face stays at the moment it last
showed. A slot showing the date draws its sample text either way.

**Zoom** is a slider from 0.2× to 4× (screen pixels per watch pixel). The
face is always drawn at the watch's own resolution and shown at the zoom
without smoothing, so every watch pixel is a visible block, as it is
while you drag. **1:1**
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
a plain arc gauge's (`style: arc`) radius when it is centred and its
angles, the fill following them, and a box's edge when the box is aligned
to the other edge. Otherwise it
shows the outline, since a centred box's edges round about its centre on
the watch in a way only the compiler knows. When you let go, the change is
written and the watch's own rendering replaces the preview. A change the face cannot take
snaps back, with the reason, and so does anything you did after it that
was still waiting to be written.

You need not wait for the watch's rendering: the next drag can start at
once, from where the last one put things ("saving…" shows while changes
are on their way). They are written in the order you made them.

**Nudging.** With the face shown, the arrow keys move the selection one
pixel, ten with **Shift**, written the same way as a drag. Repeats made
while an earlier change is still being written go together as one change,
so a held key does not write one change per pixel.

**Snapping.** A moved element's edges and centre snap to the screen's
centre and to other elements' centres and edges, within 4 pixels, shown as
lines; with none near, its centre snaps to a grid of 5%r about the screen
centre. An axis you did not drag along never moves. Sizes snap to the same
grid, angles to 30° within 3°, else to 6°. Hold **Alt** to place freely;
**Escape** cancels a drag.

**Units.** A drag is written in the unit the key already has: a `%r` stays
`%r`, a `%` stays `%`, rounded to the coarsest value that still lands on
the pixel you dropped it on, on the watch you are looking at. A key written
in `pt` cannot be dragged (a `pt` has no size outside its font). When no
value in the key's unit lands exactly on that pixel, the nearest one is
written and a notice says so.

### Properties

The selection's keys, every one the format offers for its type, each with
a control: a number and its unit, an angle, the 3×3 alignment picker, a
colour ([the colour picker](#the-colour-picker)), a text with **+ data** to insert a
reading, a font, an icon, a touch-and-hold target, a slot, a hand set (with
**edit the set**, its lines in the YAML tab), a list of choices, on
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
  slot and hands for their set (both declared in the Face tab).
- With an element selected: **↑ ↓** reorder it, **Duplicate** (Ctrl+D),
  **Delete** (Del), **move to…** any block or group. Delete, like the
  arrow keys, acts on everything selected, as one change.
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
- **Colours**: each colour with what uses it (click an element to select
  it). Click a name to rename it: every `color.<name>` in the face
  follows. Its chip opens the picker, and a new colour reaches **every**
  user listed. **+ Colour** adds one; **×** deletes one, refused while
  something uses it; **Remove unused** deletes every colour nothing
  uses, except `bg`, `accent`, `text` and `fg`, which the launcher icon
  reads. A ⚠ marks a colour a target's screen would dither
  ([colours](colors.md)). A colour tagged **auto** is one the editor
  named after its value (below).
- **Colour settings**: the accent and data colours the wearer picks on the
  watch ([configuration](configuration.md)). **+ Accent colour** adds the
  setting; then its default, the role it binds (`accent` unless you name
  another), and which of the face's colours the wearer may pick, ticked.
  The editor always writes that list, so adding a colour to the palette
  never changes what the wearer is offered. A setting written
  `choices: any` is shown, not edited: on a fēnix 8 it opens the watch's
  own colour picker, and on a watch without one (fr955) it lists every
  colour in the palette. **Make it a list** replaces it with the face's
  colours that no target dithers.
- **Schemes** ([colour schemes](colors.md#colour-schemes)): colours that
  follow the style the wearer picks. Each change below is one change, with
  one **Undo**, because a scheme is written in several places at once.
  - With none yet: tick the colours that should follow the style and
    **Make switchable…**. They move into a first scheme as its roles,
    keeping their names, so everything using them keeps working, and a
    style picking the scheme is added (or every style picks it).
  - The table: each role's colour per scheme, through the picker, without
    roles (a scheme's colour must be known when the face is built). Click
    a scheme's or a role's name to rename it: the styles naming the scheme,
    or every `color.<role>`, follow. **×** deletes a scheme with the styles
    that pick it (not the last scheme), or a role from every scheme
    (refused while something uses it).
  - **+ Scheme** adds a copy of the first scheme and a style picking it:
    one per layout when the styles name layouts (`analog_dusk`,
    `digital_dusk`). **+ Role** adds a role to every scheme, white until
    you set it.
  - **Remove schemes…** keeps one scheme's colours as palette colours of
    the same names. Every style loses its scheme: a style that named only
    a scheme goes, and one that names a layout stays, even when that
    leaves two alike. The confirmation says how many; Diagnostics then
    names each copy, for you to delete or change.
- **Styles**: the default, each style's label (the name the wearer sees;
  cleared, the entry has none), layout and scheme, add (shaped like the
  others), delete ([styles and layouts](styles-and-layouts.md)).
- **Hand sets** ([analog hands](analog-hands.md)): each set drawn alone,
  as at 10:09:42, on the face's first watch; each hand's colour through
  the picker, and how many parts it has; the elements placing it (click
  one to select it). Click a name to rename it: every `set:` naming it
  follows. **Duplicate** copies it; **×** deletes it, refused while an
  element places it. **Edit in YAML** opens the YAML tab with the set's
  lines selected: a hand's parts are edited there. **+ Hand set** adds one
  of four presets, `classic`, `baton`, `dauphine` and `subdial` (a small
  seconds hand), in the face's own colours; on a face with no hands yet it
  also places it at the centre.
- **Slots**: the complication slots the wearer points at a reading on the
  watch ([the Data axis](configuration.md#the-data-axis)), one card each;
  the same card shows above the keys of an element drawing the slot.
  - Every complication type, by group (activity, health, performance,
    weather, time, device), with its icon and the reading the editor
    draws for it. Tick the types the wearer may pick; **★** marks what the
    slot shows first, until the wearer picks (click another star to change
    it; that type joins the list). **the wearer may pick any type** hands
    the wearer the watch's own picker, Garmin's later types included;
    unticking it brings your list back.
  - A ticked type's icon button picks its icon for this slot: any
    catalogue icon, `none`, or a codepoint (`U+F1340`); **×** goes back to
    the type's own.
  - **Rename** (every `slot:` naming it follows), **×** deletes it (refused
    while an element draws it), **menu title** is its title in the settings
    menu of a watch without the native editor, and **drawn by** lists the
    elements drawing it (click one to select it).
  - **+ Slot** asks what the new slot shows first, then its name, and adds
    a data element drawing it, as one change.
- **Fonts**: a font's size, **Replace…** its file, **+ Font from a file…**,
  delete ([fonts](fonts.md)).

### The colour picker

A colour's chip opens three groups:

- **This face**: its colours, then its roles where the key takes one (a
  role follows the wearer's style or pick).
- **MIP 64**: [the 64 colours](mip-palette.md) a MIP screen shows exactly,
  by name. A ringed one is already in the face.
- **Custom**: the browser's colour picker and a hex field. Under them, the
  name it will have, and a ⚠ with the nearest safe colour when one of the
  face's screens would dither it (a 64-colour screen, or black and white
  on a 2-colour one).

Whatever you pick, the element names a colour of the face, never a bare
hex value. A colour the face already has is reused, whatever its name.
One of the 64 is added under its name, with its label (`color.red`); any
other colour as `c` and its hex (`color.cFF8000`). A name already taken,
by another colour or a role, gets `_2`. The name is yours to change at
any time.

A picker on an element changes only that element: it points the key at a
colour and never changes the colour itself, so nothing else moves. To
change a colour everywhere it is used, change it in **Colours**.

The editor's own colours are those named after their value. When you
change one's value in **Colours** it is renamed to match (`cFF8000`
becomes `cFF5500`, `red` becomes `bright_red`), and when the last element
using one picks another colour, it is removed. A colour you named yourself
is never renamed or removed for you.

### The YAML tab

**YAML** above the face shows the design's text, with completion and
explanations from the format's schema and the compiler's diagnostics in
the gutter. What you type is saved a moment (300 ms) after you stop. Text that
is not YAML for a moment (an open bracket) is not saved, and says so under
the text, until it is YAML again. Text the compiler reports errors on is
saved, with the errors beside it: the face is not drawn until they are
mended, and the canvas waits for that.

Selecting an element on the face or in the layers selects its lines; the
cursor selects the element it is in. Switching to the face and back keeps
the pane where it was, scrolled and with its cursor, unless another
element was selected meanwhile: then the pane shows that element's lines.
If the face changed elsewhere while
you were typing (the Properties or Face panel, another tab), your text is
not saved over that change: the pane keeps it and asks. **Keep my text**
saves it over the other change, which Undo brings back; **Take the face as
it is** discards your typing and shows the face as it now is.

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
- Edit a polygon's points, a hand's parts, or keys no control covers,
  except in the YAML tab.
- Run in a browser on another computer: it listens on this one only,
  unless you tell it otherwise, and then warns.
- Log in: a browser is who you are (above).

The editor's checks and gestures are tested without a browser; the pages
themselves are checked by hand ([limitations](../limitations.md)).
