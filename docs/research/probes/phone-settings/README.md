# Probe: properties, phone settings and an on-watch settings menu

**Answer: all three compile warning-free on every verification device and on
`fenix5`, and cost 112 B (properties + a phone setting) and 459 B (plus an
on-watch `Menu2` settings view) over a face with none.** Research 17 has the
context, including why phone settings do not reach a sideloaded app at all.

One source set, three variants, chosen by `excludeAnnotations`:

| Variant | Excludes | Adds |
|---|---|---|
| A | `settings`, `menu` | nothing: a face that draws the time |
| B | `nosettings`, `menu` | `properties.xml` (`ShowSeconds`, boolean), `settings.xml`, a type-checked `Properties.getValue` read, `onSettingsChanged` |
| C | `nosettings` | B plus `AppBase.getSettingsView` returning a one-toggle `Menu2` and a `Menu2InputDelegate` that writes `Properties.setValue` |

## Measured (SDK 9.2.0, `-l 3`, `-O 3z`, strict typecheck, manifest 3.1.0)

| Variant | fr955, fenix8solar47mm, fenix8solar51mm | fenix5 |
|---|---|---|
| A | 376 B data + 285 B code | 887 + 383 |
| B | 400 + 373 | 931 + 493 |
| C | 503 + 617 | 1 207 + 803 |

Warning-free everywhere except A's own "`_view` is not used" warning. A is
the control, and the field exists for B and C. `fenix5` has no
`getSettingsView` in its `api.debug.xml` and still builds C cleanly; the
override is simply never called there (constraint 6d).

`monkeyc` writes `<device>-settings.json` beside each B/C `.prg`: the setting's
key, type, default, title string id and options. The Store and the simulator
consume it.

## Not answered here

Whether the watch shows the face's settings entry in its Watch Face menu, on
`fr955` and on a fēnix 8 alongside the native editor, and which memory limit
the settings view runs under. There is no simulator (root `CLAUDE.md` §3);
it needs a sideload.

## Rebuilding it

```sh
docs/research/probes/phone-settings/build.sh /tmp/probe            # the three verification devices
docs/research/probes/phone-settings/build.sh /tmp/probe fenix5 fr955
```

The script assembles each variant into `OUTDIR/<variant>/` (manifest, jungle,
a per-device launcher icon at the size `compiler.json` asks for) and runs
`monkeyc … -w -l 3 --build-stats 0` per device.
