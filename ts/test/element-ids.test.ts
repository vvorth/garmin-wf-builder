import assert from "node:assert/strict";
import { test } from "node:test";
import { childElementId, elementIdOfPath, elementName, layoutIds, parentElementId, STATIC_GROUP_ID } from "../src/element_ids.ts";

test("an id is the key qualified by its groups, and the name is the key", () => {
  assert.equal(childElementId(null, "clock"), "clock");
  assert.equal(childElementId("top", "label"), "top.label");
  assert.equal(childElementId("top.row", "label"), "top.row.label");
  assert.equal(elementName("top.row.label"), "label");
  assert.equal(elementName("clock"), "clock");
  assert.equal(parentElementId("top.row.label"), "top.row");
  assert.equal(parentElementId("clock"), null);
});

test("the id of a YAML path agrees with the compiler's, synthetic groups included", () => {
  assert.equal(elementIdOfPath(["elements", "clock"]), "clock");
  assert.equal(elementIdOfPath(["elements", "top", "children", "label"]), "top.label");
  assert.equal(elementIdOfPath(["elements", "a", "children", "b", "children", "c"]), "a.b.c");
  assert.equal(elementIdOfPath(["static", "ticks"]), childElementId(STATIC_GROUP_ID, "ticks"));
  assert.equal(elementIdOfPath(["static", "dial", "children", "ticks"]), "static.dial.ticks");
  const [staticId, elementsId] = layoutIds("roman");
  assert.equal(elementIdOfPath(["layouts", "roman", "elements", "hour"]), `${elementsId}.hour`);
  assert.equal(elementIdOfPath(["layouts", "roman", "static", "rim"]), `${staticId}.rim`);
  assert.equal(elementIdOfPath(["layouts", "roman", "elements", "g", "children", "x"]), `${elementsId}.g.x`);
});

test("a path that is not an element's gives null", () => {
  assert.equal(elementIdOfPath(["elements"]), null);
  assert.equal(elementIdOfPath(["elements", "top", "children"]), null);
  assert.equal(elementIdOfPath(["elements", "top", "color"]), null);
  assert.equal(elementIdOfPath(["elements", "hands", "parts", "hour"]), null);
  assert.equal(elementIdOfPath(["layouts", "roman", "lint"]), null);
  assert.equal(elementIdOfPath(["layouts", "roman"]), null);
  assert.equal(elementIdOfPath(["resources", "fonts", "x"]), null);
});
