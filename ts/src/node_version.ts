// The Node releases wfb runs on. Earlier releases of each line carry known
// security vulnerabilities, fixed in Node's October 2026 security releases;
// `tools/setup-env.sh`, `ts/package.json`'s `engines`, the Dockerfile and the
// CI workflows hold the same minimums.

/** Each supported release line's lowest patched version. A later major is allowed as it comes. */
export const PATCHED_NODE: readonly (readonly [number, number, number])[] = [[22, 23, 4], [24, 22, 1], [26, 12, 1]];

const NEWEST_LISTED = PATCHED_NODE[PATCHED_NODE.length - 1]![0];

/** The minimums as an author reads them: "22.23.4+, 24.22.1+ or 26.12.1+". */
export function patchedNodeList(): string {
  const each = PATCHED_NODE.map((v) => `${v.join(".")}+`);
  return `${each.slice(0, -1).join(", ")} or ${each[each.length - 1]!}`;
}

/** Why Node `version` ("24.21.0") may not run wfb, or null when it may. */
export function nodeRefusal(version: string): string | null {
  const [major = 0, minor = 0, patch = 0] = version.split(".").map((n) => Number.parseInt(n, 10));
  if (major > NEWEST_LISTED) return null;
  const line = PATCHED_NODE.find(([m]) => m === major);
  const wanted = `wfb needs Node ${patchedNodeList()} (a later major also works)`;
  if (line === undefined) return `Node ${version} is not a supported release line; ${wanted}`;
  const [, minMinor, minPatch] = line;
  if (minor > minMinor || (minor === minMinor && patch >= minPatch)) return null;
  return `Node ${version} has known security vulnerabilities, fixed in ${line.join(".")}; ${wanted}`;
}
