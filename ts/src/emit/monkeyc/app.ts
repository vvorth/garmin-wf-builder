// `<Face>App.mc`, `Palette.mc` and `IconGlyphs.mc`: the shared,
// device-independent sources. Port of wfb/emit/monkeyc/app.py.
import type { Guards } from "../../availability.ts";
import * as icons from "../../icons.ts";
import type { Face } from "../../ir/model.ts";
import * as kinds from "../../kinds/index.ts";
import { repr } from "../../py.ts";
import { Writer } from "../writer.ts";
import { editorSlots, header, needsDelegate, type SourceFile } from "./common.ts";

/** `source/<Face>App.mc`: the application entry point. */
export function emitApp(face: Face, guards: Guards | null = null): SourceFile {
  const needsIt = needsDelegate(face);
  const menu = guards !== null && guards.config_menu;
  const hasSlots = editorSlots(face).length > 0;
  const w = new Writer();
  w.doc(header(face)).blank();
  w.lines("import Toybox.Application;", "import Toybox.Lang;", "import Toybox.WatchUi;").blank();
  w.doc(`The application entry point for ${repr(face.name)}.`);
  const viewCtor = hasSlots ? `new ${face.entry}View(_editMode)` : `new ${face.entry}View()`;
  w.block(`class ${face.entry}App extends Application.AppBase`, () => {
    if (hasSlots) {
      w.doc("Whether the watch face was started by the native config editor.\n"
        + "\n"
        + "Read exactly once, by getInitialView just below -- which is what keeps\nthis from being a written-but-never-read field (verified: "
        + "that warns\n\"Member variable '_editMode' is not used.\"; a value read back by a\nconstructor call, even one the view itself then "
        + "discards, does not).");
      w.line("private var _editMode as Boolean = false;");
      w.blank();
    }
    if (menu) {
      w.doc("The view, kept so the settings menu edits the one on screen.");
      w.line(`private var _view as ${face.entry}View?;`);
      w.blank();
    }
    w.block("function initialize()", () => w.line("AppBase.initialize();"));
    w.blank();
    if (hasSlots) {
      w.doc("Detect edit mode before the initial view is retrieved -- the SDK's own\nConfigurationWatchFaceApp.onStart, verbatim.");
      w.block("function onStart(state as Dictionary?) as Void", () => {
        w.block("if (state != null)", () => {
          w.line("var editing = state[:launchedFromWatchFaceSettingsEditor] as Boolean?;");
          w.block("if (editing != null && editing)", () => w.line("_editMode = true;"));
        });
      });
      w.blank();
    }
    w.block("function getInitialView() as [Views] or [Views, InputDelegates]", () => {
      if (!needsIt && !menu) {
        w.line(`return [ ${viewCtor} ];`);
      } else if (!needsIt) {
        w.line(`var view = ${viewCtor};`);
        w.line("_view = view;");
        w.line("return [ view ];");
      } else {
        w.line(`var view = ${viewCtor};`);
        if (menu) w.line("_view = view;");
        w.comment("the `has` guard is the SDK's own idiom (samples/Analog): a watch");
        w.comment("without WatchFaceDelegate still gets the face, just not the holds");
        w.comment("(or, for a `config:` design, the re-read on a settings edit)");
        w.block("if (WatchUi has :WatchFaceDelegate)", () => {
          w.comment("the delegate holds the view so a config edit can update it");
          w.line(`return [ view, new ${face.entry}Delegate(view) ];`);
        });
        w.line("return [ view ];");
      }
    });
    if (menu) {
      w.blank();
      w.doc("The config: settings menu, opened from the watch's Watch Face menu on a\n"
        + "device with no native editor (fr955).  With the native editor this\n"
        + "returns null: that editor edits config: there.  A device without\n"
        + "getSettingsView (fenix5) never calls this and keeps every default.");
      w.block("function getSettingsView() as [Views] or [Views, InputDelegates] or Null", () => {
        w.block("if (Application has :WatchFaceConfig)", () => w.line("return null;"));
        w.line("var view = _view;");
        w.block("if (view == null)", () => {
          w.comment("nothing documents that getInitialView runs first, so build the");
          w.comment("view here if it has not: its constructor reads the stored config");
          w.line(`view = ${viewCtor};`);
          w.line("_view = view;");
        });
        w.line(`return [ view.configMenu(), new ${face.entry}ConfigMenuDelegate(view) ];`);
      });
    }
  });
  return { path: `source/${face.entry}App.mc`, text: w.render() };
}

export function emitPalette(face: Face): SourceFile {
  const w = new Writer();
  w.doc(header(face)).blank();
  w.lines("import Toybox.Lang;").blank();
  w.doc("Colours declared in the design's `resources: palette:` block.\n"
    + "\n"
    + "Elements reference these by name rather than by hex, so a colour can be\n"
    + "changed in one place and linted in one place.");
  w.block("module Palette", () => {
    [...face.palette].forEach(([name, color], index) => {
      if (index) w.blank();
      w.doc(`\`color.${name}\` = ${color}`);
      w.line(`const ${name.toUpperCase()} as Number = ${color.asMonkeyc()};`);
    });
  });
  return { path: "source/Palette.mc", text: w.render() };
}

/** `source/IconGlyphs.mc`: catalogue name to drawn glyph, for a dynamic icon; a key in `viaChar` is built at runtime. */
export function emitIconGlyphs(face: Face, viaChar: ReadonlySet<string> = new Set()): SourceFile {
  const entries = iconGlyphEntries(face);
  const w = new Writer();
  w.doc(header(face)).blank();
  w.lines("import Toybox.Lang;").blank();
  w.doc("Catalogue name (or a per-choice 'icon: U+XXXX' override's canonical\n"
    + "spelling) -> drawn glyph, for a dynamic (`icon: {for:}`) icon.\n"
    + "\n"
    + "Generated directly from wfb.icon_catalog.CATALOG (plus any per-choice\n"
    + "override) -- see wfb/icons.py's module docstring for why this table,\n"
    + "rather than WfbWeather.mc, is where a name becomes a character.");
  w.block("module IconGlyphs", () => {
    w.block("function glyph(name as String) as String", () => {
      w.block("switch (name)", () => {
        for (const key of codePointSorted(entries.keys())) {
          if (viaChar.has(key)) {
            w.comment("built at runtime: as a literal, this glyph would share monkeyc's");
            w.comment("str___<hash> label with another string (wfb/emit/strhash.py)");
            w.line(`case "${key}": return (0x${entries.get(key)!.codePointAt(0)!.toString(16)}).toChar().toString();`);
          } else {
            w.line(`case "${key}": return "${entries.get(key)}";`);
          }
        }
        w.line(`default: return "${icons.FALLBACK_CODEPOINT}";`);
      });
    });
  });
  return { path: "source/IconGlyphs.mc", text: w.render() };
}

/** Python's `sorted()` of strings. */
function codePointSorted(items: Iterable<string>): string[] {
  return [...items].sort((a, b) => {
    const x = [...a], y = [...b];
    for (let i = 0; i < Math.min(x.length, y.length); i++) {
      const d = x[i]!.codePointAt(0)! - y[i]!.codePointAt(0)!;
      if (d !== 0) return d;
    }
    return x.length - y.length;
  });
}

/** Every key `IconGlyphs.glyph` must answer in this design, to its glyph. */
export function iconGlyphEntries(face: Face): Map<string, string> {
  const entries = new Map<string, string>();
  for (const [, run] of kinds.faceTextRuns(face)) if (run.glyph_table !== null) for (const [k, v] of run.glyph_table) entries.set(k, v);
  return entries;
}
