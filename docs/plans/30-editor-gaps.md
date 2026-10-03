# 30 — Editor gaps: colours, schemes, hand sets, slots and sessions

**Status: proposed (2026-10-03). Every decision is taken (§1); nothing is
built.** Delete this file once every slice has shipped (`docs/CLAUDE.md`).

Records this builds on:
- `docs/research/30-editor-gaps.md`: the five gaps, the probes behind them
  (`docs/research/probes/editor-gaps/`), and every decision below with its
  reasoning.

In short:

* **Colours (slice 1).**
  - The 64 named MIP colours become one table in `wfb/palette.py`.
  - The editor gets one colour picker with three groups: this face, the
    64, and custom.
  - Picking one of the 64 adds that swatch. A custom colour becomes a
    swatch named `cRRGGBB`, or its MIP name when it is one of the 64.
  - An element's picker never edits a shared swatch.
  - Automatic swatches nothing uses are removed.
  - The accent and data colour axes get a Face-tab section that always
    writes an explicit `choices:` list.
* **Colour schemes (slice 2).** Five compound edits, each one patch and
  one Undo:
  - make colours switchable;
  - add or duplicate a scheme;
  - rename or delete a scheme;
  - add, rename or delete a role;
  - remove the schemes, keeping one scheme's colours, and every style
    entry.
* **Hand sets (slice 3).**
  - A Face-tab section: list, thumbnail, used by, presets, duplicate,
    rename, delete, and "Edit in YAML".
  - `set:` becomes a dropdown.
* **Slots (slice 4).**
  - One slot card, shown both on the data element and in the Face tab.
  - Types are labelled and grouped, in `wfb.complications`, and offered
    as a checklist with glyphs.
  - A "showing" control draws the face with any one of a slot's choices.
* **Sessions (slice 5).**
  - A cookie maps to a principal, and the principal owns documents.
  - Each browser is its own principal; `--single-user` brings back
    today's single shared owner.
  - A startup claim link, and a link to attach another browser.
  - A `Host` allowlist.
* Nothing on the watch side changes, nor does the format. `wfb build`
  output is unchanged by every slice (`tools/snapshot.py`).

## 1. Decisions

All taken by the user on 2026-10-03, in `docs/research/30-editor-gaps.md`
§7.

| # | Decision |
|---|---|
| K1 | The 64 live in a table in `wfb/palette.py`; `wfb/templates/palette.yaml` and `docs/guide/mip-palette.md` are checked against it |
| K2 | A custom colour that is exactly one of the 64 takes its MIP name; anything else is `cRRGGBB`. The user cautioned against edits that follow a name across the YAML, hence R1 below |
| K3 | An automatic swatch (`cRRGGBB`, or one added from the 64) is removed in the same patch that leaves it unused; an author-named one never is |
| K4 | A Face-tab section for `accent_color` and `data_color` |
| K5 | That section always writes an explicit `choices:` list; `choices: any` stays valid in the YAML and is shown read-only, with a note |
| C1 | All five compound scheme edits |
| C2 | Removing the schemes keeps every style entry and drops only its `scheme:`; the `duplicate-style` warnings are the author's to resolve |
| H1 | A Hand sets section, a `set:` dropdown and "Edit in YAML"; the visual part editor gets its own research later |
| H2 | Presets: classic, baton, dauphine and a seconds-only subdial |
| L1 | A slot is edited in two places, by one component |
| L2 | A per-slot "showing" control: the default or any one choice, no "widest" |
| L3 | Type labels and categories go in `wfb.complications` |
| S1 | Faces belong to a principal, one per browser, always on; `--single-user` is the escape hatch |
| S2 | The cookie is persistent and sliding, lasting `--keep-days` |
| S3 | The `Host` allowlist is built with the sessions work |

**R1, a rule that follows from K2.** Two gestures stay apart:
- The picker on an element only re-points that element's `color:`.
- A swatch's value, and its automatic rename, change only in the Colours
  section. That row lists the elements it reaches before the change.

## 2. Slices

