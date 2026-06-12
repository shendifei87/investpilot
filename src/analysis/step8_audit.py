"""Step 8 automated pipeline audit — cross-step consistency checks.

Usage:
    from src.analysis.step8_audit import audit_step_chain
    result = audit_step_chain("workspaces/601658")

Returns dict with ``passed``, ``checks`` (list), and ``summary``.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.contracts import CORE_STEP_IDS, artifact_contract_status, get_step_contract

# ──────────────────────────────────────────────
#  Individual audit checks
# ──────────────────────────────────────────────


def _core_steps_through(through_step: int | str) -> list[str]:
    step_id = str(through_step)
    if step_id not in CORE_STEP_IDS:
        return list(CORE_STEP_IDS)
    return list(CORE_STEP_IDS[: CORE_STEP_IDS.index(step_id) + 1])


def _check_artifact_chain(workspace: Path, through_step: int | str = 9) -> list[dict]:
    """Verify every core step satisfies the canonical artifact contract."""
    checks = []
    for step_id in _core_steps_through(through_step):
        contract = get_step_contract(step_id)
        status = artifact_contract_status(workspace, step_id)
        issues = []
        if status["missing_required"]:
            issues.append(f"missing={status['missing_required']}")
        if status["invalid_required"]:
            issues.append(f"invalid={status['invalid_required']}")
        if status["forbidden_present"]:
            issues.append(f"forbidden={status['forbidden_present']}")
        checks.append(
            {
                "check": f"artifact_contract:step{step_id}",
                "status": "PASS" if status["passed"] else "FAIL",
                "detail": (
                    f"{contract.primary_artifact} artifact contract satisfied"
                    if status["passed"]
                    else "; ".join(issues)
                ),
                "artifact_contract": status,
            }
        )
    return checks


def _check_contrarian_coverage(workspace: Path) -> list[dict]:
    """Verify contrarian checks are present in all step outputs.

    Delegates to ``validate_contrarian_checks`` from step4_validate.
    """
    # Late import to avoid circular dependency at module level
    from src.analysis.step4_validate import validate_contrarian_checks

    result = validate_contrarian_checks(workspace, through_step=8)
    checks = []
    for step_id, info in result.get("steps", {}).items():
        checks.append(
            {
                "check": f"contrarian_check:step{step_id}",
                "status": info.get("status", "UNKNOWN"),
                "detail": info.get("detail", ""),
            }
        )
    return checks


def _check_mc_p50_alignment(workspace: Path) -> list[dict]:
    """Verify MC P50 aligns with forecast model (unit-convention guard)."""
    mc_path = workspace / "monte_carlo_results.json"
    fm_path = workspace / "forecast_model.json"

    if not mc_path.exists() or not fm_path.exists():
        return [
            {
                "check": "mc_p50_alignment",
                "status": "SKIP",
                "detail": "monte_carlo_results.json or forecast_model.json not found",
            }
        ]

    try:
        mc_data = json.loads(mc_path.read_text(encoding="utf-8"))
        fm_data = json.loads(fm_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [
            {
                "check": "mc_p50_alignment",
                "status": "FAIL",
                "detail": f"JSON parse error: {exc}",
            }
        ]

    # If the MC results already include a cross_check section, use it directly
    cross_check = mc_data.get("forecast_cross_check", {})
    if cross_check:
        eps_gap = abs(float(cross_check.get("eps_gap_pct", 999)))
        checks = [
            {
                "check": "mc_p50_alignment:eps",
                "status": "PASS" if eps_gap < 5.0 else "FAIL",
                "detail": (f"MC EPS P50 vs Forecast EPS gap: {eps_gap:.1f}% (threshold: 5%)"),
            }
        ]
    else:
        # Fall back to the full comparison function
        from src.analysis.monte_carlo import validate_mc_p50_alignment

        result = validate_mc_p50_alignment(mc_data, fm_data)
        checks = []
        for item in result.get("checks", []):
            metric = item.get("metric", "?")
            pct_diff = item.get("pct_diff", 0)
            passed = item.get("passed", False)
            checks.append(
                {
                    "check": f"mc_p50_alignment:{metric}",
                    "status": "PASS" if passed else "FAIL",
                    "detail": (
                        f"MC P50 {metric}={item.get('mc_p50', '?')} vs "
                        f"Forecast={item.get('forecast_p50', '?')} "
                        f"(diff {pct_diff:+.1f}%)"
                    ),
                }
            )
        if not checks:
            checks.append(
                {
                    "check": "mc_p50_alignment",
                    "status": "SKIP",
                    "detail": "No comparable metrics found between MC and forecast model",
                }
            )

    return checks


def _check_valuation_cross_check(workspace: Path) -> list[dict]:
    """Cross-check PB/PE from calculated_valuation.json vs MC results."""
    calc_path = workspace / "calculated_valuation.json"
    mc_path = workspace / "monte_carlo_results.json"

    if not calc_path.exists():
        return [
            {
                "check": "valuation_cross_check",
                "status": "SKIP",
                "detail": "calculated_valuation.json not found",
            }
        ]
    if not mc_path.exists():
        return [
            {
                "check": "valuation_cross_check",
                "status": "SKIP",
                "detail": "monte_carlo_results.json not found",
            }
        ]

    try:
        calc = json.loads(calc_path.read_text(encoding="utf-8"))
        mc = json.loads(mc_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return [
            {
                "check": "valuation_cross_check",
                "status": "FAIL",
                "detail": f"JSON parse error: {exc}",
            }
        ]

    checks = []

    # PB cross-check: calculated_valuation PB vs MC PB P50
    calc_pb = _extract_val(calc, "pb")
    mc_pb_pctls = mc.get("filtered_target_price_percentiles") or mc.get(
        "target_price_percentiles", {}
    )
    mc_eps_p50 = _get_nested(mc, "eps_percentiles", "50") or _get_nested(mc, "eps_percentiles", 50)
    mc_bps_p50 = _get_nested(mc, "bps_percentiles", "50") or _get_nested(mc, "bps_percentiles", 50)

    if mc_bps_p50 and mc_eps_p50 and calc_pb:
        mc_tp_p50 = _get_p50(mc_pb_pctls)
        if mc_tp_p50:
            implied_pb = mc_tp_p50 / mc_bps_p50
            pb_diff_pct = abs(implied_pb / calc_pb - 1) * 100
            checks.append(
                {
                    "check": "valuation_cross_check:pb",
                    "status": "PASS" if pb_diff_pct < 25 else "WARN",
                    "detail": (
                        f"Calculated PB={calc_pb:.3f} vs MC implied PB={implied_pb:.3f} "
                        f"(diff {pb_diff_pct:.1f}%, note: calculated is TTM, MC is Forward T+1)"
                    ),
                }
            )

    # RRR sanity check
    rrr_data = mc.get("rrr_filtered") or mc.get("rrr", {})
    rrr_val = rrr_data.get("rrr")
    if rrr_val:
        kelly_half = rrr_data.get("kelly_half", 0)
        checks.append(
            {
                "check": "valuation_cross_check:rrr",
                "status": "PASS",
                "detail": (
                    f"RRR={rrr_val:.1f}x, Kelly Half={kelly_half:.1%}. "
                    f"{'建仓信号 (RRR>2)' if rrr_val > 2 else '等待 (RRR<2)'}"
                ),
            }
        )

    if not checks:
        checks.append(
            {
                "check": "valuation_cross_check",
                "status": "SKIP",
                "detail": "Insufficient data for cross-check",
            }
        )

    return checks


def _check_kill_switch_stats(workspace: Path) -> list[dict]:
    """Verify kill switch trigger rate is within normal range."""
    mc_path = workspace / "monte_carlo_results.json"
    if not mc_path.exists():
        return [
            {
                "check": "kill_switch_stats",
                "status": "SKIP",
                "detail": "monte_carlo_results.json not found",
            }
        ]

    try:
        mc = json.loads(mc_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [
            {
                "check": "kill_switch_stats",
                "status": "FAIL",
                "detail": "monte_carlo_results.json parse error",
            }
        ]

    ks = mc.get("kill_switch", {})
    kill_rate = float(ks.get("kill_rate_pct", 0))
    paths_killed = int(ks.get("paths_killed", 0))

    # Normal: <20%, High: 20-35%, Excessive: >35%
    if kill_rate == 0:
        status = "WARN"
        detail = "No paths killed — verify kill switch criteria are active"
    elif kill_rate < 20:
        status = "PASS"
        detail = f"Kill switch rate {kill_rate:.1f}% ({paths_killed} paths) — normal"
    elif kill_rate < 35:
        status = "WARN"
        detail = f"Kill switch rate {kill_rate:.1f}% ({paths_killed} paths) — elevated"
    else:
        status = "FAIL"
        detail = f"Kill switch rate {kill_rate:.1f}% ({paths_killed} paths) — excessive, review assumptions"

    return [
        {
            "check": "kill_switch_stats",
            "status": status,
            "detail": detail,
        }
    ]


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────


def _extract_val(data: dict, key: str) -> float | None:
    """Extract a numeric value from calculated_valuation dict.

    Handles both flat ``{pb: 0.59}`` and nested ``{pb: {value: 0.59}}`` formats.
    """
    raw = data.get(key)
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, dict):
        v = raw.get("value") or raw.get("trailing") or raw.get("forward")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _get_nested(data: dict, *keys) -> float | None:
    """Safely drill into nested dict, casting result to float."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


