// This tab, as its requests name it (`X-Wfb-Tab`): the server's
// `changed` event names the tab that made the change, so a tab can skip
// its own, whose face it has from the answer.
export const TAB = (globalThis.crypto && crypto.randomUUID)
  ? crypto.randomUUID() : String(Math.random()).slice(2);

// What the page does when the server no longer knows this browser (a 401:
// the session cookie was cleared, or expired). Reloading starts a new
// session, but one that does not own the open face, so anything not yet
// saved could no longer be saved: with unsaved work the page says so and
// waits for the author instead.

// "banner" when there is unsaved work; else "reload", unless the page
// reloaded for this within the last ten seconds (a browser that refuses
// cookies would loop), when "nothing".
export function onLost({ unsaved, lastReload, now }) {
  if (unsaved) return "banner";
  return now - lastReload > 10000 ? "reload" : "nothing";
}

// The open editor's view of things: whether it has unsaved work, and how
// it shows the banner. With no editor open, there is nothing to lose.
let editor = { unsaved: () => false, show: () => {} };

export function watch(unsaved, show) {
  const mine = { unsaved, show };
  editor = mine;
  return () => { if (editor === mine) editor = { unsaved: () => false, show: () => {} }; };
}

// Act on a 401.
export function sessionLost() {
  let lastReload = 0;
  try { lastReload = Number(sessionStorage.getItem("wfb-reloaded")) || 0; } catch (_) { /* private mode */ }
  const action = onLost({ unsaved: editor.unsaved(), lastReload, now: Date.now() });
  if (action === "banner") editor.show();
  else if (action === "reload") {
    try { sessionStorage.setItem("wfb-reloaded", String(Date.now())); } catch (_) { /* private mode */ }
    location.reload();
  }
}