Each slice ships with:
- the fast suite and `mypy --strict` green;
- `tools/snapshot.py` unchanged;
- `docs/guide/studio.md`, `docs/lore/roadmap.md` and, where it lists a
  gap the slice closes, `docs/limitations.md`, all updated in the same
  commit.

Every new refusal is driven red: a test that makes the gate or the
endpoint refuse, and checks the reason. Front-end logic that is not drawing
goes in a module the Node tests reach (`tests/test_studio_frontend.py`).

### Slice 1 — the colour table, the picker and the colour axes (K1–K5)

- **Table.** Add `wfb/palette.py: MIP64_NAMED`, 64 `(name, hex, label)`
  rows in the guide's order.
  - Test: the template's palette and the guide's block equal the table,
    and every row is MIP-legal.
  - Serve the table from `/api/vocabulary`. `values.js` reads its levels
    from it instead of keeping its own copy.
- **Edits** (`wfb/edit/patch.py`, one `chain` each, through
  `Document.edit` as new ops):
  - `use_color(element_path, key, pick)`. `pick` is a swatch name, a MIP
    name or a hex. Where needed it adds the swatch: a MIP name with its
    label; `<name>_2` when the name is taken by another value; a hex
    equal to a MIP colour under its MIP name (K2); otherwise `cRRGGBB`.
    It reuses a swatch of the same value. It sets the key. It removes the
    automatic swatch the element left if nothing else uses it (K3).
  - `set_swatch(name, value)`. While the name is still automatic
    (`c` plus the old hex, or the MIP name of the old value), the swatch
    is renamed to match through `rename_reference`. Otherwise only the
    value changes.
  - **Remove unused**: deletes every swatch nothing references,
    author-named ones included, since this is the author asking.
- **Picker** (`panels.js`): a popover with **This face**, **MIP 64** (an
  8 × 8 grid) and **Custom** (the browser's colour input plus a hex field).
  - It replaces `ColorPicker`, the Colours rows' `hexInput` and the
    scheme cells' control.
  - The role group is hidden where a role is not allowed.
  - A ⚠ marks a colour a 64-colour target would dither, with a one-click
    nearest (`MIP64_SNAP`). Black and white play the same part on a
    2-colour target.
- **Colours section:** a "used by N" line per swatch, listing the elements
  (R1).
- **Colour axes section (K4, K5):** for each of `accent_color` and
  `data_color`:
  - add or remove the axis;
  - its `default:`;
  - its `choices:`, as ticks over the face's swatches, always written as
    a list;
  - `role:`;
  - a `choices: any` axis shown read-only, with the note the research
    words (§5.3), and a **Make it a list** button that writes the
    palette's legal swatches as the list.
- **Tests:**
  - each pick route, including the `_2` and same-value reuse cases;
  - the automatic rename and the case where it is not done;
  - K3's removal, with an author-named swatch kept;
  - the axis section's list writes;
  - refusals: deleting a swatch in use, renaming onto a role.
- **Docs:** `docs/guide/studio.md` (the picker, Colours, the colour-axes
  section); `docs/guide/colors.md`, which says the editor can add the 64;
  `docs/guide/mip-palette.md`, which names the table as its source.

### Slice 2 — colour schemes (C1, C2)

- **Edits**, each one `chain` proven by the research probe's shapes
  (`docs/research/probes/editor-gaps/compound.py`):
  - `make_switchable(swatches, scheme)`: move the chosen swatches into
    `theme: schemes: <scheme>: colors:` under the same names, and add
    `config: style:` with one entry when there is none. When there is
    one, `scheme:` goes on every entry (all-or-none);
  - `add_scheme(name, like)`: a copy of `like`, plus a style entry when
    every entry is scheme-only;
  - `rename_scheme`, which repoints every `scheme:`, and `delete_scheme`,
    which deletes the style entries naming it, refused if that would
    leave none;
  - `add_role(name, values)` in every scheme, `rename_role` (the key in
    every scheme plus `color.<old>`), and `delete_role` (refused while
    referenced);
  - `remove_theme(keep)`: each role of `keep` becomes a swatch (its value
    resolved to hex); every entry's `scheme:` is dropped and the entries
    kept (C2); `config: style:` is removed only when it then has no
    entries left.
- **Write block style** for a new nested block, through `_block`, not
  flow. Test: a `make_switchable` patch reads as block YAML.
- **UI:** the Colours section becomes **Colours and schemes**:
  - **Make switchable…** when there is no theme;
  - the roles × schemes table with **+ Scheme**, **+ Role**, rename and
    delete per column and row;
  - **Remove schemes…**, whose confirmation counts the entries that will
    become duplicates.
- **Diagnostic:** "unknown data source 'config.colors.<role>'" becomes a
  message about `color.<role>` having no style to pick a scheme
  (`wfb/ir/builder/reading.py`). Test: it names `color.fg`.
- **Tests:**
  - each edit on `wfb new -t minimal` and on the showcase;
  - `remove_theme` on the showcase, which reports the 4 `duplicate-style`
    warnings and changes nothing else;
  - refusals driven red: a role named like a swatch, deleting the last
    scheme a style needs, deleting a role in use.
- **Docs:** `docs/guide/studio.md`; `docs/guide/colors.md`, for the new
  message.

### Slice 3 — hand sets (H1, H2)

- **Presets:** `wfb/templates/hands/` holds `classic` (from
  `wfb/templates/analog.yaml`), `baton`, `dauphine` and `subdial`, drawn
  from the example faces' sets.
  - Their colours are rewritten to the face's `color.fg`/`color.accent`
    when present, or else the first swatch.
  - Test: each preset loads into the minimal face and builds warning-free
    on all three targets (slow suite).
- **Edits:**
  - `add_hand_set(name, preset)`, which also adds a `hands` element at
    the centre when the face has none, as one change;
  - `rename_hand_set`, which repoints every `set:`, as `rename_slot`
    does;
  - `duplicate_hand_set`;
  - `delete_hand_set`, refused while an element names it.
- **UI:**
  - A **Hand sets** section: each set's thumbnail (the set drawn alone at
    the preview's sample time, from a new `/api/documents/{id}/handset`
    frame), its hands with their part counts, each hand's colour through
    the slice 1 picker, **used by**, and **Edit in YAML**, which opens
    the YAML tab with the set's lines selected.
  - In the inspector, `set:` is a dropdown of declared sets, with the same
    link.
  - The add bar's note becomes a link to the section.
