# 30 — Editor gaps: slots, sessions, hands and colour schemes

**Question (user, 2026-10-03).** Research five things in `wfb studio`:
1. a slots UI that is more intuitive;
2. a session per browser, maybe through cookies, built so that
   authentication can reuse it later;
3. hands: there is no way to define or even see a hand set, and nothing
   says it can be edited in the YAML;
4. colour schemes: there is no way to add or define one, or to remove
   them altogether;
5. (asked the same day, after the first four) colours: the 64 named MIP
   colours already in the code should be offered by the editor's picker.
   A custom colour should open a colour picker and get a name filled in
   automatically, like `cRRGGBB`, that can be edited at any time.

**Status (2026-10-03): every decision is taken; planned as plan 30
(`docs/plans/30-editor-gaps.md`), not yet built. No compiler or editor
code changed.** §7 lists the decisions. **Decided by
the user, 2026-10-03:** L1, L3, S1, S2, H1, H2, C1 and K1–K5 as
recommended. L2 without the "widest" option. S3 goes with the sessions
work, not ahead of it. C2 is option B, keep every style entry (§4.4). K2
came with a caution about edits that follow a name across the YAML,
answered in §5.3 ("Who may change a shared swatch"). K5, predefined axis
colours, was the user's own addition (§5.3).

**Short answer.**

| # | Topic | What is wrong today | Recommended |
|---|---|---|---|
| 1 | Slots | A slot is split across two tabs. Its 42 types are raw ids in a `<select>`, and choice icons are typed by name with no glyph shown. The face is only ever drawn with the slot's `default:`, so no other pick can be seen. | Make the slot one object, editable from the data element as well as the Face tab. Use a labelled, grouped checklist of types with glyphs. Add a "showing" picker in the view bar: the default or any one choice (§1) |
| 2 | Sessions | None. Every browser sees and edits every face. The event stream sends every face's id to every tab. The server accepts any `Host`, so a DNS-rebinding page can read and edit everything (VERIFIED server-side) | An opaque cookie maps to a **principal**, and the principal owns documents. Authentication later only changes how a cookie gets its principal. Add a `Host` allowlist now, whatever else is decided (§2) |
| 3 | Hands | No Face-tab section. `set:` is a free text box, and the only hint is a note under **+ add…** that appears after you pick `hands` | A **Hand sets** section: list, preview, add from a preset, duplicate, rename (`set:` follows), delete (refused while in use), and "edit in YAML", which jumps to the block. Make `set:` a dropdown. A visual part editor is a later, separate piece (§3) |
| 4 | Schemes | The Schemes table is drawn only once a face has a scheme. Nothing adds or removes a scheme, adds a role, or removes the theme. Each of those is refused when done one key at a time (VERIFIED, 8 of 12 single edits refused) | Five **compound** edits, each one atomic patch, proven through the real gate: make colours switchable, add/duplicate a scheme, rename/delete a scheme, add/rename/delete a role, and remove the theme keeping one scheme (§4) |
| 5 | Colours | The 64 named MIP colours are in two hand-kept copies, `wfb/templates/palette.yaml` and `docs/guide/mip-palette.md`, and the code cannot read either. The picker offers only the face's own swatches and roles, and "custom" writes a bare `#RRGGBB` literal into the element | Move the 64 into a table in `wfb/palette.py`, and build one picker popover with three groups: this face, the 64 and custom. Picking one of the 64 adds that swatch and references it, in one patch. A custom colour becomes a swatch named `cRRGGBB`, renamed as its value changes until the author names it. 64 unused swatches cost 0 B (measured) (§5) |

Probes: `docs/research/probes/editor-gaps/` (`schemes.py`, `compound.py`,
`origin.py`, `unused_swatches.py`; results in each `*_results.txt`). Run
them from the repo root
with `./.venv/bin/python`.

---

## 1. Slots

### 1.1 What the author sees today

The slot UI is `SlotRow` and `FacePanel` in
`wfb/studio/static/panels.js`, the inspector's `slot` widget in
`wfb/studio/inspect.py`, and the add bar in `static/layers.js`. VERIFIED
(code reading):

1. **One idea, two places.** The slot (its name, default, choices and
   icons) lives in the Face tab. The element that draws it (position,
   font, icon size, label, unit) lives in Layers/Properties. There, `slot:`
   is a bare dropdown of names. The two are linked only by the "drawn by"
   links in the Face tab, and nothing points back. The author thinks of
   "the thing at 3 o'clock that shows a reading", which is one object.
