// `type: group`: draws nothing itself; a positioning box for its children.
// Port of wfb/kinds/group.py's build half.
import type { Builder } from "../ir/builder/index.ts";
import { type Element, Group } from "../ir/model.ts";
import { staticGroupMethod } from "../ir/naming.ts";
import { type Common, ElementKind, register, type SchemaPath } from "./base.ts";
import type { Data, DataKey } from "../edit/yaml.ts";

class GroupKind extends ElementKind<Group> {
  readonly name = "group";
  readonly irClass = Group;
  override readonly extraSymbols = [staticGroupMethod];

  build(b: Builder, node: Map<DataKey, Data>, common: Common, path: SchemaPath): Element {
    const [align, verticalAlign] = b.alignment(node);
    const size = b.size(node.get("size"));
    const items = b.buildElements(node.get("children") as Data[], [...path, "children"]);
    const group = Group.create({ ...common, size, items, align, vertical_align: verticalAlign });
    b.pushVisible(group);
    return group;
  }
}

register(new GroupKind());
