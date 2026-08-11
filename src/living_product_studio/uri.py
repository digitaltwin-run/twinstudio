from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse


class PoaUriError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PoaUri:
    """Product Object Addressing URI.

    Canonical form:
      poa://{tenant}/{project}@{revision}/{kind}/{id}/...

    The package defines POA as Product Object Addressing. It is a project-specific
    addressing contract, not CORBA Portable Object Adapter or blockchain Proof of Authority.
    """

    tenant: str
    project: str
    revision: str
    segments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for label, value in (("tenant", self.tenant), ("project", self.project), ("revision", self.revision)):
            if not value or any(ch in value for ch in "/@?#"):
                raise PoaUriError(f"Invalid {label}: {value!r}")
        if any(not segment or "/" in segment for segment in self.segments):
            raise PoaUriError("POA segments must be non-empty path atoms")

    @property
    def canonical(self) -> str:
        base = f"poa://{quote(self.tenant, safe='')}/{quote(self.project, safe='')}@{quote(self.revision, safe='')}"
        if not self.segments:
            return base
        return base + "/" + "/".join(quote(item, safe="._:-") for item in self.segments)

    def child(self, *segments: str) -> "PoaUri":
        return PoaUri(self.tenant, self.project, self.revision, self.segments + tuple(segments))

    def with_revision(self, revision: str) -> "PoaUri":
        return PoaUri(self.tenant, self.project, revision, self.segments)

    def is_ancestor_of(self, other: "PoaUri", *, ignore_revision: bool = False) -> bool:
        if self.tenant != other.tenant or self.project != other.project:
            return False
        if not ignore_revision and self.revision != other.revision:
            return False
        return other.segments[: len(self.segments)] == self.segments

    def __str__(self) -> str:
        return self.canonical


def parse_poa_uri(value: str) -> PoaUri:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "poa":
        raise PoaUriError("POA URI must use the poa:// scheme")
    if not parsed.netloc:
        raise PoaUriError("POA URI requires a tenant authority")
    atoms = [unquote(atom) for atom in parsed.path.split("/") if atom]
    if not atoms or "@" not in atoms[0]:
        raise PoaUriError("POA URI path must begin with project@revision")
    project, revision = atoms[0].rsplit("@", 1)
    return PoaUri(unquote(parsed.netloc), project, revision, tuple(atoms[1:]))


def build_poa_uri(tenant: str, project: str, revision: str, *segments: str) -> str:
    return PoaUri(tenant, project, revision, tuple(segments)).canonical


def is_within_scope(target_uri: str, scope_uris: list[str], *, ignore_revision: bool = False) -> bool:
    target = parse_poa_uri(target_uri)
    return any(parse_poa_uri(scope).is_ancestor_of(target, ignore_revision=ignore_revision) for scope in scope_uris)
