// `config:`: the four on-device configuration axes -- Styles (`style:`),
// Data (`slots:`) and the two colours (`accent_color`, `data_color`). Port
// of wfb/ir/builder/config.py.
import * as complications from "../../complications.ts";
import type { Span } from "../../diagnostics.ts";
import type { Data } from "../../edit/yaml.ts";
import type * as icons from "../../icons.ts";
import { Color, ColorError } from "../../palette.ts";
import { repr, str } from "../../py.ts";
import { CONFIG_AXIS_ROLES, ConfigChoice, ConfigColor, ConfigDataSlot, ConfigStyle, StyleEntry } from "../model.ts";
import { TopLevelBlocks } from "./blocks.ts";
import { ICON_OVERRIDE_ERROR, NO_ICON_OVERRIDE } from "./glyphs.ts";
import { lintSuppression, type Node } from "./state.ts";

/** Builds the `config:` axes. */
export class ConfigAxes extends TopLevelBlocks {
  /**
   * `config: style:`: author-named, ordered entries riding Styles. Three
   * uniform-shape passes, each rejecting the whole block at its first
   * violation (one error, not N).
   */
  private buildConfigStyle(spec: Node, span: Span | null): void {
    const rawChoices = spec.get("choices") as Map<string, Node>;
    const hasLayouts = this.layouts.size > 0;

    for (const [name, item] of rawChoices) {
      if (item.has("layout") || item.has("scheme")) continue;
      this.bag.error("config", `config.style.choices.${name}: needs at least one of 'layout:'/'scheme:'`,
        this.doc.span(rawChoices, name));
      this.rejected_config.add("style");
      return;
    }

    for (const [name, item] of rawChoices) {
      const itemSpan = this.doc.span(rawChoices, name);
      const hasLayout = item.has("layout");
      if (hasLayouts && !hasLayout) {
        this.bag.error("config", `config.style.choices.${name}: needs 'layout:' -- this `
          + "design declares 'layouts:', so every entry must pick one", itemSpan,
        { notes: ["declared layouts: " + [...this.layouts.keys()].join(", ")] });
        this.rejected_config.add("style");
        return;
      }
      if (!hasLayouts && hasLayout) {
        this.bag.error("config", `config.style.choices.${name}: 'layout:' is set, but `
          + "this design declares no 'layouts:' at all", this.doc.span(item, "layout") ?? itemSpan,
        { notes: ["remove 'layout:', or add a 'layouts:' block"] });
        this.rejected_config.add("style");
        return;
      }
    }

    const baselineName = rawChoices.keys().next().value!;
    const baselineHasColors = rawChoices.get(baselineName)!.has("scheme");
    for (const [name, item] of rawChoices) {
      const hasColors = item.has("scheme");
      if (hasColors === baselineHasColors) continue;
      const itemSpan = this.doc.span(rawChoices, name);
      const message = hasColors
        ? `config.style.choices.${name}: declares 'scheme:', but 'choices.${baselineName}' does not`
        : `config.style.choices.${name}: needs 'scheme:' -- 'choices.${baselineName}' declares one`;
      this.bag.error("config", message, itemSpan, { notes: ["'scheme:' must be declared on every entry, or none"] });
      this.rejected_config.add("style");
      return;
    }

    const entries: StyleEntry[] = [];
    let ok = true;
    for (const [name, item] of rawChoices) {
      const itemSpan = this.doc.span(rawChoices, name);
      let entryOk = true;
      let colorsName: string | null = null;
      if (item.has("scheme")) {
        colorsName = this.schemeReference(item.get("scheme") as string, this.doc.span(item, "scheme") ?? itemSpan);
        if (colorsName === null) entryOk = false;
      }
      let layoutName: string | null = null;
      if (item.has("layout")) {
        layoutName = this.layoutReference(item.get("layout") as string, this.doc.span(item, "layout") ?? itemSpan);
        if (layoutName === null) entryOk = false;
      }
      if (!entryOk) {
        ok = false;
        continue;
      }
      entries.push(StyleEntry.create({
        name, label: (item.get("label") ?? null) as string | null, colors: colorsName, layout: layoutName,
        ...lintSuppression(item), span: itemSpan,
      }));
    }
    if (!ok) {
      this.rejected_config.add("style");
      return;
    }

    const defaultName = spec.get("default") as string;
    const byName = new Map(entries.map((e) => [e.name, e]));
    if (!byName.has(defaultName)) {
      this.defaultNotInChoices("config.style", defaultName, this.doc.span(spec, "default"),
        { noun: "entry", tag: "style", listed: "declared entries: " + [...byName.keys()].join(", ") });
      this.rejected_config.add("style");
      return;
    }
    this.config_style = ConfigStyle.create({ default: defaultName, entries, span });
  }

