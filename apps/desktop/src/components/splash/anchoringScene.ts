/**
 * The anchoring scene: RV2 settling into the SERPINE1 pocket as startup completes.
 *
 * Every coordinate comes from the recorded 7AQF reference case (see
 * scripts/build_splash_scene.py): the pocket is the real cavity surface, RV2 is
 * drawn in its deposited pose, the search space is the recorded co-crystal box,
 * and the contacts are the deposited pose's polar pairs. Only the *search motion*
 * is illustrative — it narrows as the startup record fills, so the scene can
 * never look more ready than the workbench is, and it never anchors on failure.
 */

type Vec3 = [number, number, number];
type Quat = [number, number, number, number];
interface Pose { q: Quat; t: Vec3 }

export interface SceneData {
  ligand: { atoms: { p: Vec3; element: string }[]; bonds: [number, number, number][] };
  dots: { p: Vec3; polar: boolean }[];
  edges: [number, number][];
  contacts: { ligandAtom: number; p: Vec3; residue: string; distance: number }[];
  box: { corners: Vec3[]; size: Vec3 } | null;
}

export interface AnchoringScene {
  /** Fraction of the startup record confirmed, 0..1. */
  setProgress(fraction: number): void;
  anchor(): void;
  stall(): void;
  restart(): void;
  setReducedMotion(reduced: boolean): void;
  /** Where the record column begins, in CSS pixels; the scene frames itself left of it. */
  layout(columnLeft: number): void;
  destroy(): void;
}

// ---------------------------------------------------------------------------
//  Asset validation — a malformed scene is no scene, never a crash
// ---------------------------------------------------------------------------

const isNum = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isVec3 = (value: unknown): value is Vec3 => Array.isArray(value) && value.length >= 3 && value.slice(0, 3).every(isNum);

export function parseScene(raw: unknown): SceneData | null {
  if (!raw || typeof raw !== "object") return null;
  const source = raw as Record<string, unknown>;
  const ligand = source.ligand as Record<string, unknown> | undefined;
  if (!ligand || !Array.isArray(ligand.atoms) || !Array.isArray(ligand.bonds) || !Array.isArray(source.dots)) return null;
  const atoms = ligand.atoms.filter((a): a is unknown[] => isVec3(a) && typeof (a as unknown[])[3] === "string")
    .map((a) => ({ p: [a[0], a[1], a[2]] as Vec3, element: a[3] as string }));
  const bonds = ligand.bonds.filter((b): b is [number, number, number] => Array.isArray(b) && b.length === 3 && b.every(isNum)
    && b[0] < atoms.length && b[1] < atoms.length);
  const dots = source.dots.filter(isVec3).map((d) => ({ p: [d[0], d[1], d[2]] as Vec3, polar: (d as number[])[3] === 1 }));
  const edges = (Array.isArray(source.edges) ? source.edges : [])
    .filter((e): e is [number, number] => Array.isArray(e) && e.length === 2 && e.every(isNum) && e[0] < dots.length && e[1] < dots.length);
  const contacts = (Array.isArray(source.contacts) ? source.contacts : [])
    .filter((c): c is unknown[] => Array.isArray(c) && c.length === 6 && isNum(c[0]) && c[0] < atoms.length
      && isVec3(c.slice(1, 4)) && typeof c[4] === "string" && isNum(c[5]))
    .map((c) => ({ ligandAtom: c[0] as number, p: [c[1], c[2], c[3]] as Vec3, residue: c[4] as string, distance: c[5] as number }));
  const boxRaw = source.box as Record<string, unknown> | undefined;
  const box = boxRaw && Array.isArray(boxRaw.corners) && boxRaw.corners.length === 8 && boxRaw.corners.every(isVec3) && isVec3(boxRaw.size)
    ? { corners: (boxRaw.corners as Vec3[]).map((c) => [c[0], c[1], c[2]] as Vec3), size: boxRaw.size as Vec3 }
    : null;
  if (!atoms.length || !dots.length) return null;
  return { ligand: { atoms, bonds }, dots, edges, contacts, box };
}

