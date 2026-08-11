# Generated housing revision

Project: **Raspberry Pi 5 housing**  
Revision: **A**  
Generator: **Housing Studio 1.2.1**  
Units: **mm**

This directory is a reproducible artifact snapshot. The authoritative editable inputs are:

- `project_config.json` — validated project configuration;
- `project_layers.json` — functional 3D layers and drawing layers;
- `rebuild_project.py` — deterministic rebuild entry point;
- the Housing Studio Python source package.

To rebuild after installing the project package:

```bash
python rebuild_project.py --out regenerated
```

STEP files contain B-Rep geometry exported from CadQuery. STL and OBJ are mesh exports for printing and preview.
A physical prototype is required before production.
