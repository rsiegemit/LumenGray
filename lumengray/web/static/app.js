// Entry point: presets, upload, live 2D preview, export, and event wiring.
// 3D lives in viewer3d.js; config assembly in config.js; helpers in core.js.

import { $, state, status, downloadBlob } from "./core.js";
import { postJSON } from "./api.js";
import { buildConfig, refreshConfigJson, selectMode, applyConfig, updateOutputs } from "./config.js";
import { loadModel3D, setThreeMode, buildView, applyClip, currentViewMode, refreshView, updateWfControls } from "./viewer3d.js";

// ── Presets ──────────────────────────────────────────────
const svg = (inner) =>
  `<svg class="p-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round">${inner}</svg>`;

const SHAPE_ICONS = {
  prism: svg('<rect x="5" y="3" width="11" height="18" rx="1"/><path d="M16 3l4 3v12l-4 3M5 3l4 3v12l-4 3M9 6h11"/>'),
  cube: svg('<path d="M4 8l8-4 8 4-8 4z"/><path d="M4 8v8l8 4 8-4V8M12 12v8"/>'),
  cylinder: svg('<ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v14a7 3 0 0 0 14 0V5"/>'),
  sphere: svg('<circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4a12 6 0 0 0 0 16a12 6 0 0 0 0-16"/>'),
  torus: svg('<ellipse cx="12" cy="12" rx="9" ry="5"/><ellipse cx="12" cy="12" rx="3.5" ry="1.8"/>'),
  cone: svg('<path d="M12 3l8 15H4z"/><ellipse cx="12" cy="18" rx="8" ry="3"/>'),
};

const PRESET_DEFS = {}; // id → preset (incl. params)
let currentPresetId = null;
let dimsTimer = null;