  /** The shared "default is not one of 'choices:'" error every `config:` axis gives. */
  private defaultNotInChoices(where: string, defaultValue: unknown, span: Span | null,
    { noun, tag, listed }: { noun: string; tag: string; listed: string }): void {
    const article = "aeiou".includes(noun[0]!) ? "an" : "a";
    this.bag.error("config", `${where}: default ${repr(defaultValue)} is not one of 'choices:'`, span, {
      notes: [
        `the on-device editor marks one listed ${noun} as the user's `
        + `default (the generated <${tag} default="true">) -- Garmin `
        + "defines no behaviour for a default that is not in the list",
        `add it to 'choices:', or change 'default:' to match ${article} ${noun} already there`,
        listed,
      ],
    });
  }

  /** The shared "unknown complication" notes: a near match, then the full list's size. */
  complicationSuggestionNotes(name: string, noun: string): string[] {
    const notes = complications.TYPES.didYouMeanNotes(name);
    notes.push(`run \`wfb complications\` for the full list of ${complications.TYPES.size} ${noun}`);
    return notes;
  }

  /** A complication type's name from `config: slots:`'s `default:`/`choices:`. */
  private complicationReference(raw: Data | undefined, what: string, span: Span | null): string | null {
    if (typeof raw !== "string") {
      this.bag.error("config", `${what}: expected a complication type's name, got ${repr(raw ?? null)}`, span);
      return null;
    }
    if (complications.get(raw) !== undefined) return raw;
    this.bag.error("config", `${what}: unknown complication type ${repr(raw)}`, span,
      { notes: this.complicationSuggestionNotes(raw, "types") });
    return null;
  }

  /** `config: slots:`: named native complication slots. */
  private buildConfigData(raw: Node): void {
    for (const [name, spec] of raw as Map<string, Node>) {
      const span = this.doc.span(raw, name);
      this.config_data.declare(name, span);
      const defaultSpan = this.doc.span(spec, "default");
      const defaultType = this.complicationReference(spec.get("default"), `config.slots.${name}.default`, defaultSpan);
      if (defaultType === null) {
        this.config_data.reject(name);
        continue;
      }
      const rawChoices = spec.get("choices");
      const label = (spec.get("label") ?? null) as string | null;
      if (rawChoices === "any") {
        this.config_data.set(name, ConfigDataSlot.create({ name, default: defaultType, choices: "any", label, span }));
        continue;
      }
      const choices: string[] = [];
      const iconOverrides = new Map<string, icons.SlotIcon | null>();
      const seen = new Map<string, number>();
      let ok = true;
      (rawChoices as Data[]).forEach((item, index) => {
        const itemSpan = this.doc.span(rawChoices, index);
        let resolved: string | null;
        if (item instanceof Map) {
          // `{type: <name>, icon: ...}` carries more than the bare form.
          const typeSpan = item.has("type") ? this.doc.span(item, "type") : itemSpan;
          resolved = this.complicationReference(item.get("type"), `config.slots.${name}.choices[${index}].type`, typeSpan);
          if (resolved === null) {
            ok = false;
            return;
          }
          const override = this.resolveChoiceIconOverride(item, `config.slots.${name}.choices[${index}]`, itemSpan);
          if (override === ICON_OVERRIDE_ERROR) {
            ok = false;
            return;
          }
          if (override !== NO_ICON_OVERRIDE) iconOverrides.set(resolved, override);
        } else {
          resolved = this.complicationReference(item, `config.slots.${name}.choices[${index}]`, itemSpan);
          if (resolved === null) {
            ok = false;
            return;
          }
        }
        if (seen.has(resolved)) {
          this.bag.error("config", `config.slots.${name}.choices: ${resolved} is listed more than once`, itemSpan, {
            notes: [
              `already listed at choices[${seen.get(resolved)}]`,
              "a type can appear at most once in 'choices:', "
              + "regardless of which shape (a bare name or "
              + "{type, icon}) each appearance uses -- "
              + "the schema's own 'uniqueItems' cannot see through "
              + "the two different shapes",
            ],
          });
          ok = false;
          return;
        }
        seen.set(resolved, index);
        choices.push(resolved);
      });
      if (!ok) {
        this.config_data.reject(name);
        continue;
      }
      if (!choices.includes(defaultType)) {
        this.defaultNotInChoices(`config.slots.${name}`, defaultType, defaultSpan,
          { noun: "type", tag: "type", listed: "listed types: " + choices.join(", ") });
        this.config_data.reject(name);
        continue;
      }
      this.config_data.set(name, ConfigDataSlot.create({
        name, default: defaultType, choices, icon_overrides: iconOverrides, label, span,
      }));
    }
  }

