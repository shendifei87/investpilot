"""Canonical step contracts for the research pipeline.

This module is intentionally small and deterministic: it reads
``config/step_contracts.json`` and exposes the step order, artifact names, and
dependency graph used by workflow, report generation, and validators.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from json import JSONDecodeError
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = PROJECT_ROOT / "config" / "step_contracts.json"


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


def _validate_relative_path(value: str, field: str, step_id: str | None = None) -> None:
    path = Path(value)
    prefix = f"Step {step_id} " if step_id is not None else ""
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{prefix}{field} must be a safe relative path: {value!r}")


def _ensure_unique(values: list[str], label: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise ValueError(f"Duplicate {label}: {duplicates}")


def validate_contract_registry(raw: dict[str, Any]) -> tuple[StepContract, ...]:
    """Validate and return the canonical step contracts.

    The contract file is part of the execution kernel.  Invalid dependency
    graphs, unsafe paths, duplicate artifacts, or stale forbidden artifacts
    should fail at import time instead of surfacing later as workflow drift.
    """
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise ValueError("step_contracts.json must contain a non-empty steps list")

    try:
        contracts = tuple(StepContract.from_dict(item) for item in steps_raw)
    except KeyError as exc:
        raise ValueError(f"Missing required step contract field: {exc}") from exc

    ids = [contract.id for contract in contracts]
    _ensure_unique(ids, "step IDs")

    id_to_index = {step_id: idx for idx, step_id in enumerate(ids)}
    primary_artifacts = [contract.primary_artifact for contract in contracts]
    _ensure_unique(primary_artifacts, "primary artifacts")

    all_declared_artifacts: set[str] = set()
    for contract in contracts:
        if not contract.name.strip():
            raise ValueError(f"Step {contract.id} name must be non-empty")
        if not contract.report_title.strip():
            raise ValueError(f"Step {contract.id} report_title must be non-empty")
        if not contract.primary_artifact:
            raise ValueError(f"Step {contract.id} primary_artifact must be non-empty")

        _validate_relative_path(contract.prompt_file, "prompt_file", contract.id)
        prompt_path = PROJECT_ROOT / contract.prompt_file
        if not prompt_path.is_file():
            raise ValueError(f"Step {contract.id} prompt_file not found: {contract.prompt_file}")

        for field, artifacts in (
            ("primary_artifact", (contract.primary_artifact,)),
            ("required_artifacts", contract.required_artifacts),
            ("optional_artifacts", contract.optional_artifacts),
        ):
            for artifact in artifacts:
                _validate_relative_path(artifact, field, contract.id)

        if contract.primary_artifact not in contract.required_artifacts:
            raise ValueError(
                f"Step {contract.id} primary_artifact must be listed in required_artifacts"
            )

        required_set = set(contract.required_artifacts)
        optional_set = set(contract.optional_artifacts)
        if len(required_set) != len(contract.required_artifacts):
            raise ValueError(f"Step {contract.id} has duplicate required_artifacts")
        if len(optional_set) != len(contract.optional_artifacts):
            raise ValueError(f"Step {contract.id} has duplicate optional_artifacts")
        overlap = sorted(required_set & optional_set)
        if overlap:
            raise ValueError(f"Step {contract.id} artifacts cannot be both required and optional: {overlap}")

        for dep in contract.dependencies:
            if dep not in id_to_index:
                raise ValueError(f"Step {contract.id} has unknown dependency: {dep}")
            if dep == contract.id:
                raise ValueError(f"Step {contract.id} cannot depend on itself")
            if id_to_index[dep] >= id_to_index[contract.id]:
                raise ValueError(f"Step {contract.id} dependency must point to an earlier step: {dep}")

        if any(not gate.strip() for gate in contract.validation_gates):
            raise ValueError(f"Step {contract.id} validation_gates cannot contain blanks")

        all_declared_artifacts.update(required_set)
        all_declared_artifacts.update(optional_set)

    core_steps = [str(step) for step in raw.get("core_steps", [])]
    _ensure_unique(core_steps, "core_steps")
    for step_id in core_steps:
        if step_id not in id_to_index:
            raise ValueError(f"Unknown core step: {step_id}")
        contract = contracts[id_to_index[step_id]]
        if contract.optional:
            raise ValueError(f"Core step cannot be optional: {step_id}")

    forbidden = {str(name) for name in raw.get("forbidden_artifacts", [])}
    for artifact in forbidden:
        _validate_relative_path(artifact, "forbidden_artifacts")
    overlap = sorted(forbidden & all_declared_artifacts)
    if overlap:
        raise ValueError(f"Forbidden artifacts cannot also be contract artifacts: {overlap}")

    return contracts


@lru_cache(maxsize=1)
def load_step_contracts() -> tuple[StepContract, ...]:
    """Load all step contracts in configured order."""
    raw = _load_raw_contracts()
    return validate_contract_registry(raw)


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
    missing_required = []
    invalid_required = []
    for artifact in contract.required_artifacts:
        path = ws / artifact
        if not path.exists():
            missing_required.append(artifact)
            continue
        if not path.is_file():
            invalid_required.append({"artifact": artifact, "reason": "not a file"})
            continue
        try:
            if path.stat().st_size == 0:
                invalid_required.append({"artifact": artifact, "reason": "empty file"})
                continue
        except OSError as exc:
            invalid_required.append({"artifact": artifact, "reason": str(exc)})
            continue
        if path.suffix.lower() == ".json":
            try:
                parsed = json.loads(path.read_text(encoding="utf-8"))
            except (JSONDecodeError, OSError) as exc:
                invalid_required.append({"artifact": artifact, "reason": f"invalid JSON: {exc}"})
                continue
            if not isinstance(parsed, dict):
                invalid_required.append({"artifact": artifact, "reason": "JSON root must be an object"})

    forbidden_present = [
        artifact
        for artifact in sorted(forbidden_artifacts())
        if (ws / artifact).exists()
    ]
    passed = not missing_required and not invalid_required and not forbidden_present
    return {
        "passed": passed,
        "step": contract.id,
        "required_artifacts": list(contract.required_artifacts),
        "missing_required": missing_required,
        "invalid_required": invalid_required,
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
