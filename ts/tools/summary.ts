// A face's editor summary, the library and the editor's vocabulary, as the
// worker answers them, for the front end's tests (`tests/test_studio_*.py`):
//   node tools/summary.ts [STEPS] < face.yaml
// STEPS is JSON, a list of changes made first: `{"edit": op}` or `{"text": t}`.
import { readFileSync } from "node:fs";
import { DeviceDatabase } from "../src/devices/device.ts";
import { NodeDeviceFiles } from "../src/devices/node.ts";
import { ICON_FONT } from "../src/emit/resources.ts";
import { NodeFontFiles } from "../src/fonts/node.ts";
import { installAssets, readFontFile } from "../src/node.ts";
import { bundle } from "../src/studio/bundle.ts";
import { Studio } from "../src/studio/document.ts";
import { vocabulary } from "../src/studio/inspect.ts";
import { plain } from "../src/studio/json.ts";
import { MemoryBackend, Store } from "../src/studio/store.ts";

installAssets();
const db = new DeviceDatabase(NodeDeviceFiles.discover(), new NodeFontFiles());
const studio = new Studio(await Store.open(new MemoryBackend()), db, () => readFontFile(ICON_FONT));
const doc = studio.create(bundle("T", readFileSync(0, "utf8")), "new");
for (const step of JSON.parse(process.argv[2] ?? "[]") as { edit?: Record<string, unknown>; text?: string }[]) {
  if (step.edit) doc.edit(step.edit, doc.version);
  if (step.text !== undefined) doc.replaceText(step.text, doc.version);
}
process.stdout.write(JSON.stringify(plain({ summary: doc.summary(), documents: studio.store.documents(), vocabulary: vocabulary() })));
