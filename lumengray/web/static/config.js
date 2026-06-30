// Grayscale config: assemble the request body from the controls, and apply a
// config object back into the controls (used by presets / "load config").

import { $, setVal } from "./core.js";

const int = (id, d) => { const v = parseInt($(id).value, 10); return Number.isFinite(v) ? v : d; };
const num = (id, d) => { const v = parseFloat($(id).value); return Number.isFinite(v) ? v : d; };

export function currentMode() {
  return document.querySelector("#mode-seg button.active").dataset.mode;
}

export function buildConfig() {
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
      core_px: int("t-core", 0),
      boundary_px: int("t-boundary", 3),
      grey_value: int("t-grey", 128),
      white_value: int("t-white", 255),
    };
  } else if (mode === "triangular") {
    config.grayscale.triangular_tessellation = {
      cap_bottom_layers: int("tr-cap-b", 2),
      cap_top_layers: int("tr-cap-t", 2),
      tri_px: int("tr-tri", 10),
      z_layers: int("tr-z", 6),
      shell_px: int("tr-shell", 1),
      core_px: int("tr-core", 0),
      boundary_px: int("tr-boundary", 3),
      grey_value: int("tr-grey", 128),
      white_value: int("tr-white", 255),
    };
  } else if (mode === "octet") {
    config.grayscale.octet_tessellation = {
      cap_bottom_layers: int("oc-cap-b", 2),
      cap_top_layers: int("oc-cap-t", 2),
      cell_xy_px: int("oc-cell-xy", 14),
      cell_z_layers: int("oc-cell-z", 10),
      strut_px: int("oc-strut", 1),
      core_px: int("oc-core", 0),
      boundary_px: int("oc-boundary", 3),
      grey_value: int("oc-grey", 128),
      white_value: int("oc-white", 255),
    };
  }
  return config;
}

export function refreshConfigJson() {
  $("config-json").textContent = JSON.stringify(buildConfig(), null, 2);
}

export function selectMode(mode) {
  document.querySelectorAll("#mode-seg button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  document.querySelectorAll(".mode-panel").forEach((p) => { p.hidden = p.dataset.panel !== mode; });
}

export function applyConfig(c) {
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
    setVal("t-core", t.core_px); setVal("t-boundary", t.boundary_px); setVal("t-grey", t.grey_value); setVal("t-white", t.white_value);
    selectMode("cubic");
  } else if (g.triangular_tessellation) {
    const t = g.triangular_tessellation;
    setVal("tr-cap-b", t.cap_bottom_layers); setVal("tr-cap-t", t.cap_top_layers);
    setVal("tr-tri", t.tri_px); setVal("tr-z", t.z_layers); setVal("tr-shell", t.shell_px);
    setVal("tr-core", t.core_px); setVal("tr-boundary", t.boundary_px); setVal("tr-grey", t.grey_value); setVal("tr-white", t.white_value);
    selectMode("triangular");
  } else if (g.octet_tessellation) {
    const t = g.octet_tessellation;
    setVal("oc-cap-b", t.cap_bottom_layers); setVal("oc-cap-t", t.cap_top_layers);
    setVal("oc-cell-xy", t.cell_xy_px); setVal("oc-cell-z", t.cell_z_layers); setVal("oc-strut", t.strut_px);
    setVal("oc-core", t.core_px); setVal("oc-boundary", t.boundary_px); setVal("oc-grey", t.grey_value); setVal("oc-white", t.white_value);
    selectMode("octet");
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

// keep slider <output> labels in sync with their inputs
export function updateOutputs() {
  const pairs = [["solid-value", "o-solid"], ["g-min", "o-gmin"], ["g-max", "o-gmax"], ["t-grey", "o-grey"], ["t-white", "o-white"], ["tr-grey", "o-trgrey"], ["tr-white", "o-trwhite"], ["oc-grey", "o-ocgrey"], ["oc-white", "o-ocwhite"]];
  pairs.forEach(([inp, out]) => { const o = $(out); if (o) o.textContent = $(inp).value; });
}
