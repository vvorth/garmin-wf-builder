// The editor's requests to its server: JSON in and out, each naming this
// tab (`X-Wfb-Tab`), a refusal thrown as an Error carrying its status.

import { TAB, sessionLost } from "./session.js";

export async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...options.headers, "X-Wfb-Tab": TAB } });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : null;
  // the session cookie is gone (cleared, or expired): `session.js`
  if (response.status === 401) sessionLost();
  if (!response.ok) {
    const error = new Error((body && body.error) || `${response.status} ${response.statusText}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

export const enc = encodeURIComponent;
