/** Production-bundle regression gate. All API replies are SYNTHETIC UI fixtures.
 * No scientific executable, user backend, or project data is touched.
 * npm run build; node scripts/smoke_packaged_frontend.mjs
 * Install the pinned Playwright Chromium first, or set ANKORA_SMOKE_BROWSER_CHANNEL.
 */
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const root = fileURLToPath(new URL("../", import.meta.url));
const cdpIndex = process.argv.indexOf("--cdp");
const cdpEndpoint = cdpIndex >= 0 ? process.argv[cdpIndex + 1] : null;
if (cdpEndpoint) {
  const endpoint = new URL(cdpEndpoint);
  assert(endpoint.protocol === "http:" && endpoint.hostname === "127.0.0.1",
    "Installed UI smoke only attaches to an explicitly launched localhost WebView");
}
const dist = resolve(root, "apps/desktop/dist");
const output = resolve(root, "build/windows-runtime", `frontend-smoke-${Date.now()}`);
await mkdir(output, { recursive: true });
const tauri = JSON.parse(await readFile(resolve(root, "apps/desktop/src-tauri/tauri.conf.json"), "utf8"));
const csp = `${tauri.app.security.csp}; script-src 'self'`;
assert(!csp.includes("unsafe-eval"));
let fixture = await readFile(resolve(root, "backend/tests/fixtures/synthetic_m1.pdb"));
const id = "00000000-0000-0000-0000-000000000001";
const receptorRecovery = process.argv.includes("--receptor-recovery");
const receptorGuidance = process.argv.includes("--receptor-guidance");
const receptorWizard = process.argv.includes("--receptor-wizard");
assert(!receptorGuidance || receptorRecovery, "Receptor guidance extends the explicit recovery smoke");
const syntheticResidue = { chain_id: "A", residue_name: "ALA", sequence_number: 1, insertion_code: "" };
let preparationRequests = 0;
let protonationReviews = 0;
const provenance = {
  event_id: "synthetic-ui-smoke", event_type: "structure_imported", timestamp: "2026-10-08T00:00:00Z",
  input_artifacts: [], output_artifacts: [id], tool: { name: "synthetic-ui-fixture", version: "1" },
  parameters: { synthetic: true }, warnings: [], command: null,
};
let record = {
  artifact: { artifact_id: id, original_filename: "synthetic_m1.pdb", format: "pdb",
    sha256: createHash("sha256").update(fixture).digest("hex"), size_bytes: fixture.length,
    source: "local", source_uri: null, imported_at: provenance.timestamp },
  metadata: { entry_id: "TST1", title: "Synthetic M1 fixture; not experimental data",
    experimental_method: "SYNTHETIC TEST DATA", resolution_angstrom: null, model_count: 1,
    atom_count: 9, residue_count: 4,
    chains: [{ chain_id: "A", residue_count: 4, polymer_residue_count: 1, atom_count: 9 }],
    heterogens: [{ name: "LIG", chain_id: "A", sequence_number: 101, insertion_code: "", atom_count: 2, kind: "ligand" }],
    alternate_location_atom_count: 2, missing_residue_count: 1, missing_atom_count: 1, nonstandard_polymer_residues: [] },
  warnings: [], provenance, content_url: `/structures/${id}/content`,
};
const inspection = {
  source_artifact_id: id, generated_at: provenance.timestamp, candidate_chains: ["A"],
  components: [], water_count: 1, issues: [], reference_component_id: null,
  near_reference_cutoff_angstrom: 8, warnings: [], provenance,
};
const tools = Object.fromEntries(["vina", "gnina", "autogrid4", "autodock4", "autodock_gpu",
  "pdbfixer", "pdb2pqr", "propka", "meeko", "meeko_ligand", "p2rank"].map(
  (name) => [name, { available: false, path: null, version: null }],
));
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".jpg": "image/jpeg", ".svg": "image/svg+xml" };
const server = createServer(async (req, res) => {
  try {
    const pathname = decodeURIComponent(new URL(req.url, "http://127.0.0.1").pathname);
    const path = resolve(dist, `.${pathname === "/" ? "/index.html" : pathname}`);
    if (!path.startsWith(`${dist}${sep}`)) { res.writeHead(403).end(); return; }
    const bytes = await readFile(path);
    res.writeHead(200, { "Content-Type": types[extname(path)] ?? "application/octet-stream", "Content-Security-Policy": csp });
    res.end(bytes);
  } catch { res.writeHead(404).end(); }
});
await new Promise((ready) => server.listen(0, "127.0.0.1", ready));
let browser;
const evidence = { passed: false, synthetic: true, csp, fixture_sha256: record.artifact.sha256,
  health_attempts: 0, content_requests: 0, errors: [], csp_violations: [], stages: [] };
