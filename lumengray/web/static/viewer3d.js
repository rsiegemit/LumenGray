// 3D viewer: four orbitable views over the same model — Mesh (the STL),
// Photostack (thin textured slices), Volume (gap-free voxel solid), and
// Lattice (hollow-cube wireframe). three.js is imported lazily so a CDN hiccup
// never breaks the core 2D viewer / export.

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
  three = { renderer, scene, camera, controls, grid, mesh: null, stack: null, stackKey: null, mode: "mesh", meshRadius: 10, meshBottom: 0, clipR: 10 };
  three.clip = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 1e6); // cutaway plane (off by default)
  renderer.clippingPlanes = [three.clip];

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

// Cutaway: slide the clip plane along X. 100 = whole model; lower = cut more away.
export function applyClip() {
  if (!three) return;
  const frac = parseInt($("clip-slider").value, 10) / 100;
  const R = three.clipR || 10;
  three.clip.constant = -R + frac * 2 * R * 1.001;
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
      if (three.mode === "mesh") {
        mesh.visible = true;
        three.grid.position.z = three.meshBottom;
        frame(three.meshRadius);
        three.clipR = three.meshRadius;
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

// Volume: a gap-free voxel solid (full height), shaded by exposure value.
async function makeVolume() {
  const data = await postJSON("/api/voxels", { id: state.id, config: buildConfig() });
  const [sx, sy, sz] = data.voxel_size_mm;
  const h = data.height_mm;
  const vs = data.voxels;
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  vs.forEach((v) => { xmin = Math.min(xmin, v[0]); xmax = Math.max(xmax, v[0]); ymin = Math.min(ymin, v[1]); ymax = Math.max(ymax, v[1]); });
  const mx = (xmin + xmax) / 2, my = (ymin + ymax) / 2;
  const inst = new THREE.InstancedMesh(new THREE.BoxGeometry(sx, sy, sz), new THREE.MeshLambertMaterial(), vs.length);
  const m = new THREE.Matrix4(), col = new THREE.Color();
  vs.forEach((v, i) => {
    inst.setMatrixAt(i, m.makeTranslation(v[0] - mx, v[1] - my, v[2] - h / 2));
    const g = Math.max(0.06, v[3] / 255); // exposure → grayscale; floor so cores stay visible
    inst.setColorAt(i, col.setRGB(g, g, g));
  });
  inst.instanceMatrix.needsUpdate = true;
  if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  const group = new THREE.Group();
  group.add(inst);
  const radius = Math.max(xmax - xmin, ymax - ymin, h) * 0.8 || 10;
  return { obj: group, h, radius, hint: `Volume · ${data.count.toLocaleString()} voxels${data.truncated ? " (capped)" : ""}` };
}

// Lattice: the hollow-cube cage as crisp box edges (cubic-tessellation only).
// Boxes are shrunk slightly so neighbours don't merge — discrete hollow cubes.
const CUBE_CORNERS = [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]];
const CUBE_EDGES = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];

async function makeLattice() {
  const data = await postJSON("/api/lattice", { id: state.id, config: buildConfig() });
  const [sx, sy, sz] = data.cube_size_mm;
  const h = data.height_mm;
  const cs = data.cells;
  let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
  cs.forEach((c) => { xmin = Math.min(xmin, c[0]); xmax = Math.max(xmax, c[0]); ymin = Math.min(ymin, c[1]); ymax = Math.max(ymax, c[1]); });
  const mx = (xmin + xmax) / 2, my = (ymin + ymax) / 2;
  const hx = sx * 0.44, hy = sy * 0.44, hz = sz * 0.44; // 0.88 of cube → visible gap
  const pos = new Float32Array(cs.length * CUBE_EDGES.length * 2 * 3);
  let p = 0;
  cs.forEach((c) => {
    const ox = c[0] - mx, oy = c[1] - my, oz = c[2] - h / 2;
    for (const [a, b] of CUBE_EDGES) {
      const A = CUBE_CORNERS[a], B = CUBE_CORNERS[b];
      pos[p++] = ox + A[0] * hx; pos[p++] = oy + A[1] * hy; pos[p++] = oz + A[2] * hz;
      pos[p++] = ox + B[0] * hx; pos[p++] = oy + B[1] * hy; pos[p++] = oz + B[2] * hz;
    }
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0xf5a623, transparent: true, opacity: 0.75 }));
  const group = new THREE.Group();
  group.add(lines);
  return { obj: group, h, radius: Math.max(xmax - xmin, ymax - ymin, h) * 0.85 || 10, hint: `Lattice · ${data.count.toLocaleString()} cubes${data.truncated ? " (capped)" : ""}` };
}

const VIEW_BUILDERS = { stack: makeSlices, volume: makeVolume, lattice: makeLattice };
const VIEW_BUSY = { stack: "Building photostack…", volume: "Building volume…", lattice: "Building lattice…" };

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
  if (!(await loadThreeLibs())) return;
  try { if (!three) initThree(); } catch (e) { return; }
  three.mode = mode;
  if (!state.id) return;
  if (mode === "mesh") {
    if (three.stack) three.stack.visible = false;
    if (three.mesh) { three.mesh.visible = true; three.grid.position.z = three.meshBottom; frame(three.meshRadius); three.clipR = three.meshRadius; applyClip(); }
    $("three-hint").textContent = "Drag to orbit · scroll to zoom · right-drag to pan";
  } else {
    await buildView(mode);
  }
}
