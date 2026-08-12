import pytest

from twinstudio.domain import Role
from twinstudio.permissions import PermissionDenied, has_permission, require_permission


def test_role_matrix() -> None:
    assert has_permission(Role.READER, "project.read")
    assert not has_permission(Role.READER, "change.apply")
    assert has_permission(Role.EDITOR, "change.plan")
    assert has_permission(Role.ADMIN, "membership.manage")
    assert has_permission(Role.CREATOR, "project.delete")


def test_permission_exception() -> None:
    with pytest.raises(PermissionDenied):
        require_permission("reader", "membership.invite")
