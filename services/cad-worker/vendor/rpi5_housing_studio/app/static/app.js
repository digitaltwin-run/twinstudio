import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

const elements = {
  llmBadge: document.getElementById('llmBadge'),
  promptInput: document.getElementById('promptInput'),
  interpretButton: document.getElementById('interpretButton'),
  interpretMessage: document.getElementById('interpretMessage'),
  resetConfigButton: document.getElementById('resetConfigButton'),
  downloadConfigButton: document.getElementById('downloadConfigButton'),
  uploadConfigInput: document.getElementById('uploadConfigInput'),
  configEditor: document.getElementById('configEditor'),
  configStatus: document.getElementById('configStatus'),
  generateButton: document.getElementById('generateButton'),
  generationProgress: document.getElementById('generationProgress'),
  messageBanner: document.getElementById('messageBanner'),
  viewer: document.getElementById('viewer'),
  viewerPlaceholder: document.getElementById('viewerPlaceholder'),
  lidAngle: document.getElementById('lidAngle'),
  lidAngleValue: document.getElementById('lidAngleValue'),
  openLidButton: document.getElementById('openLidButton'),
  resetCameraButton: document.getElementById('resetCameraButton'),
  drawingPart: document.getElementById('drawingPart'),
  drawingView: document.getElementById('drawingView'),
  drawingPreview: document.getElementById('drawingPreview'),
  drawingPlaceholder: document.getElementById('drawingPlaceholder'),
  warningList: document.getElementById('warningList'),
  metricsGrid: document.getElementById('metricsGrid'),
  artifactList: document.getElementById('artifactList'),
  bundleButton: document.getElementById('bundleButton'),
};

const state = {
  config: null,
  manifest: null,
  scene: null,
  camera: null,
  renderer: null,
  controls: null,
  baseMesh: null,
  lidMesh: null,
  lidPivot: null,
  modelRoot: null,
  defaultCameraPosition: new THREE.Vector3(150, -175, 115),
};

function setLlmBadge() {
  const configured = document.body.dataset.litellmConfigured === 'true';
  elements.llmBadge.textContent = configured ? 'LiteLLM skonfigurowany' : 'LiteLLM: tryb fallback';
  elements.llmBadge.title = configured
    ? 'Opis naturalny będzie interpretowany przez model ustawiony w LITELLM_MODEL.'
    : 'Brak LITELLM_MODEL. Działa ostrożny parser wymiarów i warstw bez połączenia z modelem.';
}

function showBanner(message, kind = 'info') {
  elements.messageBanner.textContent = message;
  elements.messageBanner.className = `message-banner ${kind}`;
}

function hideBanner() {
  elements.messageBanner.className = 'message-banner hidden';
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail || payload);
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

function prettyConfig(config) {
  return JSON.stringify(config, null, 2);
}

function parseEditorConfig() {
  try {
    const parsed = JSON.parse(elements.configEditor.value);
    elements.configStatus.textContent = 'JSON jest poprawny składniowo.';
    elements.configStatus.className = 'status-line ok';
    return parsed;
  } catch (error) {
    elements.configStatus.textContent = `Błąd JSON: ${error.message}`;
    elements.configStatus.className = 'status-line error';
    throw error;
  }
}

function setConfig(config) {
  state.config = config;
  elements.configEditor.value = prettyConfig(config);
  elements.configStatus.textContent = 'Konfiguracja gotowa.';
  elements.configStatus.className = 'status-line ok';
}

