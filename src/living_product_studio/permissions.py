from __future__ import annotations

from living_product_studio.domain import Role


ROLE_ORDER = {
    Role.READER: 10,
    Role.EDITOR: 20,
    Role.ADMIN: 30,
    Role.CREATOR: 40,
}

PERMISSIONS: dict[str, set[Role]] = {
    "project.read": {Role.READER, Role.EDITOR, Role.ADMIN, Role.CREATOR},
    "artifact.download": {Role.READER, Role.EDITOR, Role.ADMIN, Role.CREATOR},
    "annotation.create": {Role.EDITOR, Role.ADMIN, Role.CREATOR},
    "change.plan": {Role.EDITOR, Role.ADMIN, Role.CREATOR},
    "change.apply": {Role.EDITOR, Role.ADMIN, Role.CREATOR},
    "artifact.generate": {Role.EDITOR, Role.ADMIN, Role.CREATOR},
    "simulation.run": {Role.EDITOR, Role.ADMIN, Role.CREATOR},
    "approval.grant": {Role.ADMIN, Role.CREATOR},
    "membership.invite": {Role.ADMIN, Role.CREATOR},
    "membership.manage": {Role.ADMIN, Role.CREATOR},
    "project.delete": {Role.CREATOR},
    "creator.transfer": {Role.CREATOR},
}


class PermissionDenied(PermissionError):
    pass


def has_permission(role: Role | str | None, permission: str) -> bool:
    if role is None:
        return False
    resolved = role if isinstance(role, Role) else Role(role)
    return resolved in PERMISSIONS.get(permission, set())


def require_permission(role: Role | str | None, permission: str) -> None:
    if not has_permission(role, permission):
        raise PermissionDenied(f"Role {role!r} lacks permission {permission!r}")
