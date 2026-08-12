let THREE = null;
let OrbitControls = null;
let STLLoader = null;

const elements = {
  llmBadge: document.getElementById('llmBadge'),
  promptInput: document.getElementById('promptInput'),
  interpretButton: document.getElementById('interpretButton'),
  interpretMessage: document.getElementById('interpretMessage'),
  changeReviewSection: document.getElementById('changeReviewSection'),
  changeCountBadge: document.getElementById('changeCountBadge'),
  changeList: document.getElementById('changeList'),
  applyChangesButton: document.getElementById('applyChangesButton'),
  discardChangesButton: document.getElementById('discardChangesButton'),
  quickParameterControls: document.getElementById('quickParameterControls'),
  featureLayerControls: document.getElementById('featureLayerControls'),
  drawingViewControls: document.getElementById('drawingViewControls'),
  drawingLayerControls: document.getElementById('drawingLayerControls'),
  artifactOutputControls: document.getElementById('artifactOutputControls'),
  resetConfigButton: document.getElementById('resetConfigButton'),
  validateConfigButton: document.getElementById('validateConfigButton'),
  downloadConfigButton: document.getElementById('downloadConfigButton'),
  uploadConfigInput: document.getElementById('uploadConfigInput'),
  configEditor: document.getElementById('configEditor'),
  configStatus: document.getElementById('configStatus'),
  generateButton: document.getElementById('generateButton'),
  generationProgress: document.getElementById('generationProgress'),
  refreshJobsButton: document.getElementById('refreshJobsButton'),
  jobHistory: document.getElementById('jobHistory'),
  messageBanner: document.getElementById('messageBanner'),
  viewer: document.getElementById('viewer'),
  viewerPlaceholder: document.getElementById('viewerPlaceholder'),
  lidAngle: document.getElementById('lidAngle'),
  lidAngleValue: document.getElementById('lidAngleValue'),
  openLidButton: document.getElementById('openLidButton'),
  resetCameraButton: document.getElementById('resetCameraButton'),
  showBase: document.getElementById('showBase'),
  showLid: document.getElementById('showLid'),
  showGrid: document.getElementById('showGrid'),
  showAxes: document.getElementById('showAxes'),
  drawingPart: document.getElementById('drawingPart'),
  drawingView: document.getElementById('drawingView'),
  drawingLayerVisibility: document.getElementById('drawingLayerVisibility'),
  drawingSvgHost: document.getElementById('drawingSvgHost'),
  drawingPlaceholder: document.getElementById('drawingPlaceholder'),
  drawingPreviewStatus: document.getElementById('drawingPreviewStatus'),
  warningList: document.getElementById('warningList'),
  metricsGrid: document.getElementById('metricsGrid'),
  artifactList: document.getElementById('artifactList'),
  bundleButton: document.getElementById('bundleButton'),
};

const state = {
  config: null,
  manifest: null,
  pendingProposal: null,
  interpretationMode: null,
  changes: [],
  dirtySinceInterpretation: false,
  settingEditor: false,
  drawingSvg: null,
  scene: null,
  camera: null,
  renderer: null,
  controls: null,
  baseMesh: null,
  lidMesh: null,
  lidPivot: null,
  modelRoot: null,
  grid: null,
  axes: null,
  defaultCameraPosition: [150, -175, 115],
  viewerReady: false,
  viewerError: null,
  viewerInitPromise: null,
};

