from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from twinstudio.domain import ArtifactRecord, ObjectNode, ParameterValue, ProjectSnapshot

BASE_SUFFIX = "/part/base"
LID_SUFFIX = "/part/lid"


@dataclass(frozen=True, slots=True)
class CadRegenerationResult:
    job_id: str
    manifest_path: str
    artifacts: list[ArtifactRecord]
    objects: list[ObjectNode]
    mapped_parameters: list[str]


class CadChangeInvalid(ValueError):
    """A proposed scalar change would create an invalid CAD configuration."""

    def __init__(self, warnings: list[dict[str, Any]]) -> None:
        self.warnings = warnings
        messages = "; ".join(str(item.get("message", item.get("code"))) for item in warnings)
        super().__init__(f"Blocking design validation errors: {messages}")


def _part(snapshot: ProjectSnapshot, suffix: str) -> ObjectNode:
    node = next((item for uri, item in snapshot.objects.items() if uri.endswith(suffix)), None)
    if node is None:
        raise ValueError(f"Project has no parametric housing object ending with {suffix!r}")
    return node


def _parameter_number(node: ObjectNode, parameter: str) -> float | None:
    value = node.parameters.get(parameter)
    if value is None or isinstance(value.value, bool) or not isinstance(value.value, (int, float)):
        return None
    return float(value.value)


def _number(node: ObjectNode, parameter: str, default: float) -> float:
    value = _parameter_number(node, parameter)
    return default if value is None else value


def _cad_dimensions(node: ObjectNode) -> dict[str, Any]:
    value = node.metadata.get("cad_dimensions")
    return value if isinstance(value, dict) else {}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _generated_lid_height(base: ObjectNode, lid: ObjectNode, source_total_height: float) -> float | None:
    """Return the last physical lid height when its source parameter is still current."""

    stored = _cad_dimensions(lid) or _cad_dimensions(base)
    lid_height = _finite_number(stored.get("lid_height_mm"))
    stored_source_total = _finite_number(stored.get("source_total_height_mm"))
    if lid_height is None or stored_source_total is None:
        return None
    if abs(stored_source_total - source_total_height) > 1e-9:
        # The total-height parameter was explicitly changed after the last CAD build.
        return None
    return lid_height


def physical_component_height(snapshot: ProjectSnapshot, object_uri: str) -> float | None:
    """Return the current physical component height represented by project state."""

    node = snapshot.objects.get(object_uri)
    if node is None:
        return None
    direct_height = _parameter_number(node, "height")
    if direct_height is not None:
        return direct_height
    if not object_uri.endswith(LID_SUFFIX):
        return None
    try:
        base = _part(snapshot, BASE_SUFFIX)
    except ValueError:
        return None
    source_total_height = _parameter_number(node, "total_height")
    if source_total_height is None:
        return None
    generated_height = _generated_lid_height(base, node, source_total_height)
    if generated_height is not None:
        return generated_height
    base_height = _parameter_number(base, "height")
    if base_height is None or source_total_height <= base_height:
        return None
    return source_total_height - base_height


def housing_config_from_snapshot(
    snapshot: ProjectSnapshot,
    *,
    dimension_overrides: dict[str, float] | None = None,
):
    """Translate canonical TwinStudio parameters into Housing Studio configuration."""

    from housing_studio.models import default_project_config

    base = _part(snapshot, BASE_SUFFIX)
    lid = _part(snapshot, LID_SUFFIX)
    config = default_project_config()
    base_height = _number(base, "height", config.dimensions.base_height)
    source_total_height = _number(lid, "total_height", config.dimensions.total_height)
    lid_height = _parameter_number(lid, "height")
    if lid_height is None:
        lid_height = _generated_lid_height(base, lid, source_total_height)
    overrides = dimension_overrides or {}
    if "lid_height_mm" in overrides:
        lid_height = float(overrides["lid_height_mm"])
    total_height = base_height + lid_height if lid_height is not None else source_total_height
    dimensions = config.dimensions.model_copy(
        update={
            "external_width": _number(base, "width", config.dimensions.external_width),
            "external_depth": _number(base, "depth", config.dimensions.external_depth),
            "base_height": base_height,
            "total_height": total_height,
            "wall_thickness": _number(base, "wall_thickness", config.dimensions.wall_thickness),
            "floor_thickness": _number(base, "floor_thickness", config.dimensions.floor_thickness),
            "lid_top_thickness": _number(lid, "wall_thickness", config.dimensions.lid_top_thickness),
            "lid_vertical_lower_section": _number(
                lid,
                "vertical_joint_section",
                config.dimensions.lid_vertical_lower_section,
            ),
        }
    )
    artifact_options = config.artifacts.model_copy(
        update={
            "export_step": False,
            "export_stl": True,
            "export_obj": False,
            "export_glb": False,
            "export_dxf": False,
            "export_svg": True,
            "export_pdf": False,
            "export_open_preview": False,
            "create_zip": False,
        }
    )
    metadata = config.metadata.model_copy(
        update={
            "name": snapshot.name,
            "revision": snapshot.revision,
            "description": snapshot.description or config.metadata.description,
        }
    )
    return type(config).model_validate(
        {
            **config.model_dump(mode="python"),
            "metadata": metadata.model_dump(mode="python"),
            "dimensions": dimensions.model_dump(mode="python"),
            "artifacts": artifact_options.model_dump(mode="python"),
        }
    )


