// The `fonts:` block: a baked font (a TTF/OTF rasterised to a BMFont sheet
// at build time) or a vector `face:` (a device-resident scalable font).
//
import type { Span } from "../../diagnostics.ts";
import { isNumber, repr, str, truthy } from "../../py.ts";
import * as units from "../../units.ts";
import { Length, UnitError } from "../../units.ts";
import { FontSpec } from "../model.ts";
import type { Node } from "./state.ts";
import { VisibilityHelpers } from "./visibility.ts";

/** `a/b/../c` as `a/c`: a POSIX path with `.` and `..` folded, as `Path.resolve()` leaves it. */
export function normalizePath(path: string): string {
  const out: string[] = [];
  for (const part of path.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === ".." && out.length > 0 && out[out.length - 1] !== "..") out.pop();
    else out.push(part);
  }
  return (path.startsWith("/") ? "/" : "") + out.join("/");
}

/** `base / path` as pathlib joins and prints it: an absolute `path` replaces `base`, `.` parts drop, `..` stays. */
export function joinPath(base: string, path: string): string {
  const joined = path.startsWith("/") ? path : `${base}/${path}`;
  const parts = joined.split("/").filter((part, i) => part !== "." && (part !== "" || i === 0));
  return parts.join("/") || ".";
}

/** The directory part of a POSIX path. */
export function dirname(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash < 0 ? "." : path.slice(0, slash) || "/";
}

/** `fonts:` keys that only mean something while baking a sheet, refused on a `face:` entry. */
const VECTOR_FONT_BAKING_KEYS = ["glyphs", "monospace", "align", "antialias"];

/** Builds `fonts:` into its `NamedRegistry`. */
export class FontBlock extends VisibilityHelpers {
  buildFonts(raw: Node): void {
    const base = dirname(this.doc.path);
    for (const [name, spec] of raw as Map<string, Node>) {
      const span = this.doc.span(raw, name);
      this.fonts.declare(name, span);
      // The schema's `oneOf` guarantees exactly one of `source`/`face`.
      const font = spec.has("face") ? this.buildVectorFont(name, spec, span) : this.buildBakedFont(name, spec, base, span);
      if (font === null) {
        this.fonts.reject(name);
        continue;
      }
      this.fonts.set(name, font);
    }
  }

  private buildBakedFont(name: string, spec: Node, base: string, span: Span | null): FontSpec | null {
    const written = joinPath(base, str(spec.get("source")));
    const source = normalizePath(written);
    if (!this.fileExists(written)) {
      this.bag.error("font", `font ${repr(name)}: source file not found: ${str(spec.get("source"))}`,
        this.doc.span(spec, "source"), { notes: [`resolved against the design file, to ${written}`] });
      return null;
    }
    const size = this.fontSize(name, spec);
    if (size === null) return null;
    const monospace = truthy(spec.get("monospace") ?? false);
    if (spec.has("align") && !monospace) {
      this.bag.error("font", `font ${repr(name)}: 'align' needs 'monospace: true'`, this.doc.span(spec, "align"), {
        notes: [
          "align says where a glyph's ink sits inside its cell, and a "
          + "proportional font has no cell -- every glyph is exactly as "
          + "wide as it needs to be",
          "add 'monospace: true', or drop 'align'",
        ],
      });
      return null;
    }
    if (spec.has("unsupported")) {
      this.bag.error("font", `font ${repr(name)}: 'unsupported:' is not accepted on a baked font`,
        this.doc.span(spec, "unsupported"), {
          notes: [
            "'unsupported:' governs a device-resident 'face:' font "
            + "failing to publish a face -- a baked font is rasterised from "
            + "your own 'source:' at build time, so it is never unsupported "
            + "on any device",
            "drop 'unsupported:', or switch this entry to 'face:' if "
            + "you meant a device-resident font",
          ],
        });
      return null;
    }
    return FontSpec.create({
      name,
      source,
      size,
      glyphs: (spec.get("glyphs") ?? null) as string | null,
      // No tree to inherit through: the face default applies directly.
      antialias: truthy(spec.has("antialias") ? spec.get("antialias") : this.face_antialias),
      span,
      monospace,
      align: str(spec.get("align") ?? "center"),
    });
  }

  /** `fonts.<name>.face:`: a device-resident scalable face, resolved per device later. */
  private buildVectorFont(name: string, spec: Node, span: Span | null): FontSpec | null {
    let ok = true;
    for (const key of VECTOR_FONT_BAKING_KEYS) {
      if (!spec.has(key)) continue;
      this.bag.error("font", `font ${repr(name)}: ${repr(key)} is not accepted on a 'face:' font`, this.doc.span(spec, key), {
        notes: [
          `${repr(key)} is a property of baking a bitmap sheet, and a `
          + "vector font has no sheet -- it is drawn straight from the "
          + "device's own resident face, at any size, with nothing "
          + "rasterised at build time",
          "drop it, or switch this entry to 'source:' if you meant a baked font",
        ],
      });
      ok = false;
    }
    const size = this.fontSize(name, spec);
    if (!ok || size === null) return null;
    const rawFace = spec.get("face");
    const face = typeof rawFace === "string" ? [rawFace] : [...(rawFace as string[])];
    return FontSpec.create({ name, size, span, face, unsupported: str(spec.get("unsupported") ?? "error") });
  }

  /** `fonts.<name>.size` as a `Length`; a bare number is refused with the exact conversion named. */
  private fontSize(name: string, spec: Node): Length | null {
    const raw = spec.get("size");
    if (isNumber(raw)) {
      this.bag.error("font", `font ${repr(name)}: size must be a length such as '18%r' or `
        + `'12px', not a bare number (${repr(raw)})`, this.doc.span(spec, "size"), {
        notes: [
          `size: ${repr(raw)} used to mean ${repr(raw)}px on the smallest `
          + "target, scaled per device by the ratio of minor radii "
          + "-- the exact equivalent is (size / <smallest target's "
          + "minor radius, in px> * 100)%r, e.g. 68 on a 130px minor "
          + "radius (fenix8solar47mm, fr955) is 52.3076923077%r",
          "for the same pixel count on every device instead -- "
          + "what 'scale: false' used to give you -- use 'px', "
          + `e.g. '${repr(raw)}px'`,
        ],
      });
      return null;
    }
    let size: Length;
    try {
      size = Length.parse(raw, `font ${repr(name)}: size`);
    } catch (error) {
      if (!(error instanceof UnitError)) throw error;
      this.bag.error("units", error.message, this.doc.span(spec, "size"));
      return null;
    }
    if (!(units.SIZE_UNITS as readonly string[]).includes(size.unit)) {
      this.bag.error("font", `font ${repr(name)}: size must be px or %r, not ${size.unit}`, this.doc.span(spec, "size"), {
        notes: [
          "a font's sheet is rasterised before any element is placed, so its "
          + "size cannot depend on a parent box (%) or on a font (pt) -- there "
          + "is no box yet, and the font being sized is the one 'pt' would "
          + "measure against",
          "use '%r' for a size that follows the screen, e.g. '18%r'",
        ],
      });
      return null;
    }
    if (size.value <= 0) {
      this.bag.error("font", `font ${repr(name)}: size must be greater than zero`, this.doc.span(spec, "size"));
      return null;
    }
    return size;
  }
}