2. **Raw type ids, 42 of them, in alphabetical order.** `default` is a
   `<select>` of `altitude … wheelchair_pushes`, and "add a type…" is the
   same list. `wfb.complications.ComplicationType` has a `doc` string but no
   display label or category, so the editor has nothing better to show.
   **+ Slot** picks "the first type no other slot defaults to"
   (`FacePanel`). On a new face that is `altitude`, an odd first reading.
3. **"choices: any / a list" is jargon, and switching loses work.** "a
   list" seeds `[default]`. Going back to "any" writes `choices: any` over
   the list (Undo restores it, but nothing warns).
4. **Icons are typed blind.** A choice's icon is a text field with a
   datalist of catalogue names. No glyph is drawn, and `U+XXXX` gives no
   feedback until the gate refuses it.
5. **The face is only ever drawn with `default:`.** The preview reads
   `slot.default` for the reading, the icon and a gauge's scale
   (`wfb/kinds/complication_slot.py` around lines 651–672,
   `wfb/kinds/progress.py:378`). `FrameKey` has no way to ask for another
   pick. An author whose slot offers `steps` and `current_weather` never
   sees "Mostly clear" squeezed into the box sized for `8809`.
6. **Hidden actions.** Rename is a click on the name that opens a
   `prompt()`. Delete is a × beside the label field. The label field
   ("menu label") matters only on a watch without the native editor, and
   the row does not say so.
7. **Half the data element cannot be edited.** In the inspector, its
   `icon:` (`size`, `position`, `gap`, `color`) is a "yaml" field, edited
   only in the text. `format:` is offered as a text field although the
   schema documents it as always refused ("Not accepted -- an error naming
   why"). VERIFIED with `inspect()` on `examples/showcase`'s
   `left_register`.

### 1.2 What would make it intuitive

**A. One slot card, shown in both places.** When a `data` element (or a
gauge with `slot:`) is selected, Properties shows a **Slot** card above its
keys, with name, default, choices and label. It is the same component as
the Face-tab row. Both edit `config: slots: <name>`. Neither the format nor
the patch engine changes: the card sends the same `set`/`rename`/`remove`
edits `SlotRow` sends today. The Face tab stays as the list of every slot.
It holds the slots no element draws yet, and it is the only place for a
slot several elements draw (`slot_drawers`).

**B. A checklist, not a radio button and a list.** Show the types as a
grid of checkboxes, grouped and labelled, each with its glyph and sample
reading (`COMPLICATION_SLOT_SAMPLE` has 40 of the 42; the two without one
are `last_golf_round_score` and `wheelchair_pushes`). A star marks the
default; clicking a star makes that type the default. **"All, including
types Garmin adds later"** is a switch above the grid, the honest meaning
of `any`. Turning it off keeps the ticks shown (all of them), so nothing is
lost either way. The icon override becomes a small glyph button on each
row, opening the icon picker the `icon` element needs anyway.

This needs a **label and a category per complication type** in
`wfb/complications.py`, the one table `on_hold:`, `complication.*` and
slots already share. That is data entry for 42 rows, not research. Garmin's
own names are in the SDK's `Complications` docs. Categories: activity,
health, body, weather, time and sun, performance, device.

**C. See the pick.** Add a **showing** control to the view bar, beside
style/time/asleep, with one entry per slot: *default*, any one of its
choices, or **widest**. The compiler already computes the widest plausible
reading over a slot's choices for sizing (`_complication_slot_widest` →
`complications.widest_reading`). "Widest" therefore draws exactly the case
the build sizes for. Threading a `picks: {slot: type}` through
`PreviewOptions` and `FrameKey` touches the four sites in item 5 above.
UNVERIFIED (not prototyped): the reading's own case, the icon and a gauge's
`max: auto` scale each follow the pick, because each reads `slot.default`
and nothing else. **Decided (L2): the "showing" control without
"widest"**, so each slot shows its default or any one of its choices.

**D. Smaller fixes.**
- **+ Slot** asks one question, *what should it show first?*, using the
  same grid. It then adds the slot *and* a data element drawing it, as one
  change. That needs a compound structural op, the `chain` in
  `wfb/edit/patch.py` (as §4 uses).
- Rename and delete become visible buttons on the card.
- The label field says what it is for: "Title in the settings menu (watches
  without the native editor: fr955)".
- The inspector hides a key the schema documents as never accepted
  (`format:` on `data`), and gets a nested editor for the data element's
  `icon:`. That is the same `object` widget `at:` already uses: add
  `icon` to the keys `inspect.py` expands.

---

## 2. A session per browser

### 2.1 What there is today

VERIFIED (code reading, `wfb/studio/app.py`, `store.py`, `__init__.py`,
plus the probe `origin.py`):