// ---------------------------------------------------------------------------
//  Small 3D toolkit
// ---------------------------------------------------------------------------

const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scl = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s];
const dist = (a: Vec3, b: Vec3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const IDENTITY: Quat = [1, 0, 0, 0];

function qAxis(axis: Vec3, angle: number): Quat {
  const l = Math.hypot(...axis) || 1, s = Math.sin(angle / 2);
  return [Math.cos(angle / 2), (axis[0] / l) * s, (axis[1] / l) * s, (axis[2] / l) * s];
}
function qMul(a: Quat, b: Quat): Quat {
  return [a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3], a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
    a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1], a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0]];
}
function qSlerp(a: Quat, b: Quat, t: number): Quat {
  let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
  let target = b;
  if (d < 0) { target = [-b[0], -b[1], -b[2], -b[3]]; d = -d; }
  if (d > 0.9995) {
    const r = a.map((x, i) => x + (target[i] - x) * t) as Quat;
    const l = Math.hypot(...r);
    return r.map((x) => x / l) as Quat;
  }
  const th = Math.acos(d), s = Math.sin(th), w1 = Math.sin((1 - t) * th) / s, w2 = Math.sin(t * th) / s;
  return a.map((x, i) => x * w1 + target[i] * w2) as Quat;
}
function qMat(q: Quat): number[] {
  const [w, x, y, z] = q;
  return [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
    2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
    2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)];
}
const apply = (m: number[], p: Vec3): Vec3 => [m[0] * p[0] + m[1] * p[1] + m[2] * p[2], m[3] * p[0] + m[4] * p[1] + m[5] * p[2], m[6] * p[0] + m[7] * p[1] + m[8] * p[2]];
function randUnit(): Vec3 {
  const u = Math.random() * 2 - 1, t = Math.random() * Math.PI * 2, s = Math.sqrt(1 - u * u);
  return [s * Math.cos(t), s * Math.sin(t), u];
}
function camera(yaw: number, pitch: number): number[] {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  return [cy, 0, sy, sp * sy, cp, -sp * cy, -cp * sy, sp, cp * cy];
}
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const smooth = (a: number, b: number, x: number) => { const t = clamp01((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const easeOut = (t: number) => 1 - Math.pow(1 - clamp01(t), 3);
const easeInOut = (t: number) => { const u = clamp01(t); return u < 0.5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2; };

// ---------------------------------------------------------------------------
//  Colour, read from the active theme's own tokens
// ---------------------------------------------------------------------------

type RGB = [number, number, number];
const mix = (a: RGB, b: RGB, t: number): RGB => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
const rgba = (c: RGB, a: number) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${clamp01(a).toFixed(3)})`;

function parseColour(css: string): RGB {
  let m = css.match(/rgba?\(([^)]+)\)/);
  if (m) { const p = m[1].split(/[\s,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2]]; }
  m = css.match(/color\(srgb ([^)]+)\)/);
  if (m) { const p = m[1].split(/[\s/]+/).filter(Boolean).map(Number); return [p[0] * 255, p[1] * 255, p[2] * 255]; }
  return [140, 140, 140];
}

interface Palette { canvas: RGB; accent: RGB; ligand: RGB; text: RGB; muted: RGB; tert: RGB; line: RGB; polar: RGB; apolar: RGB; light: boolean; mono: string }

function readPalette(host: HTMLElement): Palette {
  const probe = document.createElement("i");
  probe.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
  host.appendChild(probe);
  const token = (name: string, fallback: string) => {
    probe.style.color = `var(${name}, ${fallback})`;
    return parseColour(getComputedStyle(probe).color);
  };
  const canvas = token("--canvas", "var(--bg)");
  const precision = token("--precision", "var(--muted)");
  const text = token("--text", "#ddd");
  const light = (canvas[0] + canvas[1] + canvas[2]) / 3 > 128;
  const palette: Palette = {
    canvas, text, light,
    accent: token("--accent", "#888"), ligand: token("--ligand", "var(--warning)"),
    muted: token("--muted", "#888"), tert: token("--text-tertiary", "var(--muted)"),
    line: token("--line-strong", "var(--line)"),
    polar: mix(precision, text, light ? 0.15 : 0.42), apolar: mix(precision, canvas, light ? 0.05 : 0.08),
    mono: getComputedStyle(document.documentElement).getPropertyValue("--font-mono").trim() || "Consolas, monospace",
  };
  probe.remove();
  return palette;
}

// ---------------------------------------------------------------------------
//  The scene
// ---------------------------------------------------------------------------

const DEPTH = 34;            // Å — perspective focal distance
const GHOST_LIFE = 820;      // ms
const ANCHOR_MS = 1050;

export function createAnchoringScene(canvasEl: HTMLCanvasElement, data: SceneData, options: { reducedMotion: boolean }): AnchoringScene | null {
  const context = canvasEl.getContext("2d");
  if (!context) return null;
  const ctx: CanvasRenderingContext2D = context;
  const host = canvasEl.parentElement ?? document.body;
  let reduced = options.reducedMotion;
  let palette = readPalette(host);
  let W = 1, H = 1, dpr = 1, CX = 0, CY = 0, SCALE = 20, COLUMN = 0;
  let frameId = 0;

  const contactPoints = data.contacts.map((c) => c.p);
  const dots = data.dots.map((d) => {
    let near = Infinity;
    for (const q of contactPoints) near = Math.min(near, dist(d.p, q));
    return { ...d, glow: Math.max(0, 1 - near / 3.4), scatter: scl(randUnit(), 5 + Math.random() * 7), delay: (Math.hypot(...d.p) / 11) * 0.55 + Math.random() * 0.25 };
  });
  const labels = (() => {
    const byResidue = new Map<string, (typeof data.contacts)[number]>();
    for (const c of data.contacts) { const cur = byResidue.get(c.residue); if (!cur || c.distance < cur.distance) byResidue.set(c.residue, c); }
    return [...byResidue.values()];
  })();

  interface State {
    t0: number; p: number; pSmooth: number; searching: boolean; enterAt: number; anchorAt: number | null; anchorFrom: Pose | null;
    stalled: boolean; best: Pose; from: Pose | null; to: Pose | null; moveAt: number; lastMove: number;
    ghosts: { pose: Pose; born: number }[]; lastGhost: number;
  }
  let S: State;
  function reset() {
    S = { t0: performance.now(), p: 0, pSmooth: 0, searching: false, enterAt: 0, anchorAt: null, anchorFrom: null, stalled: false,
      best: { q: IDENTITY, t: [0, 0, 0] }, from: null, to: null, moveAt: 0, lastMove: 0, ghosts: [], lastGhost: 0 };
  }
  reset();

  function resize() {
    const rect = canvasEl.getBoundingClientRect();
    W = Math.max(1, rect.width); H = Math.max(1, rect.height);
    dpr = Math.min(2.5, window.devicePixelRatio || 1);
    canvasEl.width = Math.round(W * dpr); canvasEl.height = Math.round(H * dpr);
  }
  function layout(columnLeft: number) {
    resize();
    const left = columnLeft > 0 ? columnLeft : W * 0.6;
    CX = left * 0.53; CY = H * 0.522;
    SCALE = Math.max(9, Math.min(H * 0.0225, left * 0.023));
    COLUMN = left - 75;
  }

  function startSearch() {
    if (S.searching) return;
    S.searching = true;
    S.best = { q: qAxis([0.5, 1, 0.3], 2.1), t: [-5.5, 3.0, 13.0] };   // descends from the viewer's side
    S.enterAt = performance.now();
  }
  function currentPose(now: number): Pose {
    if (!S.from || !S.to) return S.best;
    const u = easeInOut((now - S.moveAt) / 380);
    if (u >= 1) { S.best = S.to; S.from = null; return S.best; }
    return { q: qSlerp(S.from.q, S.to.q, u), t: add(scl(S.from.t, 1 - u), scl(S.to.t, u)) };
  }
  function sampleNear(pose: Pose, angle: number, spread: number, pull: number): Pose {
    return {
      q: qMul(qAxis(randUnit(), (Math.random() * 2 - 1) * angle), qSlerp(pose.q, IDENTITY, pull)),
      t: add(scl(pose.t, 1 - pull), scl(randUnit(), Math.random() * spread)),
    };
  }
  const project = (cam: number[], p: Vec3): [number, number, number, number] => {
    const q = apply(cam, p), f = DEPTH / (DEPTH - q[2]);
    return [CX + q[0] * SCALE * f, CY - q[1] * SCALE * f, q[2], f];
  };
  const transform = (pose: Pose, p: Vec3) => add(apply(qMat(pose.q), p), pose.t);

  function roundRect(x: number, y: number, w: number, h: number, r: number) {
    ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
  }

  function drawLigand(cam: number[], pose: Pose, alpha: number, ghost: boolean) {
    const m = qMat(pose.q);
    const atoms = data.ligand.atoms;
    const pts = atoms.map((a) => project(cam, add(apply(m, a.p), pose.t)));
    const hetero = (i: number) => atoms[i].element !== "C";
    ctx.lineCap = "round";
    for (const [i, j, order] of data.ligand.bonds) {
      const a = pts[i], b = pts[j];
      let ax = a[0], ay = a[1], bx = b[0], by = b[1];
      const len = Math.hypot(bx - ax, by - ay) || 1, ux = (bx - ax) / len, uy = (by - ay) / len;
      if (!ghost) {                       // skeletal convention: bonds stop short of heteroatom labels
        if (hetero(i)) { ax += ux * 7.5; ay += uy * 7.5; }
        if (hetero(j)) { bx -= ux * 7.5; by -= uy * 7.5; }
      }
      const depth = smooth(-9, 9, (a[2] + b[2]) / 2);
      const w = (ghost ? 1.0 : 1.95) * (a[3] + b[3]) / 2;
      ctx.strokeStyle = rgba(palette.ligand, alpha * (ghost ? 1 : 0.62 + 0.38 * depth)); ctx.lineWidth = w;
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      if (!ghost && order > 1) {
        const nx = -uy * 3.3, ny = ux * 3.3;
        ctx.lineWidth = w * 0.8;
        if (order === 1.5) ctx.setLineDash([2.2, 3.2]);
        ctx.beginPath(); ctx.moveTo(ax + nx + ux * 2.5, ay + ny + uy * 2.5); ctx.lineTo(bx + nx - ux * 2.5, by + ny - uy * 2.5); ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    if (ghost) return;
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    atoms.forEach((atom, i) => {
      if (!hetero(i)) return;
      const p = pts[i], depth = smooth(-9, 9, p[2]);
      ctx.font = `600 ${Math.round(11.5 * p[3])}px ${palette.mono}`;
      ctx.fillStyle = rgba(mix(palette.ligand, palette.text, palette.light ? 0 : 0.22), alpha * (0.7 + 0.3 * depth));
      ctx.fillText(atom.element, p[0], p[1] + 0.5);
    });
    ctx.textBaseline = "alphabetic";
  }

  function frame(now: number) {
    frameId = requestAnimationFrame(frame);
    if (document.hidden) return;
    const t = (now - S.t0) / 1000;
    S.pSmooth += (S.p - S.pSmooth) * 0.05;
    const yaw = reduced ? 0.12 : 0.12 + 0.30 * Math.sin(t * 0.17);
    const pitch = reduced ? -0.08 : -0.08 + 0.09 * Math.sin(t * 0.12 + 0.8);
    const cam = camera(yaw, pitch);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);

    // ---- pose and search state ---------------------------------------
    const anchoring = S.anchorAt !== null && S.anchorFrom !== null;
    const anchorU = anchoring ? easeOut((now - (S.anchorAt as number)) / (reduced ? 1 : ANCHOR_MS)) : 0;
    const settled = anchoring && anchorU >= 1;
    const spread = 1 - S.pSmooth;
    const angle = S.stalled ? 1.6 : spread * 1.75 + 0.06;
    const reach = S.stalled ? 6.5 : spread * 7.2 + 0.4;
    let pose: Pose;
    if (anchoring && S.anchorFrom) {
      pose = { q: qSlerp(S.anchorFrom.q, IDENTITY, anchorU), t: scl(S.anchorFrom.t, 1 - anchorU) };
    } else if (S.searching && !reduced) {
      pose = currentPose(now);
      const every = S.stalled ? 1100 : 640 - 260 * S.pSmooth;
      if (!S.from && now - S.lastMove > every) {
        S.from = pose; S.to = sampleNear(pose, angle * 0.55, reach * 0.5, S.stalled ? 0.02 : 0.16 + 0.34 * S.pSmooth);
        S.moveAt = now; S.lastMove = now;
      }
      if (now - S.lastGhost > (S.stalled ? 320 : 120) && S.ghosts.length < 6) {
        S.ghosts.push({ pose: sampleNear(pose, angle, reach, 0), born: now }); S.lastGhost = now;
      }
    } else {
      pose = S.best;
    }
    S.ghosts = S.ghosts.filter((g) => now - g.born < GHOST_LIFE && !anchoring);
    const enter = S.searching ? smooth(0, 0.45, (now - S.enterAt) / 1000) : 0;
    const ligandAlpha = reduced ? (anchoring ? 1 : 0) : enter * (S.stalled ? 0.55 : 1);

    // ---- pocket surface ------------------------------------------------
    const ligandDepth = apply(cam, pose.t)[2];
    const projected: { s: [number, number, number, number]; d: (typeof dots)[number]; k: number }[] = [];
    const byIndex: ((typeof projected)[number] | null)[] = new Array(dots.length);
    dots.forEach((d, i) => {
      const k = reduced ? 1 : easeOut((t - d.delay) / 0.9);
      if (k <= 0) { byIndex[i] = null; return; }
      const entry = { s: project(cam, k < 1 ? add(d.p, scl(d.scatter, 1 - k)) : d.p), d, k };
      byIndex[i] = entry; projected.push(entry);
    });
    projected.sort((a, b) => a.s[2] - b.s[2]);
    const glowOn = settled ? smooth(0, 0.6, (now - (S.anchorAt as number) - ANCHOR_MS) / 1000) : 0;
    const fog = (c: RGB, depth: number) => mix(palette.canvas, c, 0.3 + 0.7 * depth);

    // ---- recorded search space ---------------------------------------
    if (data.box) {
      const corners = data.box.corners.map((p) => project(cam, p));
      const boxIn = reduced ? 1 : smooth(0.6, 1.6, t);
      const tint = settled ? smooth(0, 0.5, (now - (S.anchorAt as number) - 900) / 1000) : 0;
      const colour = mix(palette.line, palette.accent, tint * 0.85);
      ctx.lineWidth = 1;
      for (let i = 0; i < 8; i++) for (const bit of [1, 2, 4]) {
        if (i & bit) continue;
        const a = corners[i], b = corners[i | bit];
        ctx.strokeStyle = rgba(colour, 0.09 * boxIn); ctx.setLineDash([2, 7]);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
        ctx.setLineDash([]); ctx.strokeStyle = rgba(colour, (0.55 + 0.35 * tint) * boxIn);
        for (const [u, v] of [[a, b], [b, a]]) {
          ctx.beginPath(); ctx.moveTo(u[0], u[1]); ctx.lineTo(u[0] + (v[0] - u[0]) * 0.13, u[1] + (v[1] - u[1]) * 0.13); ctx.stroke();
        }
      }
      const pin = corners.reduce((m, c) => (c[0] + c[1] < m[0] + m[1] ? c : m), corners[0]);
      ctx.font = `500 10.5px ${palette.mono}`; ctx.textAlign = "left";
      ctx.fillStyle = rgba(mix(palette.tert, palette.accent, tint * 0.6), 0.95 * boxIn);
      ctx.fillText("SEARCH SPACE", pin[0] + 4, pin[1] - 22);
      ctx.fillStyle = rgba(mix(palette.muted, palette.accent, tint * 0.4), 0.95 * boxIn);
      ctx.fillText(`${data.box.size.map((v) => v.toFixed(1)).join(" × ")} Å · recorded`, pin[0] + 4, pin[1] - 8);
    }

    // ---- mesh, then the dots behind the ligand -----------------------
    const meshK = reduced ? 1 : smooth(0.55, 1.7, t);
    if (meshK > 0 && data.edges.length) {
      const buckets: [number, number, number, number][][] = [[], [], [], [], [], []];
      for (const [a, b] of data.edges) {
        const A = byIndex[a], B = byIndex[b];
        if (!A || !B || A.k < 0.98 || B.k < 0.98) continue;
        const depth = smooth(-11, 9, (A.s[2] + B.s[2]) / 2);
        buckets[Math.min(5, (depth * 6) | 0)].push(A.s, B.s);
      }
      ctx.lineCap = "round";
      buckets.forEach((seg, bi) => {
        if (!seg.length) return;
        const depth = (bi + 0.5) / 6;
        ctx.strokeStyle = rgba(fog(palette.apolar, depth), (0.05 + 0.2 * depth) * meshK);
        ctx.lineWidth = 0.55 + 0.6 * depth;
        ctx.beginPath();
        for (let i = 0; i < seg.length; i += 2) { ctx.moveTo(seg[i][0], seg[i][1]); ctx.lineTo(seg[i + 1][0], seg[i + 1][1]); }
        ctx.stroke();
      });
    }
    const drawDots = (front: boolean) => {
      for (const { s, d, k } of projected) {
        if ((s[2] > ligandDepth + 1.5) !== front) continue;
        const depth = smooth(-11, 9, s[2]);
        let a = (0.16 + 0.8 * depth) * k * (front ? 0.45 : 1);
        let r = (0.55 + 0.95 * depth) * s[3];
        let c = fog(d.polar ? palette.polar : palette.apolar, depth);
        if (d.polar) { a = Math.min(1, a * 1.12); r *= 1.18; }
        if (glowOn && d.glow > 0) { const g = d.glow * glowOn; c = mix(c, palette.accent, g); r *= 1 + 0.8 * g; a = Math.min(1, a + 0.45 * g); }
        ctx.fillStyle = rgba(c, a);
        ctx.beginPath(); ctx.arc(s[0], s[1], r, 0, Math.PI * 2); ctx.fill();
      }
    };
    drawDots(false);

    // ---- candidate poses being sampled -------------------------------
    for (const g of S.ghosts) {
      const u = (now - g.born) / GHOST_LIFE;
      drawLigand(cam, g.pose, Math.sin(Math.PI * u) * 0.22 * ligandAlpha, true);
    }

    // ---- contacts of the deposited pose, once anchored ---------------
    const contactOn = settled ? smooth(0, 0.45, (now - (S.anchorAt as number) - ANCHOR_MS) / 1000) : 0;
    if (contactOn > 0) {
      ctx.setLineDash([3, 5]); ctx.lineDashOffset = -(t * 14) % 16; ctx.lineWidth = 1.3;
      ctx.strokeStyle = rgba(palette.accent, 0.9 * contactOn);
      for (const c of data.contacts) {
        const a = project(cam, transform(pose, data.ligand.atoms[c.ligandAtom].p)), b = project(cam, c.p);
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      }
      ctx.setLineDash([]);
    }

    if (ligandAlpha > 0) drawLigand(cam, pose, ligandAlpha, false);
    drawDots(true);

    // ---- anchoring pulse and residue labels ---------------------------
    if (settled) {
      const centre = project(cam, [0, 0, 0]);
      const u = (now - (S.anchorAt as number) - ANCHOR_MS) / 1100;
      if (u > 0 && u < 1 && !reduced) {
        ctx.strokeStyle = rgba(palette.accent, 0.42 * (1 - u)); ctx.lineWidth = 1.2;
        ctx.beginPath(); ctx.arc(centre[0], centre[1], 18 + 120 * easeOut(u), 0, Math.PI * 2); ctx.stroke();
      }
      if (contactOn > 0) {
        ctx.font = `500 11px ${palette.mono}`; ctx.textAlign = "left";
        for (const label of labels) {
          const r = project(cam, label.p);
          let dx = r[0] - centre[0], dy = r[1] - centre[1];
          const n = Math.hypot(dx, dy) || 1; dx /= n; dy /= n;
          const lx = r[0] + dx * 46, ly = r[1] + dy * 34;
          ctx.strokeStyle = rgba(palette.accent, 0.5 * contactOn); ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(r[0], r[1]); ctx.lineTo(lx, ly); ctx.stroke();
          ctx.fillStyle = rgba(palette.accent, contactOn); ctx.beginPath(); ctx.arc(r[0], r[1], 2.6, 0, Math.PI * 2); ctx.fill();
          const name = label.residue, value = `  ${label.distance.toFixed(2)} Å`;
          const wName = ctx.measureText(name).width, wValue = ctx.measureText(value).width;
          const x0 = dx < 0 ? lx - 6 - wName - wValue : lx + 6;
          ctx.fillStyle = rgba(palette.canvas, 0.78 * contactOn);
          roundRect(x0 - 6, ly - 9, wName + wValue + 12, 19, 4); ctx.fill();
          ctx.fillStyle = rgba(palette.text, contactOn); ctx.fillText(name, x0, ly + 4);
          ctx.fillStyle = rgba(palette.muted, contactOn); ctx.fillText(value, x0 + wName, ly + 4);
        }
      }
    }

    // The scene dissolves before the record column and the bezels: nothing
    // the search does may ever sit on top of the text.
    ctx.save();
    ctx.globalCompositeOperation = "destination-out";
    const fadeX = ctx.createLinearGradient(COLUMN - 95, 0, COLUMN + 10, 0);
    fadeX.addColorStop(0, "rgba(0,0,0,0)"); fadeX.addColorStop(1, "rgba(0,0,0,1)");
    ctx.fillStyle = fadeX; ctx.fillRect(COLUMN - 95, 0, W - COLUMN + 95, H);
    const fadeTop = ctx.createLinearGradient(0, 48, 0, 110);
    fadeTop.addColorStop(0, "rgba(0,0,0,1)"); fadeTop.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = fadeTop; ctx.fillRect(0, 0, W, 110);
    const fadeBottom = ctx.createLinearGradient(0, H - 120, 0, H - 44);
    fadeBottom.addColorStop(0, "rgba(0,0,0,0)"); fadeBottom.addColorStop(1, "rgba(0,0,0,1)");
    ctx.fillStyle = fadeBottom; ctx.fillRect(0, H - 120, W, 120);
    ctx.restore();
  }

  // Re-read the palette whenever the workbench changes theme.
  const themeObserver = new MutationObserver(() => { palette = readPalette(host); });
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class", "style"] });

  frameId = requestAnimationFrame(frame);

  return {
    setProgress(fraction) {
      S.p = clamp01(fraction);
      if (S.p > 0) startSearch();
    },
    anchor() {
      if (S.anchorAt !== null) return;
      startSearch();
      const now = performance.now();
      S.anchorFrom = currentPose(now); S.anchorAt = now; S.stalled = false;
    },
    stall() { S.stalled = true; startSearch(); },
    restart() { reset(); },
    setReducedMotion(value) { reduced = value; },
    layout,
    destroy() { cancelAnimationFrame(frameId); themeObserver.disconnect(); },
  };
}
