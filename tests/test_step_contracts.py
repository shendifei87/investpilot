import json
from pathlib import Path

import pytest

from src.contracts import (
    CORE_STEP_IDS,
    STEP_CONTRACTS,
    STEP_DEPENDENCIES,
    STEP_FILES,
    STEP_ORDER,
    artifact_contract_status,
    forbidden_artifacts,
    get_step_contract,
    report_step_config,
    validate_contract_registry,
)
from src.contracts.step_contracts import CONTRACT_PATH


def test_contract_order_and_core_steps():
    assert STEP_ORDER == ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
    assert CORE_STEP_IDS == ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
    assert [contract.id for contract in STEP_CONTRACTS] == STEP_ORDER


def test_contract_files_and_dependencies():
    assert STEP_FILES["4"] == "step4_assumption_research.md"
    assert STEP_FILES["5"] == "step5_financial_model.md"
    assert STEP_FILES["6"] == "step6_monte_carlo_simulation.md"
    assert STEP_DEPENDENCIES["6"] == ["1", "2", "3", "4", "5"]
    assert get_step_contract("4").required_artifacts == (
        "step4_assumption_research.md",
        "step4_structured_assumptions.json",
        "_reviewed_assumptions.json",
    )


def test_report_config_derived_from_contracts():
    cfg = report_step_config()
    assert cfg[0]["key"] == "step0"
    assert cfg[0]["file"] == "step0_quick_triage.md"
    assert cfg[4]["key"] == "step4"
    assert cfg[4]["file"] == "step4_assumption_research.md"


def test_artifact_contract_status(tmp_path: Path):
    (tmp_path / "step4_assumption_research.md").write_text("# Step 4\n", encoding="utf-8")
    result = artifact_contract_status(tmp_path, "4")
    assert result["passed"] is False
    assert "step4_structured_assumptions.json" in result["missing_required"]

    (tmp_path / "step4_structured_assumptions.json").write_text("{}", encoding="utf-8")
    (tmp_path / "_reviewed_assumptions.json").write_text("{}", encoding="utf-8")
    result = artifact_contract_status(tmp_path, "4")
    assert result["passed"] is True
    assert result["invalid_required"] == []

    (tmp_path / "step4_quantitative_model.md").write_text("# Deprecated\n", encoding="utf-8")
    result = artifact_contract_status(tmp_path, "4")
    assert result["passed"] is False
    assert "step4_quantitative_model.md" in result["forbidden_present"]


def test_artifact_contract_rejects_empty_files(tmp_path: Path):
    (tmp_path / "step1_business_analysis.md").write_text("", encoding="utf-8")

    result = artifact_contract_status(tmp_path, "1")

    assert result["passed"] is False
    assert result["invalid_required"] == [
        {"artifact": "step1_business_analysis.md", "reason": "empty file"}
    ]


def test_artifact_contract_rejects_invalid_json(tmp_path: Path):
    (tmp_path / "step4_assumption_research.md").write_text("# Step 4\n", encoding="utf-8")
    (tmp_path / "step4_structured_assumptions.json").write_text("{bad json", encoding="utf-8")
    (tmp_path / "_reviewed_assumptions.json").write_text("{}", encoding="utf-8")

    result = artifact_contract_status(tmp_path, "4")

    assert result["passed"] is False
    assert result["invalid_required"][0]["artifact"] == "step4_structured_assumptions.json"
    assert "invalid JSON" in result["invalid_required"][0]["reason"]


def test_forbidden_artifacts_are_centralized():
    forbidden = forbidden_artifacts()
    assert "step4_quantitative_model.md" in forbidden
    assert "step5_rrr_strategy.md" in forbidden


def _raw_contracts() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_registry_rejects_forward_dependencies():
    raw = _raw_contracts()
    raw["steps"][1]["dependencies"] = ["2"]

    with pytest.raises(ValueError, match="earlier step"):
        validate_contract_registry(raw)


def test_contract_registry_rejects_primary_artifact_not_required():
    raw = _raw_contracts()
    raw["steps"][1]["primary_artifact"] = "step1_alt.md"

    with pytest.raises(ValueError, match="primary_artifact"):
        validate_contract_registry(raw)


def test_contract_registry_rejects_forbidden_contract_artifact():
    raw = _raw_contracts()
    raw["forbidden_artifacts"].append("step1_business_analysis.md")

    with pytest.raises(ValueError, match="Forbidden artifacts"):
        validate_contract_registry(raw)