- **No identity at all.** `/api/home` lists every document in the store.
  Any request that names a document id may read, edit, build, download or
  delete it.
- **The event stream is global.** `Events.publish` sends every document's
  `changed`/`snapshot` events, ids included, to every open stream.
- **Document ids are the only secret.** They are 128-bit `uuid4` hex, and
  build ids are the same (`builder.py:78`). A cross-site *blind* request
  cannot guess one, so ordinary CSRF can only *create* documents (`/new`,
  `/upload` are text/plain-able "simple requests").
- **Any `Host` is accepted.** The probe sends `Host: evil.example:8765`
  and `Origin: http://evil.example`, with a `text/plain` body, as a page
  would after rebinding its own name to 127.0.0.1. It creates a face, sees
  it listed by `/api/home`, edits it and downloads it, all with HTTP 200
  (`origin_results.txt`). A DNS-rebinding page is same-origin with itself,
  so it can read `/api/home` and then everything else. Whether a given
  browser's local-network protections (Chrome's Private Network Access
  work) stop this first: UNVERIFIED, and it varies by browser and version.
  **This is the one finding worth fixing whatever is decided below.**
  Starlette's `TrustedHostMiddleware`, allowing `127.0.0.1`, `localhost`,
  `[::1]` and whatever `--host` names, closes it in a few lines.

### 2.2 The shape that survives authentication

Separate three things that today do not exist:

| Thing | What it is | Lifetime |
|---|---|---|
| **session** | a random 256-bit token in a cookie | sliding, renewed on use |
| **principal** | who owns documents: `anon:<id>` now, `user:<id>` later | durable |
| **binding** | session → principal | as long as the session |

**Documents belong to a principal, never to a session.** Authentication
later is then only a new way to make a binding: "this session's principal
is the user who just logged in". Logging in from an anonymous session
*merges* that anonymous principal's documents into the user's. That is the
same operation as "open my faces in another browser" (§2.3). Nothing in
the store changes when auth arrives.

**The cookie.** `wfb_session=<token>`, `HttpOnly`, `SameSite=Strict`,
`Path=/`, and `Secure` when served over https (`--host` not loopback, or
behind a proxy that says so). `Max-Age` equals `--keep-days`, renewed on
each request, so the cookie lives as long as the faces it reaches.
`SameSite=Strict` also does CSRF's job: a cross-site request carries no
cookie, so it gets a fresh, empty principal and touches nothing. With the
`Host` check it closes rebinding too. A "browser session" in the HTTP sense
(a cookie with no `Max-Age`) would be wrong here: closing the browser would
orphan every face.

**Server side.**
- `state/sessions/<sha256(token)>.json` holds `{principal, created,
  last_seen}`. Only the token's hash is kept, so a copied state directory
  does not hand out live cookies.
- `state/principals/<id>.json` holds `{kind, created, identities: []}`.
  `identities` is where a later login records `{provider, subject}`.
- Each document's `meta.json` gains `"owner": "<principal>"`. The store
  layout is otherwise unchanged (§2.4 covers documents without an owner).
- `Store.documents(owner)` filters. `Store._dir(doc_id, owner)` raises
  `UnknownDocument` (**404, not 403**) for someone else's document, so its
  existence does not leak.
- A Starlette middleware resolves the cookie to `request.state.principal`,
  minting an anonymous one when there is none. Every `doc(request)` call in
  `app.py` passes it on. `Events.stream` subscribes per principal and
  `publish` takes the owner. Build downloads check the owner of the build's
  document.
- Pruning: sessions unseen for `--keep-days` are removed. A principal with
  no sessions and no documents is removed. Documents prune as they do now.

**Authentication later**, in order of effort:
1. **A reverse proxy's header** (oauth2-proxy, Authelia, Tailscale
   Serve's `Tailscale-User-Login`). The middleware trusts
   `X-Forwarded-User` only from a configured proxy address and binds
   `user:<that>`. This is a few dozen lines, and the usual way a small
   self-hosted tool gets SSO.
2. **OIDC in the app** (Authlib), the same binding after a callback.
3. **Local passwords.** Not recommended: storage, reset and rate limiting
   all become this project's job.

None of these touches documents, the store or the front end, beyond a
login button for (2).

### 2.3 What a per-browser editor costs the author

On a laptop with one user, per-browser ownership has a visible downside:
the faces made in Firefox are missing in Chrome, and clearing cookies
"loses" them (they stay on disk until pruned). Two mitigations, both small:
- **"Use my faces in another browser"** shows a one-time link
  (`/claim/<code>`, 10 minutes, single use). Opening it binds that browser's
  session to the same principal. This is also the hand-written precursor
  of login.
