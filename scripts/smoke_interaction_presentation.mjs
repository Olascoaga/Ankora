/** Read-only production/development UI regression; no scientific tool is started.
 * Default: SYNTHETIC presentation fixture with 30 hydrophobic contacts plus
 * donor/acceptor on one residue. Not a detector/affinity benchmark.
 * Optional: --analysis FILE --receptor FILE --pose FILE replays a saved analysis
 * and its hash-verified inputs without modifying them or recomputing contacts.
 * Run after npm run build, or use --development for the actual Vite configuration
 * with a new isolated optimizer cache. --cdp attaches only to an explicitly
 * launched localhost installed WebView; it never enables debugging in shipping
 * configuration. Otherwise uses the pinned Playwright browser.
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import ts from "typescript";

const root = fileURLToPath(new URL("../", import.meta.url));
const development = process.argv.includes("--development");
const cdpIndex = process.argv.indexOf("--cdp");
const cdpEndpoint = cdpIndex >= 0 ? process.argv[cdpIndex + 1] : null;
if (cdpIndex >= 0) {
  assert(cdpEndpoint, "--cdp requires an explicit localhost endpoint");
  const endpoint = new URL(cdpEndpoint);
  assert(endpoint.protocol === "http:" && endpoint.hostname === "127.0.0.1",
    "Installed interaction smoke only attaches to a localhost WebView");
  assert(!development, "Installed WebView and development modes are separate gates");
}
// Compile the same typed, labelled fixture the component regression uses.
const fixtureSource = await readFile(resolve(root, "apps/desktop/src/tests/fixtures/interactionPresentation.ts"), "utf8");
const compiled = ts.transpileModule(fixtureSource, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const fixture = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
const argument = (name) => {
  const index = process.argv.indexOf(name);
  if (index < 0) return null;
  assert(process.argv[index + 1] && !process.argv[index + 1].startsWith("--"), `${name} needs a file`);
  return resolve(process.argv[index + 1]);
};
const paths = [argument("--analysis"), argument("--receptor"), argument("--pose")];
const real = paths.every(Boolean);
assert(real || paths.every((path) => !path), "Supply all three recorded inputs or none");
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const recordedBytes = real ? await Promise.all(paths.map((path) => readFile(path))) : null;
const record = real ? JSON.parse(recordedBytes[0]) : fixture.analysis([
  ...Array.from({ length: 30 }, (_, index) => fixture.contact(index)),
  fixture.contact(30, "HBDonor"), fixture.contact(31, "HBAcceptor"),
]);
const receptor = real ? recordedBytes[1] : await readFile(resolve(root, "backend/tests/fixtures/synthetic_m1.pdb"));
const pose = real ? recordedBytes[2] : receptor;
if (real) {
  assert.equal(hash(receptor), record.analysis_receptor_sha256);
  assert.equal(hash(pose), record.pose.sha256);
}
const entry = { ...fixture.entry, catalog_id: record.catalog_id, engine_key: record.engine_key,
  record_id: record.record_id, engine_label: record.engine_label, receptor_id: record.receptor_id,
  ligand_id: record.ligand_id, best_result_kcal_mol: record.pose.result_kcal_mol };
const molecule = { ...fixture.molecule, ligand_id: record.ligand_id,
  name: real ? "Recorded pose (read-only replay)" : fixture.molecule.name,
  best_result_kcal_mol: record.pose.result_kcal_mol };
const inventory = { ...fixture.inventory, catalog_id: record.catalog_id, engine_label: record.engine_label,
  ligand_id: record.ligand_id, receptor_artifact_id: record.analysis_receptor_artifact_id,
  receptor_content_url: record.analysis_receptor_content_url, poses: [record.pose] };
const groupKey = (item) => JSON.stringify([item.residue, item.detector_type]);
const groups = new Set(record.contacts.map(groupKey)).size;
const oldGroups = new Set(record.contacts.map((item) => JSON.stringify([item.residue,
  item.detector_type.startsWith("HB") ? "hydrogen" : item.detector_type]))).size;
const dist = resolve(root, "apps/desktop/dist");
const tauri = JSON.parse(await readFile(resolve(root, "apps/desktop/src-tauri/tauri.conf.json"), "utf8"));
// Vite's React development preamble is inline: nonce it in the test server,
// rather than allowing inline scripts or eval. Packaged policy stays unchanged.
const nonce = createHash("sha256").update(String(Date.now())).digest("base64");
const csp = `${tauri.app.security.csp}; script-src 'self'${development ? ` 'nonce-${nonce}'` : ""}`;
const output = resolve(root, "build/windows-runtime", `interaction-ui-smoke-${Date.now()}`);
await mkdir(output, { recursive: true });
let developmentPort;
if (development) {
  // Vite treats port 0 as its default; reserve an OS-assigned candidate instead.
  // strictPort then fails on a race, never reusing another development server.
  const probe = createServer();
  await new Promise((done) => probe.listen(0, "127.0.0.1", done));
  developmentPort = probe.address().port;
  await new Promise((done) => probe.close(done));
}
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".jpg": "image/jpeg" };
const server = development ? await (await import("vite")).createServer({
  root: resolve(root, "apps/desktop"),
  configFile: resolve(root, "apps/desktop/vite.config.ts"),
  configLoader: "runner",
  cacheDir: resolve(output, "vite-cache"),
  html: { cspNonce: nonce },
  server: { host: "127.0.0.1", port: developmentPort, strictPort: true, hmr: false,
    headers: { "Content-Security-Policy": csp } },
}) : createServer(async (req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, "http://127.0.0.1").pathname);
    const path = resolve(dist, `.${pathname === "/" ? "/index.html" : pathname}`);
    if (!path.startsWith(`${dist}${sep}`)) { res.writeHead(403).end(); return; }
    const bytes = await readFile(path);
    res.writeHead(200, { "Content-Type": types[extname(path)] ?? "application/octet-stream", "Content-Security-Policy": csp });
    res.end(bytes);
  } catch { res.writeHead(404).end(); }
});
if (development) await server.listen();
else await new Promise((done) => server.listen(0, "127.0.0.1", done));
const port = (server.httpServer ?? server).address().port;
const evidence = { passed: false, serving_mode: cdpEndpoint ? "installed WebView2" : development ? "development" : "production",
  isolated_cold_cache: development, synthetic: !real, analysis_id: record.analysis_id,
  source_hashes: recordedBytes?.map(hash) ?? null, contacts: record.contacts.length,
  old_hydrogen_family_groups: oldGroups, exact_subtype_groups: groups, viewports: [], errors: [], csp_violations: [] };
let browser;
try {
  browser = cdpEndpoint ? await chromium.connectOverCDP(cdpEndpoint) : await chromium.launch({ channel: process.env.ANKORA_SMOKE_BROWSER_CHANNEL || undefined,
    headless: true, args: ["--enable-unsafe-swiftshader"] });
  evidence.browser = browser.version();
  const page = cdpEndpoint
    ? browser.contexts().flatMap((context) => context.pages()).find(
      (candidate) => candidate.url().includes("tauri.localhost"),
    )
    : await browser.newPage({ viewport: { width: 1280, height: 800 } });
  assert(page, "Installed WebView application page was not found");
  page.on("pageerror", (error) => evidence.errors.push(error.stack));
  await page.exposeFunction("recordInteractionCspViolation", (value) => evidence.csp_violations.push(value));
  await page.addInitScript(() => document.addEventListener("securitypolicyviolation", (event) => {
    window.recordInteractionCspViolation({ directive: event.violatedDirective, blocked: event.blockedURI });
  }));
  await page.route("http://127.0.0.1:8765/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    assert.equal(route.request().method(), "GET", "Changing a view must not create/recalculate scientific records");
    if (path === "/health") return json({ status: "ok", backend_version: "0.1.0" });
    if (path === "/system") return json({ platform: "windows", architecture: "x86_64", python_version: "UI replay", python_environment: "read-only", app_mode: "packaged" });
    if (path === "/tools") return json({});
    if (path === "/system/resources") return json({ cpu_percent: 0, logical_cores: 1, memory_used_bytes: 0, memory_total_bytes: 1, memory_percent: 0, gpu: null });
    if (path === "/projects") return json({ active_project_id: "default", projects: [{ project_id: "default", name: "Read-only UI replay", registered_at: "", migrated_legacy: true }] });
    if (path === "/work/recovery") return json({ items: [], reconciled_at: record.created_at });
    if (path === "/receptors/latest") return json({ message: "Read-only UI replay has no active receptor" }, 404);
    if (path === "/results/campaigns") return json({ entries: [entry], total: 1, offset: 0, limit: 25 });
    if (path.endsWith("/compounds")) return json({ catalog_id: entry.catalog_id, engine_label: entry.engine_label,
      value_label: record.pose.value_label, rows: [molecule], total: 1, offset: 0, limit: 100 });
    if (path.endsWith("/poses")) return json(inventory);
    if (path.endsWith("/interactions")) return json([record]);
    if (path === record.analysis_receptor_content_url) return route.fulfill({ status: 200, contentType: "text/plain", body: receptor });
    if (path === record.pose.content_url) return route.fulfill({ status: 200, contentType: "text/plain", body: pose });
    evidence.errors.push(`Unexpected UI request: ${path}`);
    return json({ message: "Unexpected read-only replay request" }, 404);
  });
  const navigation = cdpEndpoint ? await page.reload() : await page.goto(`http://127.0.0.1:${port}/`);
  assert(navigation.headers()["content-security-policy"].includes("script-src 'self'"));
  evidence.served_csp = navigation.headers()["content-security-policy"];
  assert(!evidence.served_csp.includes("unsafe-eval"));
  const openAnalysis = async () => {
    await page.getByTestId("splash-screen").waitFor({ state: "detached", timeout: 20_000 });
    await page.getByRole("navigation", { name: "Docking workflow" }).getByRole("button", { name: /Results/ }).click();
    await page.getByRole("list", { name: "Recorded results" }).getByRole("listitem").click();
    await page.getByRole("region", { name: "Molecules in this result" }).getByText(molecule.name, { exact: true }).click();
    await page.getByRole("region", { name: "Interaction display" }).waitFor();
    await page.locator(".molstar-host canvas, .viewer-error").first().waitFor({ timeout: 30_000 });
    await page.waitForTimeout(1000); // Mol* representation tasks finish asynchronously.
    const viewerErrors = await page.locator(".viewer-error").allTextContents();
    evidence.errors.push(...viewerErrors);
    if (development && viewerErrors.length) {
      evidence.import_error_stack = await page.evaluate(async () => {
        try { await import("/src/viewer/molstarAdapter.ts"); return null; }
        catch (error) { return error.stack ?? String(error); }
      });
    }
    await page.locator(".pose-interaction-viewer").screenshot({ path: resolve(output, `viewer-${development ? "development" : "production"}.png`) });
    assert.deepEqual(viewerErrors, [], "Mol* must import and draw without dependency/CSP failures");
    assert(await page.locator(".molstar-host canvas").count() > 0);
  };
  await openAnalysis();
  if (development) {
    // A successful cold import must also survive reuse of the optimizer cache.
    await page.reload();
    await openAnalysis();
    evidence.cached_reload_passed = true;
  }
  assert.equal(await page.locator(".interaction-edge ellipse").count(), groups);
  assert.equal(await page.locator(".interaction-contact line").count(), groups);
  assert.equal(await page.locator(".interaction-table-scroll tbody tr").count(), record.contacts.length);
  for (const viewport of [{ width: 1280, height: 800 }, { width: 1536, height: 864 }, { width: 1920, height: 1080 }]) {
    await page.setViewportSize(viewport);
    const diagram = page.getByRole("img", { name: "2D pose interaction diagram" });
    await diagram.scrollIntoViewIfNeeded();
    const fits = await diagram.evaluate((svg) => {
      const frame = svg.viewBox.baseVal;
      return [...svg.querySelectorAll(".interaction-figure-caption text, .interaction-edge ellipse, .interaction-figure-legend")].every((item) => {
        const box = item.getBBox();
        return box.x >= frame.x && box.y >= frame.y && box.x + box.width <= frame.width && box.y + box.height <= frame.height;
      });
    });
    assert(fits, "Caption, nodes and legend must fit the saved SVG frame");
    assert(await page.locator(".results-interaction-workspace").evaluate((element) => element.scrollWidth <= element.clientWidth + 1));
    await diagram.screenshot({ path: resolve(output, `diagram-${viewport.width}.png`) });
    const save = page.locator(".pose-interaction-evidence .figure-export-size").getByRole("button", { name: "Save figure" });
    await save.scrollIntoViewIfNeeded();
    assert(await save.isVisible());
    evidence.viewports.push({ ...viewport, diagram_fits: fits, saving_reachable: true });
  }
  await page.getByRole("button", { name: "All atom contacts", exact: true }).click();
  assert.equal(await page.locator(".interaction-contact line").count(), record.contacts.length);
  assert.equal(await page.locator(".interaction-table-scroll tbody tr").count(), record.contacts.length);
  if (record.contacts.length) {
    const subtype = record.contacts.find((item) => item.detector_type === "HBAcceptor")?.detector_type ?? record.contacts[0].detector_type;
    await page.getByRole("combobox", { name: "Interaction type" }).selectOption(subtype);
    const filtered = record.contacts.filter((item) => item.detector_type === subtype);
    assert.equal(await page.locator(".interaction-contact line").count(), filtered.length);
    assert.equal(await page.locator(".interaction-table-scroll tbody tr").count(), filtered.length);
    await page.getByRole("combobox", { name: "Interaction type" }).selectOption("");
    assert.equal(await page.locator(".interaction-contact line").count(), record.contacts.length);
  }
  if (real) assert.deepEqual((await Promise.all(paths.map((path) => readFile(path)))).map(hash), evidence.source_hashes);
  assert.deepEqual(evidence.errors, []);
  assert.deepEqual(evidence.csp_violations, []);
  evidence.passed = true;
  console.log(`Interaction UI: ${record.contacts.length} contacts retained, ${groups} exact subtype groups; all viewports passed.`);
} finally {
  await writeFile(resolve(output, "evidence.json"), JSON.stringify(evidence, null, 2));
  console.log(`Evidence: ${output}`);
  await browser?.close();
  if (development) await server.close();
  else await new Promise((done) => server.close(done));
}
