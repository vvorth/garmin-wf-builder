// The Node releases wfb runs on: each line's first patched release, and
// nothing before it, whichever digit carries the difference.
import assert from "node:assert/strict";
import { test } from "node:test";
import { nodeRefusal, patchedNodeList } from "../src/node_version.ts";

test("each supported line runs from its patched release on, and not one patch before", () => {
  for (const version of ["22.23.4", "22.23.10", "22.24.0", "24.22.1", "24.22.2", "24.30.0", "26.12.1", "26.13.0", "27.0.0", "30.1.2"]) {
    assert.equal(nodeRefusal(version), null, version);
  }
  for (const [version, fixed] of [["22.23.3", "22.23.4"], ["22.22.0", "22.23.4"], ["24.22.0", "24.22.1"], ["24.21.9", "24.22.1"],
    ["26.12.0", "26.12.1"], ["26.11.5", "26.12.1"]] as const) {
    assert.equal(nodeRefusal(version),
      `Node ${version} has known security vulnerabilities, fixed in ${fixed}; wfb needs Node 22.23.4+, 24.22.1+ or 26.12.1+ (a later major also works)`);
  }
});

test("a line with no patched release is refused outright", () => {
  for (const version of ["20.20.2", "23.11.1", "25.9.0", "18.0.0"]) {
    assert.match(nodeRefusal(version)!, new RegExp(`^Node ${version.replaceAll(".", "\\.")} is not a supported release line;`), version);
  }
});

test("the list an author reads", () => {
  assert.equal(patchedNodeList(), "22.23.4+, 24.22.1+ or 26.12.1+");
});
