// A page opened over plain HTTP at a LAN address has no crypto.randomUUID.
import assert from "node:assert/strict";
import { test } from "node:test";
import { uuid } from "../src/uuid.ts";

test("a v4 UUID without crypto.randomUUID, as in an insecure context", () => {
  const original = crypto.randomUUID;
  Object.defineProperty(crypto, "randomUUID", { value: undefined, configurable: true });
  try {
    const ids = new Set(Array.from({ length: 100 }, uuid));
    assert.equal(ids.size, 100);
    for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  } finally {
    Object.defineProperty(crypto, "randomUUID", { value: original, configurable: true });
  }
});