function humanBytes(bytes) {
  if (!Number.isFinite(bytes)) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function renderWarnings(warnings = []) {
  elements.warningList.innerHTML = '';
  if (!warnings.length) {
    elements.warningList.innerHTML = '<div class="placeholder">Brak ostrzeżeń.</div>';
    return;
  }
  warnings.forEach((warning) => {
    const item = document.createElement('div');
    item.className = `warning-item ${warning.severity || 'info'}`;
    const suggestion = warning.suggestion ? `<small>${escapeHtml(warning.suggestion)}</small>` : '';
    item.innerHTML = `
      <strong>${escapeHtml((warning.severity || 'info').toUpperCase())} / ${escapeHtml(warning.code || '')}</strong>
      <p>${escapeHtml(warning.message || '')}</p>
      ${suggestion}
    `;
    elements.warningList.appendChild(item);
  });
}

function renderMetrics(metrics = {}) {
  elements.metricsGrid.innerHTML = '';
  const entries = [];
  Object.entries(metrics).forEach(([key, value]) => {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      Object.entries(value).forEach(([subKey, subValue]) => entries.push([`${key}.${subKey}`, subValue]));
    } else {
      entries.push([key, value]);
    }
  });
  entries.forEach(([key, value]) => {
    const card = document.createElement('div');
    card.className = 'metric';
    const display = typeof value === 'number' ? value.toFixed(2) : String(value);
    card.innerHTML = `<span>${escapeHtml(key.replaceAll('_', ' '))}</span><strong>${escapeHtml(display)}</strong>`;
    elements.metricsGrid.appendChild(card);
  });
}

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = String(value);
  return div.innerHTML;
}

function renderArtifacts(manifest) {
  const artifacts = manifest?.artifacts || [];
  elements.artifactList.innerHTML = '';
  if (!artifacts.length) {
    elements.artifactList.innerHTML = '<div class="placeholder">Brak artefaktów.</div>';
    return;
  }
  const groups = new Map();
  artifacts.forEach((artifact) => {
    if (!groups.has(artifact.category)) groups.set(artifact.category, []);
    groups.get(artifact.category).push(artifact);
  });
  [...groups.entries()].forEach(([category, files]) => {
    const group = document.createElement('div');
    group.className = 'artifact-group';
    const rows = files.map((file) => `
      <div class="artifact-row">
        <div class="name">
          <strong>${escapeHtml(file.label)}</strong>
          <small>${escapeHtml(file.path)}</small>
        </div>
        <span class="size">${humanBytes(file.size_bytes)}</span>
        <a class="button secondary" href="${file.url}" download>Pobierz</a>
      </div>
    `).join('');
    group.innerHTML = `<h3>${escapeHtml(category)}</h3>${rows}`;
    elements.artifactList.appendChild(group);
  });

  if (manifest.bundle_url) {
    elements.bundleButton.href = manifest.bundle_url;
    elements.bundleButton.classList.remove('hidden');
    elements.bundleButton.setAttribute('download', 'housing_project_bundle.zip');
  } else {
    elements.bundleButton.classList.add('hidden');
  }
}

function updateDrawingPreview() {
  const manifest = state.manifest;
  if (!manifest) return;
  const part = elements.drawingPart.value;
  const view = elements.drawingView.value;
  const suffix = `2d/${part}/${part}_${view}.svg`;
  const artifact = manifest.artifacts.find((item) => item.path === suffix);
  if (!artifact) {
    elements.drawingPreview.style.display = 'none';
    elements.drawingPlaceholder.style.display = 'grid';
    elements.drawingPlaceholder.textContent = 'Wybrany podgląd SVG nie został wygenerowany.';
    return;
  }
  elements.drawingPreview.src = `${artifact.url}?v=${Date.now()}`;
  elements.drawingPreview.style.display = 'block';
  elements.drawingPlaceholder.style.display = 'none';
}

