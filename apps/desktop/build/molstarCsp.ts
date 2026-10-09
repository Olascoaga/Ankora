import type { Plugin } from "vite";

/** Mol* UI binding descriptions use ${triggers}, not executable expressions.
 * Values are substituted once: a value containing ${...} stays literal.
 */
export function interpolateText(str: string, params: Record<string, unknown>): string {
  return str.replace(/\$\{([^}]*)\}/g, (_match, key: string) => {
    if (!/^[A-Za-z_$][\w$]*$/.test(key) || !Object.hasOwn(params, key)) {
      throw new Error(`Unsupported Mol* text placeholder: ${key}`);
    }
    return String(params[key]);
  });
}

export const upstreamInterpolation = [
  "export function interpolate(str, params) {",
  "    const names = Object.keys(params);",
  "    const values = Object.values(params);",
  "    return new Function(...names, `return \\`${str}\\`;`)(...values);",
  "}",
].join("\n");

export const upstreamMp4Import = "import { Mp4Export } from '../../extensions/mp4-export/index.js';";
export const upstreamMp4Registration = "    'mp4-export': PluginSpec.Behavior(Mp4Export),";

export function molstarCsp(): Plugin {
  return {
    name: "ankora-molstar-csp",
    enforce: "pre",
    transform(source, id) {
      const path = id.replaceAll("\\", "/");
      // Runtime disabledExtensions is too late: the codec executes new Function
      // during import. Omit this optional video feature at build time. Ankora's
      // scientific/PDB and SVG/PNG/TIFF/PDF exports do not use the MP4 extension.
      if (path.endsWith("/molstar/lib/apps/viewer/extensions.js")) {
        if (!source.includes(upstreamMp4Import) || !source.includes(upstreamMp4Registration)) {
          throw new Error("Mol* extensions changed; review the CSP compatibility adapter before building.");
        }
        return { code: source.replace(upstreamMp4Import, "").replace(upstreamMp4Registration, ""), map: null };
      }
      if (!path.endsWith("/molstar/lib/mol-util/string.js")) return null;
      const normalized = source.replaceAll("\r\n", "\n");
      if (!normalized.includes(upstreamInterpolation)) {
        throw new Error("Mol* interpolation changed; review the CSP compatibility adapter before building.");
      }
      return {
        code: normalized.replace(upstreamInterpolation,
          `export const interpolate = ${interpolateText.toString()};`),
        map: null,
      };
    },
  };
}
