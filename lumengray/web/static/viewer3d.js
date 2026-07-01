// 3D viewer: four orbitable views over the same model — Mesh (the STL),
// Photostack (thin textured slices), Volume (gap-free voxel solid), and
// Wireframe (isolate the photostack's white/gray/black exposure bands as
// cages or blocks). three.js is imported lazily so a CDN hiccup never breaks
// the core 2D viewer / export.

import { $, state } from "./core.js";
import { buildConfig } from "./config.js";
import { postJSON } from "./api.js";

let three = null;
let THREE = null, STLLoader = null, OrbitControls = null;

export function currentViewMode() {
  return three ? three.mode : "mesh";
}

async function loadThreeLibs() {
  if (THREE) return true;
  try {
    THREE = await import("three");
    ({ STLLoader } = await import("three/addons/loaders/STLLoader.js"));
    ({ OrbitControls } = await import("three/addons/controls/OrbitControls.js"));
    return true;
  } catch (e) {
    $("model-empty").textContent = "3D view unavailable (could not load three.js — check your connection).";
    $("model-empty").hidden = false;
    return false;
  }
}

function initThree() {
  const wrap = $("three-wrap");
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  wrap.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x11141a);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
  camera.up.set(0, 0, 1); // Z is print height → up
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x223044, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(1, -1.2, 1.6);
  scene.add(key);
  const grid = new THREE.GridHelper(200, 20, 0x2a323d, 0x1c2229);
  grid.rotation.x = Math.PI / 2; // lay the grid in the XY (build-plate) plane
  scene.add(grid);
  three = { renderer, scene, camera, controls, grid, mesh: null, stack: null, stackKey: null, mode: "mesh", meshRadius: 10, meshBottom: 0, meshHalfH: 10, clipR: 10, clipRz: 10 };
  three.clipX = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 1e6); // vertical cutaway (slices along X)
  three.clipZ = new THREE.Plane(new THREE.Vector3(0, 0, -1), 1e6); // horizontal cutaway (slices along Z, bottom→top)
  renderer.clippingPlanes = [three.clipX, three.clipZ];

  function resize() {
    const w = wrap.clientWidth, h = wrap.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(wrap);
  resize();
  (function loop() {
    requestAnimationFrame(loop);
    controls.update();
    renderer.render(scene, camera);
  })();
}

function frame(radius) {
  const r = radius || 10;
  three.camera.near = r / 100;
  three.camera.far = r * 100;
  three.camera.position.set(r * 1.9, -r * 2.3, r * 1.5);
  three.camera.updateProjectionMatrix();
  three.controls.target.set(0, 0, 0);
  three.controls.update();
}

// Cutaways: Vertical slides a plane along X; Horizontal slides one along Z
// (bottom→top). 100 = whole model; lower = cut more away.
export function applyClip() {
  if (!three) return;
  const fx = parseInt($("clip-slider").value, 10) / 100;
  const Rx = three.clipR || 10;
  three.clipX.constant = -Rx + fx * 2 * Rx * 1.001;
  const zEl = $("clip-slider-z");
  const fz = zEl ? parseInt(zEl.value, 10) / 100 : 1;
  const Rz = three.clipRz || 10;
  three.clipZ.constant = -Rz + fz * 2 * Rz * 1.001;
}

