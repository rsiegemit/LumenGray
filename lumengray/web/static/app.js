// Entry point: presets, upload, live 2D preview, export, and event wiring.
// 3D lives in viewer3d.js; config assembly in config.js; helpers in core.js.

import { $, state, status, downloadBlob } from "./core.js";
import { postJSON } from "./api.js";
import { buildConfig, refreshConfigJson, selectMode, applyConfig, updateOutputs, updateGyroidAvail, updateGradeAvail } from "./config.js";
import { loadModel3D, setThreeMode, buildView, applyClip, currentViewMode, refreshView, updateWfControls } from "./viewer3d.js";
import { createRamp, ramp } from "./ramp.js";
import { showCalib3D, stopCalib3D } from "./calib3d.js";

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

// A dropped/picked file is either a model (.stl) or a saved settings file
// (manifest.json / a downloaded config .json). Route by extension.
function handleFile(file) {
  if (!file) return;
  if (/\.json$/i.test(file.name)) loadConfigFile(file);
  else uploadFile(file);
}

// Load a manifest.json (or a downloaded config .json) and apply every setting.
// A manifest also records its source model: if that was a built-in example we
// rebuild it exactly (so the export re-derives the same descriptive name); if it
// was an uploaded STL we can only restore the settings and ask for the STL.
async function loadConfigFile(file) {
  status("Loading " + file.name + "…", "busy");
  let obj;
  try {
    obj = JSON.parse(await file.text());
  } catch (e) {
    status("Couldn't read " + file.name + " — not valid JSON.", "error");
    return;
  }
  if (!obj || !obj.grayscale) {
    status("That file has no LumenGray settings (missing \"grayscale\").", "error");
    return;
  }
  const src = obj.source || {};
  try {
    if (src.kind === "preset" && PRESET_DEFS[src.preset_id]) {
      await loadPreset(src.preset_id, src.dimensions_mm || null); // rebuild the exact model
    }
    applyConfig(obj); // settings on top (overrides the preset's own defaults)
    if (state.id) {
      requestPreview();
      scheduleView3D();
      status("Loaded settings from " + file.name);
    } else if (src.kind === "upload") {
      status("Settings loaded from " + file.name + " — now drop " + (src.filename || "the STL") + " to render.");
    } else {
      status("Settings loaded from " + file.name + " — drop a model to render.");
    }
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

// ── Calibration chip (its own page) ──────────────────────
function buildCalibrationSpec() {
  const i = (id, d) => { const v = parseInt($(id).value, 10); return Number.isFinite(v) ? v : d; };
  return {
    variant: document.querySelector("#calib-variant button.active")?.dataset.variant || "full",
    chip_mm: i("calib-chipmm", 10),
    pyramid_grid: i("calib-pyr", 2),
    checker_min: i("calib-cmin", 0),
    checker_max: i("calib-cmax", 255),
    channel_count: i("calib-chn", 4),
    channel_max_px: i("calib-chw", 8),
    base_layers: i("calib-base", 8),
    feature_layers: i("calib-feat", 16),
    wedge_steps: i("calib-wedge", 16),
    material: $("calib-material").value,
    exposure: $("calib-exposure").value,
  };
}

// Show/hide the calibration page (a full view, separate from the studio).
function setCalibPage(on) {
  $("studio-view").hidden = on;
  $("calib-view").hidden = !on;
  if (on) { applyCalibVariant(); renderCalibPreview(); }
}

// Chip-size applies only to the small chip; the wedge steps only to the full chip.
function applyCalibVariant() {
  const small = document.querySelector("#calib-variant button.active")?.dataset.variant === "small";
  ["calib-chipmm-wrap", "calib-pyr-wrap", "calib-cmin-wrap", "calib-cmax-wrap", "calib-chn-wrap", "calib-chw-wrap"]
    .forEach((id) => { $(id).hidden = !small; });
  $("calib-wedge-wrap").hidden = small;
}

let calibTimer = null;
function scheduleCalibPreview() {
  clearTimeout(calibTimer);
  calibTimer = setTimeout(renderCalibPreview, 150);
}

// Render the calibration preview — the labeled reference map, the gel-only print layer
// (scrubbable), or the 3D chip — per the Reference / Gel print / 3D toggle.
let calibIndex = 1, calibTotal = 1;
function calibView() { return document.querySelector("#calib-view-seg button.active")?.dataset.cview || "reference"; }

async function renderCalibPreview() {
  const spec = buildCalibrationSpec();
  const view = calibView();
  const img = $("calib-img"), threed = $("calib-3d");
  if (view === "3d") {
    img.style.display = "none"; threed.style.display = "block"; $("calib-scrubber").hidden = true;
    status("Building 3D chip…", "busy");
    try {
      const data = await postJSON("/api/calibration/voxels", { config: buildConfig(), spec });
      const ok = await showCalib3D(threed, data);
      status(ok ? `3D chip — ${data.count} voxels${data.truncated ? " (truncated)" : ""}. Drag to orbit.` : "3D unavailable — couldn't load three.js (check your connection).");
    } catch (e) { status(e.message, "error"); }
    return;
  }
  stopCalib3D(); threed.style.display = "none"; img.style.display = "block";
  const isPrint = view === "print";
  $("calib-scrubber").hidden = !isPrint;
  status("Rendering calibration chip…", "busy");
  try {
    const res = await fetch("/api/calibration/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: buildConfig(), spec, view: isPrint ? "print" : "reference", index: calibIndex }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "render failed");
    calibTotal = parseInt(res.headers.get("X-Total-Layers") || "1", 10);
    if (isPrint) {
      calibIndex = Math.min(Math.max(1, calibIndex), calibTotal);
      const slider = $("calib-slider"); slider.max = calibTotal; slider.value = calibIndex;
      $("calib-layer-label").textContent = `${calibIndex} / ${calibTotal}`;
    }
    const blob = await res.blob();
    if (img.dataset.url) URL.revokeObjectURL(img.dataset.url);
    const url = URL.createObjectURL(blob); img.dataset.url = url; img.src = url;
    status(`Calibration chip — ${calibTotal} layers`);
  } catch (e) { status(e.message, "error"); }
}

async function exportCalibration() {
  const btn = $("calib-export");
  btn.disabled = true;
  status("Building calibration photostack…", "busy");
  try {
    const res = await fetch("/api/calibration/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: buildConfig(), spec: buildCalibrationSpec() }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "export failed");
    const blob = await res.blob();
    const name = (res.headers.get("Content-Disposition") || "").match(/filename="(.+?)"/)?.[1] || "LumenX-calibration.zip";
    downloadBlob(blob, name);
    status("Exported " + name + " (" + (blob.size / 1024).toFixed(0) + " KB) — includes manifest.json + measurement.csv");
  } catch (e) {
    status(e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

// Phase 2: a step-by-step measurement wizard → solve → show corrections.
let calibSteps = [], calibStepIdx = 0, calibAnswers = {};

let calibLimits = null;  // small-chip printability limits (for the Phase-3 guardrails)

async function startCalibWizard() {
  const spec = buildCalibrationSpec();
  status("Preparing calibration steps…", "busy");
  try {
    const res = await postJSON("/api/calibration/steps", { config: buildConfig(), spec });
    calibSteps = res.steps || [];
    if (!calibSteps.length) { status("No steps for this chip.", "error"); return; }
    calibStepIdx = 0; calibAnswers = {};
    $("calib-solve-out").hidden = true;
    $("calib-wiz").hidden = false;
    renderWizStep();
    status("Measure each feature and enter the value.");
  } catch (e) { status(e.message, "error"); }
}

function renderWizStep() {
  const s = calibSteps[calibStepIdx], w = $("calib-wiz");
  const prev = calibAnswers[s.id] ?? "";
  const opt = (o, lbl) => `<option value="${o}" ${String(o) === String(prev) ? "selected" : ""}>${lbl}</option>`;
  let input;
  if (s.kind === "resolution" || s.kind === "pick") {
    const none = s.kind === "resolution" ? "— none resolved —" : "— none / didn't print —";
    input = `<select id="calib-wiz-input"><option value="">${none}</option>${s.options.map((o) => opt(o, o + " µm")).join("")}</select>`;
  } else if (s.kind === "yesno") {
    input = `<select id="calib-wiz-input"><option value="">—</option>${opt("yes", "Yes — distinct")}${opt("no", "No — bleeding")}</select>`;
  } else {
    input = `<input type="number" id="calib-wiz-input" step="any" placeholder="measured µm" value="${prev}" />`;
  }
  const last = calibStepIdx === calibSteps.length - 1;
  w.innerHTML = `
    <div class="wiz-head"><span class="badge">${s.group}</span><span class="hint">${calibStepIdx + 1} / ${calibSteps.length}</span></div>
    <p class="wiz-prompt">${s.prompt}</p>
    ${s.nominal_um != null ? `<p class="hint">nominal: ${s.nominal_um} µm</p>` : ""}
    <div class="wiz-input">${input}</div>
    <div class="row">
      <button class="ghost-btn" id="wiz-back" ${calibStepIdx === 0 ? "disabled" : ""}>← Back</button>
      <button class="ghost-btn" id="wiz-skip">Skip</button>
      <button class="primary-btn" id="wiz-next">${last ? "Finish & compute" : "Next →"}</button>
    </div>`;
  const store = () => { const v = $("calib-wiz-input").value; if (v !== "") calibAnswers[s.id] = v; else delete calibAnswers[s.id]; };
  $("calib-wiz-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("wiz-next").click(); });
  $("calib-wiz-input").focus();
  $("wiz-back").addEventListener("click", () => { store(); calibStepIdx--; renderWizStep(); });
  $("wiz-skip").addEventListener("click", () => { delete calibAnswers[s.id]; advanceWiz(); });
  $("wiz-next").addEventListener("click", () => { store(); advanceWiz(); });
}

function advanceWiz() {
  if (calibStepIdx < calibSteps.length - 1) { calibStepIdx++; renderWizStep(); }
  else finishCalibWizard();
}

// Small chip: the answers ARE the printability limits — record them (they become the
// Phase-3 guardrails). No fitting, no photostack mutation.
function finishCalibSmall() {
  const a = calibAnswers, num = (v) => (v ? +v : null);
  calibLimits = {
    min_pillar_um: num(a.min_pillar),
    min_well_um: num(a.min_well),
    min_channel_um: num(a.min_channel),
    checker_ok: a.checker_ok || null,
  };
  $("calib-wiz").hidden = true;
  const out = $("calib-solve-out");
  out.hidden = false;
  const L = calibLimits, row = (k, v, u) => `<tr><td>${k}</td><td>${v != null ? v + (u || "") : "—"}</td></tr>`;
  out.innerHTML = `
    <h3>Printability limits</h3>
    <table class="calib-tbl">
      ${row("Min printable pillar", L.min_pillar_um, " µm")}
      ${row("Min open well", L.min_well_um, " µm")}
      ${row("Min open channel", L.min_channel_um, " µm")}
      ${row("Grayscale checker distinct", L.checker_ok === "yes" ? "yes" : L.checker_ok === "no" ? "no" : null, "")}
    </table>
    <p class="hint">These become guardrails: on export, any feature below a limit is flagged for you to allow a fix (coming next).</p>`;
  status("Printability limits recorded.");
}

// Build solve-compatible CSV rows from the collected answers, then solve.
async function finishCalibWizard() {
  if (buildCalibrationSpec().variant === "small") { finishCalibSmall(); return; }
  const lines = ["zone,id,axis,design_gray,nominal_um,measured_um,notes"];
  const resStep = calibSteps.find((s) => s.kind === "resolution");
  for (const s of calibSteps) {
    if (s.kind === "resolution") continue;
    const v = calibAnswers[s.id];
    if (v == null || v === "") continue;
    lines.push(`${s.zone},${s.id},${s.axis},${s.design_gray},${s.nominal_um},${v},`);
  }
  if (resStep) {
    const finest = parseFloat(calibAnswers[resStep.id]);
    if (Number.isFinite(finest)) resStep.options.forEach((o, i) => lines.push(`grating,w${i},pitch,255,${o},,${o >= finest ? "y" : "n"}`));
  }
  status("Computing corrections…", "busy");
  try {
    const res = await postJSON("/api/calibration/solve", { config: buildConfig(), csv: lines.join("\n") });
    $("calib-wiz").hidden = true;
    const out = $("calib-solve-out");
    out.hidden = false;
    out.innerHTML = renderSolveResult(res);
    const ap = document.getElementById("calib-apply-pitch");
    if (ap) ap.addEventListener("click", () => {
      const set = (id, val) => { $(id).value = val; $(id).dispatchEvent(new Event("input", { bubbles: true })); };
      set("voxel-width-um", ap.dataset.x); set("voxel-length-um", ap.dataset.y);
      status(`Applied true pitch ${ap.dataset.x} / ${ap.dataset.y} µm to the Printer card.`);
    });
    status("Calibration computed.");
  } catch (e) { status(e.message, "error"); }
}

function renderSolveResult(res) {
  const s = res.scale || {};
  const axisRow = (a) => s[a]
    ? `<b>${a}:</b> true pitch <b>${s[a].true_pitch_um} µm</b> <span class="hint">(assumed ${s[a].assumed_pitch_um}, scale ×${s[a].scale}, R²=${s[a].r2}, n=${s[a].n})</span>`
    : `<b>${a}:</b> <span class="hint">— need ≥2 measured scale features</span>`;
  const bloom = (res.bloom?.curve || []).map((p) => `<tr><td>${p.gray}</td><td>${p.bloom_um} µm</td></tr>`).join("");
  const th = res.threshold || {}, rz = res.resolution || {};
  const applyBtn = s.X ? `<button class="ghost-btn" id="calib-apply-pitch" data-x="${s.X.true_pitch_um}" data-y="${(s.Y || s.X).true_pitch_um}">Apply true pitch to the Printer card</button>` : "";
  return `
    <h3>Scale / pixel pitch</h3>
    <p>${axisRow("X")}</p><p>${axisRow("Y")}</p>${applyBtn}
    <h3>Gray → lateral bloom</h3>
    ${bloom ? `<table class="calib-tbl"><tr><th>gray</th><th>bloom radius</th></tr>${bloom}</table>` : "<p class='hint'>no matrix measurements found</p>"}
    <h3>Limits</h3>
    <p>Cure threshold g_min: <b>${th.g_min ?? "—"}</b>${th.vanished_grays?.length ? ` <span class="hint">· vanished: ${th.vanished_grays.join(", ")}</span>` : ""}</p>
    <p>Finest resolved: <b>${rz.finest_resolved_um ?? "—"} µm</b></p>
    ${res.warnings?.length ? `<p class="hint">⚠ ${res.warnings.join("; ")}</p>` : ""}`;
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
    img.onload = () => { if (state.lastUrl) URL.revokeObjectURL(state.lastUrl); state.lastUrl = url; updateScaleBar(); };
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
  updateScaleBar();
}

// Physical scale bar for the layer preview: on-screen pixels → mm via the XY voxel
// size, accounting for how the full-res PNG is fit to the box and the current zoom.
// Picks a "nice" 1/2/5×10ⁿ length near ~90 px. Reflects the SAME 35 µm pitch the
// slicer assumes, so it's a direct sanity check on real-world dimensions.
function updateScaleBar() {
  const bar = $("scale-bar");
  const img = $("layer-img");
  if (!$("scale-on").checked || img.style.display === "none" || !img.naturalWidth) { bar.hidden = true; return; }
  const rect = img.getBoundingClientRect();           // on-screen size, includes the zoom transform
  const voxelMm = (buildConfig().printer.voxel_width_um || 35) / 1000;
  const pxPerMm = (rect.width / img.naturalWidth) / voxelMm;
  if (!isFinite(pxPerMm) || pxPerMm <= 0) { bar.hidden = true; return; }
  const rawMm = 90 / pxPerMm;                          // mm that ~90 screen px represents
  const pow = Math.pow(10, Math.floor(Math.log10(rawMm)));
  const frac = rawMm / pow;
  const niceMm = (frac < 1.5 ? 1 : frac < 3.5 ? 2 : frac < 7.5 ? 5 : 10) * pow;
  bar.hidden = false;
  $("scale-bar-label").textContent = niceMm >= 1 ? `${+niceMm.toFixed(2)} mm` : `${Math.round(niceMm * 1000)} µm`;
  bar.querySelector(".scale-bar-line").style.width = (niceMm * pxPerMm) + "px";
}

// Drag the scale bar anywhere over the preview so it can be laid alongside a
// feature to measure it. Position is clamped to the canvas box.
function wireScaleDrag() {
  const bar = $("scale-bar");
  let drag = null;
  bar.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    const b = bar.getBoundingClientRect();
    drag = { dx: e.clientX - b.left, dy: e.clientY - b.top };
    bar.classList.add("dragging");
    bar.setPointerCapture(e.pointerId);
  });
  bar.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const wrap = bar.parentElement.getBoundingClientRect();
    const left = Math.max(0, Math.min(wrap.width - bar.offsetWidth, e.clientX - drag.dx - wrap.left));
    const top = Math.max(0, Math.min(wrap.height - bar.offsetHeight, e.clientY - drag.dy - wrap.top));
    bar.style.left = left + "px";
    bar.style.top = top + "px";
    bar.style.bottom = "auto";
  });
  const end = () => { drag = null; bar.classList.remove("dragging"); };
  bar.addEventListener("pointerup", end);
  bar.addEventListener("pointercancel", end);
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
// Phase-3 guardrail: if printability limits are loaded, check the design and return
// the flagged categories (mutates nothing).
async function checkPrintability() {
  try {
    const chk = await postJSON("/api/printability-check", { id: state.id, config: buildConfig(), limits: calibLimits });
    const flags = [];
    if (chk.pillar?.below) flags.push({ key: "pillar", title: "Features below the minimum printable size", detail: `${chk.pillar.pct}% of the cured area is thinner than ${chk.pillar.limit_um} µm — those features may not print / may vanish.` });
    if (chk.channel?.below) flags.push({ key: "channel", title: "Channels / voids below the minimum open width", detail: `${chk.channel.pct}% of the void area is narrower than ${chk.channel.limit_um} µm — those channels may fuse shut.` });
    return flags;
  } catch (e) { status(e.message, "error"); return []; }
}

// Blocking warning modal with a per-category "Allow fix" checkbox. Resolves the set of
// allowed fixes {fix_pillar, fix_channel}, or null if the user cancels.
function showPrintWarning(flags) {
  return new Promise((resolve) => {
    $("print-warn-body").innerHTML = flags.map((f) =>
      `<div class="warn-item"><h3>⚠️ ${f.title}</h3><p class="hint">${f.detail}</p>
       <label><input type="checkbox" class="warn-allow" data-fix="${f.key}" /> Allow grow-to-min fix for this</label></div>`).join("");
    const modal = $("print-warn"), cancel = $("print-warn-cancel"), proceed = $("print-warn-proceed");
    modal.hidden = false;
    const done = (v) => { modal.hidden = true; cancel.removeEventListener("click", onCancel); proceed.removeEventListener("click", onProceed); resolve(v); };
    const onCancel = () => done(null);
    const onProceed = () => {
      const allow = {};
      document.querySelectorAll(".warn-allow").forEach((cb) => { if (cb.checked) allow["fix_" + cb.dataset.fix] = true; });
      done(allow);
    };
    cancel.addEventListener("click", onCancel); proceed.addEventListener("click", onProceed);
  });
}

async function exportStack() {
  if (!state.id) return;
  const cfg = buildConfig();
  if (calibLimits) {
    const flags = await checkPrintability();
    if (flags.length) {
      const allow = await showPrintWarning(flags);
      if (!allow) { status("Export cancelled."); return; }
      if (allow.fix_pillar || allow.fix_channel) {
        cfg.grayscale.min_feature = {
          fix_pillar: !!allow.fix_pillar,
          fix_channel: !!allow.fix_channel,
          min_pillar_um: calibLimits.min_pillar_um || 0,
          min_channel_um: calibLimits.min_channel_um || 0,
        };
      }
    }
  }
  const btn = $("export-btn");
  btn.disabled = true;
  status(cfg.grayscale.min_feature ? "Building stack with grow-to-min fixes…" : "Building full stack (this may take a moment)…", "busy");
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: state.id, config: cfg }),
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
  $("file-input").addEventListener("change", (e) => handleFile(e.target.files[0]));
  const dz = $("dropzone");
  ["dragover", "dragenter"].forEach((t) => dz.addEventListener(t, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((t) => dz.addEventListener(t, () => dz.classList.remove("drag")));
  dz.addEventListener("drop", (e) => { e.preventDefault(); handleFile(e.dataTransfer.files[0]); });

  // "Load .json": restore settings (and the model, for example-based manifests)
  $("load-config").addEventListener("click", () => $("config-file").click());
  $("config-file").addEventListener("change", (e) => { loadConfigFile(e.target.files[0]); e.target.value = ""; });

  // every control → live config + 2D preview + (debounced) 3D rebuild. The 3D
  // toolbar controls (bands, cutaway, slab) handle themselves and aren't config.
  document.querySelectorAll("input, select, #mode-seg button").forEach((el) => {
    if (el.closest(".three-toolbar")) return;
    const evt = el.type === "range" || el.type === "number" || el.type === "text" ? "input" : "change";
    el.addEventListener(evt, () => { updateOutputs(); updateGyroidAvail(); schedulePreview(); scheduleView3D(); });
  });

  // grayscale-mode segmented control
  document.querySelectorAll("#mode-seg button").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectMode(btn.dataset.mode);
      updateGradeAvail();   // grade only applies to tessellation modes
      updateGyroidAvail();  // a mode without cores disables Connect voids
      schedulePreview();
      // a mode change can switch the wireframe between strut-cage and band view
      updateWfControls();
      scheduleView3D();
    });
  });

  // gyroid void-connector overlay: show/hide its params (rebuild is handled by
  // the generic input listener above)
  $("gyroid-on").addEventListener("change", () => { $("gyroid-params").hidden = !$("gyroid-on").checked; });

  // structure→core gradient: the draggable ramp editor + linear/step toggle
  const gradeCb = () => { updateGyroidAvail(); refreshConfigJson(); schedulePreview(); scheduleView3D(); };
  createRamp("grade", $("ramp-editor"), $("ramp-stops"), gradeCb);
  $("grade-on").addEventListener("change", () => { $("grade-params").hidden = !$("grade-on").checked; });
  document.querySelectorAll("#grade-interp button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#grade-interp button").forEach((b) => b.classList.toggle("active", b === btn));
      ramp("grade").setInterp(btn.dataset.interp); // triggers the ramp onChange → rebuild
    });
  });

  // base gradient: its own ramp editor + radial/linear mode + x/y/z axis + interp
  const gradCb = () => { refreshConfigJson(); schedulePreview(); scheduleView3D(); };
  createRamp("gradient", $("grad-ramp-editor"), $("grad-ramp-stops"), gradCb);
  const syncGradLabels = () => {
    const linear = document.querySelector("#grad-mode button.active")?.dataset.gmode === "linear";
    $("grad-axis-wrap").hidden = !linear;
    $("grad-ax-lo").textContent = linear ? "start" : "centre";
    $("grad-ax-hi").textContent = linear ? "end" : "edge";
  };
  document.querySelectorAll("#grad-mode button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#grad-mode button").forEach((b) => b.classList.toggle("active", b === btn));
      syncGradLabels(); gradCb();
    });
  });
  document.querySelectorAll("#grad-axis button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#grad-axis button").forEach((b) => b.classList.toggle("active", b === btn));
      gradCb();
    });
  });
  document.querySelectorAll("#grad-interp button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#grad-interp button").forEach((b) => b.classList.toggle("active", b === btn));
      ramp("gradient").setInterp(btn.dataset.interp);
    });
  });
  syncGradLabels();

  // viewer tabs (2D layers / 3D model)
  document.querySelectorAll(".viewer-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".viewer-tabs button").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".view").forEach((v) => { v.hidden = v.dataset.view !== btn.dataset.view; });
      // returning to the 3D tab in a built view picks up any parameter changes
      if (btn.dataset.view === "model" && currentViewMode() !== "mesh" && state.id) buildView(currentViewMode());
      if (btn.dataset.view === "layers") updateScaleBar();
    });
  });

  // 3D view-mode toggle + cutaway slider
  document.querySelectorAll("#three-mode button").forEach((btn) => {
    btn.addEventListener("click", () => setThreeMode(btn.dataset.tmode));
  });
  // band controls (which exposure bands + thresholds + 1:1 slab) → rebuild the view
  document.querySelectorAll("#wf3d-bands input").forEach((cb) => {
    cb.addEventListener("change", () => {
      cb.closest("label").classList.toggle("on", cb.checked);
      refreshView();
    });
  });
  ["wf3d-tlow", "wf3d-thigh", "wf3d-lfrom", "wf3d-lto"].forEach((id) => $(id).addEventListener("change", refreshView));
  $("clip-slider").addEventListener("input", applyClip);
  $("clip-slider-z").addEventListener("input", applyClip);

  // calibration chip: its own page (header button), fully separate from the studio
  $("calib-btn").addEventListener("click", () => setCalibPage(true));
  $("calib-back").addEventListener("click", () => setCalibPage(false));
  $("calib-export").addEventListener("click", exportCalibration);
  $("calib-wiz-start").addEventListener("click", startCalibWizard);
  ["calib-chipmm", "calib-pyr", "calib-cmin", "calib-cmax", "calib-chn", "calib-chw", "calib-base", "calib-feat", "calib-wedge", "calib-material", "calib-exposure"].forEach((id) =>
    $(id).addEventListener("input", scheduleCalibPreview));
  document.querySelectorAll("#calib-view-seg button").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll("#calib-view-seg button").forEach((b) => b.classList.toggle("active", b === btn));
      if (btn.dataset.cview === "print") {  // start mid-stack so 3D features show their taper
        const s = buildCalibrationSpec();
        calibIndex = (s.base_layers || 1) + Math.max(1, Math.floor((s.feature_layers || 2) / 2));
      }
      renderCalibPreview();
    }));
  const scrub = (i) => { calibIndex = Math.min(Math.max(1, i), calibTotal); $("calib-slider").value = calibIndex; $("calib-layer-label").textContent = `${calibIndex} / ${calibTotal}`; scheduleCalibPreview(); };
  $("calib-slider").addEventListener("input", (e) => scrub(parseInt(e.target.value, 10)));
  $("calib-prev").addEventListener("click", () => scrub(calibIndex - 1));
  $("calib-next").addEventListener("click", () => scrub(calibIndex + 1));
  document.querySelectorAll("#calib-variant button").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll("#calib-variant button").forEach((b) => b.classList.toggle("active", b === btn));
      applyCalibVariant();
      renderCalibPreview();
    }));
  applyCalibVariant();

  // physical scale bar on the layer preview (toggle + drag to reposition)
  $("scale-on").addEventListener("change", updateScaleBar);
  window.addEventListener("resize", updateScaleBar);
  wireScaleDrag();

  // 2D layer scrubber
  $("layer-slider").addEventListener("input", (e) => { state.index = parseInt(e.target.value, 10); syncSlider(); schedulePreview(); });
  $("prev-layer").addEventListener("click", () => { state.index = Math.max(1, state.index - 1); syncSlider(); schedulePreview(); });
  $("next-layer").addEventListener("click", () => { state.index = Math.min(state.total, state.index + 1); syncSlider(); schedulePreview(); });
  wireZoom();

  $("update-btn").addEventListener("click", checkForUpdates);
  $("export-btn").addEventListener("click", exportStack);
  $("copy-config").addEventListener("click", () => navigator.clipboard.writeText($("config-json").textContent).then(() => status("Config copied to clipboard")));
  $("download-config").addEventListener("click", () => downloadBlob(new Blob([$("config-json").textContent], { type: "application/json" }), "lumengray.config.json"));

  updateOutputs();
  updateGradeAvail();
  updateGyroidAvail();
  refreshConfigJson();
  loadPresets();
}

// Ask the server to compare our version to the latest GitHub release. Read-only:
// on an update it just surfaces a download link — the user runs the installer.
async function checkForUpdates() {
  const banner = $("update-banner");
  banner.hidden = true;
  status("Checking for updates…", "busy");
  try {
    const d = await fetch("/api/check-update").then((r) => r.json());
    if (!d.ok) { status(d.error || "Update check failed.", "error"); return; }
    if (d.update_available) {
      const isWin = /Win/i.test(navigator.userAgent) || /Win/i.test(navigator.platform || "");
      const url = isWin ? d.windows_installer_url : d.releases_url;
      banner.innerHTML =
        `A new version is available: <strong>v${d.latest}</strong> (you have v${d.current}). ` +
        `<a href="${url}" target="_blank" rel="noopener">Download ↗</a> — then run the installer to update.`;
      banner.hidden = false;
      status(`Update available: v${d.latest}`);
    } else {
      status(`You're on the latest version (v${d.current}).`);
    }
  } catch (e) {
    status("Update check failed.", "error");
  }
}

wire();