const quickParameters = [
  ['dimensions.external_width', 'Szerokość zewnętrzna', 'mm', 20, 500, 0.1],
  ['dimensions.external_depth', 'Głębokość zewnętrzna', 'mm', 20, 500, 0.1],
  ['dimensions.base_height', 'Wysokość podstawy', 'mm', 5, 300, 0.1],
  ['dimensions.total_height', 'Wysokość całkowita', 'mm', 10, 500, 0.1],
  ['dimensions.wall_thickness', 'Grubość ścian', 'mm', 0.8, 10, 0.1],
  ['dimensions.floor_thickness', 'Grubość dna', 'mm', 0.8, 10, 0.1],
  ['dimensions.lid_top_thickness', 'Grubość dachu', 'mm', 0.8, 10, 0.1],
  ['dimensions.lid_vertical_lower_section', 'Pionowy odcinek klapy', 'mm', 0, 20, 0.1],
  ['hinge.opening_angle_deg', 'Kąt otwarcia klapy', '°', 0, 270, 1],
  ['hinge.base_front_chamfer_angle_deg', 'Kąt ścięcia przy zawiasie', '°', 10, 80, 1],
  ['mating.fit_clearance', 'Luz pasowania', 'mm', 0, 2, 0.05],
  ['board.standoff.height', 'Wysokość słupków PCB', 'mm', 0.5, 30, 0.1],
  ['board.standoff.outer_diameter', 'Średnica słupków PCB', 'mm', 2, 30, 0.1],
  ['board.standoff.pilot_hole_diameter', 'Otwór słupków PCB', 'mm', 0.2, 10, 0.1],
  ['auxiliary_lid_bosses.top_z_from_base_mating_plane', 'Góra punktów klapy od podstawy', 'mm', 0, 50, 0.1],
];

const drawingViews = {
  include_front: 'Front',
  include_top: 'Top',
  include_side: 'Side',
};

const drawingLayerLabels = {
  visible_edges: 'Visible edges',
  hidden_edges: 'Hidden edges',
  centerlines: 'Centerlines',
  dimensions: 'Dimensions',
  notes: 'Notes',
  section_hatch: 'Section hatch',
  pcb_reference: 'PCB reference',
  construction: 'Construction',
  datums: 'Datums',
};

const artifactLabels = {
  export_step: 'STEP',
  export_stl: 'STL',
  export_obj: 'OBJ',
  export_glb: 'GLB preview',
  export_dxf: 'DXF',
  export_svg: 'SVG',
  export_pdf: 'PDF',
  export_open_preview: 'Open-lid GLB',
  create_zip: 'ZIP bundle',
};

function setLlmBadge() {
  const configured = document.body.dataset.litellmConfigured === 'true';
  const version = document.body.dataset.appVersion || '';
  elements.llmBadge.textContent = configured ? 'LiteLLM skonfigurowany' : 'LiteLLM: tryb fallback';
  elements.llmBadge.title = configured
    ? `Housing Studio ${version}. Opis naturalny będzie interpretowany przez model ustawiony w LITELLM_MODEL.`
    : `Housing Studio ${version}. Brak LITELLM_MODEL; działa ostrożny parser lokalny.`;
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
    const detail = typeof payload.detail === 'string'
      ? payload.detail
      : JSON.stringify(payload.detail || payload);
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = String(value);
  return div.innerHTML;
}

function prettyConfig(config) {
  return JSON.stringify(config, null, 2);
}

