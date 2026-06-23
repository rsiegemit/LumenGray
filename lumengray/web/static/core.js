// Shared primitives used across modules: DOM lookup, app state, status line, helpers.

export const $ = (id) => document.getElementById(id);

// Single source of truth for the loaded model + layer scrubber position.
export const state = { id: null, total: 1, index: 1, lastUrl: null, controller: null };

export function status(msg, kind = "") {
  const el = $("statusbar");
  el.textContent = msg;
  el.className = "statusbar" + (kind ? " " + kind : "");
}

export const setVal = (id, v) => { if (v !== undefined && v !== null) $(id).value = v; };

export function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
