from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

from pydantic import BaseModel

from shared.contracts.models import (
    ArtifactRefV1,
    BugReportV1,
    DashboardRunBundleV1,
    ErrorV1,
    FixResultV1,
    FixTaskV1,
    PersonaConfigV1,
    RunConfigV1,
    RunStateV1,
    Stage0ResetResultV1,
    TranscriptEventV1,
    VerifierDecisionV1,
    VerifierInputV1,
)


ContractModel: TypeAlias = type[BaseModel]

CONTRACTS: dict[str, ContractModel] = {
    "artifact_ref": ArtifactRefV1,
    "bug_report": BugReportV1,
    "dashboard_run_bundle": DashboardRunBundleV1,
    "error": ErrorV1,
    "fix_result": FixResultV1,
    "fix_task": FixTaskV1,
    "persona_config": PersonaConfigV1,
    "run_config": RunConfigV1,
    "run_state": RunStateV1,
    "stage0_reset_result": Stage0ResetResultV1,
    "transcript_event": TranscriptEventV1,
    "verifier_decision": VerifierDecisionV1,
    "verifier_input": VerifierInputV1,
}


def infer_contract_name(path: Path) -> str:
    filename = path.name.replace(".valid", "").replace(".invalid", "")
    if filename.endswith(".json"):
        filename = filename[:-5]

    for contract_name in sorted(CONTRACTS, key=len, reverse=True):
        if filename.startswith(contract_name):
            return contract_name

    raise ValueError(f"Cannot infer contract type from {path}")


def model_for_path(path: Path) -> ContractModel:
    return CONTRACTS[infer_contract_name(path)]
