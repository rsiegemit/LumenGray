// Minimal three.js voxel viewer for the calibration chip's 3D view. Renders the
// downsampled (x,y,z,value) voxels from /api/calibration/voxels as an instanced box
// mesh coloured by exposure, with orbit controls.
//
// three.js is imported LAZILY (like viewer3d.js) so a CDN hiccup can never break the
// rest of the app at module-load time.

let THREE = null, OrbitControls = null;
let scene, camera, renderer, controls, mesh, raf, host;

async function ensureThree() {
  if (THREE) return true;
  try {
    THREE = await import("three");
    ({ OrbitControls } = await import("three/addons/controls/OrbitControls.js"));
    return true;
  } catch (e) {
    return false;
  }
}

function init(container) {
  host = container;
  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d1016);
  const w = container.clientWidth || 640, h = container.clientHeight || 480;
  camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 5000);
  renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.AmbientLight(0xffffff, 0.65));
  const dir = new THREE.DirectionalLight(0xffffff, 0.8);
  dir.position.set(1, 2, 1.5);
  scene.add(dir);
  new ResizeObserver(resize).observe(container);
}

function resize() {
  if (!renderer || !host) return;
  const w = host.clientWidth, h = host.clientHeight;
  if (!w || !h) return;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

export async function showCalib3D(container, data) {
  if (!(await ensureThree())) return false;
  if (!renderer) init(container);
  build(data);
  if (!raf) animate();
  resize();
  return true;
}

export function stopCalib3D() {
  if (raf) { cancelAnimationFrame(raf); raf = null; }
}

function build(data) {
  if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); mesh.material.dispose(); mesh = null; }
  const vox = data.voxels || [];
  if (!vox.length) return;
  const [nx, ny, nz] = data.dims;
  const geo = new THREE.BoxGeometry(1, 1, 1);
  // No vertexColors: InstancedMesh.setColorAt drives per-instance colour via
  // instanceColor, which multiplies the material's (white) base colour.
  const mat = new THREE.MeshLambertMaterial({ color: 0xffffff });
  mesh = new THREE.InstancedMesh(geo, mat, vox.length);
  const m = new THREE.Matrix4(), col = new THREE.Color();
  for (let i = 0; i < vox.length; i++) {
    const [x, y, z, v] = vox[i];
    m.setPosition(x - nx / 2, z - nz / 2, y - ny / 2); // model z -> world y (z-up)
    mesh.setMatrixAt(i, m);
    const g = Math.max(0.06, v / 255);
    col.setRGB(g, g, g);
    mesh.setColorAt(i, col);
  }
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  scene.add(mesh);
  const span = Math.max(nx, ny, nz) || 10;
  camera.position.set(span * 1.1, span * 0.9, span * 1.4);
  controls.target.set(0, 0, 0);
  controls.update();
}

function animate() {
  raf = requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
