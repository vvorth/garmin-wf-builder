// The phone settings: on a device that edits `config:` with the generated
// settings menu, Garmin Connect edits the same stored choices for a Store
// install, through that device's own `settings.xml` over its own
// `properties.xml`, whose every string is in the shared `strings.xml`.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { REPO_ROOT } from "../src/devices/node.ts";
import { db, generated, MINIMAL } from "./designs.ts";

const CONFIG = readFileSync(join(REPO_ROOT, "examples", "features", "config", "face.yaml"), "utf8");
const HEAD = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="https://developer.garmin.com/downloads/connect-iq/resources.xsd"';

const properties = (id: string): string => `resources-${id}/settings/properties.xml`;
const settings = (id: string): string => `resources-${id}/settings/settings.xml`;
const app = (files: Map<string, string>): string => [...files].find(([name]) => name.endsWith("App.mc"))![1];
const settingsFiles = (files: Map<string, string>): string[] => [...files.keys()].filter((name) => name.includes("/settings/")).sort();

/** The `onSettingsChanged` method, from its declaration to its closing brace. */
const onSettingsChanged = (text: string): string | null => {
  const start = text.indexOf("    function onSettingsChanged()");
  return start < 0 ? null : text.slice(start, text.indexOf("\n    }\n", start) + "\n    }".length);
};

/** A design whose only `config:` is one data slot, offered on `targets`. */
const slotted = (targets: string, slot: string): string => `${MINIMAL.replace("targets: [fenix8solar47mm]", `targets: [${targets}]`)
  .replace("elements:", `config:
  slots:
    top: ${slot}
elements:`)}
  reading:
    type: data
    slot: top
    at: {anchor: center}
    font: FONT_SMALL
    color: color.fg
`;

test("examples/features/config on fr955: properties.xml defaults to the declared defaults' indices", () => {
  const files = generated(CONFIG, ["fr955"]);
  assert.equal(files.get(properties("fr955")), [
    `<properties ${HEAD}>`,
    '    <property id="config_style" type="number">0</property>',
    '    <property id="config_accent_color" type="number">3</property>',
    '    <property id="config_data_color" type="number">0</property>',
    "</properties>",
    "",
  ].join("\n"));
  assert.ok(!files.has("resources/settings/properties.xml"), "no shared properties.xml any more");
});

test("examples/features/config on fr955: settings.xml lists each axis in the menu's order", () => {
  const files = generated(CONFIG, ["fr955"]);
  assert.equal(files.get(settings("fr955")), [
    `<settings ${HEAD}>`,
    '    <setting propertyKey="@Properties.config_style" title="@Strings.ConfigTitleStyle">',
    '        <settingConfig type="list">',
    '            <listEntry value="0">@Strings.ConfigStyle0</listEntry>',
    '            <listEntry value="1">@Strings.ConfigStyle1</listEntry>',
    "        </settingConfig>",
    "    </setting>",
    '    <setting propertyKey="@Properties.config_accent_color" title="@Strings.ConfigTitleAccentColor">',
    '        <settingConfig type="list">',
    // `choices: any`: the 37 recommended MIP colours
    ...Array.from({ length: 37 }, (_, i) => `            <listEntry value="${i}">@Strings.ConfigAccentColor${i}</listEntry>`),
    "        </settingConfig>",
    "    </setting>",
    '    <setting propertyKey="@Properties.config_data_color" title="@Strings.ConfigTitleDataColor">',
    '        <settingConfig type="list">',
    '            <listEntry value="0">@Strings.ConfigDataColor0</listEntry>',
    '            <listEntry value="1">@Strings.ConfigDataColor1</listEntry>',
    '            <listEntry value="2">@Strings.ConfigDataColor2</listEntry>',
    "        </settingConfig>",
    "    </setting>",
    "</settings>",
    "",
  ].join("\n"));
  const strings = files.get("resources/strings/strings.xml")!;
  for (const line of ['<string id="ConfigTitleStyle">Style</string>', '<string id="ConfigTitleAccentColor">Accent colour</string>',
    '<string id="ConfigTitleDataColor">Data colour</string>', '<string id="ConfigStyle0">Dark</string>',
    '<string id="ConfigAccentColor3">International Orange</string>', '<string id="ConfigDataColor2">Amber</string>']) {
    assert.ok(strings.includes(`    ${line}\n`), line);
  }
});

test("a native-editor device gets no phone settings, and a build of only those is unchanged", () => {
  const mixed = generated(CONFIG);
  assert.deepEqual(settingsFiles(mixed), [properties("fr955"), settings("fr955")]);
  const native = generated(CONFIG, ["fenix8solar47mm", "fenix8solar51mm"]);
  assert.deepEqual(settingsFiles(native), []);
  assert.ok(native.has("resources-fenix8solar47mm/configs/watchface.xml"));
  assert.doesNotMatch(native.get("resources/strings/strings.xml")!, /ConfigTitle|ConfigType/);
  assert.equal(onSettingsChanged(app(native)), null);
});