def dimension_overrides_for_change(
    snapshot: ProjectSnapshot,
    parameter_patches: list[dict[str, Any]],
) -> dict[str, float]:
    """Preserve unedited component dimensions across a coupled assembly regeneration."""

    try:
        base = _part(snapshot, BASE_SUFFIX)
        lid = _part(snapshot, LID_SUFFIX)
    except ValueError:
        return {}
    changed = {(item.get("object_uri"), item.get("parameter")) for item in parameter_patches}
    lid_height_patch = next(
        (
            item
            for item in parameter_patches
            if item.get("object_uri") == lid.uri and item.get("parameter") == "height"
        ),
        None,
    )
    if lid_height_patch is not None:
        lid_height = _finite_number(lid_height_patch.get("value"))
        return {"lid_height_mm": lid_height} if lid_height is not None and lid_height > 0 else {}
    base_height_changed = (base.uri, "height") in changed
    total_height_changed = (lid.uri, "total_height") in changed
    if not base_height_changed or total_height_changed:
        return {}
    config = housing_config_from_snapshot(snapshot)
    return {"lid_height_mm": config.dimensions.lid_height}


def validate_parameter_change(
    snapshot: ProjectSnapshot,
    parameter_patches: list[dict[str, Any]],
    *,
    dimension_overrides: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Preflight scalar patches against the CAD adapter without mutating project state.

    Non-housing projects have no Housing Studio configuration and are intentionally
    ignored here. Their adapters remain responsible for their own validation.
    """

    if not parameter_patches:
        return []
    candidate = snapshot.model_copy(deep=True)
    for patch in parameter_patches:
        target = candidate.objects.get(str(patch.get("object_uri", "")))
        if target is None:
            continue
        parameter = str(patch.get("parameter", ""))
        if not parameter:
            continue
        if patch.get("remove"):
            target.parameters.pop(parameter, None)
            continue
        restored = patch.get("restore_parameter")
        if restored is not None:
            target.parameters[parameter] = ParameterValue.model_validate(restored)
            continue
        existing = target.parameters.get(parameter)
        if existing is not None:
            target.parameters[parameter] = existing.model_copy(
                update={
                    "value": patch.get("value"),
                    "unit": patch.get("unit") if patch.get("unit") is not None else existing.unit,
                }
            )
        else:
            target.parameters[parameter] = ParameterValue(
                value=patch.get("value"),
                unit=patch.get("unit"),
                status="approved",
            )

    try:
        _part(candidate, BASE_SUFFIX)
        _part(candidate, LID_SUFFIX)
    except ValueError:
        return []

    from housing_studio.validation import collect_warnings

    try:
        config = housing_config_from_snapshot(candidate, dimension_overrides=dimension_overrides)
    except ValueError as exc:
        raise CadChangeInvalid(
            [
                {
                    "code": "CAD_CONFIGURATION_INVALID",
                    "severity": "error",
                    "message": str(exc),
                    "suggestion": "Use a positive value inside the supported parameter range.",
                }
            ]
        ) from exc
    warnings = [item.to_dict() for item in collect_warnings(config)]
    blocking = [item for item in warnings if item["severity"] == "error"]
    if blocking:
        raise CadChangeInvalid(blocking)
    return warnings


def _manifest_record(manifest: dict[str, Any], path: str) -> dict[str, Any]:
    record = next((item for item in manifest.get("artifacts", []) if item.get("path") == path), None)
    if record is None:
        raise ValueError(f"CAD generator did not produce required artifact {path!r}")
    return record


def _relative_data_path(data_dir: Path, path: Path) -> str:
    resolved_data = data_dir.resolve()
    resolved = path.resolve()
    if resolved_data not in resolved.parents:
        raise ValueError("Generated CAD artifact escaped TWINSTUDIO_DATA_DIR")
    if not resolved.is_file():
        raise ValueError(f"Generated CAD artifact is missing: {resolved}")
    return resolved.relative_to(resolved_data).as_posix()


def records_from_manifest(
    snapshot: ProjectSnapshot,
    data_dir: Path,
    job_id: str,
    manifest: dict[str, Any],
    *,
    generated_dimensions: dict[str, float] | None = None,
) -> CadRegenerationResult:
    """Map generated preview files back onto stable project artifact URIs."""

    base = _part(snapshot, BASE_SUFFIX)
    lid = _part(snapshot, LID_SUFFIX)
    enclosure = next(
        (item for uri, item in snapshot.objects.items() if uri.endswith("/assembly/enclosure")),
        None,
    )

    def artifact_uri(key: str) -> str:
        existing = next((uri for uri in snapshot.artifacts if uri.endswith(f"/artifact/{key}")), None)
        if existing is None:
            raise ValueError(f"Project has no stable artifact URI for {key!r}")
        return existing

    job_root = data_dir / "cad-jobs" / job_id
    revision = snapshot.revision
    mappings = [
        ("base-stl", "3d/base.stl", "stl", "model/stl", base.uri),
        ("lid-stl", "3d/lid.stl", "stl", "model/stl", lid.uri),
        (
            "assembly-front",
            "2d/assembly/assembly_front.svg",
            "drawing_2d",
            "image/svg+xml",
            enclosure.uri if enclosure else None,
        ),
        (
            "assembly-top",
            "2d/assembly/assembly_top.svg",
            "drawing_2d",
            "image/svg+xml",
            enclosure.uri if enclosure else None,
        ),
        (
            "assembly-side",
            "2d/assembly/assembly_side.svg",
            "drawing_2d",
            "image/svg+xml",
            enclosure.uri if enclosure else None,
        ),
    ]
    artifacts: list[ArtifactRecord] = []
    for key, generated_path, kind, media_type, object_uri in mappings:
        source = job_root / generated_path
        manifest_record = _manifest_record(manifest, generated_path)
        artifacts.append(
            ArtifactRecord(
                uri=artifact_uri(key),
                name=source.name,
                kind=kind,
                path=_relative_data_path(data_dir, source),
                media_type=media_type,
                object_uri=object_uri,
                revision=revision,
                sha256=manifest_record.get("sha256"),
                size_bytes=manifest_record.get("size_bytes"),
                generated=True,
                metadata={
                    "generator": "housing-studio",
                    "cad_job_id": job_id,
                    "manifest": f"cad-jobs/{job_id}/manifest.json",
                },
            )
        )

    artifact_by_key = {item.uri.rsplit("/", 1)[-1]: item for item in artifacts}
    object_updates: list[ObjectNode] = []
    for node, artifact_key in ((base, "base-stl"), (lid, "lid-stl")):
        metadata = dict(node.metadata)
        parameters = dict(node.parameters)
        metadata["viewer_mesh"] = artifact_by_key[artifact_key].path
        metadata["cad_job_id"] = job_id
        if generated_dimensions:
            metadata["cad_dimensions"] = generated_dimensions
            if node.uri == lid.uri:
                physical_height = float(generated_dimensions["lid_height_mm"])
                existing_height = parameters.get("height")
                parameters["height"] = (
                    existing_height.model_copy(update={"value": physical_height, "unit": "mm"})
                    if existing_height is not None
                    else ParameterValue(
                        value=physical_height,
                        unit="mm",
                        status="derived",
                        notes="Physical component height synchronized from the latest CAD generation.",
                    )
                )
        object_updates.append(
            node.model_copy(
                update={"revision": revision, "metadata": metadata, "parameters": parameters}
            )
        )

    mapped_parameters = [
        f"{base.uri}:width",
        f"{base.uri}:depth",
        f"{base.uri}:height",
        f"{base.uri}:wall_thickness",
        f"{base.uri}:floor_thickness",
        f"{lid.uri}:wall_thickness",
        f"{lid.uri}:height",
        f"{lid.uri}:total_height",
        f"{lid.uri}:vertical_joint_section",
    ]
    return CadRegenerationResult(
        job_id=job_id,
        manifest_path=f"cad-jobs/{job_id}/manifest.json",
        artifacts=artifacts,
        objects=object_updates,
        mapped_parameters=mapped_parameters,
    )


def generate_project_preview(
    snapshot: ProjectSnapshot,
    data_dir: Path,
    job_id: str,
    *,
    prompt: str | None = None,
    dimension_overrides: dict[str, float] | None = None,
) -> CadRegenerationResult:
    from housing_studio.artifacts import generate_artifacts

    config = housing_config_from_snapshot(snapshot, dimension_overrides=dimension_overrides)
    manifest = generate_artifacts(
        config,
        data_dir / "cad-jobs",
        job_id=job_id,
        source_prompt=prompt,
        interpretation_mode="twinstudio-parameter-regeneration",
    )
    lid = _part(snapshot, LID_SUFFIX)
    generated_dimensions = {
        "base_height_mm": config.dimensions.base_height,
        "lid_height_mm": config.dimensions.lid_height,
        "total_height_mm": config.dimensions.total_height,
        "source_total_height_mm": _number(
            lid,
            "total_height",
            config.dimensions.total_height,
        ),
    }
    return records_from_manifest(
        snapshot,
        data_dir,
        job_id,
        manifest,
        generated_dimensions=generated_dimensions,
    )
