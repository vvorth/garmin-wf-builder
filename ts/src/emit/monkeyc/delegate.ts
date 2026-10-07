// `<Face>Delegate.mc`: touch and hold, and the on-device config editor
// callbacks.
//
// `onPress` only, on every device: `onTap` is documented "Only available in
// WatchFace config mode", and serves only the native editor's highlight.
import { type Guards, NO_GUARDS } from "../../availability.ts";
import * as complications from "../../complications.ts";
import { DataElement } from "../../ir/model.ts";
import { dataHoldMethod } from "../../ir/naming.ts";
import type { ResolvedFace } from "../../layout.ts";
import { Writer } from "../writer.ts";
import {
  CONFIG_LAYOUT_METHOD, constPrefix, type EditorSlot, editorSlots, gatedHolds, header, HOLDS_SHOWN, holdTargets, maskLiteral, type SourceFile,
} from "./common.ts";

function emitOnWatchFaceConfigEdited(w: Writer, hasSlots = false): void {
  w.doc("The wearer changed something in the native editor.  Re-read the whole\n"
    + "settings snapshot and hand it to the view -- the same `applyConfig` the\n"
    + "first onLayout read already uses, so there is exactly one place that\n"
    + "turns a Settings object into view state.");
  w.block("function onWatchFaceConfigEdited(options as {\n"
    + "        :configId as $.Toybox.Application.WatchFaceConfig.Id,\n"
    + "        :type as WatchFaceConfigType?,\n"
    + "        :committed as $.Toybox.Lang.Boolean}) as Void", () => {
    if (hasSlots) {
      w.comment("a null :type is the end of editing; any other type means no slot");
      w.comment("is being animated -- either way, stop skipping the last one");
      w.block("if (options[:type] != WatchUi.WATCH_FACE_CONFIG_TYPE_COMPLICATION)", () => w.line("_view.setPulsing(0);"));
    }
    w.line("var id = options[:configId] as WatchFaceConfig.Id?;");
    w.block("if (id != null)", () => {
      w.line("var settings = WatchFaceConfig.getSettings(id);");
      w.block("if (settings != null)", () => w.line("_view.applyConfig(settings);"));
    });
  });
  w.blank();
}

function emitExitTo(w: Writer, exitArg: string, guard: string | null = null): void {
  w.blockIf(guard !== null ? `if (${guard})` : null, () => {
    w.line(`Complications.exitTo(${exitArg});`);
    w.line("return true;");
  });
}

/** The `if` header testing the touch point against one `Layout` rectangle, plus any extra term. */
function hitTest(box: string, extra = ""): string {
  return `if (x >= Layout.${box}_X && x < Layout.${box}_X + Layout.${box}_WIDTH\n`
    + `        && y >= Layout.${box}_Y && y < Layout.${box}_Y + Layout.${box}_HEIGHT${extra})`;
}