export async function loadModel3D(id) {
  if (!(await loadThreeLibs())) return;
  const fail = (msg) => { $("model-empty").textContent = msg; $("model-empty").hidden = false; };
  try {
    if (!three) initThree();
  } catch (e) {
    fail("3D view unavailable (WebGL not supported in this browser).");
    return;
  }
  $("model-empty").hidden = true;
  disposeStack(); // the model changed; any previous stack is stale
  new STLLoader().load(
    "/api/model/" + id,
    (geometry) => {
      if (three.mesh) { three.scene.remove(three.mesh); three.mesh.geometry.dispose(); three.mesh.material.dispose(); }
      geometry.computeVertexNormals();
      geometry.center();
      geometry.computeBoundingBox();
      geometry.computeBoundingSphere();
      const material = new THREE.MeshStandardMaterial({ color: 0xf5a623, metalness: 0.1, roughness: 0.6 });
      const mesh = new THREE.Mesh(geometry, material);
      three.scene.add(mesh);
      three.mesh = mesh;
      three.meshRadius = geometry.boundingSphere.radius || 10;
      three.meshBottom = geometry.boundingBox.min.z;
      three.meshHalfH = (geometry.boundingBox.max.z - geometry.boundingBox.min.z) / 2 || 10;
      if (three.mode === "mesh") {
        mesh.visible = true;
        three.grid.position.z = three.meshBottom;
        frame(three.meshRadius);
        three.clipR = three.meshRadius;
        three.clipRz = three.meshHalfH;
        applyClip();
      } else {
        mesh.visible = false;
        buildView(three.mode);
      }
    },
    undefined,
    () => fail("Could not load the model geometry."),
  );
}

function disposeStack() {
  if (!three || !three.stack) return;
  three.stack.traverse((o) => {
    if (o.material) { if (o.material.map) o.material.map.dispose(); o.material.dispose(); }
    if (o.geometry) o.geometry.dispose();
  });
  three.scene.remove(three.stack);
  three.stack = null;
  three.stackKey = null;
}

// Photostack: the literal layer images stacked as thin textured slices.
async function makeSlices() {
  const data = await postJSON("/api/stack", { id: state.id, config: buildConfig() });
  const group = new THREE.Group();
  const loader = new THREE.TextureLoader();
  const h = data.height_mm;
  data.layers.forEach((L) => {
    const tex = loader.load(L.png);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.magFilter = THREE.NearestFilter;
    const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, side: THREE.DoubleSide });
    const plane = new THREE.Mesh(new THREE.PlaneGeometry(data.plane_w_mm, data.plane_h_mm), mat);
    plane.position.z = L.z_mm - h / 2;
    group.add(plane);
  });
  return { obj: group, h, radius: Math.max(data.plane_w_mm, data.plane_h_mm, h) * 0.8, hint: `Photostack · ${data.count} of ${data.total_layers} layers` };
}

// Wireframe (band-isolation): split the photostack's exposure values into
// white / gray / black bands and show any combination in 3D — each as a
// see-through wireframe cage or as solid blocks. White is the high-exposure
// geometry (e.g. tessellation struts/caps), gray the mid faces/core, black the
// interior voids (carved core pockets). Two editable thresholds set the splits.
const BAND_SHADE = { white: 0xffffff, gray: 0x8a8a8a, black: 0x4f7ad6 };

function bandControls() {
  const wrap = $("wf3d-bandwrap");
  // Tessellation hides the band picker; the solid style then fills all bands.
  const bands = wrap && wrap.hidden
    ? ["white", "gray", "black"]
    : [...document.querySelectorAll("#wf3d-bands input:checked")].map((i) => i.value);
  const style = document.querySelector("#wf3d-style button.active")?.dataset.style || "cage";
  const tLow = parseInt($("wf3d-tlow")?.value, 10) || 64;
  const tHigh = parseInt($("wf3d-thigh")?.value, 10) || 192;
  return { bands, style, tLow, tHigh };
}

// Which tessellation lattice (if any) the current config describes.
function wfKind() {
  const g = buildConfig().grayscale;
  return g.octet_tessellation ? "octet"
    : g.triangular_tessellation ? "triangular"
    : g.cubic_tessellation ? "cubic" : null;
}

// Show/hide the band picker + the 1:1 slab control by view style. Only the
// procedural strut cage (tessellation + Cage) ignores the exposure bands.
export function updateWfControls() {
  const style = document.querySelector("#wf3d-style button.active")?.dataset.style || "cage";
  const wrap = $("wf3d-bandwrap");
  if (wrap) wrap.hidden = !!wfKind() && style === "cage";
  const slab = $("wf3d-slab");
  if (slab) slab.hidden = style !== "native";
}

