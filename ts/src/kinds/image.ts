import type { Data, DataKey } from "../edit/yaml.ts";
import type { Builder } from "../ir/builder/index.ts";
import { BitmapElement } from "../ir/model.ts";
import { Placed, type Resolver } from "../layout.ts";
import { IntBox, roundPx, type Box } from "../units.ts";
import { readBitmap } from "../bitmaps.ts";
import { BitmapDraw, Const, type DrawContext, type Op } from "../draw/program.ts";
import { constPrefix } from "../emit/monkeyc/common.ts";
import { ElementKind, register, type Common } from "./base.ts";

class ImageKind extends ElementKind<BitmapElement> {
  readonly name = "image";
  readonly irClass = BitmapElement;

  build(b: Builder, node: Map<DataKey, Data>, common: Common): BitmapElement | null {
    const png = String(node.get("png") ?? "");
    try { return BitmapElement.create({ ...common, png, image: readBitmap(png) }); }
    catch (error) {
      b.bag.error("element", `${common.id}: ${(error as Error).message}`, b.doc.span(node, "png"));
      return null;
    }
  }

  override resolve(r: Resolver, element: BitmapElement, parent: Box, depth: number): Placed {
    const [cx, cy] = r.point(element.at, parent);
    const { width, height } = element.image;
    const x = roundPx(cx - width / 2), y = roundPx(cy - height / 2);
    return Placed.create({ element, box: new IntBox(x, y, width, height), center: [roundPx(cx), roundPx(cy)], depth });
  }

  override lower(_ctx: DrawContext, placed: Placed): Op[] {
    const element = placed.element as BitmapElement;
    const prefix = constPrefix(placed.id);
    return [BitmapDraw(element.resourceId, element.image, Const(`${prefix}_X`, placed.box.x), Const(`${prefix}_Y`, placed.box.y))];
  }

  override layoutConstants(prefix: string, placed: Placed): [string, number, string][] {
    return [[`${prefix}_X`, placed.box.x, ""], [`${prefix}_Y`, placed.box.y, ""]];
  }
}

register(new ImageKind());