- **A startup link.** `wfb studio` prints `http://127.0.0.1:8765/?claim=…`
  the way Jupyter prints its token. The first browser to open it becomes
  the **owner principal**, which holds the face named on the command line
  and every document created before sessions existed.

### 2.4 Migration

Documents in today's store have no `owner`. Options: give them to the
owner principal from the startup link (recommended), or to whichever
session connects first (racy on a shared host). There is also a
single-user mode in which every session binds to one fixed `local`
principal: today's behaviour, kept behind a flag. Decision S1.

---

## 3. Hands

### 3.1 What the author sees today

VERIFIED (code reading and `inspect()` on `examples/showcase`):
- `globals_of` sends the names in `resources: hand_sets:` and nothing more.
  The Face panel has sections for targets, colours, schemes, styles, slots
  and fonts, but **none for hand sets**.
- A `hands` element's `set:` is a **plain text field** (`_widget` has no
  case for it). Its `outline:` and `aod:` are "yaml" fields.
- The only hint is a note under **+ add…**, *"Declare a hand set under
  resources: hand_sets: first"*, shown only once `hands` is picked and the
  face has no set. A face from a non-analog template has no route to hands
  short of writing the YAML.
- Hands draw and move like any element (`at:` is the axis). A hand's parts,
  colours and lengths are reachable only through the YAML tab.

11 of the 25 example faces declare `hand_sets:`; `wfb new -t analog` has
one (`classic`).

### 3.2 Recommended, in two steps

**Step 1: a Hand sets section, with no new geometry.**
- **List** each set with a thumbnail (the set drawn alone at 10:09:42, the
  preview's sample time, on the face's ground), its hands (hour, minute,
  second) and part counts, and **used by**: the `hands` elements naming it,
  linked like a slot's "drawn by".
- **+ Hand set** from a preset: `classic` from the analog template, plus a
  few taken from the example faces (baton, dauphine, a seconds-only
  subdial). Presets are YAML snippets in `wfb/templates/`, colours
  rewritten to the face's own `color.fg`/`color.accent` (or the first
  palette entry) so the gate accepts them. If the face has no `hands`
  element, offer to add one at the centre in the same change.
- **Duplicate**, **Rename** (rewrites every element's `set:`; `_repoint`
  already does exactly this for `slot:`) and **Delete** (refused while an
  element uses it, like a slot).
- **Each hand's colour** as a colour picker. **seconds:** stays on the
  element.
- **Edit in YAML** switches to the YAML tab with the set's lines selected.
  The YAML tab already selects an element's lines, and the same span lookup
  works for any path. That is the honest pointer the user asked for, and it
  costs almost nothing.
- **In the inspector**, `set:` becomes a dropdown of declared sets, and the
  `hands` element gets the same "Edit the hand set" link.

**Step 2, later: a hand editor.** A small canvas per hand in its own frame
(axis at the centre, pointing at 12). It lists the parts, drags
polygon/line/rectangle/circle points in `%r` or `px`, and adds or removes
parts (1–16, the four rotatable types). This is a real piece of work, with
its own handle model (a frame relative to an axis, half-away-from-zero
rounding, mirrored-pair symmetry). The geometry patcher handles
element-level keys today, not points inside a hand part. It deserves its
own research once step 1 shows how often authors reach for it. A polygon's
`points:` are YAML-only for ordinary elements too (`docs/guide/studio.md`,
"What it does not do"), so a point editor would serve both.

---

## 4. Colour schemes

### 4.1 What breaks when done one key at a time

`schemes.py` applies each single edit through the editor's own
`set_value`/`remove`/`rename_*` and `Gate` (results in
`schemes_results.txt`), starting from `wfb new -t minimal`:

| Single edit | Result | Why |
|---|---|---|
| add `theme:` with one scheme | accepted | |
| then use `color.fg` (a role) with no style | **refused** | a role is undefined until a `config: style:` entry names a scheme |
| add a 2nd scheme with other roles | **refused** | every scheme must declare the same roles |
| add a 2nd scheme with the same roles | accepted | |
| add a role to one scheme | **refused** | the other scheme lacks it |
| a role named like a swatch (`dim`) | **refused** | one `color.` namespace |
| add `config: style:` naming both | accepted | |
| remove a scheme a style names | **refused** | unknown colour scheme |
| remove the whole `theme:` | **refused** | the styles name its schemes |
| remove a scheme's last role | **refused** | `colors:` must be non-empty |
| rename a scheme (key only) | **refused** | the styles still name the old name |
| rename a role in one scheme (`rename_reference`) | **refused** | the other schemes still have the old role |

