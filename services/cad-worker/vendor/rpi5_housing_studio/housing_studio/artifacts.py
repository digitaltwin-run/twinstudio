from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .cad3d import (
    export_assembly_step,
    export_part,
    make_models,
    shape_stats,
)
from .draw2d import export_all_2d
from .mesh_preview import export_obj_from_stl, export_preview_scenes
from .models import ProjectConfig
from .validation import collect_warnings, design_metrics


@dataclass(slots=True)
class ArtifactRecord:
    path: str
    category: str
    label: str
    media_type: str
    size_bytes: int
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _record(root: Path, path: Path, category: str, label: str, media_type: str) -> ArtifactRecord:
    return ArtifactRecord(
        path=path.relative_to(root).as_posix(),
        category=category,
        label=label,
        media_type=media_type,
        size_bytes=path.stat().st_size,
        sha256=_sha256(path),
    )


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _job_id(config: ProjectConfig) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(config.model_dump_json().encode("utf-8")).hexdigest()[:8]
    return f"{stamp}-{digest}"


def _safe_job_id(value: str) -> str:
    identifier = value.strip()
    if (
        not identifier
        or identifier in {".", ".."}
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier)
    ):
        raise ValueError(
            "job_id must contain only letters, digits, dots, underscores, or hyphens "
            "and must start with a letter or digit"
        )
    return identifier


def _specification_markdown(config: ProjectConfig, warnings: list[dict[str, Any]]) -> str:
    d = config.dimensions
    b = config.board
    aux = config.auxiliary_lid_bosses
    lines = [
        f"# {config.metadata.name}",
        "",
        f"Revision: **{config.metadata.revision}**  ",
        "Units: **mm**",
        "",
        "## Source assumptions requiring confirmation",
        "",
        "- The default total external depth of 95 mm is a working assumption derived from the 80 mm flat lid section plus 13 mm front and 2 mm rear insets.",
        "- Connector opening positions are configurable placeholders and must be verified against the final board, components, and plug bodies.",
        "- Hinge clearances and the pin method require a physical FDM prototype before production.",
        "",
        "## Main enclosure",
        "",
        f"- External width: {d.external_width:.2f}",
        f"- External depth: {d.external_depth:.2f}",
        f"- Total height: {d.total_height:.2f}",
        f"- Lower base height: {d.base_height:.2f}",
        f"- Wall thickness: {d.wall_thickness:.2f}",
        f"- Lid flat top: {d.top_width:.2f} x {d.top_depth:.2f}",
        f"- Lower vertical lid section: {d.lid_vertical_lower_section:.2f}",
        f"- Nominal external edge radius: {d.edge_radius:.2f}",
        "",
        "## Raspberry Pi mounting",
        "",
        f"- PCB reference: {b.width:.2f} x {b.length:.2f}",
        f"- Mounting-hole pattern: {b.hole_spacing_width:.2f} x {b.hole_spacing_length:.2f}",
        f"- Standoffs: OD {b.standoff.outer_diameter:.2f}, pilot {b.standoff.pilot_hole_diameter:.2f}, height {b.standoff.height:.2f}",
        f"- Position A: front {b.position_a.front_clearance:.2f}, right {b.position_a.right_clearance:.2f}",
        f"- Position B: front {b.position_b.front_clearance:.2f}, right {b.position_b.right_clearance:.2f}, requested left {b.position_b.expected_left_clearance:.2f}",
        "",
        "## Lid internal bosses",
        "",
        f"- Auxiliary boss OD: {aux.outer_diameter:.2f}",
        f"- Auxiliary boss hole: {aux.hole_diameter:.2f}",
        f"- Auxiliary boss top datum from the upper base mating plane (Datum A): {aux.top_z_from_base_mating_plane:.2f}",
        "",
        "## Hinge",
        "",
        f"- Knuckle OD: {config.hinge.outer_diameter:.2f}",
        f"- Nominal pin diameter: {config.hinge.pin_diameter:.2f}",
        f"- Bore diameter: {config.hinge.bore_diameter:.2f} (includes {config.hinge.pin_bore_clearance:.2f} diametral clearance)",
        f"- Target opening angle: {config.hinge.opening_angle_deg:.2f} deg",
        f"- Front base chamfer: {config.hinge.base_front_chamfer_angle_deg:.2f} deg; vertical drop {config.hinge.base_front_chamfer_size:.2f}",
        f"- Base wall rotational relief: {config.hinge.base_wall_relief:.2f}",
        f"- Lid edge rotational relief: {config.hinge.lid_edge_relief:.2f}",
        "",
        "## Connector openings",
        "",
    ]
    for opening in config.connector_openings:
        state = "enabled" if opening.enabled else "disabled"
        lines.append(
            f"- {opening.name}: {state}; wall={opening.wall}; width={opening.width:.2f}; "
            f"height={opening.height:.2f}; corner radius={opening.corner_radius:.2f}; "
            f"bottom Z={opening.bottom_z:.2f}"
        )
    lines.extend([
        "",
        "## Enabled feature layers",
        "",
    ])
    for name, layer in config.feature_layers.model_dump().items():
        lines.append(f"- `{name}`: {'enabled' if layer['enabled'] else 'disabled'} - {layer['label']}")
    lines.extend(["", "## Validation notes", ""])
    for warning in warnings:
        lines.append(f"- **{warning['severity'].upper()} / {warning['code']}**: {warning['message']}")
        if warning.get("suggestion"):
            lines.append(f"  - Suggested action: {warning['suggestion']}")
    lines.extend(
        [
            "",
            "## Manufacturing notice",
            "",
            "This generator produces parametric CAD and documentation artifacts. A physical prototype is still required before production, especially for the hinge, moving clearances, connector access, and FDM tolerances.",
            "",
        ]
    )
    return "\n".join(lines)


