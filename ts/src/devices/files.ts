// Where a device's files come from. The compiler reads them synchronously,
// in Node from the SDK's device folders
// (`./node.ts`), in the browser from a store the editor fills from the
// server before it compiles (`MemoryDeviceFiles`).

/** The files of the installed devices, and the SDK's device reference. */
export interface DeviceFiles {
  /** Every device with a `compiler.json`, sorted. */
  ids(): string[];
  /** A file in the device's folder (`compiler.json`, `<id>.api.debug.xml`, the skin), or `undefined`. */
  file(id: string, name: string): Uint8Array | undefined;
  /** The device's page of the SDK device reference (`.cache/device-reference/devices/<id>.json`), or `undefined`. */
  reference(id: string): unknown;
  /** Every device the reference has a page for, installed or not. */
  referenceIds(): string[];
}

const decoder = new TextDecoder();

/** A device file parsed as JSON, or `undefined` when it is absent. */
export function readJson(files: DeviceFiles, id: string, name: string): unknown {
  const bytes = files.file(id, name);
  return bytes === undefined ? undefined : JSON.parse(decoder.decode(bytes));
}

/** Device files held in memory: what the browser fills from the server, and what tests build. */
export class MemoryDeviceFiles implements DeviceFiles {
  private readonly devices = new Map<string, Map<string, Uint8Array>>();
  private readonly references = new Map<string, unknown>();

  add(id: string, name: string, content: Uint8Array | string): void {
    let folder = this.devices.get(id);
    if (folder === undefined) {
      folder = new Map();
      this.devices.set(id, folder);
    }
    folder.set(name, typeof content === "string" ? new TextEncoder().encode(content) : content);
  }

  addReference(id: string, page: unknown): void {
    this.references.set(id, page);
  }

  ids(): string[] {
    return [...this.devices].filter(([, folder]) => folder.has("compiler.json")).map(([id]) => id).sort();
  }

  file(id: string, name: string): Uint8Array | undefined {
    return this.devices.get(id)?.get(name);
  }

  reference(id: string): unknown {
    return this.references.get(id);
  }

  referenceIds(): string[] {
    return [...this.references.keys()].sort();
  }
}