- **Tests:** each edit and refusal; the inspector's `set:` widget; the
  thumbnail endpoint's size and that it draws the set's ink.
- **Docs:** `docs/guide/studio.md`; `docs/guide/analog-hands.md`, which
  points to the section; `docs/limitations.md`, which says hand parts are
  edited in the YAML.

### Slice 4 — slots (L1–L3)

- **Table:** `wfb.complications.ComplicationType` gains `label` (Garmin's
  name for the type, from the SDK's `Complications` docs) and `category`
  (activity, health, body, weather, time and sun, performance, device),
  for all 42.
  - Test: every type has both, and labels are unique.
  - `wfb complications` prints them. Its `--help` text loses the format 1
    vocabulary (`config: data:`, `complication_slot`, `icon_size:`).
- **Showing (L2):**
  - `PreviewOptions` and `FrameKey` gain `picks: {slot: type}`.
  - The preview's reads of `slot.default` take the pick instead: the
    reading, the icon, and a gauge's `max: auto` scale.
  - The view bar gains one control per slot: default, or any of its
    choices.
  - Test: a picked `current_weather` draws its sample where `steps` drew
    its own, and a slot gauge's scale follows the pick (the research left
    both UNVERIFIED).
- **Slot card (L1):** one component, shown in the Face tab's Slots list
  and above the keys of a selected `data` element or slot gauge.
  - Name, with rename as a button.
  - Default, as the star in the checklist.
  - Choices: the grouped checklist with glyphs and samples, plus "All,
    including types Garmin adds later", which is `any`. Switching to it
    keeps the ticks shown.
  - Per-choice icon: a glyph button opening an icon picker, shared with
    the `icon` element's own `icon:`.
  - Label: "Title in the settings menu (watches without the native
    editor)".
  - Drawn by; delete.