function formatValue(value) {
  if (value === null || value === undefined) return 'null';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function getNested(root, dottedPath) {
  return dottedPath.split('.').reduce((value, key) => value?.[key], root);
}

function setNested(root, dottedPath, value) {
  const parts = dottedPath.split('.');
  let target = root;
  parts.slice(0, -1).forEach((part) => {
    target = target[part];
  });
  target[parts.at(-1)] = value;
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

function clearPendingProposal() {
  state.pendingProposal = null;
  elements.changeReviewSection.classList.add('hidden');
  elements.changeList.innerHTML = '';
  elements.changeCountBadge.textContent = '0';
}

function clearAppliedAudit({ markDirty = true } = {}) {
  state.interpretationMode = null;
  state.changes = [];
  state.dirtySinceInterpretation = markDirty;
}

function setConfig(config, { preserveAudit = false } = {}) {
  state.config = config;
  state.settingEditor = true;
  elements.configEditor.value = prettyConfig(config);
  state.settingEditor = false;
  elements.configStatus.textContent = 'Konfiguracja gotowa.';
  elements.configStatus.className = 'status-line ok';
  if (!preserveAudit) clearAppliedAudit();
  renderQuickParameters(config);
  renderFeatureLayers(config);
  renderDrawingViews(config);
  renderDrawingLayers(config);
  renderArtifactOptions(config);
  applyDrawingLayerVisibility();
}

function applyManualConfigChange(dottedPath, value) {
  const config = parseEditorConfig();
  setNested(config, dottedPath, value);
  clearAppliedAudit();
  clearPendingProposal();
  setConfig(config, { preserveAudit: true });
  elements.configStatus.textContent = `Zmieniono ${dottedPath}; uruchom walidację przed generowaniem.`;
}

function renderQuickParameters(config) {
  elements.quickParameterControls.innerHTML = '';
  quickParameters.forEach(([path, label, unit, min, max, step]) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'quick-field';
    const inputId = `quick-${path.replaceAll('.', '-')}`;
    wrapper.innerHTML = `
      <label for="${inputId}">${escapeHtml(label)}</label>
      <input id="${inputId}" type="number" value="${escapeHtml(getNested(config, path))}"
        min="${min}" max="${max}" step="${step}" />
      <small>${escapeHtml(path)} · ${escapeHtml(unit)}</small>
    `;
    wrapper.querySelector('input').addEventListener('change', (event) => {
      applyManualConfigChange(path, Number(event.target.value));
    });
    elements.quickParameterControls.appendChild(wrapper);
  });
}

function createToggle({ checked, title, code, note = '', onChange }) {
  const row = document.createElement('label');
  row.className = 'toggle-item';
  row.innerHTML = `
    <input type="checkbox" ${checked ? 'checked' : ''} />
    <span class="toggle-copy">
      <strong>${escapeHtml(title)}</strong>
      <small>${code ? `<code>${escapeHtml(code)}</code>` : ''}${note ? `${code ? ' · ' : ''}${escapeHtml(note)}` : ''}</small>
    </span>
  `;
  row.querySelector('input').addEventListener('change', (event) => onChange(event.target.checked));
  return row;
}

function renderFeatureLayers(config) {
  elements.featureLayerControls.innerHTML = '';
  Object.entries(config.feature_layers || {}).forEach(([key, layer]) => {
    elements.featureLayerControls.appendChild(createToggle({
      checked: Boolean(layer.enabled),
      title: layer.label || key,
      code: key,
      note: layer.notes || '',
      onChange: (enabled) => applyManualConfigChange(`feature_layers.${key}.enabled`, enabled),
    }));
  });
}

function renderDrawingViews(config) {
  elements.drawingViewControls.innerHTML = '';
  Object.entries(drawingViews).forEach(([key, label]) => {
    elements.drawingViewControls.appendChild(createToggle({
      checked: Boolean(config.drawing?.[key]),
      title: label,
      code: `drawing.${key}`,
      onChange: (enabled) => applyManualConfigChange(`drawing.${key}`, enabled),
    }));
  });
}

function renderDrawingLayers(config) {
  elements.drawingLayerControls.innerHTML = '';
  Object.entries(config.drawing?.layers || {}).forEach(([key, layer]) => {
    elements.drawingLayerControls.appendChild(createToggle({
      checked: Boolean(layer.enabled),
      title: drawingLayerLabels[key] || key,
      code: layer.dxf_name || key,
      note: `${layer.line_type}, ${layer.line_weight_mm} mm, color ${layer.color_index}`,
      onChange: (enabled) => applyManualConfigChange(`drawing.layers.${key}.enabled`, enabled),
    }));
  });
}

function renderArtifactOptions(config) {
  elements.artifactOutputControls.innerHTML = '';
  Object.entries(artifactLabels).forEach(([key, label]) => {
    elements.artifactOutputControls.appendChild(createToggle({
      checked: Boolean(config.artifacts?.[key]),
      title: label,
      code: `artifacts.${key}`,
      onChange: (enabled) => applyManualConfigChange(`artifacts.${key}`, enabled),
    }));
  });
}

function renderChangeProposal(proposal) {
  const changes = proposal?.changes || [];
  elements.changeList.innerHTML = '';
  elements.changeCountBadge.textContent = String(changes.length);
  elements.changeReviewSection.classList.remove('hidden');

  if (!changes.length) {
    elements.changeList.innerHTML = '<div class="change-empty">Opis nie zmienia żadnej wartości konfiguracji.</div>';
    elements.applyChangesButton.disabled = true;
    return;
  }

  elements.applyChangesButton.disabled = false;
  changes.forEach((change) => {
    const row = document.createElement('div');
    row.className = 'change-row';
    row.innerHTML = `
      <code>${escapeHtml(change.path || '')}</code>
      <span class="change-kind">${escapeHtml(change.kind || 'changed')}</span>
      <div class="change-values">
        <span class="before" title="Przed">${escapeHtml(formatValue(change.before))}</span>
        <span class="arrow">→</span>
        <span class="after" title="Po">${escapeHtml(formatValue(change.after))}</span>
      </div>
    `;
    elements.changeList.appendChild(row);
  });
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

async function updateDrawingPreview() {
  const manifest = state.manifest;
  elements.drawingSvgHost.innerHTML = '';
  elements.drawingLayerVisibility.innerHTML = '';
  elements.drawingLayerVisibility.classList.add('hidden');
  state.drawingSvg = null;
  if (!manifest) {
    elements.drawingPlaceholder.style.display = 'grid';
    return;
  }

  const part = elements.drawingPart.value;
  const view = elements.drawingView.value;
  const suffix = `2d/${part}/${part}_${view}.svg`;
  const artifact = manifest.artifacts.find((item) => item.path === suffix);
  if (!artifact) {
    elements.drawingPlaceholder.style.display = 'grid';
    elements.drawingPlaceholder.textContent = 'Wybrany podgląd SVG nie został wygenerowany.';
    elements.drawingPreviewStatus.textContent = 'Włącz odpowiedni widok i format SVG, a następnie wygeneruj nową rewizję.';
    return;
  }

  elements.drawingPlaceholder.style.display = 'grid';
  elements.drawingPlaceholder.textContent = 'Ładowanie warstwowego SVG…';
  const response = await fetch(`${artifact.url}?v=${Date.now()}`);
  if (!response.ok) throw new Error(`Nie można pobrać SVG: HTTP ${response.status}`);
  const svgText = await response.text();
  const parsed = new DOMParser().parseFromString(svgText, 'image/svg+xml');
  if (parsed.querySelector('parsererror')) throw new Error('Wygenerowany SVG jest niepoprawny.');
  const svg = parsed.documentElement;
  svg.removeAttribute('width');
  svg.removeAttribute('height');
  svg.classList.add('embedded-drawing');
  const imported = document.importNode(svg, true);
  elements.drawingSvgHost.appendChild(imported);
  state.drawingSvg = imported;
  elements.drawingPlaceholder.style.display = 'none';
  renderDrawingPreviewLayerControls();
  applyDrawingLayerVisibility();
}

function renderDrawingPreviewLayerControls() {
  elements.drawingLayerVisibility.innerHTML = '';
  if (!state.drawingSvg) {
    elements.drawingLayerVisibility.classList.add('hidden');
    return;
  }
  const groups = [...state.drawingSvg.querySelectorAll(':scope > g[id]')];
  if (!groups.length) {
    elements.drawingLayerVisibility.classList.add('hidden');
    return;
  }
  elements.drawingLayerVisibility.classList.remove('hidden');
  const configLayers = Object.values(state.config?.drawing?.layers || {});
  groups.forEach((group) => {
    const configured = configLayers.find((layer) => layer.dxf_name === group.id);
    const label = document.createElement('label');
    label.className = 'inline-check layer-visibility-check';
    const checked = configured ? Boolean(configured.enabled) : true;
    label.innerHTML = `<input type="checkbox" ${checked ? 'checked' : ''} /><span>${escapeHtml(group.id)}</span>`;
    label.querySelector('input').addEventListener('change', (event) => {
      group.style.display = event.target.checked ? '' : 'none';
      elements.drawingPreviewStatus.textContent = 'Widoczność zmieniona tylko w podglądzie; konfiguracja projektu nie została zmieniona.';
    });
    elements.drawingLayerVisibility.appendChild(label);
  });
}

function applyDrawingLayerVisibility() {
  if (!state.drawingSvg || !state.config?.drawing?.layers) return;
  const groups = [...state.drawingSvg.querySelectorAll(':scope > g[id]')];
  const groupById = new Map(groups.map((group) => [group.id, group]));
  let visibleCount = 0;
  Object.values(state.config.drawing.layers).forEach((layer) => {
    const group = groupById.get(layer.dxf_name);
    if (group) {
      group.style.display = layer.enabled ? '' : 'none';
      if (layer.enabled) visibleCount += 1;
    }
  });
  elements.drawingPreviewStatus.textContent = `${visibleCount} warstw widocznych w podglądzie. Zmiana DXF/PDF wymaga ponownego generowania.`;
}

async function loadViewerDependencies() {
  if (THREE && OrbitControls && STLLoader) return;
  const [threeModule, controlsModule, stlModule] = await Promise.all([
    import('three'),
    import('three/addons/controls/OrbitControls.js'),
    import('three/addons/loaders/STLLoader.js'),
  ]);
  THREE = threeModule;
  OrbitControls = controlsModule.OrbitControls;
  STLLoader = stlModule.STLLoader;
}

async function initViewer() {
  try {
    await loadViewerDependencies();
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 5000);
    camera.up.set(0, 0, 1);
    camera.position.set(...state.defaultCameraPosition);

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
    Object.assign(state, { scene, camera, renderer, controls, modelRoot, grid, axes });

    const resize = () => {
      const width = elements.viewer.clientWidth;
      const height = Math.max(360, elements.viewer.clientHeight);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(elements.viewer);
    resize();

    const animate = () => {
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    state.viewerReady = true;
    state.viewerError = null;
    animate();
    return true;
  } catch (error) {
    state.viewerReady = false;
    state.viewerError = error instanceof Error ? error.message : String(error);
    elements.viewerPlaceholder.textContent = `Podgląd 3D jest niedostępny: ${state.viewerError}. Generator, dokumentacja 2D i pobieranie plików nadal działają.`;
    elements.viewerPlaceholder.style.display = 'grid';
    console.warn('Housing Studio 3D viewer initialization failed', error);
    return false;
  }
}

function clearModels() {
  [state.baseMesh, state.lidMesh].forEach((mesh) => {
    if (mesh) {
      mesh.geometry?.dispose();
      mesh.material?.dispose();
    }
  });
  state.modelRoot?.clear();
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
  if (!state.viewerReady && state.viewerInitPromise) await state.viewerInitPromise;
  if (!state.viewerReady) {
    elements.viewerPlaceholder.textContent = `Podgląd 3D jest niedostępny${state.viewerError ? `: ${state.viewerError}` : ''}. Pliki STL/STEP można nadal pobrać.`;
    elements.viewerPlaceholder.style.display = 'grid';
    return;
  }
  const baseUrl = manifest?.preview?.base_stl_url;
  const lidUrl = manifest?.preview?.lid_stl_url;
  if (!baseUrl || !lidUrl) {
    elements.viewerPlaceholder.textContent = 'Brak plików STL wymaganych do podglądu 3D.';
    elements.viewerPlaceholder.style.display = 'grid';
    clearModels();
    return;
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

  const axis = manifest.preview.hinge_axis || [0, 0, 25];
  lidGeometry.translate(-axis[0], -axis[1], -axis[2]);
  const lidMesh = new THREE.Mesh(lidGeometry, lidMaterial);
  lidMesh.castShadow = true;
  lidMesh.receiveShadow = true;
  const lidPivot = new THREE.Group();
  lidPivot.position.set(axis[0], axis[1], axis[2]);
  lidPivot.add(lidMesh);

  state.modelRoot.add(baseMesh, lidPivot);
  Object.assign(state, { baseMesh, lidMesh, lidPivot });
  baseMesh.visible = elements.showBase.checked;
  lidPivot.visible = elements.showLid.checked;
  elements.viewerPlaceholder.style.display = 'none';

  const configuredOpen = Math.min(270, Math.round(manifest.preview.opening_angle_deg || 195));
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
  const maximum = Math.max(size.x, size.y, size.z, 1);
  const distance = maximum * 2.05;
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
  if (state.lidPivot && THREE) state.lidPivot.rotation.x = THREE.MathUtils.degToRad(degrees);
  const openAngle = Number(elements.lidAngle.dataset.openAngle || 195);
  elements.openLidButton.textContent = Math.abs(degrees) > 1 ? 'Zamknij' : `Otwórz ${openAngle}°`;
}

async function loadDefaultConfig() {
  hideBanner();
  const payload = await fetchJson('/api/default-config');
  clearPendingProposal();
  setConfig(payload.config);
  state.dirtySinceInterpretation = false;
  renderWarnings(payload.warnings);
  renderMetrics(payload.metrics);
}

async function validateConfig({ announce = true } = {}) {
  hideBanner();
  const config = parseEditorConfig();
  elements.validateConfigButton.disabled = true;
  try {
    const payload = await fetchJson('/api/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    });
    setConfig(payload.config, { preserveAudit: true });
    renderWarnings(payload.warnings);
    renderMetrics(payload.metrics);
    elements.configStatus.textContent = 'Konfiguracja została zwalidowana przez Pydantic.';
    if (announce) showBanner('Konfiguracja jest poprawna i gotowa do generowania.', 'success');
    return payload.config;
  } catch (error) {
    showBanner(`Walidacja nie powiodła się: ${error.message}`, 'error');
    throw error;
  } finally {
    elements.validateConfigButton.disabled = false;
  }
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
    state.pendingProposal = payload;
    renderChangeProposal(payload);
    elements.interpretMessage.textContent = `${payload.message} Tryb: ${payload.mode}. Proponowanych zmian: ${(payload.changes || []).length}.`;
    showBanner('Propozycja została przygotowana. Sprawdź różnice i zatwierdź albo odrzuć.', 'info');
  } catch (error) {
    elements.interpretMessage.textContent = error.message;
    showBanner(`Interpretacja nie powiodła się: ${error.message}`, 'error');
  } finally {
    elements.interpretButton.disabled = false;
  }
}

function applyProposedChanges() {
  const proposal = state.pendingProposal;
  if (!proposal) return;
  state.interpretationMode = proposal.mode;
  state.changes = proposal.changes || [];
  state.dirtySinceInterpretation = false;
  setConfig(proposal.config, { preserveAudit: true });
  renderWarnings(proposal.warnings);
  renderMetrics(proposal.metrics);
  clearPendingProposal();
  elements.interpretMessage.textContent = `Zastosowano ${state.changes.length} zmian w trybie ${state.interpretationMode}.`;
  showBanner('Zatwierdzone zmiany są teraz częścią konfiguracji projektu.', 'success');
}

function discardProposedChanges() {
  clearPendingProposal();
  elements.interpretMessage.textContent = 'Propozycja została odrzucona; konfiguracja nie została zmieniona.';
  showBanner('Nie zastosowano zmian.', 'info');
}

async function generate() {
  hideBanner();
  elements.generateButton.disabled = true;
  elements.generationProgress.classList.remove('hidden');
  try {
    const config = await validateConfig({ announce: false });
    const auditIsCurrent = Boolean(state.interpretationMode) && !state.dirtySinceInterpretation;
    const manifest = await fetchJson('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        config,
        source_prompt: elements.promptInput.value,
        interpretation_mode: auditIsCurrent ? state.interpretationMode : 'manual',
        configuration_changes: auditIsCurrent ? state.changes : [],
      }),
    });
    state.manifest = manifest;
    renderWarnings(manifest.warnings);
    renderMetrics(manifest.metrics);
    renderArtifacts(manifest);
    await Promise.all([updateDrawingPreview(), load3dPreview(manifest)]);
    await loadJobHistory();
    showBanner(`Rewizja ${manifest.job_id} została wygenerowana. Plików: ${manifest.artifacts.length}.`, 'success');
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
  const parsed = JSON.parse(await file.text());
  clearPendingProposal();
  clearAppliedAudit();
  setConfig(parsed, { preserveAudit: true });
  await validateConfig({ announce: false });
  showBanner('Konfiguracja została wczytana i zwalidowana.', 'success');
}

async function loadJob(jobId) {
  hideBanner();
  const [manifest, configPayload] = await Promise.all([
    fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`),
    fetchJson(`/api/jobs/${encodeURIComponent(jobId)}/config`),
  ]);
  clearPendingProposal();
  clearAppliedAudit({ markDirty: false });
  setConfig(configPayload.config, { preserveAudit: true });
  state.manifest = manifest;
  renderWarnings(configPayload.warnings);
  renderMetrics(configPayload.metrics);
  renderArtifacts(manifest);
  await Promise.all([updateDrawingPreview(), load3dPreview(manifest)]);
  showBanner(`Otworzono rewizję ${jobId}.`, 'success');
}

async function loadJobHistory() {
  elements.jobHistory.innerHTML = '<div class="placeholder">Ładowanie historii…</div>';
  try {
    const payload = await fetchJson('/api/jobs?limit=20');
    const jobs = payload.jobs || [];
    elements.jobHistory.innerHTML = '';
    if (!jobs.length) {
      elements.jobHistory.innerHTML = '<div class="placeholder">Brak wygenerowanych rewizji.</div>';
      return;
    }
    jobs.forEach((job) => {
      const row = document.createElement('div');
      row.className = 'job-row';
      const created = job.created_at ? new Date(job.created_at).toLocaleString() : 'unknown date';
      row.innerHTML = `
        <div class="job-name">
          <strong>${escapeHtml(job.project?.name || job.job_id)}</strong>
          <small>${escapeHtml(job.job_id)}</small>
          <div class="job-meta">${escapeHtml(created)} · v${escapeHtml(job.generator_version || '?')} · ${job.artifact_count} plików · ${job.change_count} zmian</div>
        </div>
        <div class="job-actions">
          <button type="button" class="button secondary open-job">Otwórz</button>
          ${job.bundle_url ? `<a class="button secondary" href="${job.bundle_url}" download>ZIP</a>` : ''}
        </div>
      `;
      row.querySelector('.open-job').addEventListener('click', () => {
        loadJob(job.job_id).catch((error) => showBanner(`Nie można otworzyć rewizji: ${error.message}`, 'error'));
      });
      elements.jobHistory.appendChild(row);
    });
  } catch (error) {
    elements.jobHistory.innerHTML = `<div class="placeholder">Nie można wczytać historii: ${escapeHtml(error.message)}</div>`;
  }
}

setLlmBadge();
state.viewerInitPromise = initViewer();
loadDefaultConfig().catch((error) => showBanner(`Nie można załadować konfiguracji domyślnej: ${error.message}`, 'error'));
loadJobHistory();

elements.configEditor.addEventListener('input', () => {
  if (state.settingEditor) return;
  clearPendingProposal();
  clearAppliedAudit();
  try {
    parseEditorConfig();
  } catch (_) {
    // parseEditorConfig presents the syntax error.
  }
});
elements.interpretButton.addEventListener('click', interpretPrompt);
elements.applyChangesButton.addEventListener('click', applyProposedChanges);
elements.discardChangesButton.addEventListener('click', discardProposedChanges);
elements.resetConfigButton.addEventListener('click', () => loadDefaultConfig().catch((error) => showBanner(error.message, 'error')));
elements.validateConfigButton.addEventListener('click', () => validateConfig().catch(() => {}));
elements.downloadConfigButton.addEventListener('click', downloadConfig);
elements.uploadConfigInput.addEventListener('change', (event) => {
  const file = event.target.files?.[0];
  if (file) uploadConfig(file).catch((error) => showBanner(`Nie można wczytać JSON: ${error.message}`, 'error'));
  event.target.value = '';
});
elements.generateButton.addEventListener('click', generate);
elements.refreshJobsButton.addEventListener('click', loadJobHistory);
elements.drawingPart.addEventListener('change', () => updateDrawingPreview().catch((error) => showBanner(error.message, 'error')));
elements.drawingView.addEventListener('change', () => updateDrawingPreview().catch((error) => showBanner(error.message, 'error')));
elements.lidAngle.addEventListener('input', (event) => setLidAngle(event.target.value));
elements.openLidButton.addEventListener('click', () => {
  const current = Number(elements.lidAngle.value || 0);
  const target = current > 1 ? 0 : Number(elements.lidAngle.dataset.openAngle || 195);
  setLidAngle(target);
});
elements.resetCameraButton.addEventListener('click', fitCameraToModels);
elements.showBase.addEventListener('change', () => { if (state.baseMesh) state.baseMesh.visible = elements.showBase.checked; });
elements.showLid.addEventListener('change', () => { if (state.lidPivot) state.lidPivot.visible = elements.showLid.checked; });
elements.showGrid.addEventListener('change', () => { if (state.grid) state.grid.visible = elements.showGrid.checked; });
elements.showAxes.addEventListener('change', () => { if (state.axes) state.axes.visible = elements.showAxes.checked; });