def _get_p50(pctls: dict) -> float | None:
    """Extract P50 from a percentile dict (keys may be int or str)."""
    for key in (50, "50"):
        val = pctls.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


# ──────────────────────────────────────────────
#  Main entry point
# ──────────────────────────────────────────────


def audit_step_chain(workspace_dir: str | Path, through_step: int | str = 8) -> dict:
    """Run the full Step 8 automated pipeline audit.

    Checks:
      1. Artifact chain completeness (step artifacts through ``through_step`` exist)
      2. Contrarian check coverage (all steps have contrarian sections)
      3. MC P50 alignment with forecast model (unit-convention guard)
      4. Valuation cross-check (calculated_valuation.json vs MC results)
      5. Kill switch trigger rate (within normal range)

    Returns dict with:
      - passed (bool): True if all checks pass
      - checks (list[dict]): Per-check results
      - summary (str): Human-readable summary
    """
    workspace = Path(workspace_dir)

    all_checks: list[dict] = []

    # 1. Artifact chain
    all_checks.extend(_check_artifact_chain(workspace, through_step=through_step))

    # 2. Contrarian coverage
    all_checks.extend(_check_contrarian_coverage(workspace))

    # 3. MC P50 alignment
    all_checks.extend(_check_mc_p50_alignment(workspace))

    # 4. Valuation cross-check
    all_checks.extend(_check_valuation_cross_check(workspace))

    # 5. Kill switch stats
    all_checks.extend(_check_kill_switch_stats(workspace))

    failures = [c for c in all_checks if c["status"] == "FAIL"]
    warnings = [c for c in all_checks if c["status"] == "WARN"]
    passed = len(failures) == 0

    return {
        "passed": passed,
        "checks": all_checks,
        "n_passed": sum(1 for c in all_checks if c["status"] == "PASS"),
        "n_failed": len(failures),
        "n_warnings": len(warnings),
        "n_skipped": sum(1 for c in all_checks if c["status"] == "SKIP"),
        "summary": (
            f"ALL {len(all_checks)} CHECKS PASSED"
            if passed and not warnings
            else (
                f"PASSED with {len(warnings)} warning(s)"
                if passed
                else f"{len(failures)} FAILURE(S), {len(warnings)} warning(s)"
            )
        ),
    }
