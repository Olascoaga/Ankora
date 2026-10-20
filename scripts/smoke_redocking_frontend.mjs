/** Production UI regression: SYNTHETIC API replies only, never scientific data
 * or engine execution. Run after npm run build; optionally select msedge with
 * ANKORA_SMOKE_BROWSER_CHANNEL. Uses an ephemeral loopback static server.
 */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = fileURLToPath(new URL("../", import.meta.url));
const dist = resolve(root, "apps/desktop/dist");
const output = resolve(root, "build/windows-runtime", `redocking-ui-${Date.now()}`);
await mkdir(output, { recursive: true });
const tauri = JSON.parse(await readFile(resolve(root, "apps/desktop/src-tauri/tauri.conf.json"), "utf8"));
const csp = `${tauri.app.security.csp}; script-src 'self'`;
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://127.0.0.1");
    const path = resolve(dist, `.${url.pathname === "/" ? "/index.html" : decodeURIComponent(url.pathname)}`);
    assert(path.startsWith(`${dist}${sep}`));
    const bytes = await readFile(path);
    response.writeHead(200, { "Content-Type": types[extname(path)] ?? "application/octet-stream", "Content-Security-Policy": csp });
    response.end(bytes);
  } catch { response.writeHead(404).end(); }
});
await new Promise((ready) => server.listen(0, "127.0.0.1", ready));
const kinds = ["vina_job", "autodock4_job", "autodock_gpu_job"];
const entries = kinds.map((kind) => ({ catalog_id: `${kind}:synthetic-job`, engine_key: kind,
  record_id: "synthetic-job", mode: "single_ligand", status: "completed",
  engine_label: `Synthetic ${kind}`, best_molecule: "Synthetic ligand", created_at: "2026-10-20T12:00:00Z" }));
