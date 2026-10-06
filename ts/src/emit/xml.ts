// The resource files' shared XML preamble pieces.
export const XSD = "https://developer.garmin.com/downloads/connect-iq/resources.xsd";
export const XMLNS = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"';

/** `xml.sax.saxutils.escape`: `&`, `<`, `>`, then any extra entities. */
export function escape(text: string, entities: Record<string, string> = {}): string {
  let out = text.replaceAll("&", "&amp;").replaceAll(">", "&gt;").replaceAll("<", "&lt;");
  for (const [k, v] of Object.entries(entities)) out = out.replaceAll(k, v);
  return out;
}
