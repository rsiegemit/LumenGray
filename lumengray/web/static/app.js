// three.js is imported lazily (see initThree) so a CDN hiccup never breaks the
// core 2D viewer / export — the 3D tab simply shows a fallback message.
const $ = (id) => document.getElementById(id);
const state = { id: null, total: 1, index: 1, lastUrl: null, controller: null };

// ── Config assembly ──────────────────────────────────────
function currentMode() {
  return document.querySelector("#mode-seg button.active").dataset.mode;
}

function buildConfig() {
  const config = {
    printer: {
      resolution: [int("res-w", 1920), int("res-h", 1080)],
      pixel_size_um: num("pixel-um", 35),
      layer_height_um: num("layer-um", 50),
    },
    model: {
      center_xy: $("center-xy").checked,
      rotation_deg: [num("rot-x", 0), num("rot-y", 0), num("rot-z", 0)],
    },
    grayscale: {},
  };
  const mode = currentMode();
  if (mode === "uniform") {
    config.grayscale.default_solid_value = int("solid-value", 255);
  } else if (mode === "gradient") {
    config.grayscale.gradient = {
      type: "edge_feather",
      min: int("g-min", 40),
      max: int("g-max", 255),
      falloff_mm: num("g-falloff", 0.35),
    };
  } else if (mode === "cubic") {
    config.grayscale.cubic_tessellation = {
      cap_bottom_layers: int("t-cap-b", 2),
      cap_top_layers: int("t-cap-t", 2),
      cube_xy_px: int("t-cube-xy", 6),
      cube_z_layers: int("t-cube-z", 6),
      shell_px: int("t-shell", 1),
      boundary_um: num("t-boundary", 100),
      grey_value: int("t-grey", 128),
      white_value: int("t-white", 255),
    };
  }
  return config;
}

const int = (id, d) => { const v = parseInt($(id).value, 10); return Number.isFinite(v) ? v : d; };
const num = (id, d) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : d; };

function refreshConfigJson() {
  $("config-json").textContent = JSON.stringify(buildConfig(), null, 2);
}

// ── Status ───────────────────────────────────────────────
function status(msg, kind = "") {
  const el = $("statusbar");
  el.textContent = msg;
  el.className = "statusbar" + (kind ? " " + kind : "");
}

// ── Live preview ─────────────────────────────────────────
let previewTimer = null;
function schedulePreview() {
  refreshConfigJson();
  if (!state.id) return;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(requestPreview, 120);
}

async function requestPreview() {
  if (!state.id) return;
  if (state.controller) state.controller.abort();
  state.controller = new AbortController();
  $("layer-spin").hidden = false;
  status("Slicing layer " + state.index + "…", "busy");
  try {
    const res = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.id, config: buildConfig(), index: state.index }),
      signal: state.controller.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "preview failed");
    }
    const total = parseInt(res.headers.get("X-Total-Layers") || "1", 10);
    const index = parseInt(res.headers.get("X-Layer-Index") || "1", 10);
    setTotal(total);
    state.index = index;
    syncSlider();
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const img = $("layer-img");
    img.onload = () => { if (state.lastUrl) URL.revokeObjectURL(state.lastUrl); state.lastUrl = url; };
    img.src = url;
    img.style.display = "block";
    $("layer-empty").hidden = true;
    status(`Layer ${index} / ${total} · ${buildConfig().printer.resolution.join("×")} px`);
  } catch (e) {
    if (e.name === "AbortError") return;
    status(e.message, "error");
  } finally {
    $("layer-spin").hidden = true;
  }
}

function setTotal(total) {
  state.total = Math.max(1, total);
  const slider = $("layer-slider");
  slider.max = state.total;
  slider.disabled = false;
  if (state.index > state.total) state.index = state.total;
}

function syncSlider() {
  $("layer-slider").value = state.index;
  $("layer-label").textContent = `${state.index} / ${state.total}`;
}

// ── Presets ──────────────────────────────────────────────
const SHAPE_ICONS = {
  prism: svg('<rect x="5" y="3" width="11" height="18" rx="1"/><path d="M16 3l4 3v12l-4 3M5 3l4 3v12l-4 3M9 6h11"/>'),
  cube: svg('<path d="M4 8l8-4 8 4-8 4z"/><path d="M4 8v8l8 4 8-4V8M12 12v8"/>'),
  cylinder: svg('<ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v14a7 3 0 0 0 14 0V5"/>'),
  sphere: svg('<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4a12 6 0 0 0 0 16a12 6 0 0 0 0-16"/>'),
  torus: svg('<ellipse cx="12" cy="12" rx="9" ry="5"/><ellipse cx="12" cy="12" rx="3.5" ry="1.8"/>'),
  cone: svg('<path d="M12 3l8 15H4z"/><ellipse cx="12" cy="18" rx="8" ry="3"/>'),
};
function svg(inner) {
  return `<svg class="p-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round">${inner}</svg>`;
}