async function loadPresets() {
  try {
    const res = await fetch("/api/presets");
    if (!res.ok) return;
    const items = await res.json();
    const wrap = $("presets");
    wrap.innerHTML = "";
    items.forEach((p) => {
      PRESET_DEFS[p.id] = p;
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

async function loadPreset(id, values = null) {
  status("Building example…", "busy");
  try {
    const data = await postJSON("/api/preset/" + id, { params: values });
    setModel(data);
    document.querySelectorAll(".preset").forEach((el) => el.classList.toggle("active", el.dataset.id === id));
    applyConfig(data.config);
    if (id !== currentPresetId) renderDims(id, data.values); // rebuild only on preset switch (keep focus on edits)
    currentPresetId = id;
    status("Loaded " + data.name);
    loadModel3D(data.id);
    requestPreview();
  } catch (e) {
    status(e.message, "error");
  }
}

// Editable mm dimensions for the active preset; editing regenerates the mesh.
function renderDims(id, values) {
  const def = PRESET_DEFS[id];
  const wrap = $("dims");
  wrap.innerHTML = "";
  if (!def || !def.params || !def.params.length) { $("dims-card").hidden = true; return; }
  def.params.forEach((param) => {
    const label = document.createElement("label");
    label.textContent = param.label;
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0.1";
    input.step = "0.5";
    input.dataset.key = param.key;
    label.title = param.label + " of the model, in mm (regenerates the mesh).";
    input.value = (values && values[param.key] != null ? values[param.key] : param.default);
    input.addEventListener("input", () => {
      clearTimeout(dimsTimer);
      dimsTimer = setTimeout(() => loadPreset(id, collectDims()), 250);
    });
    label.appendChild(input);
    wrap.appendChild(label);
  });
  $("dims-card").hidden = false;
}

function collectDims() {
  const out = {};
  document.querySelectorAll("#dims input").forEach((i) => { out[i.dataset.key] = parseFloat(i.value); });
  return out;
}

// ── Model metadata ───────────────────────────────────────
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
    currentPresetId = null;
    $("dims-card").hidden = true;
    status("Loaded " + data.name);
    loadModel3D(data.id);
    requestPreview();
  } catch (e) {
    status(e.message, "error");
  }
}

// ── Live 2D preview ──────────────────────────────────────
let previewTimer = null;
function schedulePreview() {
  refreshConfigJson();
  if (!state.id) return;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(requestPreview, 120);
}

// Rebuild the open 3D view when parameters change (debounced — the voxel/native
// builds are heavy). No-op unless the 3D tab is showing a built view.
let view3dTimer = null;
function scheduleView3D() {
  const model = document.querySelector('.view[data-view="model"]');
  if (!state.id || !model || model.hidden || currentViewMode() === "mesh") return;
  clearTimeout(view3dTimer);
  view3dTimer = setTimeout(refreshView, 500);
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

// ── 2D zoom / pan ────────────────────────────────────────
const zoomState = { z: 1, x: 0, y: 0, drag: null };

function applyZoom() {
  const img = $("layer-img");
  const maxX = Math.max(0, (zoomState.z - 1) * img.clientWidth / 2);
  const maxY = Math.max(0, (zoomState.z - 1) * img.clientHeight / 2);
  zoomState.x = Math.max(-maxX, Math.min(maxX, zoomState.x));
  zoomState.y = Math.max(-maxY, Math.min(maxY, zoomState.y));
  img.style.transform = `translate(${zoomState.x}px, ${zoomState.y}px) scale(${zoomState.z})`;
  img.classList.toggle("zoomed", zoomState.z > 1);
}

function setZoom(pct) {
  zoomState.z = Math.max(1, pct / 100);
  if (zoomState.z === 1) { zoomState.x = 0; zoomState.y = 0; }
  $("zoom-label").textContent = Math.round(zoomState.z * 100) + "%";
  applyZoom();
}

function wireZoom() {
  $("zoom-slider").addEventListener("input", (e) => setZoom(parseInt(e.target.value, 10)));
  const img = $("layer-img");
  img.addEventListener("pointerdown", (e) => {
    if (zoomState.z <= 1) return;
    e.preventDefault();
    zoomState.drag = { sx: e.clientX, sy: e.clientY, ox: zoomState.x, oy: zoomState.y };
    img.classList.add("dragging");
    img.setPointerCapture(e.pointerId);
  });
  img.addEventListener("pointermove", (e) => {
    if (!zoomState.drag) return;
    zoomState.x = zoomState.drag.ox + (e.clientX - zoomState.drag.sx);
    zoomState.y = zoomState.drag.oy + (e.clientY - zoomState.drag.sy);
    applyZoom();
  });
  const end = () => { zoomState.drag = null; img.classList.remove("dragging"); };
  img.addEventListener("pointerup", end);
  img.addEventListener("pointercancel", end);
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

// ── Wiring ───────────────────────────────────────────────
function wire() {
  $("file-input").addEventListener("change", (e) => uploadFile(e.target.files[0]));
  const dz = $("dropzone");
  ["dragover", "dragenter"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, () => dz.classList.remove("drag")));
  dz.addEventListener("drop", (e) => { e.preventDefault(); uploadFile(e.dataTransfer.files[0]); });

  // every control → live config + 2D preview + (debounced) 3D rebuild. The 3D
  // toolbar controls (bands, cutaway, slab) handle themselves and aren't config.
  document.querySelectorAll("input, #mode-seg button").forEach((el) => {
    if (el.closest(".three-toolbar")) return;
    const evt = el.type === "range" || el.type === "number" || el.type === "text" ? "input" : "change";
    el.addEventListener(evt, () => { updateOutputs(); schedulePreview(); scheduleView3D(); });
  });

  // grayscale-mode segmented control
  document.querySelectorAll("#mode-seg button").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectMode(btn.dataset.mode);
      schedulePreview();
      // a mode change can switch the wireframe between strut-cage and band view
      updateWfControls();
      scheduleView3D();
    });
  });

  // viewer tabs (2D layers / 3D model)
  document.querySelectorAll(".viewer-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".viewer-tabs button").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".view").forEach((v) => { v.hidden = v.dataset.view !== btn.dataset.view; });
      // returning to the 3D tab in a built view picks up any parameter changes
      if (btn.dataset.view === "model" && currentViewMode() !== "mesh" && state.id) buildView(currentViewMode());
    });
  });

  // 3D view-mode toggle + cutaway slider
  document.querySelectorAll("#three-mode button").forEach((btn) => {
    btn.addEventListener("click", () => setThreeMode(btn.dataset.tmode));
  });
  // wireframe band controls (which exposure bands, cage/solid, thresholds) → rebuild the view
  document.querySelectorAll("#wf3d-bands input").forEach((cb) => {
    cb.addEventListener("change", () => {
      cb.closest("label").classList.toggle("on", cb.checked);
      refreshView();
    });
  });
  document.querySelectorAll("#wf3d-style button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#wf3d-style button").forEach((b) => b.classList.toggle("active", b === btn));
      updateWfControls();
      refreshView();
    });
  });
  ["wf3d-tlow", "wf3d-thigh", "wf3d-lfrom", "wf3d-lto"].forEach((id) => $(id).addEventListener("change", refreshView));
  $("clip-slider").addEventListener("input", applyClip);
  $("clip-slider-z").addEventListener("input", applyClip);

  // 2D layer scrubber
  $("layer-slider").addEventListener("input", (e) => { state.index = parseInt(e.target.value, 10); syncSlider(); schedulePreview(); });
  $("prev-layer").addEventListener("click", () => { state.index = Math.max(1, state.index - 1); syncSlider(); schedulePreview(); });
  $("next-layer").addEventListener("click", () => { state.index = Math.min(state.total, state.index + 1); syncSlider(); schedulePreview(); });
  wireZoom();

  $("export-btn").addEventListener("click", exportStack);
  $("copy-config").addEventListener("click", () => navigator.clipboard.writeText($("config-json").textContent).then(() => status("Config copied to clipboard")));
  $("download-config").addEventListener("click", () => downloadBlob(new Blob([$("config-json").textContent], { type: "application/json" }), "lumengray.config.json"));

  updateOutputs();
  refreshConfigJson();
  loadPresets();
}

wire();
