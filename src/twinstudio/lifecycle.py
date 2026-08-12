from __future__ import annotations

from typing import Any

from twinstudio.domain import ArtifactKind, ChangeOperationKind, LifecycleStage, Role
from twinstudio.evolution_catalog import load_evolution_catalog
from twinstudio.evolution_models import (
    EvolutionMethod,
    LifecycleBlueprint,
    LifecycleStageDefinition,
    LifecycleTransition,
)


_STAGE_PURPOSE: dict[LifecycleStage, str] = {
    LifecycleStage.OPPORTUNITY: "Identify value, stakeholders and the opportunity worth pursuing.",
    LifecycleStage.DISCOVERY: "Observe context, users, interfaces and present evidence.",
    LifecycleStage.EVIDENCE: "Collect source artifacts and separate facts from assumptions.",
    LifecycleStage.PROBLEM_FRAMING: "Express the desired outcome without fixing the current mechanism.",
    LifecycleStage.REQUIREMENTS: "Define measurable needs, constraints and verification routes.",
    LifecycleStage.CONCEPT: "Generate diverse mechanisms and architectures.",
    LifecycleStage.FEASIBILITY: "Retire dominant technical, commercial and supply uncertainties.",
    LifecycleStage.ARCHITECTURE: "Allocate functions, modules, interfaces and responsibilities.",
    LifecycleStage.DETAILED_DESIGN: "Complete geometry, electronics, software, tolerances and documentation.",
    LifecycleStage.DESIGN_REVIEW: "Review cross-domain consistency, risks and readiness to build.",
    LifecycleStage.PROTOTYPE: "Build representative artifacts for learning.",
    LifecycleStage.INTEGRATION: "Integrate mechanical, electrical, software and human interfaces.",
    LifecycleStage.VERIFICATION: "Verify implementation against requirements.",
    LifecycleStage.VALIDATION: "Validate intended use with representative users and contexts.",
    LifecycleStage.COMPLIANCE: "Establish conformity and required technical evidence.",
    LifecycleStage.PILOT: "Demonstrate the product and process at limited scale.",
    LifecycleStage.PILOT_PRODUCTION: "Demonstrate production readiness at limited volume.",
    LifecycleStage.INDUSTRIALIZATION: "Stabilize process, supply, quality and work instructions.",
    LifecycleStage.RELEASE: "Freeze and package approved product and production baselines.",
    LifecycleStage.PRODUCTION: "Build released products under controlled change.",
    LifecycleStage.QUALITY_CONTROL: "Inspect and control production conformance.",
    LifecycleStage.FULFILLMENT: "Package, configure, distribute and deliver products.",
    LifecycleStage.OPERATION: "Deliver intended value in real use.",
    LifecycleStage.MONITORING: "Observe field performance, failures and emerging needs.",
    LifecycleStage.MAINTENANCE: "Restore function and manage wear.",
    LifecycleStage.SERVICE: "Diagnose, repair and support products in the field.",
    LifecycleStage.IMPROVEMENT: "Convert operational evidence into controlled product evolution.",
    LifecycleStage.UPGRADE: "Extend capability while retaining long-lived value.",
    LifecycleStage.RECALL: "Control unsafe or materially nonconforming field populations.",
    LifecycleStage.REUSE: "Prepare components or products for another use.",
    LifecycleStage.REUSE_REMANUFACTURE: "Recover, restore and requalify long-lived value.",
    LifecycleStage.RETIREMENT: "Remove products from service safely and preserve records.",
    LifecycleStage.RECYCLING: "Separate and recover materials responsibly.",
    LifecycleStage.END_OF_LIFE: "Close obligations and dispose of unrecoverable residuals.",
}


def _stage_methods(stage: LifecycleStage) -> list[EvolutionMethod]:
    if stage in {LifecycleStage.PROBLEM_FRAMING, LifecycleStage.OPPORTUNITY}:
        return [
            EvolutionMethod.GOAL_LADDER,
            EvolutionMethod.ASSUMPTION_REVERSAL,
            EvolutionMethod.CONSTRAINT_RELAXATION,
            EvolutionMethod.BRAINSWARM,
        ]
    if stage in {LifecycleStage.CONCEPT, LifecycleStage.ARCHITECTURE}:
        return [
            EvolutionMethod.OBJECT_DECOMPOSITION,
            EvolutionMethod.BIDIRECTIONAL_GRAPH,
            EvolutionMethod.FEATURE_LENSES,
            EvolutionMethod.ADJACENT_POSSIBLE,
            EvolutionMethod.RECOMBINATION,
        ]
    if stage in {LifecycleStage.FEASIBILITY, LifecycleStage.PROTOTYPE, LifecycleStage.VERIFICATION}:
        return [EvolutionMethod.EXPERIMENT, EvolutionMethod.MUTATION, EvolutionMethod.FEATURE_LENSES]
    if stage in {LifecycleStage.OPERATION, LifecycleStage.MONITORING, LifecycleStage.IMPROVEMENT}:
        return [EvolutionMethod.FEATURE_LENSES, EvolutionMethod.ADJACENT_POSSIBLE, EvolutionMethod.EXPERIMENT]
    return [EvolutionMethod.FEATURE_LENSES]


