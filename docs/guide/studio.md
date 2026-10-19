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

| Flag | What it does |
|---|---|
| `-p`, `--port` | the port (default 8765) |
| `--host` | the address to listen on (default `127.0.0.1`, this computer only); anything else warns, since whoever reaches the port can run builds. The server answers only a request addressed to an IP address, `localhost`, this host or an `--allow-host` name, and takes a build only from its own page, so a web page elsewhere cannot use it |
| `--allow-host NAME` | also answer requests addressed to `NAME`: the name you reach a remote machine by, or a proxy's; repeat it, or give several names comma separated (`--allow-host studio-box,studio-box.lan`). Run on a remote machine as `wfb studio --host 0.0.0.0 --allow-host studio-box` and open `http://studio-box:8765/` |
| `--allow-any-host` | answer requests addressed by any name, for debugging; it warns, since a web page whose name points at this computer can then read the editor (builds still come only from its own page) |
| `--devices-dir` | the device definitions, as for `wfb build` |
| `--fonts` | Garmin's own font files, as for `wfb preview` |

In the Docker image, publish the port to your computer only
([the container guide](../container.md#the-editor)).

## Where the faces are

The editor runs in the browser, compiler and all: the server sends the
watches' files and fonts, and builds a `.prg` when you ask. Every face,
with its history and snapshots, is kept in that browser's own storage
(IndexedDB), so closing the tab or stopping the server loses nothing.
Tabs of one browser share those faces: a change made in one tab shows in
every other tab that has the face open, and editing it there carries on
from that change.
Each browser has its own faces, and so does each address: the faces
opened at `http://127.0.0.1:8765/` are not the ones at
`http://localhost:8765/` or on another port, and the home screen names
the address its library belongs to. To edit a face in another browser,
or at another address, download it there and open it. The editor asks
the browser to keep its storage even when the disk runs low; clearing
the browser's site data still deletes the faces, so download a face you
want to keep elsewhere.

## Faces in and out

The home screen offers:

- **New face**: from one of `wfb new`'s templates, with a name; its watches
  are set in the Face tab.
- **Open**: drop or choose a `.zip` or a `.yaml`.
- **Library**: every face the editor holds, each pictured on its first
  watch, with its history. Click the picture or the name to open it;
  **Rename** changes the name it is listed and downloaded under (not part
  of its text, so not a change in its history). A face stays until you
  **Delete** it, which removes its history and snapshots with it; a tab
  that has it open then says so, and offers to copy its text.

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
| **Layers**: the element tree; **Face**: the face's name and id, targets, defaults, colours, schemes, layouts, styles, slots, fonts | the face on one watch, or its **YAML**; below it, one small frame per target | **Properties** of the selection; **Diagnostics** and **History** |

Drag the edge between a side panel and the centre to widen or narrow
the panel; a double click on the edge puts its width back. The browser
remembers both widths. The right column's two parts fold away, each on
its own: click **Properties**, or the **▾** at the end of the tabs. The
browser remembers which are folded. The face's name in the top bar is
renamed by clicking it, as in the library. The small frames below the
face catch up with it once it has been still for a moment, so a run of
drags does not redraw them all each time, and they are drawn after
anything else the editor is asked, so they never delay a change; a click
on one views that watch.

Messages (a refused change's reason, a notice) show for a few seconds at
the bottom. **Messages**, in the bottom right corner, keeps every one,
newest first, and counts those you have not seen.

**Diagnostics** are the compiler's errors, warnings and notes, most severe
first, one finding the same on several targets listed once ("-- and the
same on …"); the tab counts each kind, and when there is more than one kind,
chips above the list show one at a time. The chosen kind stays chosen when
you visit History and come back, and the tab says so (**· warnings
only**). Clicking a diagnostic selects the element it is about. When the
face has errors, the top bar counts them; click the count to see them.

A warning you may accept on the element it is about (a check `lint:
{allow: [...]}` can silence, on a line inside an element; [lint
suppression](lints.md#lint-suppression)) has **accept here…**. It asks why, in a box on the
row: type the reason and press **Enter** or **Accept** (the reason cannot
be empty), or **Escape** or **×** to keep the warning. The element's
`lint:` is then written as one change: `lint: {allow: [<code>], reason:
<why>}` when it has none, else the code joins its `allow:` list, and its
reason, which the box starts with, is kept unless you change it. The
warning goes, since the element now accepts it.

The bar above the centre picks the watch, where a geometry edit lands
(**Edit for**, [below](#on-the-face)), the style and the zoom.
**Preview ▾** holds the rest of what the face is drawn at: the time and
date, what each slot shows, which frame is drawn and the skin; its label
lists whatever is not the default, and **Back to the sample moment**
puts the sample time and date back, leaving the rest as it is.
The frame is one of **awake**, **asleep** and **AOD**: asleep is an
always-on (MIP) watch's low-power frame and AOD an AMOLED watch's, so each
watch offers only its own, and switching watch swaps one for the other.
Together, the watch, the frame and the style are the **editing context**:
what the canvas draws, and what Properties shows and edits
([Properties](#properties)). A slot is drawn showing its first type until you pick
another of its choices there: the watch draws whatever the wearer picks,
so check each choice fits. The faces in the strip under it switch the
watch on a click.

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
It is a switch: while on, every watch you pick is shown at its own real
size; clicking it again, or **1**, goes back to the zoom you had, and
zooming any other way turns it off from the size shown.
A browser cannot measure its screen, and takes 96 of its pixels as an
inch, which is right on some screens and not others. **⚙** calibrates it:
hold a bank card to the screen and drag until the box matches; the
browser keeps the result. The editor remembers the zoom too.

**Ctrl** (or **Cmd**) and the mouse wheel zoom about the pointer, and
**Ctrl+=** and **Ctrl+-** zoom in and out; **Ctrl+0** fits the watch in
the space, and **1** shows it at its real size. To pan
a face larger than the space, drag the space around the watch, drag with
the middle button, or hold **Space** and drag; the wheel scrolls too.

**?** (or the **?** button in the top bar) lists every shortcut. None of
them acts while you type in a field or the YAML tab.

**Ctrl+K** (**Cmd+K**) opens a search over every element (by id, its type
shown beside it), colour, role, font, slot, hand set and style name: type
any part of a name, arrow keys move the highlight, Enter picks it.
Picking an element selects it, exactly as clicking it in Layers or on the
face would; picking anything else switches to the Face tab, open at the
section that lists it (a Face tab already showing switches section).

**Help** (in the top bar, and beside the title on the faces page) opens
this guide and the README in a popup: links between pages open there,
with **Back** to return and **Contents** for the chapter list; a link to
an example face or any other file opens in a new tab.

**Skin** draws the watch round its screen, as the simulator does, at the
same zoom; some watches' files have no skin, and the box is then off. The
editor remembers it.

### On the face

Click an element to select it; its box and handles appear. Drag it to move
it. Its handles resize it (an element locked in Layers takes no click,
drag or handle on the face, [below](#layers)):

| Handle | Where | Changes |
|---|---|---|
| size | the edge that moves when it grows (a centred box grows both ways, so its edge moves half as far as its size) | `size:` width or height |
| radius | the circle's right | `radius:` |
| angle | an arc's two ends | `start_angle:`, `sweep:` |
| end | a line's two ends | `at:`, `to:` |
| vertex | each point of a polygon, a small square | that point of `points:` |
| segment | the middle of each of a polygon's edges, a dot | adds a point there |
| font size | a text's top right, when it draws in a font baked from a file; drag up to grow | its font's `size:` |

**A text's font size.** The handle writes the `size:` of the text's own
font when it is written inline, or of the face's `fonts:` entry when no
other element uses it; a font another element shares is refused, naming
it (change it in the Face tab's Fonts, or give the text its own font in
Properties). A font's size is the same on every watch, so **Edit for** a
watch, shape or display refuses it. While you drag, the box is outlined
rather than redrawn: the font is baked again at the new size, which only
the worker can do.

A handle takes a press within a few pixels of it, except where that zone
would cover the element itself: pressing inside a thin bar, thinner than
the zone, moves the bar, and its size handle takes a press just outside it.
A line's ends keep their handles; a press on its middle moves it.

**A polygon's points.** Dragging a vertex moves that one point, written in
the unit its `points:` entry already has; dragging the polygon itself
moves every point. Clicking a vertex picks it: it is drawn filled, its item
in the `points:` list in Properties is marked, and **Delete** removes it (a
polygon keeps at least three points). Hovering an item of the list picks
its vertex the same way, so the list and the face always name the same
point. Clicking a segment handle adds a point at the edge's middle, after
the point the edge follows; dragging it adds the point where you let go.
A polygon part written with `mirror: x` shows its reflected half too, as
hollow squares that cannot be dragged: move a listed point and its
reflection follows, and a point on the axis stays on it.

#### Hands, patterns and needles: enter the set

A `hands` element draws its set's parts, a `pattern` its copies of its
parts, and a `gauge` with `style: needle` its needle's parts, all in a frame
of their own: the parts are written pointing at 12 o'clock about the axis,
in `px` or `%r`, and the watch turns them ([analog
hands](analog-hands.md), [patterns](patterns.md)). To edit them, **enter**
the element: the **↘** on its Layers row, or a double-click on the row.
The face is then drawn as a ghost, dimmed to a third, with the element's
parts in full colour where the watch draws them, and over it the parts'
own frame: the axis as a dashed cross, the ring at 100 %r, and the 12
o'clock ray turned the way the parts are, with ticks at 25, 50, 75 and
100 %r. For a hands element that is the hour hand's angle at the moment
the face is drawn at, and every hand's parts are drawn at their own hand's
angle; for a radial pattern it is the first copy drawn (copy 0, or the
first not skipped, turned by `start:`); for a needle, the angle of the
sample reading. The label at the top right of the face names the element
you are in.

Inside, Layers lists the element's hands and their parts (or its parts)
under its row, each with its type; click one to select it, and Properties
shows its keys as it shows an element's, headed by what it belongs to
(`hour › blade`, `hour_ticks › tick`), with no **Edit for** and no AOD
note: a part has no overrides and no `aod:` block, so its keys are edited
as they are whatever frame the context views. On the face, click a part to
select it, drag it to move it (a line's ends, a circle's radius, a
rectangle's size and an arc's angles have their handles as an element's
do, turned with the part), and drag a polygon part's vertices as above. A
drag is written in the part's own frame: the pixels you moved it by on the
screen are turned back by the angle the part is drawn at, so a hand part
dragged along its hand stays on the hand. Drag a part row onto a sibling
in Layers to change the order the parts are drawn in (upper half: before
it; lower half: after). A pattern entered keeps its frame while you change
its `count`, `step_angle`, `step` or `skip` in Properties, so the ghosted
copies follow each change.

**Exit**, at the top of Layers, or **Escape** with nothing being dragged,
leaves the element; so does selecting an element outside it. A hands
element's parts belong to its set (`resources: hand_sets:`), so a change
made inside one `hands` element shows in every element placing the same
set.

**Selecting.** Click an element to select it; a click on the space
around the watch, or **Escape**, selects nothing, whether it was selected
on the face or in the layers (with a menu or dialog open, Escape closes
that first; inside an entered set, Escape leaves the set first). Ctrl-, Cmd- or
Shift-click more elements on the face to add them (or take them out
again); in the layers, Ctrl- or Cmd-click does that, and Shift-click
selects every row from the selection to the one clicked. **Ctrl+A**
selects everything the face shows; a group stands for what is in it.

**Copy and paste.** **Ctrl+C** copies the selection as its YAML, **Ctrl+X**
cuts it, and **Ctrl+V** pastes it in front of the selection, in its block
(or at the front of `elements`), as one change. The clipboard holds plain
YAML, so elements go from one face to another, or to and from a text
editor. A pasted element whose id the face already has gets a number
(`dot` becomes `dot2`); a paste that needs something the face lacks, a
colour or a font, is refused with the reason.

**Moving several at once.** Select them as above. A group, or a selection of several, shows a
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
are on their way). They are written in the order you made them, and so
is anything else you change meanwhile (a property, the layers, Undo):
it waits for the drag before it instead of being refused.

**Nudging.** With the face shown, the arrow keys move the selection one
pixel, ten with **Shift**, written the same way as a drag. Repeats made
while an earlier change is still being written go together as one change,
so a held key does not write one change per pixel.

**Snapping.** A moved element's edges and centre snap to the screen's
centre and to other elements' centres and edges, within 4 pixels, shown as
lines; with none near, its centre snaps to a grid of 5%r about the screen
centre. An axis you did not drag along never moves. Sizes snap to the same
grid, angles to 30° within 3°, else to 6°. Hold **Alt** to place freely;
**Escape** cancels a drag. While you drag, a label at the top left of the
face says how far the drag has gone and whether it snaps.

**Edit for.** The segmented control beside the watch picker, **all
watches · this watch · this shape · this display**, says where a change
to `at:`, `size:`, `radius:` or `align:` is written, whether dragged on
the face or typed in Properties ([per-device and per-shape
overrides](placement.md#per-device-and-per-shape-overrides)):

- **all watches** writes the element's own key. A drag on the face then
  goes where the watch you are looking at reads the key: its most specific
  override if it has one (the watch's, then the shape's, then the display
  class's), else the key itself.
- **this watch**, **this shape** and **this display** write that override
  (`fr955:`, `shape:round`, `display:amoled`, after the watch in view),
  creating it when needed, in the unit of the value it replaces. An
  override replaces the element's key whole, so a new override's `at:` or
  `size:` starts as a copy of the one the watch in view reads (the
  element's own, or a wider override's), with the dragged or typed key
  changed in it. A selector with a colon in it is written as a quoted key.

**Units.** A drag is written in the unit the key already has: a `%r` stays
`%r`, a `%` stays `%`, rounded to the coarsest value that still lands on
the pixel you dropped it on, on the watch you are looking at. A key written
in `pt` cannot be dragged (a `pt` has no size outside its font). When no
value in the key's unit lands exactly on that pixel, the nearest one is
written and a notice says so. In Properties, choosing another unit for a
number converts it where no watch is needed to (degrees and turns) and
writes it; otherwise (`px`, `%`, `%r`, `pt`, radians) the number box
empties, shows the old number as a hint, and nothing is written until you
type the number in the new unit. `pt` is offered only on a `text` or
`data` element, whose font it measures against. A change the watch cannot
lay out, such as a `pt` length on an element with no font in scope or a
target one of the face's fonts has no face on, is refused with the reason,
like any other change the compiler would not take; typed in the YAML tab,
it is kept and shown as an error on its line.

### Properties

Its own id, at the top, renames the same way a colour's name does: click
it, type the new one, Enter. Nothing else in the format names an element
by its id, so this only ever changes the one YAML key; a name already
used anywhere else in the face (every id must be unique) is refused.

Below it, every key the format has for the element's type, generated from
the format's schema, so there is nothing a key can hold that the panel
cannot edit:

- A plain value has the control for its kind: a number and its unit, an
  angle, the 3×3 alignment picker, a colour ([the colour
  picker](#the-colour-picker)), a `text:` template as chips
  ([below](#a-text-template-as-chips)), a font (the watch's, the face's
  own `font.<name>`, or **own font…**, which writes the font inline as this
  text's own: the named font's file and size, else the face's first font
  file; an inline font shows its file, a size box and the way back to a
  named font), an icon, a touch-and-hold target, a slot, a hand set
  (with **edit the set**, its lines in the YAML tab), a list of choices, on
  or off. A colour bound to a scheme role, rather than one of the face's
  swatches, names the role and jumps to the Schemes section. A colour,
  `visible:`, a gauge's `value:`/`max:` and a graph's `min:`/`max:` can
  follow data, edited as rows ([below](#a-value-that-follows-data-rows)). A
  key written in a shape its control does not take (an `icon:` that follows
  data) is edited as the YAML it is written as, in a text box: what you
  type is read as a YAML value when you leave the box and written if it
  reads.
- A key holding keys (`at:`, `curve:`, `outline:`, `lint:`, `aod:` in the
  awake frame) is a fieldset of them, indented under its name. One with
  nothing written yet is folded to its name and a **+**; open it and set a
  key, and the keys it must have come with it (a `curve:` gets its `style`
  and `angle` at once). `overrides:` lists the selectors written and adds
  one by name (**+ key**), starting as a copy of the element's own `at:`.
- A list (`points:`, `lint: allow:`) shows its items,
  each with **↑**, **↓** and **×**, and **+ add** puts a new one at the
  end: the schema's default, else an empty item of the right shape. A
  polygon's `points:` and its vertex handles on the face name the same
  point: the picked vertex's item is marked, and hovering an item picks
  its vertex ([on the face](#on-the-face)).
- A key the format writes in more than one shape (`absent:` as `hide`, a
  text or a value; a text's `aod: outline:` as `none` or a ring) is a
  segmented control over the shapes, the written one marked; picking
  another writes that shape's starting value in one change, and the shape's
  own keys appear beneath.

A required key is starred; a key's name explains it on hover. **×**
removes a key, back to its default (the last key of an override, or of an
`aod:` block, takes the emptied block with it, so none is left behind as
`at: {}`). A change the face cannot take, such as an object missing a key
it must have, is refused with the reason, like any other change the
compiler would not take.

**What the panel shows and where an edit goes follow the editing context**
(the watch, the frame and the style in the bar above the face):

- Every control shows the value the context *reads* for the key: awake,
  the element's own key or, when the watch in view reads an override, that
  override's value; in the AOD frame, what the always-on frame draws. When
  that is not the element's own key, a badge after the name says where it
  comes from: the override's selector (`fr955`, `shape:round`,
  `display:amoled`), `aod` for the element's own `aod:` block, `from
  <group>` for an enclosing group's block, `defaults` for the face's
  `defaults: aod:`. The control's tooltip says where a change is written.
- **Edit for** ([above](#on-the-face)) decides where `at:`, `size:`,
  `radius:` and `align:` go: with **all watches**, the element's own key,
  even while the watch in view reads an override (the badge says so); with
  **this watch**, **this shape** or **this display**, that override, whose
  **×** (on `at:` or on any key inside it) removes the override's whole
  key, since an override replaces the key whole. An override not written
  yet shows an empty number box and what it would inherit.
- In the **AOD** frame, the keys the element's kind restyles there (its
  `aod:` block's: `color:`, `text:`, `font:`, `outline:`, `thickness:`,
  `filled:`, …, and every element's `visible:` and `dim:`, shown even when
  the block does not write them) are edited in the element's `aod:`
  block: pick a colour and `aod: color:` is written, never the awake
  colour. The others (`at:`, `size:`, …) are shown as the watch reads them
  and say **not restyled in AOD; edit it in the awake frame**. In the
  awake frame the `aod:` block is an ordinary fieldset, so either frame
  can edit it. The asleep frame of a MIP watch draws the awake design, so
  it edits as awake does.

#### A text template as chips

A `text:` template ([the `text:` template](text.md#the-text-template)) is
shown as chips: one for each run of literal text, edited in place; one for
each placeholder, naming the source it reads, its format spec and the
source's unit; and one for `{unit}` where the template has one. Click a
placeholder for its picker: the sources by namespace (each one's
description on hover), the expression itself for a computed reading, the
specs the source's type takes (a number's `d`, `02d`, `.1f`, … set the
spec; a clock's, a date's and a duration's `%H`, `%e`, `%-M`, … add to
it, [formats](data.md#formats)) and the spec as text. Drag a chip by its
grip (⠿) onto another to move it there; **×** removes one; **+ text** and **+ data** add
one where the caret is (the chip you were in, splitting a literal at its
caret), or at the end. Each change writes the whole template once, and a
chip you did not touch is written back exactly as it was. **edit as text**
gives the template as one line of text; a template that does not read
(a lone `{`) opens that way, with the reason, so nothing typed is lost.

#### A value that follows data: rows

A key whose value may depend on data (`color:` and the other colours,
`visible:`, a gauge's `value:` and `max:`, a graph's `min:` and `max:`,
`absent: {value:}`, and the same keys in `aod:`) is edited as rows of
**source · operator · value → result**, tried in order, and an **else**
row for the rest: a [rule list](data.md#rules). The source is picked from
the catalogue by namespace (its description on hover); the operators are
`<`, `≤`, `>`, `≥`, `=`, `≠`, **is absent** and **is present**; the value
is true/false for a boolean source, a number for a number (its unit is the
box's placeholder) and text for a string; the result is the key's own
control (the colour picker for a colour, a value box for a number). A
picked colour that is not yet one of the face's is added as a swatch in
the same change, since a rule names its colour. The rows are written
once every row is complete, as the rule list; a list already written is
changed in place, row by row, so what you did not change stays as it was.

`visible:` has no result column: its rows are the conditions it is shown
under, any one of which shows it. One row is written as the condition
alone (`visible: system.charging`); several as the rule list of `true`
rows and `else: false`.

A value with no condition opens in the key's own control, with **follows
data…** (a colour) or **rows** beside it. A `?:` expression whose
conditions are one comparison each and whose branches are plain values (a
reading, a number, a `color.<name>`) opens in the rows too, and is written
back as the rule list. **as expression** shows the value as one
expression, edited as text; a value the rows cannot hold (two comparisons
joined by `and`, a computed colour) opens that way, its **rows** button
disabled with the reason.

### Layers

The tree lists the face's blocks: `static` and `elements`, then each
layout's own two, with groups as folders. Within each block and group the
rows run in drawing order, as the YAML lists them: the top row is drawn
first, under the ones below it. A block the face does not have yet is listed empty, as
somewhere an element can go. A row for an element the current frame does
not draw (hidden, absent, a different style's layout, asleep with no
`aod:`) is dimmed; a group dims only when none of its own children draw,
since a group never draws itself. A `hands` element lists its set's hands
and their parts beneath it, a `pattern` or a needle gauge its parts, each
part with its type; its **↘** enters the element ([hands, patterns and
needles](#hands-patterns-and-needles-enter-the-set)), and **Exit** at the
top of the list leaves it. A row whose element writes `z:` shows it as a
small badge (**z 5**): `z:` orders drawing among its siblings before their
order in the list does ([elements](elements.md)).

Each element's row has two switches of the editor's own, at its right
end: **🔒** locks the element, so a click or a drag on the face passes
over it to whatever is under it, and its handles and the move handle are
not offered (the arrow keys do not move it either); it is still selected
from Layers, and Properties still edits it. **👁** hides it in the
editor: the face is drawn without it (its row dimmed and struck through),
so you can reach what it covers, and Properties still edits it. Either
one on a group reaches everything inside it. Neither is part of the face:
the face's text, its build and the small frames under the face are
unchanged. The editor keeps them for each face in this browser, beside the
face, so they are there again when you reopen it.

The box above the tree searches it: typing narrows the rows to those whose
id or type holds what you typed, in any case, each shown under the rows it
sits in (its groups, its element, its hand), and a block with none of them
is left out. **Escape** in the box, or its **×**, clears it. Searching
selects nothing and keeps the selection as it was.

- **+ add…** adds an element of any type in front of the selection (or
  at the front of `elements`). A graph asks for its series, a data
  element for its slot and hands for their set (both declared in the
  Face tab). A type that cannot be static (a data element, a graph, hands,
  a gauge reading a value) is never put in a `static` block: with a
  static element selected it goes to the front of the sibling `elements`
  (the layout's own, when the selection is a layout's).
- With an element selected: **↑** sends it backward and **↓** brings it
  forward (**Ctrl+[**, **Ctrl+]**), **Duplicate** (Ctrl+D), **Delete**
  (Del), **move to…** any block or group. Delete, like the arrow keys,
  acts on everything selected, as one change.
- Drag a row onto another to put it behind it (upper half) or in front
  of it (lower half); onto a group's middle to put it inside; onto a
  block's name to put it in front of everything in the block.
- **Group** (**Ctrl+G**): select more elements beside the first (Ctrl-,
  Cmd- or Shift-click), then Group. The new group has no position or size
  of its own, so nothing moves on the screen. **Ungroup**
  (**Ctrl+Shift+G**) puts its children back where it was; it is refused
  for a group with other keys (`at:`, `visible:`, ...), whose children
  take something from it.

A delete that would leave something dangling is refused the same way:
the only element of a layout a style names (the layout would go with it),
or a group's only child (a group needs children; delete the group). A move
the compiler refuses, such as a live reading into `static:`, is
refused with its reason ([static content](elements.md#static--draw-it-once-then-blit-it)).

### The Face tab

Its own row of buttons, one per section below, shows one section at a
time -- the browser remembers which, so switching to Layers and back
does not reset it. Each section's own **? Guide** link opens Help at the
guide chapter for it.

Wherever a section lists things in an order the face keeps -- the targets,
the colours, a slot's choices, the layouts and the styles -- each row has
**↑** and **↓**, which move it one place among its neighbours; the first
cannot move up, nor the last down. The order is the one the text has, so
it is what the wearer's list shows, or the order the face is drawn in.

- **Face**: the face's **name**, its **version** (`1.0.0` when the key is
  left out) and its **id**, the UUID the watch knows the face by
  ([the design file](design-file.md)). Each is a text box: type, then
  **Enter** or click away. A name cannot be emptied, and an id is written
  only as a UUID; changing it makes the watch treat the face as a
  different app, kept beside the old one.
- **Target devices**: the watches the face is built for, in order (the
  first is the one the library's picture and the hand sets' thumbnails are
  drawn on). **↑ ↓** reorder, **×** removes one, and **+ add target…**
  lists every installed watch that can run a face and is not a target yet.
  A target whose files are not installed here is marked ⚠.
- **Defaults**: what every element inherits unless it, or a group around
  it, says otherwise ([the design file](design-file.md)): `antialias`,
  `min_1px`, and the always-on frame's `aod.visible`, `aod.dim` (above 0,
  at most 1) and `aod.mask` ([always-on display](always-on-display.md)).
  A key the face does not write is greyed and shows the format's default
  in its place; choosing a value writes it (and the `defaults:` block, when
  the face has none). Choosing the default again, or **×**, removes the
  key.
- **Colours**: each colour with what uses it (click an element to select
  it). Click a name to rename it: every `color.<name>` in the face
  follows. Its chip opens the picker, and a new colour reaches **every**
  user listed. Its **label** box is the name the watch's editor shows for
  it when a colour setting offers it ([the long
  form](colors.md#long-form-a-label-for-the-on-device-editor)): typed, the
  colour is written in the long form (`dim: { value: "#AAAAAA", label: Dim
  grey }`); emptied, it goes back to the bare colour (`dim: "#AAAAAA"`).
  **+ Colour** adds one; **×** deletes one, refused while
  something uses it; **Remove unused** deletes every colour nothing
  uses, except `bg`, `accent`, `text` and `fg`, which the launcher icon
  reads. A ⚠ marks a colour a target's screen would dither
  ([colours](colors.md)). A colour tagged **auto** is one the editor
  named after its value (below).
- **Colour settings**: the accent and data colours the wearer picks on the
  watch ([configuration](configuration.md)). **+ Accent colour** adds the
  setting; then its default, the role it binds (`accent` unless you name
  another), and the colours the wearer may pick, listed in the order the
  watch shows them, each as its swatch with its label, **↑ ↓** and **×**
  (the default cannot be taken off the list, nor its last colour).
  **+ add** offers another through the picker: one of the face's colours
  is listed by name (`color.<name>`), any other as itself (`{color:
  "#FFFFAA"}`); one already listed is not added again. The editor always
  writes that list, so adding a colour to the palette never changes what
  the wearer is offered. A setting written `choices: any` is shown, not
  edited: on a fēnix 8 it opens the watch's own colour picker, and on a
  watch without one (fr955) it lists every colour in the palette. **Make
  it a list** replaces it with the face's colours that no target dithers.
- **Colour schemes** ([colour schemes](colors.md#colour-schemes)): colours that
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
    (refused while something uses it). Under each scheme's name, its
    **label** (the name the watch's Style list shows for it; emptied, it is
    removed), and its **base** ([`base:`](colors.md#colour-schemes)): one of the other
    schemes, whose roles it inherits, or **no base**. A role a scheme
    inherits is shown greyed with **from** its base; picking a colour there
    sets it on this scheme, and **↺** beside a role it sets itself, where
    its base has that role, inherits it again.
  - **+ Scheme** adds a copy of the first scheme and a style picking it:
    one per layout when the styles name layouts (`analog_dusk`,
    `digital_dusk`). **+ Role** adds a role to every scheme, white until
    you set it.
  - **Remove schemes…** keeps one scheme's colours as palette colours of
    the same names. Every style loses its scheme: a style that named only
    a scheme goes, and one that names a layout stays, even when that
    leaves two alike. The confirmation says how many; Diagnostics then
    names each copy, for you to delete or change.
- **Layouts** ([styles and layouts](styles-and-layouts.md)): one row per
  `layouts:` entry: its name, its **label** (the editor's own name for
  it, which the Styles table shows beside the name; nothing on the watch
  reads it; emptied, it is removed), how many elements its `elements:` and
  `static:` blocks hold, and the styles that pick it (⚠ when none does:
  the wearer could not reach it). Click the name to rename it: every
  style's `layout:` follows. **↑ ↓** reorder the layouts. **×** deletes a
  layout together with the styles that pick it, as one change; when the
  style the face opens in is one of them, the row asks which of the styles
  that stay to open in instead, and the delete is made once you choose.
  The last layout every style picks cannot be deleted: add another first,
  or remove the styles. **+ Layout** adds an empty one, listed here and in
  Layers with nothing in it yet, and keeps it reachable: with no style
  yet to name it, it also adds one pointing at the new layout; on a face
  whose styles name only schemes, every style that picks no layout now
  picks the new one, as one change.
- **Styles**: a table, one row per style in the order the wearer's Style
  list shows them: its layout and its colour scheme (each a list of the
  face's own, or **no layout** / **no scheme**), the label the wearer
  sees, the radio for the one the face **opens in**, **↑ ↓** and **×**.
  **+ Style** adds one shaped like the others; **+ Layout** is here too
  ([styles and layouts](styles-and-layouts.md)).
- **Hand sets** ([analog hands](analog-hands.md)): each set drawn alone,
  as at 10:09:42, on the face's first watch; each hand's colour through
  the picker, and how many parts it has; the elements placing it (click
  one to select it). Click a name to rename it: every `set:` naming it
  follows. **Duplicate** copies it; **×** deletes it, refused while an
  element places it. **Edit in YAML** opens the YAML tab with the set's
  lines selected; a hand's parts are edited on the face by entering an
  element placing the set ([above](#hands-patterns-and-needles-enter-the-set)).
  **+ Hand set** adds one
  of four presets, `classic`, `baton`, `dauphine` and `subdial` (a small
  seconds hand), in the face's own colours; on a face with no hands yet it
  also places it at the centre. A `hands` element shows the same card
  above its keys.
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
    the type's own. **order** lists the ticked types as the wearer's list
    shows them, each with **↑ ↓**.
  - Click its name to rename it (every `slot:` naming it follows), **×** deletes it (refused
    while an element draws it), **menu title** is its title in the settings
    menu of a watch without the native editor, and **drawn by** lists the
    elements drawing it (click one to select it).
  - **+ Slot** asks what the new slot shows first, then its name, and adds
    a data element drawing it, as one change.
- **Fonts**: a font's size, **Replace…** its file, **+ Font from a file…**
  (then its name), **×** deletes it, refused while an element uses it
  ([fonts](fonts.md)). A file that is not a TrueType or OpenType font (its
  first bytes say so) is refused before anything is stored. **options ▸**
  opens the rest of the font's keys beneath it, edited as Properties edits
  an element's: for a font baked from a file, `glyphs`, `antialias`,
  `monospace` and `align`; for a watch's own scalable face, `face` (one
  name, or a list of names tried in order, each box suggesting the faces
  the face's watches publish; switching between the two keeps the names)
  and `unsupported`. A key that is a build error on the font's kind (a
  vector font's `glyphs`, a baked font's `unsupported`) is not offered,
  unless the font writes it, so it can be removed.

A name is always edited in place: click it, type, then **Enter** (or
click away) to rename and **Escape** to keep it. A new name (a scheme, a
role, a style, a slot, a hand set, a font) is typed in the same way where
its button was, with a suggestion where there is one; **✓** or **Enter**
adds it. A name that is not letters, digits and `_` (not starting with a
digit) is marked and not sent.

### The colour picker

A colour's chip opens three groups:

- **This face**: its colours, then its roles where the key takes one (a
  role follows the wearer's style or pick).
- **MIP 64**: [the 64 colours](mip-palette.md) a MIP screen shows exactly,
  by name. A ringed one is already in the face. They are laid out by
  family: red, yellow, green on the first line with the grays beside them,
  cyan, blue, magenta on the second. Every family is the same block, so a
  shade sits in the same place in each: a light row with the pastel in the
  middle, the vivid row with the pure colour in the middle, a medium row
  with the muted shade in the middle, and the one dark shade under it.
  Each block's left column leans toward the previous family and its right
  toward the next.
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
the gutter. **Tab** indents the line, or every selected line, by two
spaces and **Shift+Tab** takes the indent back, rather than moving to the
next control; to leave the text with the keyboard, press **Escape** and
then **Tab**. What you type is saved a moment (300 ms) after you stop, or
at once when you leave or reload the page, and
a burst of typing, saves less than 10 seconds apart, is one step for
**Undo** outside the tab. Text that
is not YAML for a moment (an open bracket) is not saved, and says so under
the text, until it is YAML again. A save that fails (the editor stopped,
say) says **Not saved** under the text, with **Retry**, until one gets
through; typing on tries again too. Text the compiler reports errors on is
saved, with the errors beside it: the face is not drawn until they are
mended, and the canvas waits for that.

Selecting an element on the face or in the layers selects its lines; the
cursor selects the element it is in. Switching to the face and back keeps
the pane where it was, scrolled and with its cursor, unless another
element was selected meanwhile: then the pane shows that element's lines.
Text not saved yet goes with you: switching away keeps it, unsaved, and
the top bar keeps saying **not saved** until you come back to it.
If the face changed elsewhere while
you were typing (the Properties or Face panel, another tab), your text is
not saved over that change: the pane keeps it and asks, saying how many
lines the other change added and removed; **Show it** lists them, with a
little context. **Keep my text**
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
the editor loses nothing; while a change is still on its way, the browser
asks before you close or reload the page, since leaving then would lose
it. The top bar says so: **saved**, **saving…**
while a change is on its way, or **not saved** while the YAML tab holds
text the editor could not record; click it to open the YAML tab, where
the reason is under the text or in a banner above it. The status's
tooltip gives the face's version, the number a refused change names.
**Undo** and **Redo** (Ctrl+Z, Ctrl+Shift+Z or Ctrl+Y; in the YAML tab
these undo your typing) work across restarts; each one's tooltip names
the change it would take back or bring back. A change after an undo
ends the redo line, as in any editor.

**▾** beside them lists the changes, newest first: click one to go back,
or forward, to it in one step. The changes listed in the History tab
work the same way. Either is one move along the line, as one undo or
redo is, so nothing is lost: every change stays in the list to go back
to. The History tab lists the newest 100 changes; **Show all** lists the
rest.

A **snapshot** is a point in time to go back to. One is taken every few
minutes while the face changes, on every download, and on **Snapshot
now** in the History tab. **Restore** brings one back as an ordinary
change, so it too can be undone; **Open copy** opens it as a separate
face.

The history is kept with the face in the browser until you delete the
face from the home screen, which deletes its history and snapshots with
it. Each face keeps its newest 500 changes: older ones are removed, with
any file only they used, so a face dragged for hours does not grow
without end. A snapshot keeps what it needs, however old.

## What it does not do

- Put the `.prg` on the watch: copy it yourself
  ([getting started](getting-started.md)).
- Run in a browser on another computer: it listens on this one only,
  unless you tell it otherwise, and then warns.
- Share faces between browsers: each keeps its own (above).

The editor's checks and gestures are tested without a browser, and the
pages themselves in a headless browser against the real server and worker:
every example and template opened, and each gesture, control, Face-tab
section and YAML-tab path of this chapter driven and read back from the
face's text (`npm run test:browser`, [developing](../development.md)). What
the editor cannot do is in [limitations](../limitations.md).
