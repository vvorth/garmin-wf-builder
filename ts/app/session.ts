// This tab, as its requests name it: the worker's `changed` event names the
// tab that made the change, so a tab can skip its own, whose face it has
// from the answer.
export const TAB: string = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
  ? crypto.randomUUID() : String(Math.random()).slice(2);
