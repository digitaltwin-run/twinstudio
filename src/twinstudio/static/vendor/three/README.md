# Three.js browser modules

These files are copied unchanged from the official npm package `three@0.185.1`:

- `build/three.module.js`
- `build/three.core.js` (a relative dependency of `three.module.js`)
- `examples/jsm/controls/OrbitControls.js`
- `examples/jsm/loaders/STLLoader.js`
- `LICENSE`

They are served by TwinStudio under `/static/vendor/three/` so the 3D viewer does
not need a runtime connection to a public CDN. To reproduce the source package,
run `npm pack three@0.185.1` and compare the files against `SHA256SUMS`.