def generate_artifacts(
    config: ProjectConfig,
    generated_root: Path,
    *,
    job_id: str | None = None,
    source_prompt: str | None = None,
) -> dict[str, Any]:
    generated_root = generated_root.resolve()
    generated_root.mkdir(parents=True, exist_ok=True)
    identifier = _safe_job_id(job_id) if job_id is not None else _job_id(config)
    job_dir = generated_root / identifier
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True)

    warning_objects = collect_warnings(config)
    warnings = [warning.to_dict() for warning in warning_objects]
    blocking = [warning for warning in warnings if warning["severity"] == "error"]
    if blocking:
        raise ValueError("Blocking design validation errors: " + "; ".join(w["message"] for w in blocking))

    records: list[ArtifactRecord] = []

    config_path = job_dir / "project_config.json"
    _write_json(config_path, config.model_dump(mode="json"))
    records.append(_record(job_dir, config_path, "configuration", "Validated project configuration", "application/json"))

    schema_path = job_dir / "project_config.schema.json"
    _write_json(schema_path, ProjectConfig.model_json_schema(mode="serialization"))
    records.append(_record(job_dir, schema_path, "configuration", "Project configuration JSON Schema", "application/schema+json"))

    metrics_path = job_dir / "design_metrics.json"
    _write_json(metrics_path, design_metrics(config))
    records.append(_record(job_dir, metrics_path, "validation", "Computed design metrics", "application/json"))

    warnings_path = job_dir / "design_warnings.json"
    _write_json(warnings_path, warnings)
    records.append(_record(job_dir, warnings_path, "validation", "Design warnings", "application/json"))

    layers_path = job_dir / "project_layers.json"
    _write_json(
        layers_path,
        {
            "feature_layers": config.feature_layers.model_dump(mode="json"),
            "drawing_layers": config.drawing.layers.model_dump(mode="json"),
        },
    )
    records.append(_record(job_dir, layers_path, "configuration", "Feature and drawing layer configuration", "application/json"))

    if source_prompt:
        prompt_path = job_dir / "source_description.txt"
        prompt_path.write_text(source_prompt, encoding="utf-8")
        records.append(_record(job_dir, prompt_path, "configuration", "Natural-language source description", "text/plain"))

    spec_path = job_dir / "technical_specification.md"
    spec_path.write_text(_specification_markdown(config, warnings), encoding="utf-8")
    records.append(_record(job_dir, spec_path, "documentation", "Generated technical specification", "text/markdown"))

    models = make_models(config)
    three_d_dir = job_dir / "3d"
    base_step = three_d_dir / "base.step"
    base_stl = three_d_dir / "base.stl"
    lid_step = three_d_dir / "lid.step"
    lid_stl = three_d_dir / "lid.stl"

    need_stl = config.artifacts.export_stl or config.artifacts.export_obj or config.artifacts.export_glb
    export_part(
        models.base,
        step_path=base_step if config.artifacts.export_step else None,
        stl_path=base_stl if need_stl else None,
        mesh_tolerance=config.artifacts.mesh_tolerance,
        angular_tolerance=config.artifacts.angular_tolerance,
    )
    export_part(
        models.lid,
        step_path=lid_step if config.artifacts.export_step else None,
        stl_path=lid_stl if need_stl else None,
        mesh_tolerance=config.artifacts.mesh_tolerance,
        angular_tolerance=config.artifacts.angular_tolerance,
    )

    if config.artifacts.export_step:
        records.extend(
            [
                _record(job_dir, base_step, "3d", "Lower base STEP", "model/step"),
                _record(job_dir, lid_step, "3d", "Upper lid STEP", "model/step"),
            ]
        )
        assembly_step = three_d_dir / "assembly.step"
        export_assembly_step(models.assembly, assembly_step)
        records.append(_record(job_dir, assembly_step, "3d", "Closed assembly STEP", "model/step"))

    if need_stl:
        # STL files also drive the browser preview. They remain available even when a user
        # disables STL as a formal export but asks for OBJ/GLB preview artifacts.
        records.extend(
            [
                _record(job_dir, base_stl, "3d", "Lower base STL", "model/stl"),
                _record(job_dir, lid_stl, "3d", "Upper lid STL", "model/stl"),
            ]
        )

    if config.artifacts.export_obj:
        base_obj = three_d_dir / "base.obj"
        lid_obj = three_d_dir / "lid.obj"
        export_obj_from_stl(base_stl, base_obj)
        export_obj_from_stl(lid_stl, lid_obj)
        records.extend(
            [
                _record(job_dir, base_obj, "3d", "Lower base OBJ", "model/obj"),
                _record(job_dir, lid_obj, "3d", "Upper lid OBJ", "model/obj"),
            ]
        )

    preview: dict[str, Any] = {
        "base_stl": base_stl.relative_to(job_dir).as_posix() if need_stl else None,
        "lid_stl": lid_stl.relative_to(job_dir).as_posix() if need_stl else None,
        "hinge_axis": list(models.hinge_axis),
        "opening_angle_deg": config.hinge.opening_angle_deg,
    }
    if config.artifacts.export_glb:
        closed_glb = three_d_dir / "assembly.glb"
        open_glb = three_d_dir / "assembly_open.glb" if config.artifacts.export_open_preview else None
        mesh_bounds = export_preview_scenes(config, base_stl, lid_stl, closed_glb, open_glb)
        records.append(_record(job_dir, closed_glb, "3d", "Closed assembly GLB", "model/gltf-binary"))
        preview["closed_glb"] = closed_glb.relative_to(job_dir).as_posix()
        preview["mesh_bounds"] = mesh_bounds
        if open_glb is not None:
            records.append(_record(job_dir, open_glb, "3d", "Open assembly GLB", "model/gltf-binary"))
            preview["open_glb"] = open_glb.relative_to(job_dir).as_posix()

    two_d_paths = export_all_2d(config, job_dir / "2d")
    media = {
        ".dxf": "image/vnd.dxf",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
    }
    for path in two_d_paths:
        records.append(
            _record(
                job_dir,
                path,
                "2d",
                path.stem.replace("_", " ").title(),
                media[path.suffix.lower()],
            )
        )

    stats = {
        "base": shape_stats(models.base),
        "lid": shape_stats(models.lid),
    }
    stats_path = job_dir / "3d" / "model_stats.json"
    _write_json(stats_path, stats)
    records.append(_record(job_dir, stats_path, "validation", "3D model statistics", "application/json"))

    manifest: dict[str, Any] = {
        "job_id": identifier,
        "created_at": datetime.now(UTC).isoformat(),
        "project": config.metadata.model_dump(mode="json"),
        "warnings": warnings,
        "metrics": design_metrics(config),
        "preview": preview,
        "artifacts": [asdict(record) for record in records],
    }

    manifest_path = job_dir / "manifest.json"
    _write_json(manifest_path, manifest)
    manifest_record = _record(job_dir, manifest_path, "manifest", "Artifact manifest", "application/json")
    records.append(manifest_record)
    manifest["artifacts"] = [asdict(record) for record in records]
    _write_json(manifest_path, manifest)

    if config.artifacts.create_zip:
        zip_path = job_dir / "housing_project_bundle.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(job_dir.rglob("*")):
                if path.is_file() and path != zip_path:
                    archive.write(path, path.relative_to(job_dir))
        zip_record = _record(job_dir, zip_path, "bundle", "Complete artifact bundle", "application/zip")
        records.append(zip_record)
        manifest["bundle"] = zip_record.path
        manifest["artifacts"] = [asdict(record) for record in records]
        _write_json(manifest_path, manifest)

    return manifest