const runs = [];
const posts = [];
const tools = Object.fromEntries(["vina", "gnina", "autogrid4", "autodock4", "autodock_gpu",
  "pdbfixer", "pdb2pqr", "propka", "meeko", "meeko_ligand", "p2rank"].map(
  (name) => [name, { available: false, path: null, version: null }],
));
const evidence = { synthetic: true, passed: false, csp, viewports: [], errors: [], cspViolations: [] };
let browser;
try {
  browser = await chromium.launch({ headless: true, channel: process.env.ANKORA_SMOKE_BROWSER_CHANNEL || undefined });
  evidence.browser = browser.version();
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.setDefaultTimeout(15000);
  page.on("pageerror", (error) => evidence.errors.push(error.message));
  await page.exposeFunction("recordCsp", (data) => evidence.cspViolations.push(data));
  await page.addInitScript(() => document.addEventListener("securitypolicyviolation", (event) => {
    window.recordCsp({ directive: event.violatedDirective, blocked: event.blockedURI });
  }));
  await page.route("http://127.0.0.1:8765/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const json = (body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/health") return json({ status: "ok", backend_version: "0.1.0" });
    if (path === "/system") return json({ platform: "windows", architecture: "x86_64", python_version: "synthetic", app_mode: "development" });
    if (path === "/tools") return json(tools);
    if (path === "/system/resources") return json({ cpu_percent: 0, logical_cores: 1, memory_used_bytes: 0, memory_total_bytes: 1, memory_percent: 0, gpu: null });
    if (path === "/projects") return json({ active_project_id: "default", projects: [{ project_id: "default", name: "Synthetic UI test", registered_at: "", migrated_legacy: true }] });
    if (path === "/work/recovery") return json({ items: [] });
    if (path === "/receptors/latest") return json({ message: "No receptor: synthetic empty session" }, 404);
    if (path === "/results/campaigns") return json({ entries, total: 3, offset: 0, limit: 25 });
    if (path === "/validation/redocking/references") return json({
      references: [{ ligand_id: "synthetic-crystal", name: "Synthetic crystal", heavy_atom_count: 1,
        locator: { component_name: "TST", chain_id: "A", sequence_number: 1, insertion_code: "" }, sha256: "a".repeat(64) }],
      total: 1, offset: 0, limit: 100,
    });
    if (path === "/validation/redocking" && request.method() === "POST") {
      const body = request.postDataJSON(); posts.push(body);
      const run = { validation_id: `synthetic-${posts.length}`, ...body,
        created_at: "2026-10-20T12:00:00Z", reference_case: "SYNTHETIC UI TEST — not scientific evidence",
        engine: `Synthetic ${body.source_kind}`, engine_version: "test", bitwise_reproducible: false,
        metrics: { threshold_angstrom: body.threshold_angstrom, top1_rmsd_angstrom: 3,
          best_top5_rmsd_angstrom: 1, best_overall_rmsd_angstrom: 1, first_recovering_rank: 2,
          recovered_pose_count: 1, pose_count: 2, sampling_success: true, ranking_success: false,
          outcome: "recovered_but_misranked" },
        poses: [{ rank: 1, run: 1, binding_energy_kcal_mol: -1, rmsd_angstrom: 3, recovered: false },
          { rank: 2, run: 2, binding_energy_kcal_mol: -1, rmsd_angstrom: 1, recovered: true }],
        warnings: [], provenance: null };
      runs.unshift(run); return json(run, 201);
    }
    if (path === "/validation/redocking") return json(runs);
    evidence.errors.push(`Unexpected request: ${path}`); return json({}, 404);
  });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  const navigation = page.getByRole("navigation", { name: "Docking workflow" });
  await navigation.waitFor();
  await navigation.getByRole("button", { name: /Validation/ }).click();
  await page.getByText("No redocking validation recorded yet", { exact: true }).waitFor();
  for (const [index, kind] of kinds.entries()) {
    await page.getByLabel("Completed docking result", { exact: true }).selectOption(`${kind}:synthetic-job`);
    await page.getByLabel("Crystallographic reference", { exact: true }).selectOption("synthetic-crystal");
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Calculate RMSD and save validation", exact: true }).click();
    await page.getByRole("region", { name: "Redocking validation results" }).getByRole("heading", { name: `Synthetic ${kind} test`, exact: true }).waitFor();
    assert.equal(posts.length, index + 1);
    assert.equal(posts[index].source_kind, kind);
  }
  for (const size of [{ width: 960, height: 680 }, { width: 1280, height: 800 }, { width: 1366, height: 768 }]) {
    await page.setViewportSize(size);
    const workspace = page.getByRole("region", { name: "Redocking validation workspace" });
    for (const control of [page.getByLabel("Completed docking result", { exact: true }),
      page.getByLabel("Crystallographic reference", { exact: true }),
      page.getByRole("button", { name: "Calculate RMSD and save validation", exact: true }),
      page.getByRole("table")]) {
      await control.scrollIntoViewIfNeeded();
      const box = await control.boundingBox();
      assert(box && box.width > 0 && box.y < size.height && box.y + box.height > 0);
    }
    const geometry = await workspace.evaluate((element) => ({ workspaceWidth: element.clientWidth,
      contentWidth: element.scrollWidth, scroll: getComputedStyle(element).overflowY }));
    assert(geometry.contentWidth <= geometry.workspaceWidth + 1, "No horizontal clipping of the workspace");
    assert.equal(geometry.scroll, "auto");
    await workspace.evaluate((element) => { element.scrollTop = 0; });
    await page.screenshot({ path: resolve(output, `${size.width}-setup.png`) });
    await page.getByRole("table").scrollIntoViewIfNeeded();
    await page.screenshot({ path: resolve(output, `${size.width}-results.png`) });
    evidence.viewports.push({ ...size, ...geometry });
  }
  await page.reload();
  await navigation.getByRole("button", { name: /Validation/ }).click();
  await page.getByRole("region", { name: "Redocking validation results" }).waitFor();
  assert.equal(await page.getByRole("group", { name: "Recorded validations" }).getByRole("button").count(), 3);
  assert.equal(posts.length, 3, "Reopening must never re-run validation");
  assert.deepEqual(evidence.errors, []); assert.deepEqual(evidence.cspViolations, []);
  evidence.posts = posts; evidence.reopenedWithoutInputs = true; evidence.passed = true;
} finally {
  await writeFile(resolve(output, "evidence.json"), JSON.stringify(evidence, null, 2));
  await browser?.close(); await new Promise((done) => server.close(done));
  console.log(`Redocking UI evidence: ${output}; passed=${evidence.passed}`);
}