  /** `config:`: the colour axes, the Styles axis and the Data axis. */
  buildConfig(raw: Node): void {
    for (const [name, spec] of raw as Map<string, Node>) {
      const span = this.doc.span(raw, name);
      if (name === "style") {
        this.buildConfigStyle(spec, span);
        continue;
      }
      if (name === "slots") {
        this.buildConfigData(spec);
        continue;
      }
      const role = str(spec.get("role") ?? CONFIG_AXIS_ROLES.get(name)!);
      this.config_roles.set(name, role);
      const defaultSpan = this.doc.span(spec, "default");
      const defaultColor = this.resolveConfigColor(spec.get("default"), `config.${name}.default`, defaultSpan);
      if (defaultColor === null) {
        this.rejected_config.add(name);
        continue;
      }
      const rawChoices = spec.get("choices");
      if (rawChoices === "any") {
        this.config.set(name, ConfigColor.create({ name, default: defaultColor, choices: "any", span, role }));
        continue;
      }
      const choices: ConfigChoice[] = [];
      let ok = true;
      (rawChoices as Data[]).forEach((item, index) => {
        const itemSpan = this.doc.span(rawChoices, index);
        if (typeof item === "string") {
          // A bare `color.<swatch>` reference: its colour and, if it has one, its label.
          const color = this.paletteReference(item, itemSpan);
          if (color === null) {
            ok = false;
            return;
          }
          choices.push(ConfigChoice.create({ color, label: this.palette_labels.get(item.slice("color.".length)) ?? null }));
          return;
        }
        const entry = item as Node;
        let color: Color;
        try {
          color = Color.parse(entry.get("color") ?? null, `config.${name}.choices[${index}]`);
        } catch (error) {
          if (!(error instanceof ColorError)) throw error;
          this.bag.error("config", error.message, this.doc.span(entry, "color"));
          ok = false;
          return;
        }
        choices.push(ConfigChoice.create({ color, label: (entry.get("label") ?? null) as string | null }));
      });
      if (!ok) {
        this.rejected_config.add(name);
        continue;
      }
      if (!choices.some((choice) => choice.color.equals(defaultColor))) {
        this.defaultNotInChoices(`config.${name}`, str(spec.get("default")), defaultSpan,
          { noun: "colour", tag: "color", listed: "listed colours: " + choices.map((c) => c.color.toString()).join(", ") });
        this.rejected_config.add(name);
        continue;
      }
      this.config.set(name, ConfigColor.create({ name, default: defaultColor, choices, span, role }));
    }
  }
}