So 8 of the 12 are refused, and every refusal is correct. **A scheme
change is a change to several places at once.** The gate does not need
loosening; the editor needs edits that change all those places together.

**Aside: a diagnostic leaks an internal name.** The refusal for "role used
with no style" reads *"unknown data source 'config.colors.fg'"*. The author
wrote `color.fg`, and `config.colors` is format 1 vocabulary. The message
should say "color.fg is a scheme role, but no `config: style:` entry picks
a scheme". `wfb/ir/builder/reading.py:20–25` already pattern-matches this
message, so that is where to rewrite it.

### 4.2 The compound edits, proven

`compound.py` builds each one as a single patch with `chain`
(`wfb/edit/patch.py`) and runs it through the same gate:

| Compound edit | What it writes | Result |
|---|---|---|
| **Make colours switchable** (minimal: `bg`, `text`, `dim`) | moves the chosen swatches from `palette:` into `theme: schemes: <name>: colors:` under the **same names**, and adds `config: style: {default: <name>, choices: {<name>: {scheme: <name>}}}`. No reference is rewritten: `color.bg` now means the role | **accepted**, 405 ms |
| **Add a scheme** (duplicate an existing one, plus its style entry) | `theme.schemes.light` with the same roles, and `config.style.choices.light` | **accepted**, 37 ms |
| **Add a role to every scheme** | the role in each scheme's `colors:` | **accepted**, 35 ms |
| **Delete a scheme**, and the style entries naming it | both, in one patch | **accepted**, 28 ms |
| **Remove the theme** (showcase: 4 schemes, 6 roles, 7 style entries over 3 layouts), keeping `dark` | `theme:` removed; each role of `dark` becomes a palette swatch of the same name, its value resolved to a hex literal; each layout keeps one style entry, with `scheme:` dropped; `default:` kept or moved | **accepted**, 1.8 s (the showcase's cold font bake) |

Two things the probe found along the way:
- **A palette value must be a literal.** The first flatten attempt copied
  `bg: color.black` into the palette and was refused ("has the wrong
  shape"). The flatten resolves each role to its hex through the palette.
- **The face must keep a style entry for each layout**, or the layouts
  become unreachable. The probe keeps the first entry per layout. Their
  labels ("Analog · Dark") then name a scheme that is gone, so the UI
  should offer to relabel them. Removing the theme from a face with no
  layouts removes `config: style:` entirely.

Not probed but the same shape: **rename a scheme** (key plus every
`config.style.choices.*.scheme`, a `_repoint` over style entries) and
**rename a role** (the key in every scheme plus `color.<old>` → `color.<new>`
everywhere, which is `rename_reference` with the key step repeated per
scheme).

**Written style.** The patch engine writes a new nested value as a flow
mapping (`theme: { schemes: { dark: { colors: {...} } } }` in
`compound_results.txt`). For a block the author will read, the compound
edits should write block style. `_block` in `patch.py` already renders one.

### 4.3 The UI

The **Colours** section becomes **Colours and schemes**:
- With no theme: the palette as today, plus **Make switchable…**. Tick the
  swatches that should change with the wearer's choice (they become roles),
  and name the first scheme.
- With a theme: the roles × schemes table as today, plus:
  - **+ Scheme** (a copy of the current scheme; also adds a style entry
    when every style entry is scheme-only, and otherwise asks which layouts
    get it);
  - rename and delete on each column;
  - **+ Role** (one value per scheme, prefilled), and rename and delete on
    each row (delete is refused while something uses the role);
  - **Remove schemes…** (pick the scheme whose colours stay).
- Each role cell keeps today's choice of a swatch or a hex value. The ⚠ for
  64-colour dithering applies to a role's literal too. With §5, a cell
  opens the same picker as everywhere else, without the role group (a
  role's value must be known at build time).

### 4.4 C2, explained: what happens to the styles when the schemes go

A `config: style:` entry is a **combination** the wearer picks: a layout,
a scheme, or both. The showcase has 7 such entries over 3 layouts and 4
schemes:

| Entry | Layout | Scheme |
|---|---|---|
| analog_dark | analog | dark |
| analog_light | analog | light |
| analog_crimson | analog | crimson |
| digital_dark *(default)* | digital | dark |
| digital_light | digital | light |
| roman_dark | roman | dark |
| roman_crimson | roman | crimson |

Removing the theme takes away every entry's `scheme:`. Each entry then
names only a layout, and the three analog entries become the same thing:
same layout, same colours. Either the editor merges each layout's entries
into one, or it keeps them all as identical copies. There is no third
outcome.

- **A. One entry per layout (recommended).** `analog_dark`, `digital_dark`
  and `roman_dark` stay; the other four go. The wearer's Style list goes
  from 7 items to 3, one per layout, and that is all the face can still
  show. Proven: `compound.py` B1, accepted. Which entry survives: the
  default's entry for its layout, else the first, so `default:` never has
  to move. Labels such as "Analog · Dark" name a colour that no longer
  exists, so the editor offers to rename them ("Analog") in the same step.
- **B. Keep all 7.** The wearer sees 7 items, and 4 of them look exactly
  like another. The lint says so: `compound.py` C1 is accepted by the
  gate, which does not run lints, but `run_design` then reports **4
  `duplicate-style` warnings** (`analog_light`, `analog_crimson`,
  `digital_light`, `roman_crimson`). The face no longer builds
  warning-free, the project's bar (root `CLAUDE.md` §7), until the author
  deletes the copies by hand, which is option A done manually.

A face with no `layouts:` is simpler: its entries were schemes only, so
`config: style:` is removed entirely, and no decision arises.

**Decided by the user, 2026-10-03: B.** The style entries are the author's
own, written by hand, so the editor does not merge or delete them. Removing
the theme drops each entry's `scheme:` and keeps everything else. The
`duplicate-style` warnings that follow appear in Diagnostics, naming each
copy, and the author deletes or changes those entries. The confirmation
before removing says how many entries will become duplicates.

---

## 5. Colours: the 64 named MIP colours and custom colours

### 5.1 What there is today

VERIFIED (code reading):
- **The 64 names are not in the code the editor can read.** They exist
  twice, kept by hand: `wfb/templates/palette.yaml` (the `wfb new -t
  palette` starter) and `docs/guide/mip-palette.md`. Each entry has a name,
  a hex value and a `label:` ("Laser Lemon"). `wfb/palette.py` has the
  *rule* (`MIP64_LEVELS`, `MIP64_SNAP`) but no names. The editor has its
  own copy of the levels (`static/values.js`, `mipNearest`).
- **The element colour picker** (`ColorPicker` in `panels.js`) is a
  `<select>` of the face's swatches and scheme roles, plus "custom". Custom
  shows the browser's `<input type="color">` and writes a **bare literal**
  (`color: "#FF8000"`) into the element. That colour then has no name, and
  nothing else can share it. A ⚠ marks a literal a 64-colour screen would
  dither.
- **The Colours section** of the Face tab edits each swatch's hex value (a
  text field plus the browser's picker). Its name can be renamed: every
  `color.<name>` follows, through `rename_reference`. **+ Colour** asks for
  a name and writes `#FFFFFF`.
- **No UI for the colour axes.** `config: accent_color:` and `data_color:`
  (their `default:` and `choices:`) are edited only in the YAML. The picker
  below would serve them too, so they are listed here as an adjacent gap.

### 5.2 What a swatch costs

`unused_swatches.py` builds `wfb new -t minimal` twice for
`fenix8solar47mm`: once with its 3 swatches, and once with all 64 MIP
swatches added and none used. Both builds measure **1,414 B (625 B data,
789 B code)**, with exit 0 and no warnings. A swatch is a Monkey C `const`
(`emit_palette` in `wfb/emit/monkeyc/app.py`), folded away when unused.
VERIFIED. **Swatches are free in memory.** Two things still make them
visible:
- On a watch **without the native editor** (fr955), a colour axis with
  `choices: any` lists **every** swatch in the generated settings menu
  (`config_menu.menu_axes`: "`choices: any` offers the palette"). Each
  swatch the picker adds becomes a menu item there.
- They lengthen the Colours list the author reads.

### 5.3 Recommended design

**One table.** Move the 64 into `wfb/palette.py` as `MIP64_NAMED` (name,
hex, label), in the guide's order. A test checks that the template and the
guide page match it (or generates both from it). The editor gets the table
from `/api/vocabulary` and drops its own copy of the levels.

**One picker, everywhere a colour goes.** A popover opened from a colour
chip, used by element colours, outline colours, hand colours, scheme role
cells, palette values and the colour axes:

| Group | Shows | Writes |
|---|---|---|
| **This face** | its swatches, then its roles (chip and name) | `color.<name>` |
| **MIP 64** | an 8 × 8 grid of chips, each named on hover, with a face swatch of the same value marked | see below |
| **Custom** | the browser's colour input and a hex field, side by side | see below |

Where a role is not allowed (a scheme's role value, a colour axis's
`default:`/`choices:`, a palette value), the role group is hidden. A
palette value is written as hex: the probe found a palette entry refuses
`color.black` ("has the wrong shape", §4.2).

**Picking one of the 64** writes `color.<mip name>`. If the face has no
swatch by that name, one compound patch adds it,
`resources: palette: <name>: {value, label}`, and sets the reference: one
change, one Undo. If the face has a swatch by that name with the same
value, it is reused. If the name is taken with a different value (an
author's own `red: "#CC0000"`), the new swatch is `<name>_2`.

**A custom colour gets a swatch named `c` + its hex**: `#FF8000` becomes
`cFF8000`, a valid name (it starts with a letter) that sorts together with
the other custom colours. A swatch of the same value already in the face
is reused instead. The name is **editable at any time**, through the
rename the Colours section has today (every reference follows). While a
swatch still has its automatic name, editing its value **renames it to
match** in the same patch: `cFF8000` set to `#FF5500` becomes `cFF5500`.
That is a `set_value` chained with `rename_reference`. Once the author
gives it a name of their own, the name stays.

**Who may change a shared swatch.** The user's caution with K2: an edit
that follows a name across the YAML can change more than the author meant.
The risk is real for one gesture in particular: changing the colour *of
one element* by editing the value of a swatch other elements also use. So
the two gestures are kept apart:
- **The picker on an element never edits a swatch's value.** It only
  re-points that element's `color:` at another swatch: an existing one, one
  of the 64 (added if missing), or a new `cRRGGBB`. The other elements
  using the old swatch do not change.
- **A swatch's value, and the automatic rename that follows it, change
  only in the Colours section.** There the row says "used by N", listing
  the elements, before the change, and the change is meant to reach all
  of them.
- **The rename touches only `color.<name>` references.** It is
  `rename_reference`'s whole-name match, so `color.cFF8000` matches and
  `color.cFF8000_dim` does not. The gate then checks that the patched text
  parses to exactly the data intended (`gate.py`, rule 1), so a rewrite
  that reached anything else is refused rather than written. Comments are
  never rewritten.

**Dithering.** On a face with a 64-colour target, a custom colour off the
64 shows the ⚠, and one click swaps it for its nearest MIP colour,
`MIP64_SNAP`, the same snap the preview draws. A 2-colour target gets the
same treatment with black and white. AMOLED-only faces show no warning.
The grid stays useful there for its names.

**Clutter.** When the picker moves the last user off a swatch with an
automatic name (`cRRGGBB`, or one it added from the 64), that swatch is
removed in the same patch. Author-named swatches are never removed
silently. A **Remove unused** button in the Colours section covers the
rest. This keeps the fr955 menu (§5.2) from filling up with colours tried
and abandoned.

**Predefined axis colours (K5, raised by the user).** The menu grows only
through `choices: any`: on fr955, `any` lists the whole palette. An
explicit list is fixed, and the palette can grow freely without changing
what the wearer is offered. Recommended: the colour-axis section (K4)
always writes an **explicit `choices:` list**, picked from the same picker.
It starts from the face's swatches that are legal on every target, and the
author ticks the ones to offer. `choices: any` stays valid in the YAML
and is shown read-only, with a note: "fēnix 8: the watch's own picker; on
fr955, every colour in the palette, which grows as you add colours". The
compiler's meaning of `any` does not change. The alternative is a lint
warning when `any` meets a palette above some size, which leaves the
growth possible.

**Not changed.** A bare literal written in the YAML stays valid, and an
expression colour (`"cond ? color.a : color.b"`) stays a text field.

## 6. Where this fits

- None of the five needs a format change. Slots (§1.2 B) needs labels and
  categories added to the complication table, and colours (§5) need the 64
  names moved into `wfb/palette.py`. Sessions (§2) is server structure plus
  a few lines of front end (the cookie travels on `fetch`/`EventSource` by
  itself, same-origin).
- Each is independent of the others, and of plan 29, with one exception:
  the colour picker (§5) is the control the scheme cells (§4.3) and the
  hand colours (§3.2) use, so it comes before both, or with whichever is
  built first.
- **The `Host` allowlist (§2.1)** is built with the sessions work (S3).
- Two small stale texts were found along the way, and neither is in the
  editor: the diagnostic in §4.1, and `wfb complications --help`
  (`_complications` in `wfb/cli.py`), which still says `config: data:`,
  `complication_slot` and `icon_size:` (format 1).

## 7. Decisions for the user

| # | Decision | Options | Recommended |
|---|---|---|---|
| L1 | Where a slot is edited | Face tab only, improved · **also as a card on the selected data element** | **decided 2026-10-03: both**: one component, two places |
| L2 | Seeing a pick | none · a per-slot "showing" control · also **widest** | **decided 2026-10-03: the "showing" control, without widest** |
| L3 | Type labels and categories | in the editor only · **in `wfb.complications`** | **decided 2026-10-03: `wfb.complications`** |
| S1 | Who owns faces by default | **per browser** (cookie → anonymous principal, startup claim link for existing faces) · single-user `local` by default, per-browser behind a flag | **decided 2026-10-03: per browser, always on**, with `--single-user` as the escape hatch |
| S2 | Cookie lifetime | **persistent, sliding, = `--keep-days`** · until the browser closes | **decided 2026-10-03: persistent, sliding** |
| S3 | `Host` allowlist | **now, separately** · with S1 | **decided 2026-10-03: with the sessions work** (S1), not ahead of it |
| H1 | Hands scope | **Hand sets section + `set:` dropdown + Edit in YAML** · also a visual part editor | **decided 2026-10-03: the section first**; the part editor gets its own research |
| H2 | Presets | the analog template's `classic` only · **a few from the examples** | **decided 2026-10-03: a few** (classic, baton, dauphine, a subdial) |
| C1 | Scheme edits | **all five compound edits** (§4.2) · add/remove scheme only | **decided 2026-10-03: all five** |
| C2 | Removing the theme with layouts (§4.4) | A: one style entry per layout · **B: keep every entry** | **decided 2026-10-03: B**; the entries are the author's own, so `scheme:` is dropped and the `duplicate-style` warnings are left for the author to resolve |
| K1 | Where the 64 live | **a table in `wfb/palette.py`**, template and guide checked against it · leave them in the template | **decided 2026-10-03: the table** |
| K2 | A custom colour that is exactly one of the 64 | **its MIP name** (`international_orange`) · always `cRRGGBB` | **decided 2026-10-03: the MIP name**; an element's picker never edits a shared swatch (§5.3) |
| K3 | Automatic swatches nothing uses any more | **removed in the same patch** (author-named never) · kept until **Remove unused** | **decided 2026-10-03: removed** |
| K4 | Colour axes (`accent_color`, `data_color`) | **a Face-tab section using the same picker** · YAML only | **decided 2026-10-03: a section** |
| K5 | What a colour axis offers | **an explicit list, always written by the editor** (`any` YAML-only, shown read-only) · `any` editable, with a lint above some palette size | **decided 2026-10-03: an explicit list** |

---

## Sources

- Editor: `wfb/studio/static/panels.js` (`SlotRow`, `FacePanel`,
  `Widget`), `wfb/studio/static/layers.js` (the add bar's notes),
  `wfb/studio/inspect.py` (`_widget`, `globals_of`, `_slots`),
  `wfb/studio/app.py` (routes, `Events`), `wfb/studio/store.py`,
  `wfb/studio/document.py` (`Document.edit`, `FrameKey`, `Studio`),
  `wfb/studio/builder.py:78`, `wfb/studio/__init__.py` (`LOOPBACK`).
- Patch engine: `wfb/edit/patch.py` (`chain`, `_repoint`,
  `rename_reference`, `remove_slot`, `_block`), `wfb/edit/gate.py`.
- Compiler: `wfb/kinds/complication_slot.py` (`_complication_slot_widest`,
  `COMPLICATION_SLOT_SAMPLE`, the preview's `slot.default` reads),
  `wfb/kinds/progress.py:378`, `wfb/complications.py`,
  `wfb/emit/monkeyc/config_menu.py` (`slot_types`),
  `wfb/ir/builder/reading.py:20–25`, `wfb/preview.py` (`sample_values`).
- Schema: `schema/wfb-face-2.schema.json` (`theme`, `scheme`, `handSet`,
  `hand`, `handPart`, `handsElement`, `dataElement`).
- Guide: `docs/guide/studio.md`, `docs/guide/colors.md`,
  `docs/guide/configuration.md` ("The Data axis"),
  `docs/guide/analog-hands.md`.
- Starlette `TrustedHostMiddleware` (`starlette.middleware.trustedhost`).
  Cookie attributes per RFC 6265bis (`SameSite`).
- Colours: `wfb/palette.py` (`MIP64_LEVELS`, `MIP64_SNAP`),
  `wfb/templates/palette.yaml`, `docs/guide/mip-palette.md`,
  `wfb/emit/monkeyc/app.py` (`emit_palette`),
  `wfb/emit/monkeyc/config_menu.py` (`menu_axes`),
  `wfb/studio/static/values.js` (`mipNearest`, `mipLegal`).
- Probes: `docs/research/probes/editor-gaps/`.
