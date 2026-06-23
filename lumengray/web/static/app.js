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
    state.id = data.id;
    state.index = 1;
    $("m-name").textContent = data.name;
    $("m-extents").textContent = data.extents_mm.map((v) => v.toFixed(2)).join(" × ");
    $("m-tris").textContent = data.triangles.toLocaleString();
    $("m-water").textContent = data.watertight ? "yes" : "no — fills may be off";
    $("m-water").style.color = data.watertight ? "var(--good)" : "var(--bad)";
    $("model-meta").hidden = false;
    $("export-btn").disabled = false;
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
    btn.addEventListener("click", () => {
      document.querySelectorAll("#mode-seg button").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".mode-panel").forEach((p) => { p.hidden = p.dataset.panel !== btn.dataset.mode; });
      schedulePreview();
    });
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
}

// keep slider <output> labels in sync
function updateOutputs() {
  const pairs = [["solid-value", "o-solid"], ["g-min", "o-gmin"], ["g-max", "o-gmax"], ["t-grey", "o-grey"], ["t-white", "o-white"]];
  pairs.forEach(([inp, out]) => { const o = $(out); if (o) o.textContent = $(inp).value; });
}

wire();
