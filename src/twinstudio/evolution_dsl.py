"""Compatibility facade for the canonical TwinStudio DSL compiler."""
from __future__ import annotations

from dataclasses import dataclass

from twinstudio.dsl import ParsedDsl, parse_dsl
from twinstudio.evolution_models import DslDiagnostic, TwinDslDocument


@dataclass(frozen=True, slots=True)
class CompileResult:
    program: TwinDslDocument | None
    diagnostics: list[DslDiagnostic]
    normalized_source: str
    input_format: str

    @property
    def valid(self) -> bool:
        return self.program is not None and ParsedDsl(
            document=self.program,
            diagnostics=self.diagnostics,
            source_format=self.input_format,
        ).valid


class EvolutionDslCompiler:
    """Parse TwinScript, YAML or JSON into the canonical ``TwinDslDocument``.

    Validation against a concrete project and generation of evolution artifacts are
    performed by :func:`twinstudio.dsl.compile_dsl` and
    :class:`twinstudio.evolution.ProjectEvolutionEngine`.
    """

    schema_version = "twinstudio.io/v1alpha1"
    dsl_version = "1.0"

    def compile(
        self,
        source: str,
        *,
        input_format: str = "auto",
        project_id: str | None = None,
        targets: list[str] | None = None,
    ) -> CompileResult:
        parsed = parse_dsl(source, source_format=input_format)
        document = parsed.document
        if document and (project_id or targets):
            updates = document.model_dump(mode="python")
            if project_id:
                updates["spec"]["project_id"] = project_id
            if targets:
                updates["spec"]["targets"] = list(targets)
            document = TwinDslDocument.model_validate(updates)
        return CompileResult(
            program=document,
            diagnostics=parsed.diagnostics,
            normalized_source=document.model_dump_json(indent=2) if document else "",
            input_format=parsed.source_format,
        )


__all__ = ["CompileResult", "EvolutionDslCompiler"]
