from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import cadquery as cq


class ScopedCadError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _vector(data: dict[str, Any]) -> cq.Vector:
    return cq.Vector(float(data["x"]), float(data["y"]), float(data["z"]))


def _average(vectors: Iterable[cq.Vector]) -> cq.Vector:
    items = list(vectors)
    if not items:
        raise ScopedCadError("Selection has no usable vectors")
    return cq.Vector(
        sum(item.x for item in items) / len(items),
        sum(item.y for item in items) / len(items),
        sum(item.z for item in items) / len(items),
    )


def _unit(vector: cq.Vector) -> cq.Vector:
    length = math.sqrt(vector.x * vector.x + vector.y * vector.y + vector.z * vector.z)
    if length <= 1e-9:
        raise ScopedCadError("Selection normal has zero length")
    return cq.Vector(vector.x / length, vector.y / length, vector.z / length)


def _selection_center(selection: dict[str, Any]) -> cq.Vector:
    hits = selection.get("ray_hits") or []
    if hits:
        return _average(_vector(hit["point"]) for hit in hits)
    aabb = selection.get("world_aabb")
    if not aabb:
        raise ScopedCadError("A local operation requires ray hits or a world-space AABB")
    low, high = _vector(aabb["minimum"]), _vector(aabb["maximum"])
    return cq.Vector((low.x + high.x) / 2, (low.y + high.y) / 2, (low.z + high.z) / 2)


def _selection_normal(selection: dict[str, Any]) -> cq.Vector:
    normals = [_vector(hit["normal"]) for hit in selection.get("ray_hits") or [] if hit.get("normal")]
    if not normals:
        raise ScopedCadError("A directional local operation requires at least one ray-hit normal")
    return _unit(_average(normals))


def _verify_scope(selection: dict[str, Any], operation: dict[str, Any]) -> str:
    selected = set(selection.get("target_object_uris") or [])
    target = str(operation.get("target_uri") or "")
    if not selected or target not in selected:
        raise ScopedCadError("Operation target must exactly match one of the selected object URIs")
    hit_targets = {str(hit.get("object_uri")) for hit in selection.get("ray_hits") or []}
    if hit_targets and not hit_targets.issubset(selected):
        raise ScopedCadError("Ray hits contain objects outside the selected scope")
    return target


def _load_step(path: Path) -> cq.Shape:
    if path.suffix.lower() not in {".step", ".stp"}:
        raise ScopedCadError("The demonstration B-Rep adapter accepts STEP input only")
    imported = cq.importers.importStep(str(path))
    shape = imported.val()
    if shape is None or shape.isNull():
        raise ScopedCadError("STEP input does not contain a valid shape")
    return shape


def _hole_tool(shape: cq.Shape, selection: dict[str, Any], arguments: dict[str, Any]) -> cq.Shape:
    diameter = float(arguments.get("diameter_mm", 0))
    if diameter <= 0:
        raise ScopedCadError("Hole diameter must be positive")
    center = _selection_center(selection)
    direction = _selection_normal(selection)
    bounds = shape.BoundingBox()
    length = max(bounds.xlen, bounds.ylen, bounds.zlen) * 3.0 + diameter * 4.0
    start = center - direction.multiply(length / 2.0)
    return cq.Solid.makeCylinder(diameter / 2.0, length, start, direction)


def _aabb_box(selection: dict[str, Any], arguments: dict[str, Any]) -> cq.Shape:
    aabb = selection.get("world_aabb")
    if not aabb:
        raise ScopedCadError("A local box operation requires world_aabb")
    low, high = _vector(aabb["minimum"]), _vector(aabb["maximum"])
    margin = float(arguments.get("margin_mm", 0.0))
    dx, dy, dz = high.x - low.x + 2 * margin, high.y - low.y + 2 * margin, high.z - low.z + 2 * margin
    if min(dx, dy, dz) <= 0:
        raise ScopedCadError("Selected AABB has zero or negative extent")
    return cq.Solid.makeBox(dx, dy, dz, cq.Vector(low.x - margin, low.y - margin, low.z - margin))


def apply_scoped_operation(
    *,
    input_step: Path,
    output_dir: Path,
    selection: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any]:
    """Apply a small allow-listed local B-Rep operation and write review artifacts.

    Supported operations intentionally remain narrow:
      * boolean_cut with feature_type=hole
      * boolean_cut with feature_type=local_box
      * boolean_add with feature_type=local_box

    This produces a derived B-Rep revision and an operation journal. It does not
    reconstruct a native SolidWorks/CadQuery feature history.
    """

    target_uri = _verify_scope(selection, operation)
    input_step = input_step.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    shape = _load_step(input_step)
    before_volume = float(shape.Volume())
    kind = str(operation.get("kind"))
    arguments = dict(operation.get("arguments") or {})
    feature_type = str(arguments.get("feature_type") or "")

    if kind == "boolean_cut" and feature_type == "hole":
        tool = _hole_tool(shape, selection, arguments)
        result = shape.cut(tool)
    elif kind == "boolean_cut" and feature_type == "local_box":
        tool = _aabb_box(selection, arguments)
        result = shape.cut(tool)
    elif kind == "boolean_add" and feature_type == "local_box":
        tool = _aabb_box(selection, arguments)
        result = shape.fuse(tool)
    else:
        raise ScopedCadError(f"Unsupported scoped operation: {kind}/{feature_type}")

    if result is None or result.isNull():
        raise ScopedCadError("CAD kernel returned a null result")
    if not result.isValid():
        raise ScopedCadError("CAD kernel result is invalid")

    step_path = output_dir / "scoped-result.step"
    stl_path = output_dir / "scoped-result.stl"
    cq.exporters.export(result, str(step_path), exportType="STEP")
    cq.exporters.export(result, str(stl_path), exportType="STL", tolerance=0.08, angularTolerance=0.15)
    after_volume = float(result.Volume())
    journal = {
        "adapter": "cadquery-scoped-brep-v1",
        "target_uri": target_uri,
        "input": {"path": str(input_step), "sha256": _sha256(input_step), "volume_mm3": before_volume},
        "selection": selection,
        "operation": operation,
        "outputs": {
            "step": {"path": str(step_path), "sha256": _sha256(step_path)},
            "stl": {"path": str(stl_path), "sha256": _sha256(stl_path)},
        },
        "result": {
            "volume_mm3": after_volume,
            "volume_delta_mm3": after_volume - before_volume,
            "valid": bool(result.isValid()),
            "solid_count": len(result.Solids()),
        },
        "limitations": [
            "Derived B-Rep only; native parametric feature history is not reconstructed.",
            "Selection-to-topology stability still depends on semantic/native IDs from the source generator.",
            "Only allow-listed hole and axis-aligned local-box operations are implemented.",
        ],
    }
    journal_path = output_dir / "operation-journal.json"
    journal_path.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
    journal["outputs"]["journal"] = {"path": str(journal_path), "sha256": _sha256(journal_path)}
    return journal