/** `source/<Face>Delegate.mc`: turn a touch and hold into a glance. */
export function emitDelegate(resolved: ResolvedFace, guards: Guards = NO_GUARDS): SourceFile {
  const face = resolved.face;
  const targets = holdTargets(face);
  const hasConfig = face.hasConfig;
  const slots = editorSlots(face);
  const w = new Writer();
  w.doc(header(face)).blank();
  const imports = ["import Toybox.Lang;", "import Toybox.WatchUi;"];
  if (hasConfig) imports.unshift("import Toybox.Application.WatchFaceConfig;");
  if (targets.length > 0) imports.unshift("import Toybox.Complications;");
  w.lines(...imports).blank();
  w.doc(`Touch handling for ${face.name}.\n`
    + "\n"
    + "Each region below is one element's own drawn box, resolved per device in\n"
    + "the Layout module, so what the finger must hit is what the eye sees.");
  const gated = gatedHolds(face);
  const needsView = hasConfig || gated.length > 0;
  w.block(`class ${face.entry}Delegate extends WatchUi.WatchFaceDelegate`, () => {
    if (needsView) {
      w.doc("The view, so a config edit can be applied to it, a `data`\n"
        + "element's hold target read back, or what the last frame drew.\n"
        + "\n"
        + "Only declared when it is actually read from: `monkeyc -w` reports an\n"
        + "unused member variable (verified -- \"Member variable '_view' is not\n"
        + "used.\" on a plain `on_hold:` design with neither `config:` nor a\n"
        + "`data` element), and a generator has no excuse for output a human\n"
        + "wouldn't have written (CLAUDE.md).  The constructor parameter stays\n"
        + "unconditional either way: an unused *parameter* does not warn (verified\n"
        + "the same way, standalone), so one delegate shape and one\n"
        + "`new ...Delegate(view)` call site still serve every design -- only the\n"
        + "field is conditional.");
      w.line(`private var _view as ${face.entry}View;`);
      w.blank();
    }
    w.block(`function initialize(view as ${face.entry}View)`, () => {
      w.line("WatchFaceDelegate.initialize();");
      if (needsView) w.line("_view = view;");
    });
    w.blank();
    if (hasConfig) emitOnWatchFaceConfigEdited(w, slots.length > 0);
    if (slots.length > 0) {
      emitOnTap(w, slots);
      emitGetComplicationDrawable(w);
    }
    w.doc("A touch and hold -- the only gesture a live watch face receives.\n"
      + "\n"
      + "There is deliberately no onTap here for a live face: it is documented\n"
      + "\"Only available in WatchFace config mode\" and never fires during normal\n"
      + "display, on any device."
      + (slots.length > 0 ? "  The onTap above exists purely to serve the\n"
        + "native editor's own animated highlight over a `data` element, which\n"
        + "is a different thing entirely.\n" : "\n")
      + "\n"
      + "Returns true when the touch was consumed, so the system does not also\n"
      + "act on it.");
    w.block("function onPress(clickEvent as ClickEvent) as Boolean", () => {
      if (targets.length === 0) {
        w.comment("this design declares no on_hold target -- the delegate exists");
        w.comment("only for onWatchFaceConfigEdited above");
      } else {
        w.line("var where = clickEvent.getCoordinates();");
        w.line("var x = where[0];");
        w.line("var y = where[1];");
      }
      for (const element of targets) {
        const prefix = constPrefix(element.id);
        w.blank();
        const layoutTest = element.layout !== null ? ` && _view.${CONFIG_LAYOUT_METHOD}() == ${face.layouts.indexOf(element.layout)}` : "";
        const bit = gated.indexOf(element);
        const shownTest = bit >= 0 ? ` && (_view.${HOLDS_SHOWN} & ${maskLiteral((1 << bit) >>> 0)}) != 0` : "";
        const condition = hitTest(`${prefix}_HOLD`, layoutTest + shownTest);
        if (element instanceof DataElement) {
          w.comment(`\`${element.id}\` -> whatever the wearer picked for slot ${element.slot}`);
          w.block(condition, () => {
            if (guards.complications) {
              w.line(`var id = _view.${dataHoldMethod(element.id)}();`);
              emitExitTo(w, "id", "id != null");
            } else {
              emitExitTo(w, `_view.${dataHoldMethod(element.id)}()`);
            }
          });
          continue;
        }
        const launch = complications.TYPES.get(element.on_hold!)!;
        w.comment(`\`${element.id}\` -> ${element.on_hold}`);
        w.block(condition, () => emitExitTo(w, `new Complications.Id(Complications.${launch.constant})`, guards.complications ? "Toybox has :Complications" : null));
      }
      w.blank();
      w.line("return false;");
    });
  });
  return { path: `source/${face.entry}Delegate.mc`, text: w.render() };
}

function emitOnTap(w: Writer, slots: readonly EditorSlot[]): void {
  w.doc("Only fires inside the on-device config editor (research 07 1a) -- tells\n"
    + "it which slot was pointed at, exactly the SDK sample's own\n"
    + "ConfigurationWatchFaceDelegate.onTap: the smallest slot box holding the\n"
    + "touch, so a slot inside a ring stays selectable.  Never fires while the\n"
    + "face is simply being looked at, on any device.");
  w.block("function onTap(clickEvent as ClickEvent) as Boolean", () => {
    w.line("var where = clickEvent.getCoordinates();");
    w.line("var x = where[0];");
    w.line("var y = where[1];");
    w.line("var chosen = 0;");
    w.line("var chosenArea = 0;");
    for (const slot of slots) {
      const box = `Layout.${slot.constPrefix}_BOX`;
      w.blank();
      w.comment(`slot ${slot.name}: ${slot.elements.map((e) => `\`${e.id}\``).join(", ")}`);
      w.block(hitTest(`${slot.constPrefix}_BOX`), () => {
        w.line(`var area = ${box}_WIDTH * ${box}_HEIGHT;`);
        w.block("if (chosen == 0 || area < chosenArea)", () => {
          w.line(`chosen = ${slot.unique};`);
          w.line("chosenArea = area;");
        });
      });
    }
    w.blank();
    w.block("if (chosen == 0)", () => w.line("return false;"));
    w.line("setSelectedComplication(chosen);");
    w.line("return true;");
  });
  w.blank();
}

function emitGetComplicationDrawable(w: Writer): void {
  w.doc("Only fires inside the on-device config editor: hands back a Drawable the\n"
    + "system animates while the wearer picks a new value for one slot.\n"
    + "\n"
    + "Seen on a fenix8solar47mm: the highlight animates over the slot and\n"
    + "previews each choice.  A watch with no editor never calls this.");
  w.block("function getComplicationDrawable(complication as ComplicationRef)\n        as Drawable or WatchUi.ComplicationDrawableRef or Null", () => {
    w.line("var unique = complication.uniqueIdentifier;");
    w.block("if (unique == null)", () => w.line("return null;"));
    w.line("_view.setPulsing(unique);");
    w.line("return _view.drawableFor(unique);");
  });
  w.blank();
}