function initViewer() {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 5000);
  camera.up.set(0, 0, 1);
  camera.position.copy(state.defaultCameraPosition);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  elements.viewer.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.target.set(40, 45, 18);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x334155, 2.0));
  const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
  keyLight.position.set(120, -90, 180);
  keyLight.castShadow = true;
  scene.add(keyLight);
  const fillLight = new THREE.DirectionalLight(0xaac8ff, 1.1);
  fillLight.position.set(-100, 110, 80);
  scene.add(fillLight);

  const grid = new THREE.GridHelper(260, 26, 0x657187, 0x394458);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = -0.2;
  scene.add(grid);

  const axes = new THREE.AxesHelper(24);
  scene.add(axes);

  const modelRoot = new THREE.Group();
  scene.add(modelRoot);

  state.scene = scene;
  state.camera = camera;
  state.renderer = renderer;
  state.controls = controls;
  state.modelRoot = modelRoot;

  const resize = () => {
    const width = elements.viewer.clientWidth;
    const height = Math.max(360, elements.viewer.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  const resizeObserver = new ResizeObserver(resize);
  resizeObserver.observe(elements.viewer);
  resize();

  const animate = () => {
    requestAnimationFrame(animate);
    controls.update();
    renderer.render(scene, camera);
  };
  animate();
}

function clearModels() {
  [state.baseMesh, state.lidMesh].forEach((mesh) => {
    if (mesh) {
      mesh.geometry?.dispose();
      mesh.material?.dispose();
    }
  });
  if (state.modelRoot) state.modelRoot.clear();
  state.baseMesh = null;
  state.lidMesh = null;
  state.lidPivot = null;
}

function stlGeometry(url) {
  const loader = new STLLoader();
  return new Promise((resolve, reject) => {
    loader.load(url, (geometry) => {
      geometry.computeVertexNormals();
      resolve(geometry);
    }, undefined, reject);
  });
}

async function load3dPreview(manifest) {
  const baseUrl = manifest?.preview?.base_stl_url;
  const lidUrl = manifest?.preview?.lid_stl_url;
  if (!baseUrl || !lidUrl) {
    throw new Error('Manifest nie zawiera plików STL do podglądu.');
  }
  clearModels();
  elements.viewerPlaceholder.textContent = 'Ładowanie geometrii STL…';
  elements.viewerPlaceholder.style.display = 'grid';

  const [baseGeometry, lidGeometry] = await Promise.all([
    stlGeometry(`${baseUrl}?v=${Date.now()}`),
    stlGeometry(`${lidUrl}?v=${Date.now()}`),
  ]);

  const baseMaterial = new THREE.MeshStandardMaterial({ color: 0x8f99aa, roughness: 0.68, metalness: 0.02 });
  const lidMaterial = new THREE.MeshStandardMaterial({ color: 0xd7dbe2, roughness: 0.62, metalness: 0.01 });
  const baseMesh = new THREE.Mesh(baseGeometry, baseMaterial);
  baseMesh.castShadow = true;
  baseMesh.receiveShadow = true;
  baseMesh.name = 'base';

  const axis = manifest.preview.hinge_axis || [0, 0, 25];
  lidGeometry.translate(-axis[0], -axis[1], -axis[2]);
  const lidMesh = new THREE.Mesh(lidGeometry, lidMaterial);
  lidMesh.castShadow = true;
  lidMesh.receiveShadow = true;
  lidMesh.name = 'lid';
  const lidPivot = new THREE.Group();
  lidPivot.position.set(axis[0], axis[1], axis[2]);
  lidPivot.add(lidMesh);

  state.modelRoot.add(baseMesh, lidPivot);
  state.baseMesh = baseMesh;
  state.lidMesh = lidMesh;
  state.lidPivot = lidPivot;
  elements.viewerPlaceholder.style.display = 'none';

  const configuredOpen = Math.min(210, Math.round(manifest.preview.opening_angle_deg || 195));
  elements.lidAngle.max = String(Math.max(210, configuredOpen));
  elements.lidAngle.dataset.openAngle = String(configuredOpen);
  setLidAngle(0);
  fitCameraToModels();
}

function fitCameraToModels() {
  if (!state.modelRoot || !state.camera || !state.controls) return;
  const box = new THREE.Box3().setFromObject(state.modelRoot);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const maxDimension = Math.max(size.x, size.y, size.z, 1);
  const distance = maxDimension * 2.05;
  state.camera.position.set(center.x + distance * 0.75, center.y - distance, center.z + distance * 0.72);
  state.camera.near = Math.max(0.1, distance / 200);
  state.camera.far = distance * 15;
  state.camera.updateProjectionMatrix();
  state.controls.target.copy(center);
  state.controls.update();
}

function setLidAngle(value) {
  const degrees = Number(value) || 0;
  elements.lidAngle.value = String(degrees);
  elements.lidAngleValue.textContent = `${degrees}°`;
  if (state.lidPivot) state.lidPivot.rotation.x = THREE.MathUtils.degToRad(degrees);
  const openAngle = Number(elements.lidAngle.dataset.openAngle || 195);
  elements.openLidButton.textContent = Math.abs(degrees) > 1 ? 'Zamknij' : `Otwórz ${openAngle}°`;
}

async function loadDefaultConfig() {
  hideBanner();
  const payload = await fetchJson('/api/default-config');
  setConfig(payload.config);
  renderWarnings(payload.warnings);
  renderMetrics(payload.metrics);
}

async function interpretPrompt() {
  hideBanner();
  const config = parseEditorConfig();
  elements.interpretButton.disabled = true;
  elements.interpretMessage.textContent = 'Interpretowanie opisu…';
  try {
    const payload = await fetchJson('/api/interpret', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: elements.promptInput.value, config }),
    });
    setConfig(payload.config);
    renderWarnings(payload.warnings);
    renderMetrics(payload.metrics);
    elements.interpretMessage.textContent = `${payload.message} Tryb: ${payload.mode}.`;
    showBanner('Opis został przekształcony w zwalidowaną konfigurację projektu.', 'success');
  } catch (error) {
    elements.interpretMessage.textContent = error.message;
    showBanner(`Interpretacja nie powiodła się: ${error.message}`, 'error');
  } finally {
    elements.interpretButton.disabled = false;
  }
}

