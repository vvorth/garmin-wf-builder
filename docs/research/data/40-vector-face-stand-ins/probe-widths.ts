// The metrics probe's width readings (research 10 §9) against the project's own
// measurement, for the fenix 8 FONT_NUMBER_* symbols (Bionic_semibold), with
// each stand-in named in SOURCES (comma-separated registry keys) put behind
// that name. Run from the repository root:
//   WFB_NO_GARMIN_FONTS=1 SOURCES=rajdhani-semibold,roboto-condensed-bold node docs/research/data/40-vector-face-stand-ins/probe-widths.ts
// (the keys installed, e.g. by `ts/tools/fetch-system-fonts.ts --registry`).
import { readFileSync } from "node:fs";
import { DeviceDatabase } from "../../../../ts/src/devices/device.ts";
import { NodeDeviceFiles } from "../../../../ts/src/devices/node.ts";
import { NodeFontFiles } from "../../../../ts/src/fonts/node.ts";
import { REGISTRY } from "../../../../ts/src/fonts/files.ts";
const rows = readFileSync("docs/research/probes/system-font-metrics/results-2026-09-18.txt", "utf8").split("\n").filter((l) => l && !l.startsWith("#")).map((l) => l.split(" "));
const sources = (process.env["SOURCES"] ?? "").split(",");
for (const src of sources) {
  if (src) (REGISTRY.names as any)["Bionic_semibold"] = src; // another stand-in for the same name
  const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());
  let exact = 0, total = 0, n = 0; const lines: string[] = [];
  for (const [dev, sym, , , , w1, w2] of rows) {
    const d = db.get(dev!); const m = d.systemFonts.get(sym!);
    if (!m || !/bionic/i.test(m.font)) continue;
    const face = db.measure.systemFace(m)!;
    for (const [text, want] of [["Hxg0123", Number(w1)], ["0123456789", Number(w2)]] as const) {
      const got = Math.round(face.width(text)); n++; if (got === want) exact++; total += Math.abs(got - want);
      lines.push(`${dev} ${sym} ${text} device=${want} measured=${got}`);
    }
  }
  console.log(`${src || "registry as is"}: ${exact}/${n} exact, total error ${total} px`);
  if (process.env["VERBOSE"]) console.log(lines.join("\n"));
}
