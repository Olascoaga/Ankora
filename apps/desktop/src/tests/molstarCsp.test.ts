// @vitest-environment node
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { describe, expect, it } from "vitest";
import { interpolateText, molstarCsp, upstreamInterpolation } from "../../build/molstarCsp";
import viteConfig from "../../vite.config";

describe("Mol* CSP-compatible UI text", () => {
  it("prebundles Mol*'s deep CommonJS dependency without bypassing its CSP transform", () => {
    const require = createRequire(import.meta.url);
    const source = readFileSync(require.resolve("molstar/lib/mol-util/produce.js"), "utf8");
    expect(source).toContain("import { create } from 'mutative/dist/index.js'");
    expect(viteConfig.optimizeDeps?.exclude).toContain("molstar");
    expect(viteConfig.optimizeDeps?.include).toContain("molstar > mutative/dist/index.js");
    expect(viteConfig.optimizeDeps?.include).toContain("molstar > react-markdown");
  });

  it("substitutes repeated named parameters without evaluating JavaScript", () => {
    expect(interpolateText("Click ${triggers}; again ${triggers}", { triggers: "<i>left button</i>" }))
      .toBe("Click <i>left button</i>; again <i>left button</i>");
    expect(interpolateText("No template ` or \\ or newline\n", {})).toBe("No template ` or \\ or newline\n");
    expect(interpolateText("${triggers}", { triggers: "${globalThis.evil()}" })).toBe("${globalThis.evil()}");
    expect(() => interpolateText("${globalThis.evil()}", {})).toThrow("Unsupported");
    expect(() => interpolateText("${toString}", {})).toThrow("Unsupported");
  });

  it.each(["", "?v=development-cache"])("recognizes the dependency and fails closed on an upgrade (%s)", (query) => {
    const require = createRequire(import.meta.url);
    const file = require.resolve("molstar/lib/mol-util/string.js");
    const id = file + query;
    const source = readFileSync(file, "utf8");
    expect(source.replaceAll("\r\n", "\n")).toContain(upstreamInterpolation);
    const transform = molstarCsp().transform as (source: string, id: string) => { code: string } | null;
    const result = transform(source, id)!;
    expect(result.code).not.toContain("new Function");
    expect(result.code).toContain("export const interpolate");
    expect(() => transform("changed upstream", id)).toThrow("review");
    expect(transform(source, "/another/string.js")).toBeNull();
  });

  it("keeps the packaged CSP restrictive", () => {
    const config = JSON.parse(readFileSync(new URL("../../src-tauri/tauri.conf.json", import.meta.url), "utf8"));
    expect(config.app.security.csp).not.toContain("unsafe-eval");
    expect(config.app.security.csp).toContain("default-src 'self'");
  });

  it.each(["", "?v=development-cache"])("excludes only the optional MP4 extension before evaluation (%s)", (query) => {
    const require = createRequire(import.meta.url);
    const file = require.resolve("molstar/lib/apps/viewer/extensions.js");
    const id = file + query;
    const source = readFileSync(file, "utf8");
    const transform = molstarCsp().transform as (source: string, id: string) => { code: string };
    const result = transform(source, id);
    expect(result.code).not.toContain("Mp4Export");
    expect(result.code).not.toContain("mp4-export");
    expect(result.code).toContain("'model-export': PluginSpec.Behavior(ModelExport)");
    expect(result.code).toContain("'geo-export': PluginSpec.Behavior(GeometryExport)");
    expect(() => transform("changed upstream", id)).toThrow("review");
  });
});