function bandOf(v, tLow, tHigh) {
  if (v < tLow) return "black";
  if (v < tHigh) return "gray";
  return "white";
}

// The 12 clean edges of a box (24 verts) as offsets from its centre — used to
// draw each voxel as a crisp cube cage (no triangle diagonals), so internal
// struts read as clear lines rather than a noisy triangulated shell.
function boxEdges(sx, sy, sz) {
  const a = sx / 2, b = sy / 2, c = sz / 2;
  const C = [[-a, -b, -c], [a, -b, -c], [a, b, -c], [-a, b, -c], [-a, -b, c], [a, -b, c], [a, b, c], [-a, b, c]];
  const E = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
  const out = new Float32Array(E.length * 6);
  E.forEach(([p, q], i) => { out.set(C[p], i * 6); out.set(C[q], i * 6 + 3); });
  return out;
}

// Draw a band's voxels as merged cube-edge lines (one geometry, performant).
function cageMesh(pts, sx, sy, sz, mx, my, hh, color) {
  const edge = boxEdges(sx, sy, sz);
  const n = edge.length; // 72 floats per voxel
  const pos = new Float32Array(pts.length * n);
  pts.forEach((v, i) => {
    const ox = v[0] - mx, oy = v[1] - my, oz = v[2] - hh;
    for (let k = 0; k < n; k += 3) {
      pos[i * n + k] = edge[k] + ox;
      pos[i * n + k + 1] = edge[k + 1] + oy;
      pos[i * n + k + 2] = edge[k + 2] + oz;
    }
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  return new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.85 }));
}

// Voxel fetches are cached by config + whether voids are included, so toggling
// bands / style / thresholds re-filters client-side without hitting the server
// (only flipping the black band, which needs voids, triggers a refetch).
async function fetchVoxels(includeVoid) {
  const cfg = buildConfig();
  const key = JSON.stringify(cfg) + "|v" + (includeVoid ? 1 : 0);
  if (three.voxCache && three.voxCache.key === key) return three.voxCache.data;
  // peak: classify each voxel by its brightest pixel so thin white struts
  // inside a mostly-grey cell still show up — keeps the internal lattice.
  const data = await postJSON("/api/voxels", { id: state.id, config: cfg, include_void: includeVoid, peak: true });
  three.voxCache = { key, data };
  return data;
}

async function makeBands() {
  const { bands, style, tLow, tHigh } = bandControls();
  if (!bands.length) return { obj: new THREE.Group(), h: 2, radius: three.meshRadius || 10, hint: "Pick a band — White / Gray / Black" };
  const data = await fetchVoxels(bands.includes("black"));
  const [sx, sy, sz] = data.voxel_size_mm;
  const h = data.height_mm;
  const vs = data.voxels;
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  vs.forEach((v) => { xmin = Math.min(xmin, v[0]); xmax = Math.max(xmax, v[0]); ymin = Math.min(ymin, v[1]); ymax = Math.max(ymax, v[1]); });
  const mx = (xmin + xmax) / 2, my = (ymin + ymax) / 2;
  const group = new THREE.Group();
  const m = new THREE.Matrix4();
  let shown = 0;
  bands.forEach((band) => {
    const pts = vs.filter((v) => bandOf(v[3], tLow, tHigh) === band);
    if (!pts.length) return;
    shown += pts.length;
    if (style === "cage") {
      group.add(cageMesh(pts, sx, sy, sz, mx, my, h / 2, BAND_SHADE[band]));
    } else {
      const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(sx, sy, sz), new THREE.MeshLambertMaterial({ color: BAND_SHADE[band] }), pts.length);
      pts.forEach((v, i) => inst.setMatrixAt(i, m.makeTranslation(v[0] - mx, v[1] - my, v[2] - h / 2)));
      inst.instanceMatrix.needsUpdate = true;
      group.add(inst);
    }
  });
  const radius = Math.max(xmax - xmin, ymax - ymin, h) * 0.8 || 10;
  const vum = Math.round(sx * 1000);
  const hint = `Bands · ${bands.join("+")} · ${shown.toLocaleString()} voxels · ~${vum}µm downsampled preview (use 1:1 for true 35µm)${data.truncated ? " · capped" : ""}`;
  return { obj: group, h, radius, hint };
}

