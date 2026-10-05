// The part of opentype.js (which ships no types) this package uses.
declare module "opentype.js" {
  interface Font {
    tables: Record<string, unknown>;
  }
  const opentype: { parse(buffer: ArrayBuffer): Font };
  export default opentype;
}