def _allowed_operations(stage: LifecycleStage) -> list[ChangeOperationKind]:
    observation_only = [ChangeOperationKind.ADD_ANNOTATION, ChangeOperationKind.ATTACH_REQUIREMENT]
    if stage in {
        LifecycleStage.OPPORTUNITY,
        LifecycleStage.DISCOVERY,
        LifecycleStage.EVIDENCE,
        LifecycleStage.PROBLEM_FRAMING,
        LifecycleStage.REQUIREMENTS,
    }:
        return observation_only + [ChangeOperationKind.ADD_TEST]
    if stage in {
        LifecycleStage.CONCEPT,
        LifecycleStage.FEASIBILITY,
        LifecycleStage.ARCHITECTURE,
        LifecycleStage.DETAILED_DESIGN,
        LifecycleStage.PROTOTYPE,
        LifecycleStage.INTEGRATION,
        LifecycleStage.IMPROVEMENT,
        LifecycleStage.UPGRADE,
    }:
        return list(ChangeOperationKind)
    return observation_only + [
        ChangeOperationKind.SET_PARAMETER,
        ChangeOperationKind.UPDATE_MANUFACTURING,
        ChangeOperationKind.ADD_TEST,
    ]


class LifecycleRegistry:
    """Versioned product lifecycle templates and transition checks."""

    def __init__(self) -> None:
        self.catalog = load_evolution_catalog()

    def catalog_payload(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog.catalog_version,
            "templates": {
                key: value.model_dump(mode="json")
                for key, value in self.catalog.lifecycle_templates.items()
            },
            "stage_values": [item.value for item in LifecycleStage],
        }

    def blueprint(
        self,
        template_id: str = "hardware-product",
        *,
        current_stage: LifecycleStage | str | None = None,
    ) -> LifecycleBlueprint:
        try:
            template = self.catalog.lifecycle_templates[template_id]
        except KeyError as exc:
            raise ValueError(f"Unknown lifecycle template: {template_id}") from exc
        stages = [LifecycleStage(item) for item in template.stages]
        if not stages:
            raise ValueError("Lifecycle template has no stages")
        current = LifecycleStage(current_stage) if current_stage else stages[0]
        if current not in stages:
            current = stages[0]
        definitions = [
            LifecycleStageDefinition(
                stage=stage,
                name=stage.value.replace("_", " ").title(),
                purpose=_STAGE_PURPOSE.get(stage, "Manage this product lifecycle stage."),
                entry_criteria=["The previous stage has a recorded decision or an approved exception."],
                exit_criteria=["Required evidence, risks and decisions for this stage are recorded."],
                required_artifact_kinds=_required_artifacts(stage),
                required_test_types=_required_tests(stage),
                recommended_evolution_methods=_stage_methods(stage),
                allowed_change_operations=_allowed_operations(stage),
                approver_roles=[Role.ADMIN, Role.CREATOR],
                optional=stage in {LifecycleStage.RECALL, LifecycleStage.UPGRADE, LifecycleStage.REUSE},
                repeatable=stage in {
                    LifecycleStage.PROTOTYPE,
                    LifecycleStage.VERIFICATION,
                    LifecycleStage.MONITORING,
                    LifecycleStage.IMPROVEMENT,
                    LifecycleStage.MAINTENANCE,
                },
            )
            for stage in stages
        ]
        transitions = [
            LifecycleTransition(
                from_stage=stages[index],
                to_stage=stages[index + 1],
                conditions=["Exit criteria are satisfied or an approved deviation exists."],
                required_gate_status="approved",
                approver_roles=[Role.ADMIN, Role.CREATOR],
            )
            for index in range(len(stages) - 1)
        ]
        return LifecycleBlueprint(
            blueprint_id=template_id,
            name=template.name,
            version=self.catalog.catalog_version,
            stages=definitions,
            transitions=transitions,
            current_stage=current,
            tailored=False,
            notes=[
                "Template generated from the TwinStudio evolution catalog.",
                "Tailor gates, evidence and approvals to product risk and regulation.",
            ],
        )

    @staticmethod
    def transition(
        blueprint: LifecycleBlueprint,
        to_stage: LifecycleStage | str,
    ) -> LifecycleTransition:
        target = LifecycleStage(to_stage)
        for transition in blueprint.transitions:
            if transition.from_stage == blueprint.current_stage and transition.to_stage == target:
                return transition
        raise ValueError(
            f"Transition {blueprint.current_stage.value} -> {target.value} is not allowed by the blueprint"
        )


def _required_artifacts(stage: LifecycleStage) -> list[ArtifactKind]:
    if stage == LifecycleStage.DETAILED_DESIGN:
        return [ArtifactKind.CAD_SOURCE, ArtifactKind.DRAWING_2D, ArtifactKind.BOM]
    if stage in {LifecycleStage.PROTOTYPE, LifecycleStage.VERIFICATION, LifecycleStage.VALIDATION}:
        return [ArtifactKind.TEST_RESULT]
    if stage == LifecycleStage.RELEASE:
        return [ArtifactKind.CAD_SOURCE, ArtifactKind.STEP, ArtifactKind.BOM, ArtifactKind.PDF]
    if stage in {LifecycleStage.PRODUCTION, LifecycleStage.QUALITY_CONTROL}:
        return [ArtifactKind.DRAWING_2D, ArtifactKind.BOM, ArtifactKind.TEST_RESULT]
    return []


def _required_tests(stage: LifecycleStage) -> list[str]:
    if stage == LifecycleStage.VERIFICATION:
        return ["mechanical", "electrical", "thermal", "software", "manufacturing"]
    if stage == LifecycleStage.VALIDATION:
        return ["human_use", "field_context"]
    if stage == LifecycleStage.COMPLIANCE:
        return ["regulatory", "safety", "emc"]
    if stage in {LifecycleStage.PILOT, LifecycleStage.PILOT_PRODUCTION, LifecycleStage.PRODUCTION}:
        return ["manufacturing", "inspection"]
    return []