// Procedural strut cage: crisp 3D edges of the cubic/triangular lattice (columns
// + frame triangles/squares), computed server-side from the params. Shows the
// lattice the coarse voxel view can't resolve.
async function makeCage() {
  const data = await postJSON("/api/cage", { id: state.id, config: buildConfig() });
  if (!data.segments.length) {
    return { obj: new THREE.Group(), h: 2, radius: three.meshRadius || 10,
      hint: data.kind ? "Strut cage: nothing inside the part" : "Strut cage is for Cubic / Triangular modes" };
  }
  const segs = data.segments, h = data.height_mm;
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  segs.forEach((s) => { for (let k = 0; k < 6; k += 3) { xmin = Math.min(xmin, s[k]); xmax = Math.max(xmax, s[k]); ymin = Math.min(ymin, s[k + 1]); ymax = Math.max(ymax, s[k + 1]); } });
  const mx = (xmin + xmax) / 2, my = (ymin + ymax) / 2;
  const pos = new Float32Array(segs.length * 6);
  segs.forEach((s, i) => {
    pos[i * 6] = s[0] - mx; pos[i * 6 + 1] = s[1] - my; pos[i * 6 + 2] = s[2] - h / 2;
    pos[i * 6 + 3] = s[3] - mx; pos[i * 6 + 4] = s[4] - my; pos[i * 6 + 5] = s[5] - h / 2;
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 }));
  const group = new THREE.Group();
  group.add(lines);
  const radius = Math.max(xmax - xmin, ymax - ymin, h) * 0.8 || 10;
  return { obj: group, h, radius, hint: `${data.kind} strut cage · ${data.count.toLocaleString()} edges${data.truncated ? " (capped)" : ""}` };
}

// 1:1 machine voxels: every voxel is one print pixel (35×35×50µm), coloured by
// its real exposure band, rendered as solid boxes at exact voxel size so they
// tile seamlessly (no gaps). Bounded to a layer slab + a cap to stay in memory.
// black kept just above the 0x11141a background so the lumen reads as near-black.
const BAND_RGB = { white: [1, 1, 1], gray: [0.54, 0.54, 0.54], black: [0.15, 0.16, 0.19] };
async function makeNative() {
  const { bands, tLow, tHigh } = bandControls();
  if (!bands.length) return { obj: new THREE.Group(), h: 2, radius: three.meshRadius || 10, hint: "Pick a band — White / Gray / Black" };
  const lfrom = parseInt($("wf3d-lfrom")?.value, 10) || 1;
  const lto = parseInt($("wf3d-lto")?.value, 10) || 0;
  const res = await fetch("/api/native", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: state.id, config: buildConfig(), bands, t_low: tLow, t_high: tHigh, layer_from: lfrom, layer_to: lto }),
  });
  if (!res.ok) throw new Error("native voxels failed");
  const meta = JSON.parse(res.headers.get("X-Meta"));
  const buf = await res.arrayBuffer();
  const n = meta.n, pm = meta.pixel_mm, lm = meta.layer_mm, H = meta.height, h = meta.height_mm;
  const cx = new Int16Array(buf, 0, n), cy = new Int16Array(buf, 2 * n, n), cz = new Int16Array(buf, 4 * n, n), cb = new Uint8Array(buf, 6 * n, n);
  const BSHADE = ["white", "gray", "black"];
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  for (let i = 0; i < n; i++) { const x = cx[i] * pm, y = (H - 1 - cy[i]) * pm; if (x < xmin) xmin = x; if (x > xmax) xmax = x; if (y < ymin) ymin = y; if (y > ymax) ymax = y; }
  const mx = (xmin + xmax) / 2, my = (ymin + ymax) / 2;
  // Exact voxel-sized boxes → adjacent voxels touch and cores render solid.
  // Plain material: InstancedMesh applies the per-instance setColorAt() colour
  // automatically (vertexColors would instead look for a per-vertex attribute).
  const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(pm, pm, lm), new THREE.MeshLambertMaterial(), n);
  const m4 = new THREE.Matrix4(), c = new THREE.Color();
  for (let i = 0; i < n; i++) {
    m4.makeTranslation(cx[i] * pm - mx, (H - 1 - cy[i]) * pm - my, (cz[i] - 0.5) * lm - h / 2);
    inst.setMatrixAt(i, m4);
    const rgb = BAND_RGB[BSHADE[cb[i]]] || BAND_RGB.gray;
    inst.setColorAt(i, c.setRGB(rgb[0], rgb[1], rgb[2]));
  }
  inst.instanceMatrix.needsUpdate = true;
  if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  const group = new THREE.Group();
  group.add(inst);
  const radius = Math.max(xmax - xmin, ymax - ymin, (meta.layer_to - meta.layer_from + 1) * lm) * 0.8 || 10;
  const hint = `1:1 machine voxels · ${n.toLocaleString()}${meta.truncated ? " (capped — narrow bands or the layer range)" : ""} · layers ${meta.layer_from}–${meta.layer_to}/${meta.total_layers}`;
  return { obj: group, h, radius, hint };
}

