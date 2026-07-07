// Draggable structure->core ramp editor. X = normalized distance from the struts
// (0 = struts, left) to 1 (core, right); Y = exposure value (255 white top .. 0
// black bottom). Drag points, click empty space to add, double-click to remove.

const NS = "http://www.w3.org/2000/svg";
let stops = [[0, 255], [1, 0]];
let interp = "linear";
let onChange = () => {};
let svg;
const W = 240, H = 112, pad = 12;

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const X = (p) => pad + p * (W - 2 * pad);
const Y = (v) => pad + (1 - v / 255) * (H - 2 * pad);
const toPos = (x) => clamp((x - pad) / (W - 2 * pad), 0, 1);
const toVal = (y) => clamp(Math.round((1 - (y - pad) / (H - 2 * pad)) * 255), 0, 255);

export function initRamp(container, changeCb) {
  onChange = changeCb || (() => {});
  svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.classList.add("ramp-svg");
  svg.addEventListener("pointerdown", onBackgroundDown);
  container.appendChild(svg);
  render();
}

export function getRamp() { return { stops: stops.map((s) => [s[0], s[1]]), interp }; }

export function setRamp(r) {
  if (r && Array.isArray(r.stops) && r.stops.length >= 2) {
    stops = r.stops.map((s) => [s[0], s[1]]).sort((a, b) => a[0] - b[0]);
    interp = r.interp === "step" ? "step" : "linear";
    render();
  }
}

export function setInterp(mode) { interp = mode === "step" ? "step" : "linear"; render(); onChange(); }

function pt(e) {
  const r = svg.getBoundingClientRect();
  return [((e.clientX - r.left) / r.width) * W, ((e.clientY - r.top) / r.height) * H];
}

function onBackgroundDown(e) {
  if (e.target.dataset && e.target.dataset.i !== undefined) return; // a stop handles itself
  const [x, y] = pt(e);
  const s = [toPos(x), toVal(y)];
  stops.push(s);
  stops.sort((a, b) => a[0] - b[0]);
  render();
  onChange();
  startDrag(stops.indexOf(s), e);
}

function startDrag(i, e) {
  e.preventDefault();
  const move = (ev) => {
    const [x, y] = pt(ev);
    const last = stops.length - 1;
    let p = toPos(x);
    if (i === 0) p = 0; else if (i === last) p = 1;
    else p = clamp(p, stops[i - 1][0] + 0.001, stops[i + 1][0] - 0.001);
    stops[i] = [p, toVal(y)];
    render();
    onChange();
  };
  const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function el(name, attrs) {
  const n = document.createElementNS(NS, name);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}

function render() {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const defs = el("defs", {});
  const grad = el("linearGradient", { id: "rampgrad", x1: "0", x2: "1", y1: "0", y2: "0" });
  stops.forEach((s) => { const g = Math.round(s[1]); grad.appendChild(el("stop", { offset: s[0], "stop-color": `rgb(${g},${g},${g})` })); });
  defs.appendChild(grad);
  svg.appendChild(defs);
  svg.appendChild(el("rect", { x: pad, y: H - 8, width: W - 2 * pad, height: 4, fill: "url(#rampgrad)", opacity: "0.9" }));
  svg.appendChild(el("rect", { x: pad, y: pad, width: W - 2 * pad, height: H - 2 * pad - 12, fill: "none", stroke: "#2a323d" }));

  let d = `M ${X(stops[0][0])} ${Y(stops[0][1])}`;
  for (let k = 1; k < stops.length; k++) {
    if (interp === "step") d += ` L ${X(stops[k][0])} ${Y(stops[k - 1][1])} L ${X(stops[k][0])} ${Y(stops[k][1])}`;
    else d += ` L ${X(stops[k][0])} ${Y(stops[k][1])}`;
  }
  svg.appendChild(el("path", { d, class: "ramp-curve" }));

  stops.forEach((s, i) => {
    const c = el("circle", { cx: X(s[0]), cy: Y(s[1]), r: 4.5, class: "ramp-stop" });
    c.dataset.i = i;
    c.addEventListener("pointerdown", (e) => { e.stopPropagation(); startDrag(i, e); });
    c.addEventListener("dblclick", (e) => {
      e.stopPropagation();
      if (stops.length > 2 && i !== 0 && i !== stops.length - 1) { stops.splice(i, 1); render(); onChange(); }
    });
    svg.appendChild(c);
  });
}