- **+ Slot** asks what to show first, from the same grid, and adds the
  slot and a `data` element as one change.
- **Inspector:**
  - a `data` element's `icon:` becomes an object field (`size`,
    `position`, `gap`, `color`);
  - keys whose schema description marks them as never accepted
    (`format:` on `data`) are hidden.
- **Tests:**
  - the `picks` frame;
  - + Slot's compound add;
  - the `any` ↔ list round trip;
  - the inspector fields;
  - refusals kept: removing the default from the list, deleting a drawn
    slot.
- **Docs:** `docs/guide/studio.md`; `docs/guide/configuration.md`, for
  the labels where it lists types.

### Slice 5 — sessions and the `Host` check (S1–S3)

- **Host:** `TrustedHostMiddleware` allowing `127.0.0.1`, `localhost`,
  `[::1]` and the `--host` value, plus `--allow-host` for a name a proxy
  uses.
  - Test (driving red first): `docs/research/probes/editor-gaps/origin.py`'s
    foreign `Host` is refused with 400.
- **Principals and sessions** (`wfb/studio/store.py` or a new
  `sessions.py`):
  - `state/sessions/<sha256(token)>.json` holds the principal, created
    and last seen;
  - `state/principals/<id>.json` holds the kind, created, and
    `identities: []`;
  - `meta.json` gains `owner`;
  - `Store.documents(owner)` filters by owner, and `_dir(doc_id, owner)`
    raises `UnknownDocument` (404) for someone else's document.
- **Middleware:** resolves the `wfb_session` cookie, minting an anonymous
  principal when there is none.
  - The cookie is `HttpOnly`, `SameSite=Strict` and `Path=/`, with
    `Secure` over https, and `Max-Age` equal to `--keep-days`, renewed
    on use.
  - Every route takes `request.state.principal`.
  - `Events` streams only the principal's documents.
  - Build downloads are checked against the owner of the build's
    document.
- **Claiming:**
  - At startup, `wfb studio` prints `http://127.0.0.1:<port>/?claim=<code>`.
    The browser that opens it becomes the owner principal, which holds
    documents with no `owner` and the face named on the command line.
  - **Use my faces in another browser** (home screen) issues a single-use
    `/claim/<code>` link that lasts 10 minutes and binds the opening
    browser to the same principal.
- **`--single-user`:** every session binds to one `local` principal.
  That is today's behaviour, with the `Host` check kept.
- **Pruning:** sessions unseen for `--keep-days` are removed. A principal
  with no sessions and no documents is removed.
- **Tests:**
  - two clients with separate cookies see disjoint home lists;
  - the other client's id gets a 404 on every document route, including
    events and build downloads;
  - a claim link joins two clients, and a second use is refused;
  - legacy documents go to the claimer;
  - `--single-user` shares everything;
  - a missing cookie mints a principal;
  - pruning.
- **Docs:** `docs/guide/studio.md`, covering sessions, the claim link,
  another browser and `--single-user`; `docs/container.md`, since the
  claim link is printed in the container's log; `docs/limitations.md`
  (no login yet).

### Close-out

Delete this file, and add its row to `docs/plans/README.md`'s
deleted-plans table, with each slice's commit. Update the status at the
top of research 30.

## 3. Risks

- **The automatic rename (slice 1) is the riskiest edit.** It rewrites
  references across the file. R1 keeps it to the Colours section, the
  whole-name match keeps it to `color.<name>`, and the gate refuses a
  patch whose data differs from the intent. A test renames `cFF8000` in a
  face that also has `color.cFF8000_dim` and an expression using both.
- **Claim links are bearer secrets.** They are single use, last 10
  minutes, and only their hash is stored. A link printed to a shared
  terminal log is as good as a password until it is used.
- **Per-browser ownership will surprise a single user** who switches
  browsers. The home screen says which browser it is, and the "another
  browser" link is one click away.
- **Labels for 42 types** are data entry against the SDK docs. A wrong
  label is cosmetic, but each one must be checked, not guessed (working
  agreement: never invent).