async function loadPresets() {
  try {
    const res = await fetch("/api/presets");
    if (!res.ok) return;
    const items = await res.json();
    const wrap = $("presets");
    wrap.innerHTML = "";
    items.forEach((p) => {
      const cubic = p.mode === "cubic_tessellation";
      const cls = p.mode === "gradient" ? "gradient" : cubic ? "" : "uniform";
      const btn = document.createElement("button");
      btn.className = "preset";
      btn.dataset.id = p.id;
      btn.title = p.description;
      btn.innerHTML =
        (SHAPE_ICONS[p.id] || "") +
        `<span class="p-name">${p.name}</span>` +
        `<span class="p-dims">${p.extents_mm.join(" × ")} mm</span>` +
        `<span class="badge ${cls}">${cubic ? "cubic" : p.mode}</span>`;
      btn.addEventListener("click", () => loadPreset(p.id));
      wrap.appendChild(btn);
    });
  } catch (e) { /* presets are optional */ }
}

async function loadPreset(id) {
  status("Loading example…", "busy");
  try {
    const res = await fetch("/api/preset/" + id, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "could not load preset");
    }
    const data = await res.json();
    setModel(data);
    document.querySelectorAll(".preset").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
    applyConfig(data.config);
    status("Loaded " + data.name);
    loadModel3D(data.id);
    requestPreview();
  } catch (e) {
    status(e.message, "error");
  }
}