test("where a slot's options differ per device, so do its list and its default", { skip: !db.ids().includes("instinct3solar45mm") }, () => {
  // sleep_score is API 6.0.2: offered last on instinct3solar45mm, and put
  // first on fr955 (5.2.0), where `choices: any` does not otherwise offer it
  const files = generated(slotted("fr955, instinct3solar45mm", "{ default: sleep_score, choices: any }"));
  const entries = (id: string): string[] => [...files.get(settings(id))!.matchAll(/@Strings\.(ConfigType\w+)/g)].map((m) => m[1]!);
  const fr955 = entries("fr955"), instinct = entries("instinct3solar45mm");
  assert.equal(fr955[0], "ConfigTypeSleepScore");
  assert.equal(instinct.at(-1), "ConfigTypeSleepScore");
  assert.deepEqual([...fr955.slice(1)], instinct.slice(0, -1));
  assert.ok(files.get(properties("fr955"))!.includes('<property id="config_data_top" type="number">0</property>'));
  assert.ok(files.get(properties("instinct3solar45mm"))!.includes(`<property id="config_data_top" type="number">${instinct.length - 1}</property>`));
  // the same order and default the menu reads from Layout on each device
  for (const id of ["fr955", "instinct3solar45mm"]) {
    const layout = files.get(`source-${id}/Layout.mc`)!;
    const labels = /CONFIG_DATA_TOP_LABELS as Array<String> = \[(.*)\];/.exec(layout)![1]!.split(", ").length;
    const fallback = /CONFIG_DATA_TOP_DEFAULT as Number = (\d+);/.exec(layout)![1]!;
    assert.equal(labels, entries(id).length, id);
    assert.ok(files.get(properties(id))!.includes(`type="number">${fallback}</property>`), id);
  }
  // one shared label per type, the union over both devices
  const strings = files.get("resources/strings/strings.xml")!;
  assert.equal(strings.match(/<string id="ConfigTypeSleepScore">Sleep score<\/string>/g)?.length, 1);
  assert.equal(strings.match(/<string id="ConfigTypeSteps">Steps<\/string>/g)?.length, 1);
});

test("a slot with no options on a device (no Toybox.Complications) is not offered there, its property kept", { skip: !db.ids().includes("fenix6") }, () => {
  const files = generated(slotted("fenix6", "{ default: steps, choices: [steps, calories] }"));
  assert.equal(files.get(properties("fenix6")), `<properties ${HEAD}>\n    <property id="config_data_top" type="number">-1</property>\n</properties>\n`);
  assert.ok(!files.has(settings("fenix6")), "nothing to offer, so no settings.xml");
});

test("onSettingsChanged: only with a settings-menu device, guarded only beside a native-editor one", () => {
  const body = [
    "            var view = _view;",
    "            if (view != null) {",
    "                view.applyStoredConfig();",
    "                WatchUi.requestUpdate();",
    "            }",
  ];
  assert.equal(onSettingsChanged(app(generated(CONFIG))), [
    "    function onSettingsChanged() as Void {",
    "        if (!(Application has :WatchFaceConfig)) {",
    ...body,
    "        }",
    "    }",
  ].join("\n"));
  assert.equal(onSettingsChanged(app(generated(CONFIG, ["fr955"]))), [
    "    function onSettingsChanged() as Void {",
    ...body.map((line) => line.slice(4)),
    "    }",
  ].join("\n"));
  assert.equal(onSettingsChanged(app(generated(CONFIG, ["fenix8solar47mm"]))), null);
  assert.equal(onSettingsChanged(app(generated(MINIMAL.replace("[fenix8solar47mm]", "[fr955]")))), null);
});

test("every @Strings and @Properties reference resolves to an emitted id", () => {
  const designs = [generated(CONFIG), generated(readFileSync(join(REPO_ROOT, "examples", "features", "slots", "face.yaml"), "utf8"))];
  if (db.ids().includes("instinct3solar45mm")) designs.push(generated(slotted("fr955, instinct3solar45mm", "{ default: steps, choices: any }")));
  for (const files of designs) {
    const strings = [...files.get("resources/strings/strings.xml")!.matchAll(/<string id="(\w+)">/g)].map((m) => m[1]!);
    assert.equal(new Set(strings).size, strings.length, "each string id once");
    const devices = settingsFiles(files).filter((n) => n.endsWith("settings.xml")).map((n) => n.split("/")[0]!);
    assert.ok(devices.length > 0);
    for (const directory of devices) {
      const settingsText = files.get(`${directory}/settings/settings.xml`)!;
      const keys = [...files.get(`${directory}/settings/properties.xml`)!.matchAll(/<property id="(\w+)" type="number">-?\d+<\/property>/g)].map((m) => m[1]!);
      const named = [...settingsText.matchAll(/@Strings\.(\w+)/g)].map((m) => m[1]!);
      const referenced = [...settingsText.matchAll(/@Properties\.(\w+)/g)].map((m) => m[1]!);
      assert.ok(named.length > 0 && referenced.length > 0);
      for (const id of named) assert.ok(strings.includes(id), `${directory}: @Strings.${id}`);
      for (const key of referenced) assert.ok(keys.includes(key), `${directory}: @Properties.${key}`);
      // a list entry's value is the index the menu stores, in range of its property's options
      for (const [, list] of settingsText.matchAll(/<settingConfig type="list">\n([\s\S]*?)\n {8}<\/settingConfig>/g)) {
        const values = [...list!.matchAll(/value="(\d+)"/g)].map((m) => Number(m[1]));
        assert.deepEqual(values, values.map((_, i) => i));
      }
    }
  }
});

test("a face without config: emits no phone settings", () => {
  const files = generated(MINIMAL.replace("[fenix8solar47mm]", "[fr955, fenix8solar47mm]"));
  assert.deepEqual(settingsFiles(files), []);
  assert.equal(files.get("resources/strings/strings.xml"), `<strings ${HEAD}>\n    <string id="AppName">Test</string>\n</strings>\n`);
  assert.equal(onSettingsChanged(app(files)), null);
});