async function generate() {
  hideBanner();
  const config = parseEditorConfig();
  elements.generateButton.disabled = true;
  elements.generationProgress.classList.remove('hidden');
  try {
    const manifest = await fetchJson('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config, source_prompt: elements.promptInput.value }),
    });
    state.manifest = manifest;
    renderWarnings(manifest.warnings);
    renderMetrics(manifest.metrics);
    renderArtifacts(manifest);
    updateDrawingPreview();
    await load3dPreview(manifest);
    showBanner(`Projekt ${manifest.job_id} został wygenerowany. Dostępnych plików: ${manifest.artifacts.length}.`, 'success');
  } catch (error) {
    showBanner(`Generowanie nie powiodło się: ${error.message}`, 'error');
  } finally {
    elements.generateButton.disabled = false;
    elements.generationProgress.classList.add('hidden');
  }
}

function downloadConfig() {
  const config = parseEditorConfig();
  const blob = new Blob([prettyConfig(config)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'housing_project_config.json';
  link.click();
  URL.revokeObjectURL(url);
}

async function uploadConfig(file) {
  const text = await file.text();
  const parsed = JSON.parse(text);
  setConfig(parsed);
  showBanner('Konfiguracja JSON została wczytana. Walidacja serwerowa nastąpi przy interpretacji lub generowaniu.', 'info');
}

setLlmBadge();
initViewer();
loadDefaultConfig().catch((error) => showBanner(`Nie można załadować konfiguracji domyślnej: ${error.message}`, 'error'));

elements.configEditor.addEventListener('input', () => {
  try {
    parseEditorConfig();
  } catch (_) {
    // Status is set by parseEditorConfig.
  }
});
elements.interpretButton.addEventListener('click', interpretPrompt);
elements.generateButton.addEventListener('click', generate);
elements.resetConfigButton.addEventListener('click', () => loadDefaultConfig().catch((error) => showBanner(error.message, 'error')));
elements.downloadConfigButton.addEventListener('click', downloadConfig);
elements.uploadConfigInput.addEventListener('change', (event) => {
  const file = event.target.files?.[0];
  if (file) uploadConfig(file).catch((error) => showBanner(`Nie można wczytać JSON: ${error.message}`, 'error'));
  event.target.value = '';
});
elements.drawingPart.addEventListener('change', updateDrawingPreview);
elements.drawingView.addEventListener('change', updateDrawingPreview);
elements.lidAngle.addEventListener('input', (event) => setLidAngle(event.target.value));
elements.openLidButton.addEventListener('click', () => {
  const current = Number(elements.lidAngle.value || 0);
  const target = current > 1 ? 0 : Number(elements.lidAngle.dataset.openAngle || 195);
  setLidAngle(target);
});
elements.resetCameraButton.addEventListener('click', fitCameraToModels);