// Dispatch the Wireframe view by style: 1:1 → machine voxels; tessellation +
// Cage → procedural strut cage; otherwise the exposure-band voxel view.
async function makeWireframe() {
  const style = document.querySelector("#wf3d-style button.active")?.dataset.style || "cage";
  if (style === "native") return makeNative();
  if (wfKind() && style === "cage") return makeCage();
  return makeBands();
}

// Force a rebuild of the current built view (e.g. a band control changed, which
// isn't part of the config dedup key).
export function refreshView() {
  if (three && three.mode !== "mesh" && state.id) {
    three.stackKey = null;
    buildView(three.mode);
  }
}

const VIEW_BUILDERS = { stack: makeSlices, wireframe: makeWireframe };
const VIEW_BUSY = { stack: "Building photostack…", wireframe: "Building 3D structure…" };

export async function buildView(mode) {
  if (!state.id || !three) return;
  const key = mode + "|" + JSON.stringify(buildConfig());
  if (three.stack && three.stackKey === key) {
    if (three.mesh) three.mesh.visible = false;
    three.stack.visible = true;
    return;
  }
  $("three-spin").hidden = false;
  $("three-hint").textContent = VIEW_BUSY[mode] || "Building…";
  try {
    const built = await (VIEW_BUILDERS[mode] || makeSlices)();
    disposeStack();
    three.scene.add(built.obj);
    three.stack = built.obj;
    three.stackKey = key;
    if (three.mesh) three.mesh.visible = false;
    three.grid.position.z = -built.h / 2;
    frame(built.radius);
    three.clipR = built.radius;
    three.clipRz = built.h / 2 || 10;
    applyClip();
    $("three-hint").textContent = built.hint;
  } catch (e) {
    $("three-hint").textContent = mode + " failed: " + e.message;
  } finally {
    $("three-spin").hidden = true;
  }
}

export async function setThreeMode(mode) {
  document.querySelectorAll("#three-mode button").forEach((b) => b.classList.toggle("active", b.dataset.tmode === mode));
  const panel = $("wf3d-panel");
  if (panel) panel.hidden = mode !== "wireframe";
  updateWfControls();
  if (!(await loadThreeLibs())) return;
  try { if (!three) initThree(); } catch (e) { return; }
  three.mode = mode;
  if (!state.id) return;
  if (mode === "mesh") {
    if (three.stack) three.stack.visible = false;
    if (three.mesh) { three.mesh.visible = true; three.grid.position.z = three.meshBottom; frame(three.meshRadius); three.clipR = three.meshRadius; three.clipRz = three.meshHalfH; applyClip(); }
    $("three-hint").textContent = "Drag to orbit · scroll to zoom · right-drag to pan";
  } else {
    await buildView(mode);
  }
}