try {
  browser = cdpEndpoint ? await chromium.connectOverCDP(cdpEndpoint) : await chromium.launch({
    channel: process.env.ANKORA_SMOKE_BROWSER_CHANNEL || undefined,
    headless: true, args: ["--enable-unsafe-swiftshader"],
  });
  evidence.browser = browser.version();
  const page = cdpEndpoint
    ? browser.contexts().flatMap((context) => context.pages()).find(
      (candidate) => candidate.url().includes("tauri.localhost"),
    )
    : await browser.newPage({ viewport: { width: 1280, height: 800 } });
  assert(page, "Installed WebView application page was not found");
  evidence.surface = cdpEndpoint ? "installed WebView2" : "production Chromium";
  page.setDefaultTimeout(20_000);
  if (cdpEndpoint) {
    // Observe the real first launch before any synthetic route interception.
    await page.getByTestId("splash-screen").waitFor({ state: "detached", timeout: 120_000 });
    await page.getByRole("navigation", { name: "Docking workflow" }).waitFor();
    assert.equal(await page.getByText("Retry Connection", { exact: false }).count(), 0);
    evidence.actual_first_launch_ready_without_retry = true;
    await page.screenshot({ path: resolve(output, "installed-first-launch.png") });
  }
  if (process.argv.includes("--trace-eval")) {
    const debuggerSession = await page.context().newCDPSession(page);
    await debuggerSession.send("Debugger.enable");
    await debuggerSession.send("Debugger.setPauseOnExceptions", { state: "all" });
    debuggerSession.on("Debugger.paused", async (event) => {
      if (event.data?.description?.includes("unsafe-eval")) {
        console.log(JSON.stringify({ exception: event.data.description, frames: event.callFrames.map(
          ({ functionName, location }) => ({ functionName, location }),
        ) }));
      }
      await debuggerSession.send("Debugger.resume");
    });
  }
  page.on("pageerror", (error) => evidence.errors.push(error.stack));
  await page.exposeFunction("recordCspViolation", (value) => evidence.csp_violations.push(value));
  await page.addInitScript(() => document.addEventListener("securitypolicyviolation", (event) => {
    window.recordCspViolation({ directive: event.violatedDirective, blocked: event.blockedURI });
  }));
  await page.route("http://127.0.0.1:8765/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    const json = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(data) });
    if (path === "/health") {
      evidence.health_attempts++;
      if (!process.argv.includes("--ready-immediately") && evidence.health_attempts < 3) return route.abort("connectionrefused");
      return json({ status: "ok", backend_version: "0.1.0" });
    }
    if (path === "/system") return json({ platform: "windows", architecture: "x86_64", python_version: "synthetic", python_environment: "UI test", app_mode: "packaged" });
    if (path === "/tools") return json(tools);
    if (path === "/system/resources") return json({ cpu_percent: 0, logical_cores: 1, memory_used_bytes: 0, memory_total_bytes: 1, memory_percent: 0, gpu: null });
    if (path === "/projects") return json({ active_project_id: "default", projects: [{ project_id: "default", name: "Synthetic UI test", registered_at: "", migrated_legacy: true }] });
    if (path === "/work/recovery") return json({ items: [], reconciled_at: provenance.timestamp });
    if (path === "/receptors/latest") return json({ message: "Synthetic fixture: no saved receptor" }, 404);
    if (path === "/structures/import") return json(record, 201);
    if (path.endsWith("/content")) {
      evidence.content_requests++;
      return route.fulfill({ status: 200, contentType: "text/plain", body: fixture });
    }
    if (path.endsWith("/receptor-inspection")) return json(inspection);
    if (receptorGuidance && path.endsWith("/receptor-protonation-preview")) {
      protonationReviews++;
      return json({ generated_at: provenance.timestamp, input_sha256: "b".repeat(64), target_ph: 7.4,
        force_field: "AMBER", tool_version: "synthetic", reference_component_id: null,
        near_reference_cutoff_angstrom: 8, metal_warning_cutoff_angstrom: 4,
        proposals: [{ proposal_id: "synthetic-his", residue: { ...syntheticResidue, residue_name: "HIS", sequence_number: 2 },
          group_label: "Synthetic HIS A:2", group_type: "HIS", predicted_pka: 7, model_pka: null,
          buried_fraction: null, coupled_group: null, predicted_state: "HIS_NEUTRAL_AUTO",
          default_state: "HIS_NEUTRAL_AUTO", selected_state: "HIS_NEUTRAL_AUTO", output_state: "HID",
          allowed_states: ["HIS_NEUTRAL_AUTO", "HID", "HIE", "HIP"], decision_source: "propka_prediction",
          distance_to_reference_angstrom: null, near_reference: false, nearby_metals: [], warnings: ["PKA_NEAR_TARGET_PH"] }],
      });
    }
    if (receptorRecovery && path === `/structures/${id}/receptors`) {
      preparationRequests++;
      if (receptorGuidance && preparationRequests > 1) return json({
        code: "MEEKO_CONNECTIVITY_FAILURE", stage: "receptor_pdbqt", message: "Synthetic Meeko connectivity failure.",
        details: { affected_residues: [syntheticResidue] }, recoverable: true,
      }, 422);
      return json({ code: "RECEPTOR_RELAXATION_TOLERANCE_EXCEEDED", stage: "receptor_relaxation",
        message: "Synthetic UI fixture: an observed atom exceeded the 0.5 Å safety limit.", recoverable: true,
        details: { max_displacement_angstrom: 0.9, tolerance_angstrom: 0.5, displaced_atom_count: 1,
          displaced_atoms: [{ residue: syntheticResidue, atom_name: "O", displacement_angstrom: 0.9,
            original_position_angstrom: [14.5, 12.7, 9], relaxed_position_angstrom: [15.4, 12.7, 9] }],
          affected_residues: [syntheticResidue] },
      }, 422);
    }
    evidence.errors.push(`Unmocked UI request: ${path}`);
    return json({ message: "Unexpected synthetic request" }, 404);
  });
  const navigation = cdpEndpoint
    ? await page.reload()
    : await page.goto(`http://127.0.0.1:${server.address().port}/`);
  evidence.served_csp = navigation?.headers()["content-security-policy"];
  assert(evidence.served_csp && !evidence.served_csp.includes("unsafe-eval"),
    "The tested surface must actually serve a restrictive CSP");
  const splash = page.getByTestId("splash-screen");
  await splash.waitFor();
  // The startup screen carries no images: it draws the recorded pocket on a
  // canvas and holds once every startup row has been answered.
  evidence.splash_images = await splash.locator("img").count();
  await page.locator('[data-testid="splash-screen"][data-phase="ready"]').waitFor({ timeout: 20_000 });
  evidence.startup_record = await splash.locator(".ak-row").evaluateAll(
    (rows) => rows.map((row) => row.getAttribute("data-status")));
  evidence.splash_scene = await splash.locator("canvas.ak-scene").evaluate(
    (canvas) => canvas.width > 0 && canvas.height > 0);
  await splash.waitFor({ state: "detached", timeout: 20_000 });
  for (const extension of ["pdb", "cif"]) {
    const filename = `synthetic_m1.${extension}`;
    inspection.issues = receptorRecovery && extension === "pdb" ? [{
      issue_id: "synthetic-missing-atom", kind: "missing_atoms", residue: syntheticResidue,
      missing_atoms: ["CB"], alternate_locations: [], distance_to_reference_angstrom: null,
      severity: "unassessed", allowed_actions: ["repair", "leave", "remove", "manual_review"],
      message: "Synthetic UI missing-atom issue; not scientific preparation evidence.",
    }] : [];
    fixture = await readFile(resolve(root, "backend/tests/fixtures", filename));
    record = { ...record, artifact: { ...record.artifact, original_filename: filename,
      format: extension === "cif" ? "mmcif" : "pdb", size_bytes: fixture.length,
      sha256: createHash("sha256").update(fixture).digest("hex"),
    } };
    if (extension === "cif") {
      // This separate fixture has four atom rows and two residues, no altlocs.
      record.metadata = { ...record.metadata, entry_id: "SYN1", atom_count: 4,
        residue_count: 2, alternate_location_atom_count: 0, missing_residue_count: 0, missing_atom_count: 0,
        chains: [{ chain_id: "A", residue_count: 2, polymer_residue_count: 1, atom_count: 4 }],
        heterogens: [{ ...record.metadata.heterogens[0], atom_count: 1 }],
      };
      inspection.water_count = 0;
    }
    await page.locator("input.visually-hidden[type=file]").setInputFiles(resolve(root, "backend/tests/fixtures", filename));
    for (const stage of ["structure", "receptor"]) {
      if (stage === "receptor") {
        await page.getByRole("navigation", { name: "Docking workflow" }).getByRole("button", { name: /Receptor/ }).click();
        if (receptorWizard && extension === "pdb") {
          assert.equal(await page.getByRole("button", { name: "Guided preparation", exact: true }).getAttribute("aria-pressed"), "true");
          assert(await page.getByRole("button", { name: "2 · Review repairs", exact: true }).isDisabled());
          assert.equal(await page.getByRole("checkbox", { name: /Run PDB2PQR/ }).count(), 0);
          await page.getByRole("button", { name: "Chain A", exact: true }).click();
          await page.getByRole("button", { name: "Remove", exact: true }).click();
          for (const [width, height] of [[1280, 800], [960, 680]]) {
            await page.setViewportSize({ width, height });
            for (const step of [0, 1, 2]) {
              if (step === 2 && await page.getByRole("button", { name: "Repair 1 incomplete side-chain(s)", exact: true }).count()) {
                await page.getByRole("button", { name: "Repair 1 incomplete side-chain(s)", exact: true }).click();
              }
              await page.getByRole("navigation", { name: "Receptor preparation steps" }).getByRole("button").nth(step).click();
              const visibleAction = step === 0 ? page.getByRole("button", { name: "Next · review repairs" })
                : step === 1 ? page.getByRole("button", { name: "Next · hydrogens and preparation" })
                : page.getByRole("checkbox", { name: /Prepare for docking/ });
              await visibleAction.scrollIntoViewIfNeeded();
              assert(await visibleAction.isVisible());
              const bounds = await visibleAction.boundingBox();
              assert(bounds && bounds.y >= 0 && bounds.y + bounds.height <= height, "Guided controls must remain reachable");
              assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
              await page.screenshot({ path: resolve(output, `wizard-${width}-step-${step + 1}.png`) });
            }
          }
          assert.equal(preparationRequests, 0);
          assert.equal(protonationReviews, 0);
          evidence.receptor_wizard = { synthetic: true, default_guided: true, three_steps: true,
            viewports: [[1280, 800], [960, 680]], controls_reachable: true, no_automatic_calculation: true };
          // Restore only the synthetic UI draft for the existing recovery scenario.
          await page.getByRole("navigation", { name: "Receptor preparation steps" }).getByRole("button").first().click();
          await page.getByRole("button", { name: "Chain A", exact: true }).click();
        }
        await page.getByRole("button", { name: "Advanced controls", exact: true }).click();
      }
      try {
        await page.locator(".molstar-host canvas").first().waitFor({ timeout: 15_000 });
        await page.waitForFunction(() => document.querySelector(".molstar-host canvas")?.width > 0);
        // Allow the asynchronous structure representation/render to finish.
        await page.waitForTimeout(1500);
        const error = await page.locator(".viewer-error").allTextContents();
        assert.deepEqual(error, []);
        if (receptorRecovery && extension === "pdb" && stage === "receptor") {
          await page.getByRole("button", { name: "Chain A", exact: true }).click();
          await page.getByRole("button", { name: "Remove", exact: true }).click();
          const decision = page.getByLabel("Decision for ALA 1", { exact: true });
          await decision.selectOption("repair");
          const relaxation = page.getByRole("checkbox", { name: /Relax repaired residues with OpenMM/ });
          await relaxation.check();
          assert.equal(await page.locator("details.relaxation-advanced").getAttribute("open"), null);
          await page.getByRole("button", { name: "Apply explicit preparation plan", exact: true }).click();
          await page.getByText("0.900 Å displacement", { exact: true }).waitFor();
          await page.getByRole("button", { name: "Inspect ALA A:1 · O in 3D", exact: true }).click();
          assert.deepEqual(await page.locator(".viewer-error").allTextContents(), []);
          for (const [width, height] of [[1280, 800], [960, 680]]) {
            await page.setViewportSize({ width, height });
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
            await page.locator(".receptor-error").screenshot({ path: resolve(output, `recovery-${width}.png`) });
          }
          await decision.selectOption("manual_review");
          await page.getByText(/This failure belongs to a previous plan/).waitFor();
          assert(await relaxation.isEnabled(), "A checked relaxation must remain possible to disable");
          await relaxation.uncheck();
          assert(await relaxation.isDisabled());
          assert(await page.getByRole("button", { name: "Apply explicit preparation plan", exact: true }).isDisabled());
          assert.equal(preparationRequests, 1, "Recovery controls must not trigger another preparation");
          evidence.receptor_recovery = { synthetic: true, viewports: [[1280, 800], [960, 680]], preparation_requests: preparationRequests,
            focus_without_viewer_error: true, checkbox_recovered: true, previous_plan_labeled: true };
          if (receptorGuidance) {
            await decision.selectOption("repair");
            await page.getByRole("checkbox", { name: /Run PDB2PQR/ }).check();
            await page.getByRole("checkbox", { name: /Generate receptor PDBQT/ }).check();
            const nextStep = page.getByRole("region", { name: "Preparation next step" });
            await nextStep.getByRole("button", { name: "Analyze pKa proposals", exact: true }).click();
            await page.getByText("1 pKa proposals", { exact: true }).waitFor();
            await nextStep.getByRole("button", { name: "Prepare this receptor", exact: true }).click();
            await page.getByRole("button", { name: "Inspect ALA A:1 in 3D", exact: true }).click();
            await page.getByRole("button", { name: "Mark 1 affected residue for removal", exact: true }).click();
            await page.getByText(/Your structural plan changed/).waitFor();
            assert(await page.getByRole("button", { name: "Apply explicit preparation plan", exact: true }).isDisabled());
            assert.equal(preparationRequests, 2);
            assert.equal(protonationReviews, 1);
            assert.equal(await page.locator(".receptor-error").getAttribute("role"), "status");
            for (const [width, height] of [[1280, 800], [960, 680]]) {
              await page.setViewportSize({ width, height });
              await nextStep.scrollIntoViewIfNeeded();
              // Mol* asynchronously resizes its drawing buffer after viewport/scroll changes.
              await page.waitForTimeout(500);
              assert(await nextStep.getByRole("button", { name: "Analyze pKa proposals", exact: true }).isVisible());
              assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
              await page.screenshot({ path: resolve(output, `guidance-${width}.png`) });
              await page.getByLabel("Decision for ALA 1", { exact: true }).scrollIntoViewIfNeeded();
              const bounds = await page.getByLabel("Decision for ALA 1", { exact: true }).boundingBox();
              assert(bounds && bounds.y >= 0 && bounds.y + bounds.height <= height,
                "Structural decisions must remain reachable below the error and guidance");
            }
            await nextStep.getByRole("button", { name: "Analyze pKa proposals", exact: true }).click();
            await nextStep.getByRole("button", { name: "Prepare this receptor", exact: true }).waitFor();
            await page.getByRole("button", { name: "Needs attention (1)", exact: true }).click();
            await page.getByLabel("Protonation decision for Synthetic HIS A:2").selectOption("HIE");
            assert.equal(preparationRequests, 2, "Review/filter controls must not create a receptor");
            assert.equal(protonationReviews, 2);
            evidence.receptor_guidance = { synthetic: true, preparation_requests: 2, reviews: 2,
              no_automatic_retry: true, stale_review_invalidated: true, table_reachable: true,
              next_action_visible: true, proposal_override_reachable: true };
          }
          await page.setViewportSize({ width: 1280, height: 800 });
        }
        await page.screenshot({ path: resolve(output, `${extension}-${stage}.png`) });
        evidence.stages.push(`${extension}-${stage}`);
      } catch (error) {
        evidence.errors.push(`${stage}: ${error.message}; ${await page.locator(".viewer-error").allTextContents()}`);
        await page.screenshot({ path: resolve(output, `${extension}-${stage}-failed.png`) });
        break;
      }
    }
  }
  assert.deepEqual(evidence.errors, []);
  assert.deepEqual(evidence.csp_violations, []);
  assert.equal(evidence.splash_images, 0);
  assert.equal(evidence.startup_record.length, 5);
  assert(evidence.startup_record.every((status) => status === "ok" || status === "notice"));
  assert(evidence.splash_scene);
  assert(evidence.content_requests >= 4);
  assert.deepEqual(evidence.stages, ["pdb-structure", "pdb-receptor", "cif-structure", "cif-receptor"]);
  if (!process.argv.includes("--ready-immediately")) assert.equal(evidence.health_attempts, 3);
  evidence.passed = true;
  console.log("Packaged frontend: cold start, assets, Structure and Receptor passed under strict CSP.");
} finally {
  await writeFile(resolve(output, "evidence.json"), JSON.stringify(evidence, null, 2));
  console.log(`Evidence: ${output}`);
  await browser?.close();
  await new Promise((done) => server.close(done));
}