// ── Apply a config object back into the controls ─────────
function selectMode(mode) {
  document.querySelectorAll("#mode-seg button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  document.querySelectorAll(".mode-panel").forEach((p) => { p.hidden = p.dataset.panel !== mode; });
}
const setVal = (id, v) => { if (v !== undefined && v !== null) $(id).value = v; };

function applyConfig(c) {
  const p = c.printer || {}, m = c.model || {}, g = c.grayscale || {};
  if (p.resolution) { setVal("res-w", p.resolution[0]); setVal("res-h", p.resolution[1]); }
  setVal("pixel-um", p.pixel_size_um);
  setVal("layer-um", p.layer_height_um);
  if (typeof m.center_xy === "boolean") $("center-xy").checked = m.center_xy;
  if (m.rotation_deg) { setVal("rot-x", m.rotation_deg[0]); setVal("rot-y", m.rotation_deg[1]); setVal("rot-z", m.rotation_deg[2]); }
  if (g.cubic_tessellation) {
    const t = g.cubic_tessellation;
    setVal("t-cap-b", t.cap_bottom_layers); setVal("t-cap-t", t.cap_top_layers);
    setVal("t-cube-xy", t.cube_xy_px); setVal("t-cube-z", t.cube_z_layers); setVal("t-shell", t.shell_px);
    setVal("t-boundary", t.boundary_um); setVal("t-grey", t.grey_value); setVal("t-white", t.white_value);
    selectMode("cubic");
  } else if (g.gradient) {
    setVal("g-min", g.gradient.min); setVal("g-max", g.gradient.max); setVal("g-falloff", g.gradient.falloff_mm);
    selectMode("gradient");
  } else {
    setVal("solid-value", g.default_solid_value);
    selectMode("uniform");
  }
  updateOutputs();
  refreshConfigJson();
}

function setModel(data) {
  state.id = data.id;
  state.index = 1;
  $("m-name").textContent = data.name;
  $("m-extents").textContent = data.extents_mm.map((v) => v.toFixed(2)).join(" × ");
  $("m-tris").textContent = data.triangles.toLocaleString();
  $("m-water").textContent = data.watertight ? "yes" : "no — fills may be off";
  $("m-water").style.color = data.watertight ? "var(--good)" : "var(--bad)";
  $("model-meta").hidden = false;
  $("export-btn").disabled = false;
}

// ── Upload ───────────────────────────────────────────────
async function uploadFile(file) {
  if (!file) return;
  status("Uploading " + file.name + "…", "busy");
  const form = new FormData();
  form.append("file", file);
  try {
    const res = await fetch("/api/upload", { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "upload failed");
    }
    const data = await res.json();
    setModel(data);
    document.querySelectorAll(".preset").forEach((el) => el.classList.remove("active"));
    status("Loaded " + data.name);
    loadModel3D(data.id);
    requestPreview();
  } catch (e) {
    status(e.message, "error");
  }
}

// ── 3D viewer ────────────────────────────────────────────
let three = null;
let THREE = null, STLLoader = null, OrbitControls = null;

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
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x223044, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(1, 1.5, 1);
  scene.add(key);
  const grid = new THREE.GridHelper(200, 20, 0x2a323d, 0x1c2229);
  scene.add(grid);
  three = { renderer, scene, camera, controls, grid, mesh: null };

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

async function loadModel3D(id) {
  if (!(await loadThreeLibs())) return;
  const fail = (msg) => { $("model-empty").textContent = msg; $("model-empty").hidden = false; };
  try {
    if (!three) initThree();
  } catch (e) {
    fail("3D view unavailable (WebGL not supported in this browser).");
    return;
  }
  $("model-empty").hidden = true;
  new STLLoader().load(
    "/api/model/" + id,
    (geometry) => {
      if (three.mesh) three.scene.remove(three.mesh);
      geometry.computeVertexNormals();
      geometry.center();
      const material = new THREE.MeshStandardMaterial({ color: 0xf5a623, metalness: 0.1, roughness: 0.6 });
      const mesh = new THREE.Mesh(geometry, material);
      three.scene.add(mesh);
      three.mesh = mesh;
      geometry.computeBoundingSphere();
      const r = geometry.boundingSphere.radius || 10;
      three.camera.position.set(r * 1.8, r * 1.4, r * 1.8);
      three.controls.target.set(0, 0, 0);
      three.grid.position.y = -r;
      three.controls.update();
    },
    undefined,
    () => fail("Could not load the model geometry."),
  );
}

// ── Export ───────────────────────────────────────────────
async function exportStack() {
  if (!state.id) return;
  const btn = $("export-btn");
  btn.disabled = true;
  status("Building full stack (this may take a moment)…", "busy");
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.id, config: buildConfig() }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "export failed");
    }
    const blob = await res.blob();
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="(.+?)"/)?.[1] || "lumengray.zip";
    downloadBlob(blob, name);
    status("Exported " + name + " (" + (blob.size / 1024).toFixed(0) + " KB)");
  } catch (e) {
    status(e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ── Wiring ───────────────────────────────────────────────
function wire() {
  // file input + dropzone
  $("file-input").addEventListener("change", (e) => uploadFile(e.target.files[0]));
  const dz = $("dropzone");
  ["dragover", "dragenter"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, () => dz.classList.remove("drag")));
  dz.addEventListener("drop", (e) => { e.preventDefault(); uploadFile(e.dataTransfer.files[0]); });

  // every control → live config + preview
  document.querySelectorAll("input, #mode-seg button").forEach((el) => {
    const evt = el.type === "range" || el.type === "number" || el.type === "text" ? "input" : "change";
    el.addEventListener(evt, () => {
      updateOutputs();
      schedulePreview();
    });
  });

  // mode segmented
  document.querySelectorAll("#mode-seg button").forEach((btn) => {
    btn.addEventListener("click", () => { selectMode(btn.dataset.mode); schedulePreview(); });
  });

  // viewer tabs
  document.querySelectorAll(".viewer-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".viewer-tabs button").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".view").forEach((v) => { v.hidden = v.dataset.view !== btn.dataset.view; });
      if (btn.dataset.view === "model" && three) three.renderer.domElement.dispatchEvent(new Event("resize"));
    });
  });

  // scrubber
  $("layer-slider").addEventListener("input", (e) => { state.index = parseInt(e.target.value, 10); syncSlider(); schedulePreview(); });
  $("prev-layer").addEventListener("click", () => { state.index = Math.max(1, state.index - 1); syncSlider(); schedulePreview(); });
  $("next-layer").addEventListener("click", () => { state.index = Math.min(state.total, state.index + 1); syncSlider(); schedulePreview(); });

  $("export-btn").addEventListener("click", exportStack);
  $("copy-config").addEventListener("click", () => navigator.clipboard.writeText($("config-json").textContent).then(() => status("Config copied to clipboard")));
  $("download-config").addEventListener("click", () => downloadBlob(new Blob([$("config-json").textContent], { type: "application/json" }), "lumengray.config.json"));

  updateOutputs();
  refreshConfigJson();
  loadPresets();
}

// keep slider <output> labels in sync
function updateOutputs() {
  const pairs = [["solid-value", "o-solid"], ["g-min", "o-gmin"], ["g-max", "o-gmax"], ["t-grey", "o-grey"], ["t-white", "o-white"]];
  pairs.forEach(([inp, out]) => { const o = $(out); if (o) o.textContent = $(inp).value; });
}

wire();
