"""Canonical step contracts for the research pipeline.

This module is intentionally small and deterministic: it reads
``config/step_contracts.json`` and exposes the step order, artifact names, and
dependency graph used by workflow, report generation, and validators.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "config" / "step_contracts.json"


@dataclass(frozen=True)
class StepContract:
    id: str
    name: str
    report_title: str
    report_icon: str
    prompt_file: str
    primary_artifact: str
    required_artifacts: tuple[str, ...]
    optional_artifacts: tuple[str, ...]
    dependencies: tuple[str, ...]
    optional: bool
    phase: str
    validation_gates: tuple[str, ...]
    contract_focus: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepContract:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            report_title=str(data["report_title"]),
            report_icon=str(data["report_icon"]),
            prompt_file=str(data["prompt_file"]),
            primary_artifact=str(data["primary_artifact"]),
            required_artifacts=tuple(str(x) for x in data.get("required_artifacts", [])),
            optional_artifacts=tuple(str(x) for x in data.get("optional_artifacts", [])),
            dependencies=tuple(str(x) for x in data.get("dependencies", [])),
            optional=bool(data.get("optional", False)),
            phase=str(data.get("phase", "")),
            validation_gates=tuple(str(x) for x in data.get("validation_gates", [])),
            contract_focus=str(data.get("contract_focus", "")),
        )


def _load_raw_contracts() -> dict[str, Any]:
    with CONTRACT_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data.get("steps"), list):
        raise ValueError(f"{CONTRACT_PATH} must contain a steps list")
    return data


@lru_cache(maxsize=1)
def load_step_contracts() -> tuple[StepContract, ...]:
    """Load all step contracts in configured order."""
    raw = _load_raw_contracts()
    contracts = tuple(StepContract.from_dict(item) for item in raw["steps"])
    ids = [c.id for c in contracts]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate step IDs in step_contracts.json")
    return contracts


@lru_cache(maxsize=1)
def _contract_map() -> dict[str, StepContract]:
    return {contract.id: contract for contract in load_step_contracts()}


@lru_cache(maxsize=1)
def forbidden_artifacts() -> set[str]:
    raw = _load_raw_contracts()
    return {str(name) for name in raw.get("forbidden_artifacts", [])}


def artifact_contract_status(workspace: str | Path, step: int | str) -> dict[str, Any]:
    """Validate required artifacts and forbidden artifacts for a step."""
    ws = Path(workspace)
    contract = get_step_contract(step)
    missing_required = [
        artifact
        for artifact in contract.required_artifacts
        if not (ws / artifact).exists()
    ]
    forbidden_present = [
        artifact
        for artifact in sorted(forbidden_artifacts())
        if (ws / artifact).exists()
    ]
    passed = not missing_required and not forbidden_present
    return {
        "passed": passed,
        "step": contract.id,
        "required_artifacts": list(contract.required_artifacts),
        "missing_required": missing_required,
        "forbidden_present": forbidden_present,
        "summary": (
            "artifact contract satisfied"
            if passed
            else "artifact contract failed"
        ),
    }


def get_step_contract(step: int | str) -> StepContract:
    step_id = normalize_step_id(step)
    return _contract_map()[step_id]


def normalize_step_id(step: int | str) -> str:
    """Normalize workflow step labels."""
    raw = str(step).strip().lower()
    if raw not in _contract_map():
        valid = ", ".join(STEP_ORDER)
        raise ValueError(f"Invalid step: {step}. Expected one of: {valid}.")
    return raw


STEP_CONTRACTS = load_step_contracts()
STEP_ORDER = [contract.id for contract in STEP_CONTRACTS]
STEP_FILES = {contract.id: contract.primary_artifact for contract in STEP_CONTRACTS}
STEP_DEPENDENCIES = {contract.id: list(contract.dependencies) for contract in STEP_CONTRACTS}

_RAW = _load_raw_contracts()
CORE_STEP_IDS = [str(step) for step in _RAW.get("core_steps", [])]


def report_step_config() -> list[dict[str, Any]]:
    """Return report section metadata derived from canonical step contracts."""
    return [
        {
            "key": f"step{contract.id}",
            "file": contract.primary_artifact,
            "icon": contract.report_icon,
            "title": contract.report_title,
            "optional": contract.optional,
        }
        for contract in STEP_CONTRACTS
    ]
