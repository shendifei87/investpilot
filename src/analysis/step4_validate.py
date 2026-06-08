"""Step 4 output validator — enforces bottom-up rigor before Monte Carlo.

Usage:
    from src.analysis.step4_validate import validate_step4
    result = validate_step4("workspaces/600584.SH/step4_assumption_research.md")

If result["passed"] is False, the LLM MUST fix issues before running Monte Carlo.

Validation is structured-artifact only.  Markdown keyword scraping is not a
valid Step 4 path.

Checks (15 total):
  1. Required sections (driver decomposition, bridge, Q1 check, etc.)
  2. Bridge arithmetic consistency
  3. Segment revenue sum matches total
  4. Q1 constraint check result
  5. Margin derivation present
  6. Growth rates accompanied by driver decomposition
  7. Historical PE/PB anchoring present
  8. Peer comparison table (>=3 companies)
  9. Reverse DCF results present
 10. DCF cross-validation present
 11. Per-variable contrarian check table present
 12. Assumption consistency self-check present
 13. Valuation ratios calculated (not from news/old data)
 14. Apple-to-apple valuation comparison (no trailing vs forward mixing, no T+1 vs T+2 mixing)
 15. Workspace has calculated_valuation.json artifact
"""

from __future__ import annotations

import json
from pathlib import Path

from src.analysis._utils import coerce_float as _to_float, is_pct_variable as _is_pct_variable_name
from src.analysis.evidence_registry import (
    known_evidence_ids,
    validate_step4_evidence_contract,
)
from src.analysis.financial_model import (
    REQUIRED_MODEL_INPUTS,
    REQUIRED_REVIEWED_VARIABLES,
    REVIEWED_VARIABLE_ALIASES,
)
from src.analysis.step4_schema import STEP4_STRUCTURED_FILENAME
from src.contracts import CORE_STEP_IDS, get_step_contract


def _normalize_segments(structured: dict) -> list[dict]:
    """Normalize segment_revenues from either format to a flat list of dicts.

    Supports:
      - List format: [{name, base_revenue, p50_growth, ...}, ...]
      - Nested dict: {product_level: {SegName: {base, p50, p50_growth}, ...}, ...}
    """
    raw = structured.get("segment_revenues", []) or []
    if isinstance(raw, list):
        return [s for s in raw if isinstance(s, dict)]
    if isinstance(raw, dict):
        level_data = raw.get("product_level") or raw.get("geographic_level") or {}
        if not isinstance(level_data, dict):
            return []
        result = []
        for seg_name, seg_data in level_data.items():
            if not isinstance(seg_data, dict):
                continue
            result.append({
                "name": seg_name,
                "base_revenue": seg_data.get("base", seg_data.get("base_revenue", 0)),
                "p50_revenue": seg_data.get("p50", seg_data.get("p50_revenue", 0)),
                "p50_growth": seg_data.get("p50_growth", 0),
            })
        return result
    return []


# ──────────────────────────────────────────────
#  Structured JSON helpers
# ──────────────────────────────────────────────

def _load_structured_json(filepath: Path) -> dict | None:
    """Load step4_structured_assumptions.json if it exists alongside the markdown."""
    json_path = filepath.parent / STEP4_STRUCTURED_FILENAME
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None


# _to_float is imported from src.analysis._utils


def _workspace_evidence_ids(workspace: Path) -> set[str]:
    """Collect structured evidence IDs known to this workspace."""
    try:
        return known_evidence_ids(workspace)
    except Exception:
        return {"calculated_valuation.json", "valuation_raw_inputs.json", "price_history.csv"}


def _evidence_ref_ok(ref: str, known_ids: set[str]) -> bool:
    """Validate evidence references without blocking local raw-data aliases.

    Evidence IDs are accepted if they match any of:
      - Exact match in the workspace evidence registry
      - DATA:/CALC:/WEB:/FILING:/MODEL: prefixed references
      - E### / EG### / CS### / DOC### pattern (agent-assigned evidence IDs)
      - Filename-based references (e.g. calculated_valuation.json)
    """
    ref = str(ref or "").strip()
    if not ref:
        return False
    if ref in known_ids:
        return True
    # Prefixed references from evidence pipeline
    if ref.startswith(("DATA:", "CALC:", "WEB:", "FILING:", "MODEL:")):
        return True
    # Agent-assigned evidence IDs (E001, EG9bbd7a, CS9ea5f5, DOC014eb7)
    import re
    if re.match(r'^(E\d+|EG[0-9a-f]+|CS[0-9a-f]+|DOC[0-9a-f]+)$', ref):
        return True
    # Common workspace artifacts used as evidence
    if ref in ("calculated_valuation.json", "price_history.csv", "valuation_raw_inputs.json",
               "Step 1 Analysis", "Step 2 Comps", "Step 3 Marginal Changes"):
        return True
    return False


def _canonical_variable_name(variable: str) -> str:
    raw = str(variable or "").strip()
    raw_lower = raw.lower()
    for canonical, aliases in REVIEWED_VARIABLE_ALIASES.items():
        if raw_lower == canonical.lower() or raw_lower in {a.lower() for a in aliases}:
            return canonical
    return raw


def _canonical_variable_set(variables) -> set[str]:
    return {_canonical_variable_name(v) for v in variables if str(v or "").strip()}


def _validate_percentile_order(row: dict, label: str, keys: tuple[str, ...]) -> dict:
    values = []
    missing = []
    for key in keys:
        val = _to_float(row.get(key))
        if val is None:
            missing.append(key)
        else:
            values.append((key, val))

    if missing:
        return {
            "check": f"percentile_order:{label}",
            "status": "FAIL",
            "detail": f"{label} missing percentile values: {missing}",
        }

    bad = [
        f"{values[i][0]}={values[i][1]} > {values[i + 1][0]}={values[i + 1][1]}"
        for i in range(len(values) - 1)
        if values[i][1] > values[i + 1][1]
    ]
    return {
        "check": f"percentile_order:{label}",
        "status": "FAIL" if bad else "PASS",
        "detail": "; ".join(bad) if bad else f"{label} percentiles are monotonic",
    }


def _validate_structured(structured: dict, filepath: Path) -> list[dict]:
    """Run checks 1-14 against structured JSON data.

    Returns list of check result dicts.
    """
    checks = []

    # ── Check 1: Required sections ──
    required_keys = [
        "segment_revenues", "bridge_analysis", "q1_constraint",
        "margin_derivation", "growth_drivers", "assumption_matrix",
        "financial_model_inputs",
    ]
    for key in required_keys:
        present = key in structured and structured[key] is not None
        if key == "growth_drivers":
            present = present and len(structured.get("growth_drivers", [])) > 0
        if key == "assumption_matrix":
            am = structured.get("assumption_matrix", [])
            if isinstance(am, dict):
                present = present and len(am) > 0
            else:
                present = present and len(am) > 0
        checks.append({
            "check": f"required_section:{key}",
            "status": "PASS" if present else "MISSING",
            "detail": f"Structured key '{key}' {'present' if present else 'absent'}",
        })

    # ── Check 2: Bridge arithmetic ──
    bridge = structured.get("bridge_analysis", {})
    # Bridge arithmetic: support both legacy (base_total/delta/p50_total) and
    # current T+1/T+2/T+3 format with per-period EPS bridges.
    bridge_ok = False
    if bridge:
        # Legacy format
        if "base_total" in bridge and "p50_total" in bridge and "delta" in bridge:
            base = _to_float(bridge.get("base_total"))
            delta = _to_float(bridge.get("delta"))
            stated = _to_float(bridge.get("p50_total"))
            if base is not None and delta is not None and stated is not None:
                expected = base + delta
                diff_pct = abs(stated - expected) / abs(expected) if abs(expected) > 0.01 else 0.0
                checks.append({
                    "check": "bridge_arithmetic",
                    "status": "PASS" if diff_pct < 0.05 else "FAIL",
                    "detail": f"Bridge: {base} + {delta} = {expected} vs stated {stated} (diff {diff_pct:.1%})",
                })
                bridge_ok = True

        # T+1/T+2/T+3 format: check that each period has EPS derivation
        if not bridge_ok:
            period_keys = [k for k in bridge if k.startswith("t") and isinstance(bridge[k], dict)]
            if period_keys:
                issues = []
                for pk in sorted(period_keys):
                    period = bridge[pk]
                    rev_g = _to_float(period.get("revenue_growth"))
                    gm = _to_float(period.get("gross_margin"))
                    opex = _to_float(period.get("opex_ratio"))
                    tax = _to_float(period.get("tax_rate"))
                    eps = _to_float(period.get("eps"))
                    # Approximate EPS check: rev × gm × (1-opex) × (1-tax) / shares ≈ eps
                    # We can't do the full calculation without base revenue & shares,
                    # so just verify EPS is present and the chain is complete.
                    missing_fields = []
                    if rev_g is None: missing_fields.append("revenue_growth")
                    if gm is None: missing_fields.append("gross_margin")
                    if opex is None: missing_fields.append("opex_ratio")
                    if tax is None: missing_fields.append("tax_rate")
                    if eps is None: missing_fields.append("eps")
                    if missing_fields:
                        issues.append(f"{pk}: missing {missing_fields}")
                if issues:
                    checks.append({
                        "check": "bridge_arithmetic",
                        "status": "FAIL",
                        "detail": f"Bridge period issues: {'; '.join(issues)}",
                    })
                else:
                    checks.append({
                        "check": "bridge_arithmetic",
                        "status": "PASS",
                        "detail": f"Bridge covers {len(period_keys)} periods with EPS derivation chain",
                    })
                bridge_ok = True

    if not bridge_ok:
        checks.append({
            "check": "bridge_arithmetic",
            "status": "FAIL",
            "detail": "bridge_analysis uses unrecognized format — add base_total/delta/p50_total or t1_2026E/t2_2027E/t3_2028E periods with revenue_growth, gross_margin, opex_ratio, tax_rate, eps fields",
        })

    # ── Check 3: Segment sum vs total ──
    segments = _normalize_segments(structured)
    if segments and len(segments) >= 2:
        component_segments = [
            s for s in segments
            if str(s.get("name", "")).strip().lower() != "total"
        ]
        numeric_revenues = [_to_float(s.get("p50_revenue")) for s in component_segments]
        if any(v is None for v in numeric_revenues):
            checks.append({
                "check": "segment_sum",
                "status": "FAIL",
                "detail": "segment_revenues p50_revenue values must be numeric",
            })
        else:
            seg_total = sum(numeric_revenues)
            stated_total = _to_float(bridge.get("p50_total")) if bridge else None
            if stated_total and stated_total > 0:
                diff = abs(seg_total - stated_total) / stated_total
                checks.append({
                    "check": "segment_sum",
                    "status": "PASS" if diff < 0.05 else "FAIL",
                    "detail": f"Segment sum {seg_total:.1f} vs stated total {stated_total:.1f} ({diff:.1%})",
                })
            else:
                checks.append({
                    "check": "segment_sum",
                    "status": "PASS",
                    "detail": f"Found {len(component_segments)} component segment revenue entries",
                })
    else:
        checks.append({
            "check": "segment_sum",
            "status": "SKIP",
            "detail": "segment_revenues incomplete in structured JSON",
        })

    # ── Check 4: Q1 constraint ──
    q1 = structured.get("q1_constraint", {})
    if q1 and "feasibility" in q1:
        feas = str(q1["feasibility"])
        checks.append({
            "check": "q1_constraint",
            "status": "FAIL" if "UNREASONABLE" in feas else "PASS",
            "detail": f"Q1 feasibility: {feas}",
        })
    else:
        checks.append({
            "check": "q1_constraint",
            "status": "FAIL",
            "detail": "q1_constraint absent from structured JSON",
        })

    # ── Check 5: Margin derivation ──
    margin = structured.get("margin_derivation", {})
    if margin and margin.get("method") and margin.get("cost_items"):
        checks.append({
            "check": "margin_derivation",
            "status": "PASS",
            "detail": f"Margin derived via {margin['method']} with {len(margin['cost_items'])} cost items",
        })
    else:
        checks.append({
            "check": "margin_derivation",
            "status": "FAIL",
            "detail": "margin_derivation incomplete — must include method and cost_items",
        })

    # ── Check 6: Growth drivers ──
    drivers = structured.get("growth_drivers", [])
    checks.append({
        "check": "growth_has_drivers",
        "status": "PASS" if drivers else "FAIL",
        "detail": f"Found {len(drivers)} segment growth driver decompositions",
    })

    checks.extend(_validate_growth_driver_integrity(structured, filepath.parent))
    checks.extend(_validate_assumption_matrix(structured, filepath.parent))

    model_inputs = structured.get("financial_model_inputs", {}) or {}
    missing_model_inputs = [
        field for field in REQUIRED_MODEL_INPUTS
        if model_inputs.get(field) in (None, "")
    ]
    invalid_model_inputs = []
    for field in ("shares_outstanding", "diluted_shares"):
        val = _to_float(model_inputs.get(field))
        if val is not None and val <= 0:
            invalid_model_inputs.append(f"{field} must be positive")
    checks.append({
        "check": "financial_model_inputs_required_fields",
        "status": "FAIL" if missing_model_inputs or invalid_model_inputs else "PASS",
        "detail": (
            "; ".join(
                [
                    f"missing required model inputs: {missing_model_inputs}"
                    if missing_model_inputs else "",
                    "; ".join(invalid_model_inputs),
                ]
            ).strip("; ")
            if missing_model_inputs or invalid_model_inputs
            else "Step 5 financial_model_inputs required fields are present"
        ),
    })

    # ── Check 7: Historical valuation anchor ──
    hist_val = structured.get("historical_valuation", {})
    if hist_val and "pe_min" in hist_val and "pe_median" in hist_val:
        checks.append({
            "check": "historical_valuation_anchor",
            "status": "PASS",
            "detail": (
                f"Historical PE: min={hist_val['pe_min']}, "
                f"median={hist_val['pe_median']}, max={hist_val.get('pe_max', 'N/A')}"
            ),
        })
    else:
        checks.append({
            "check": "historical_valuation_anchor",
            "status": "FAIL",
            "detail": "historical_valuation absent — must include pe_min, pe_median, pe_max",
        })

    # ── Check 8: Peer comparison ──
    peer = structured.get("peer_comparison", {})
    n_peers = peer.get("n_peers", len(peer.get("peers", [])))
    if n_peers >= 3:
        checks.append({
            "check": "peer_comparison",
            "status": "PASS",
            "detail": (
                f"Peer comparison with {n_peers} companies, "
                f"metric={peer.get('metric', '?')}, basis={peer.get('basis', '?')}"
            ),
        })
    else:
        checks.append({
            "check": "peer_comparison",
            "status": "FAIL",
            "detail": f"Need >=3 peers, got {n_peers}",
        })

    # ── Check 9: Reverse DCF ──
    rdcf = structured.get("reverse_dcf", {})
    if rdcf and "implied_growth" in rdcf:
        checks.append({
            "check": "reverse_dcf",
            "status": "PASS",
            "detail": f"Reverse DCF implied growth: {rdcf['implied_growth']}",
        })
    else:
        checks.append({
            "check": "reverse_dcf",
            "status": "FAIL",
            "detail": "reverse_dcf absent from structured JSON",
        })

    # ── Check 10: DCF cross-validation ──
    dcf = structured.get("dcf_cross_validation", {})
    if dcf and "deviation_pct" in dcf:
        dev = _to_float(dcf.get("deviation_pct"))
        checks.append({
            "check": "dcf_cross_validation",
            "status": "PASS" if dev is not None and abs(dev) < 0.30 else "FAIL",
            "detail": (
                f"DCF vs MC deviation: {dev:.1%}"
                if dev is not None
                else "dcf_cross_validation.deviation_pct must be numeric"
            ),
        })
    else:
        checks.append({
            "check": "dcf_cross_validation",
            "status": "FAIL",
            "detail": "dcf_cross_validation absent from structured JSON",
        })

    # ── Check 11: Contrarian checks per variable ──
    contrarian = structured.get("contrarian_checks", [])
    checks.append({
        "check": "contrarian_per_variable",
        "status": "PASS" if len(contrarian) >= 3 else "FAIL",
        "detail": f"Found {len(contrarian)} per-variable contrarian checks",
    })

    # ── Check 12: Assumption consistency ──
    consistency = structured.get("assumption_consistency", {})
    if consistency:
        violations = []
        if consistency.get("post_review_changes"):
            violations.append("Assumptions modified after user review")
        if not consistency.get("pe_moat_aligned", True):
            violations.append("PE not aligned with moat rating")
        if not consistency.get("revenue_segment_aligned", True):
            violations.append("Revenue not aligned with segment analysis")
        checks.append({
            "check": "assumption_consistency",
            "status": "PASS" if not violations else "FAIL",
            "detail": "; ".join(violations) if violations else "All consistency checks passed",
        })
    else:
        checks.append({
            "check": "assumption_consistency",
            "status": "FAIL",
            "detail": "assumption_consistency absent from structured JSON",
        })

    # ── Check 13: Valuation source ──
    val_src = structured.get("valuation_source", {})
    # val_src can be a dict with pe_calculated, or a descriptive string that
    # explicitly says the ratios were calculated from raw data.
    if isinstance(val_src, dict) and val_src.get("pe_calculated"):
        checks.append({
            "check": "valuation_ratios_calculated",
            "status": "PASS",
            "detail": "Structured JSON confirms PE was calculated from source data",
        })
    elif isinstance(val_src, str) and _valuation_source_string_is_calculated(val_src):
        checks.append({
            "check": "valuation_ratios_calculated",
            "status": "PASS",
            "detail": f"Valuation source: {val_src[:100]}",
        })
    else:
        checks.append({
            "check": "valuation_ratios_calculated",
            "status": "FAIL",
            "detail": "valuation_source.pe_calculated is not True",
        })

    # ── Check 14: Apple-to-apple ──
    peer = structured.get("peer_comparison", {})
    if peer and peer.get("peers") and len(peer["peers"]) >= 2:
        comparisons = [
            {
                "metric": peer.get("metric", "pe"),
                "basis": peer.get("basis", ""),
                "value": p.get("value", 0),
                "source": p.get("source", ""),
                "label": p.get("name", ""),
            }
            for p in peer["peers"]
        ]
        from src.analysis.financial import validate_valuation_apple_to_apple
        result = validate_valuation_apple_to_apple(comparisons)
        # Build a detailed error message including specific violations
        if result["passed"]:
            detail = result["summary"]
        else:
            violation_msgs = []
            for v in result.get("violations", []):
                vtype = v.get("type", "unknown")
                vdetail = v.get("detail", str(v))
                violation_msgs.append(f"[{vtype}] {vdetail}")
            detail = "; ".join(violation_msgs) if violation_msgs else result["summary"]
        checks.append({
            "check": "apple_to_apple_valuation",
            "status": "PASS" if result["passed"] else "FAIL",
            "detail": detail,
        })
    else:
        checks.append({
            "check": "apple_to_apple_valuation",
            "status": "SKIP",
            "detail": "peer_comparison has fewer than 2 entries",
        })

    return checks


def _validate_growth_driver_integrity(structured: dict, workspace: Path) -> list[dict]:
    """Validate that segment growth comes from driver decomposition."""
    checks = []
    segments = _normalize_segments(structured)
    driver_rows = structured.get("growth_drivers", []) or []
    known_ids = _workspace_evidence_ids(workspace)

    driver_by_segment = {
        str(row.get("segment", "")).strip().lower(): row
        for row in driver_rows
        if row.get("segment")
    }
    missing_segments = []
    depth_issues = []
    structure_issues = []
    evidence_issues = []
    arithmetic_issues = []

    for segment in segments:
        name = str(segment.get("name", "")).strip()
        if not name or name.lower() == "total":
            continue
        row = driver_by_segment.get(name.lower())
        if not row:
            missing_segments.append(name)
            continue

        ds = row.get("drivers", []) or []
        if len(ds) < 2 or len(ds) > 4:
            depth_issues.append(f"{name}: needs 2-4 drivers, got {len(ds)}")

        contributions = []
        for d in ds:
            driver_name = d.get("name", "?")
            if not d.get("name"):
                structure_issues.append(f"{name}: driver missing name")
            if not (d.get("derivation") or d.get("mechanism") or d.get("formula")):
                structure_issues.append(
                    f"{name}/{driver_name}: missing derivation/mechanism/formula"
                )
            refs = d.get("evidence_ids") or d.get("evidence_id") or []
            if isinstance(refs, str):
                refs = [refs]
            if not refs:
                evidence_issues.append(f"{name}/{driver_name}: missing evidence_ids")
            else:
                bad_refs = [r for r in refs if not _evidence_ref_ok(str(r), known_ids)]
                if bad_refs:
                    evidence_issues.append(
                        f"{name}/{driver_name}: unknown evidence refs {bad_refs}"
                    )

            contrib = _to_float(d.get("contribution_pct"))
            if contrib is None:
                arithmetic_issues.append(
                    f"{name}/{driver_name}: missing numeric contribution_pct"
                )
            else:
                contributions.append(contrib)

        stated_growth = _to_float(segment.get("p50_growth"))
        if stated_growth is not None and len(contributions) == len(ds) and contributions:
            summed = sum(contributions)
            if abs(summed - stated_growth) > 0.01:
                arithmetic_issues.append(
                    f"{name}: driver contribution sum {summed:.1%} vs segment p50_growth {stated_growth:.1%}"
                )

        pct_keys = tuple(k for k in ("p10_growth", "p30_growth", "p50_growth", "p70_growth", "p90_growth") if k in segment)
        if len(pct_keys) >= 3:
            checks.append(_validate_percentile_order(segment, f"segment:{name}", pct_keys))

    checks.append({
        "check": "driver_segment_coverage",
        "status": "FAIL" if missing_segments else "PASS",
        "detail": (
            f"Missing driver decomposition for segments: {missing_segments}"
            if missing_segments
            else "Every non-total segment has a driver decomposition"
        ),
    })
    checks.append({
        "check": "driver_minimum_depth",
        "status": "FAIL" if depth_issues else "PASS",
        "detail": "; ".join(depth_issues) if depth_issues else "Each segment has 2-4 drivers",
    })
    checks.append({
        "check": "driver_quantified_decomposition",
        "status": "FAIL" if structure_issues or missing_segments else "PASS",
        "detail": (
            "; ".join(structure_issues)
            if structure_issues
            else "Every driver has a named quantitative derivation/mechanism"
        ),
    })
    checks.append({
        "check": "no_bare_growth_rates",
        "status": "FAIL" if missing_segments or depth_issues else "PASS",
        "detail": (
            "Bare segment growth rates are not allowed; every segment must have 2-4 quantified drivers"
            if missing_segments or depth_issues
            else "No bare segment growth rates detected"
        ),
    })
    checks.append({
        "check": "driver_evidence_links",
        "status": "FAIL" if evidence_issues else "PASS",
        "detail": "; ".join(evidence_issues) if evidence_issues else "Every driver has valid evidence refs",
    })
    checks.append({
        "check": "driver_arithmetic",
        "status": "FAIL" if arithmetic_issues else "PASS",
        "detail": "; ".join(arithmetic_issues) if arithmetic_issues else "Driver contributions reconcile to segment growth",
    })

    return checks


def _normalize_assumption_matrix(structured: dict) -> list[dict]:
    """Flatten nested-dict assumption_matrix into list-of-rows."""
    raw = structured.get("assumption_matrix", []) or []
    if isinstance(raw, list):
        return raw
    # nested dict: {period: {variable: {p10, p50, ...}}}
    rows = []
    for period_key, variables in raw.items():
        if not isinstance(variables, dict):
            continue
        for var_name, pct_dict in variables.items():
            if not isinstance(pct_dict, dict):
                continue
            row = dict(pct_dict)
            row["variable"] = var_name
            row["year"] = period_key
            rows.append(row)
    return rows


def _valuation_source_string_is_calculated(value: str) -> bool:
    """Allow descriptive valuation source strings only when they clearly say calculated."""
    text = str(value or "").strip().lower()
    if not text:
        return False
    disallowed = [
        "news",
        "article",
        "media",
        "summary",
        "broker",
        "press release",
        "新闻",
        "媒体",
        "摘要",
        "研报",
    ]
    if any(token in text for token in disallowed):
        return False
    required = [
        "calculated",
        "self-calculated",
        "computed from raw",
        "raw financial data",
        "source: calculated",
        "自行计算",
        "原始数据计算",
    ]
    return any(token in text for token in required)


# _is_pct_variable_name is imported from src.analysis._utils


def _validate_assumption_matrix(structured: dict, workspace: Path) -> list[dict]:
    """Validate variable-level assumptions before Monte Carlo."""
    checks = []
    matrix = _normalize_assumption_matrix(structured)
    known_ids = _workspace_evidence_ids(workspace)

    missing_required = []
    evidence_issues = []
    high_sensitivity_vars = []
    matrix_vars = set()
    canonical_matrix_vars = set()
    decimal_format_issues = []

    for idx, row in enumerate(matrix):
        label = row.get("variable") or f"row_{idx}"
        matrix_vars.add(str(label))
        canonical_matrix_vars.add(_canonical_variable_name(str(label)))
        required = [
            "variable",
            "p10",
            "p50",
            "p90",
            "sensitivity",
            "confidence",
            "evidence_ids",
            "derivation",
            "what_would_change_this",
        ]
        miss = [k for k in required if row.get(k) in (None, "", [])]
        if miss:
            missing_required.append(f"{label}: missing {miss}")

        refs = row.get("evidence_ids") or []
        if isinstance(refs, str):
            refs = [refs]
        bad_refs = [r for r in refs if not _evidence_ref_ok(str(r), known_ids)]
        if bad_refs:
            evidence_issues.append(f"{label}: unknown evidence refs {bad_refs}")

        keys = tuple(k for k in ("p10", "p30", "p50", "p70", "p90") if k in row)
        if len(keys) >= 3:
            checks.append(_validate_percentile_order(row, f"assumption:{label}", keys))

        if str(row.get("sensitivity", "")).lower() == "high":
            high_sensitivity_vars.append(str(label))

        # ── Decimal-form validation ──
        if _is_pct_variable_name(str(label)):
            for pct_key in ("p10", "p30", "p50", "p70", "p90"):
                val = row.get(pct_key)
                if val is not None and isinstance(val, (int, float)):
                    if abs(float(val)) > 1.0:
                        decimal_format_issues.append(
                            f"{label}.{pct_key}={val} appears to be a whole-number % "
                            f"(e.g. 20 meaning 20%). Store as decimal: {float(val)/100:.3f}"
                        )

    contrarian = structured.get("contrarian_checks", []) or []
    contrarian_vars = {
        _canonical_variable_name(str(c.get("variable", "")))
        for c in contrarian
        if c.get("variable")
    }
    missing_contrarian = [
        v for v in high_sensitivity_vars
        if _canonical_variable_name(v) not in contrarian_vars
    ]

    checks.append({
        "check": "assumption_matrix_decimal_format",
        "status": "FAIL" if decimal_format_issues else "PASS",
        "detail": (
            f"Percentage variables with whole-number format (use decimal: 20 → 0.20): {'; '.join(decimal_format_issues)}"
            if decimal_format_issues
            else "All percentage-type variables are in decimal form (e.g. 0.20 = 20%)"
        ),
    })
    checks.append({
        "check": "assumption_matrix_required_fields",
        "status": "FAIL" if missing_required else "PASS",
        "detail": "; ".join(missing_required) if missing_required else f"{len(matrix)} assumptions have required fields",
    })
    checks.append({
        "check": "assumption_matrix_evidence_links",
        "status": "FAIL" if evidence_issues else "PASS",
        "detail": "; ".join(evidence_issues) if evidence_issues else "Every assumption has valid evidence refs",
    })
    checks.append({
        "check": "high_sensitivity_contrarian_coverage",
        "status": "FAIL" if missing_contrarian else "PASS",
        "detail": (
            f"High-sensitivity variables missing contrarian checks: {missing_contrarian}"
            if missing_contrarian
            else "Every high-sensitivity variable has a contrarian check"
        ),
    })
    missing_model_vars = sorted(REQUIRED_REVIEWED_VARIABLES - canonical_matrix_vars)
    checks.append({
        "check": "assumption_matrix_model_variable_coverage",
        "status": "FAIL" if missing_model_vars else "PASS",
        "detail": (
            f"Step 5 model variables missing from assumption_matrix: {missing_model_vars}"
            if missing_model_vars
            else "Assumption matrix covers all Step 5 model variables"
        ),
    })

    reviewed_path = workspace / "_reviewed_assumptions.json"
    if reviewed_path.exists():
        try:
            reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
            reviewed_vars = _canonical_variable_set((reviewed.get("assumptions") or {}).keys())
            missing_review = sorted(canonical_matrix_vars - reviewed_vars)
            extra_review = sorted(reviewed_vars - canonical_matrix_vars)
            status = "FAIL" if missing_review or extra_review else "PASS"
            detail = []
            if missing_review:
                detail.append(f"not saved in reviewed assumptions: {missing_review}")
            if extra_review:
                detail.append(f"reviewed but absent from matrix: {extra_review}")
            checks.append({
                "check": "reviewed_assumption_lock_coverage",
                "status": status,
                "detail": "; ".join(detail) if detail else "Reviewed assumptions cover the full matrix",
            })
        except (json.JSONDecodeError, OSError, ValueError) as e:
            checks.append({
                "check": "reviewed_assumption_lock_coverage",
                "status": "FAIL",
                "detail": f"_reviewed_assumptions.json is invalid: {e}",
            })
    else:
        checks.append({
            "check": "reviewed_assumption_lock_coverage",
            "status": "FAIL",
            "detail": "_reviewed_assumptions.json missing. Save user-reviewed matrix before validation.",
        })

    return checks


# ──────────────────────────────────────────────
#  Main entry point
# ──────────────────────────────────────────────

def validate_step4(filepath: str | Path) -> dict:
    """Validate Step 4 structured assumptions for numerical consistency.

    Checks (14 total):
      1. All required sections present (driver decomposition, bridge, Q1 check, etc.)
      2. Bridge analysis arithmetic consistency
      3. Segment revenue sum matches total
      4. Q1 constraint check result
      5. Margin derivation present (not just a flat number)
      6. Growth rates accompanied by driver decomposition
      7. Historical PE/PB anchoring present
      8. Peer comparison table present (>=3 companies)
      9. Reverse DCF results present
     10. DCF cross-validation present
     11. Contrarian Check per-variable section present
     12. Assumption consistency self-check present
     13. Valuation ratios calculated from source data (not news)
     14. Apple-to-apple valuation comparison (no trailing vs forward / T+1 vs T+2 mixing)

    Returns dict with passed (bool), checks (list), and fix_required (list).
    """
    filepath = Path(filepath)
    if not filepath.exists():
        return {"passed": False, "error": f"File not found: {filepath}"}
    if filepath.name == "step4_quantitative_model.md":
        return {
            "passed": False,
            "error": (
                "Deprecated Step 4 artifact is not accepted: "
                "use step4_assumption_research.md, step5_financial_model.md, "
                "and step6_monte_carlo_simulation.md."
            ),
        }

    structured = _load_structured_json(filepath)
    if structured:
        checks = _validate_structured(structured, filepath)
        validation_mode = "structured_json"
    else:
        checks = [{
            "check": "structured_assumptions",
            "status": "MISSING",
            "detail": (
                f"{STEP4_STRUCTURED_FILENAME} is required. "
                "Markdown-only Step 4 validation is not allowed."
            ),
        }]
        validation_mode = "structured_json_required"

    # ── Check 15: Workspace has calculated_valuation.json (always filesystem) ──
    evidence_contract = validate_step4_evidence_contract(filepath.parent)
    checks.append({
        "check": "evidence_registry_material_coverage",
        "status": "PASS" if evidence_contract.get("passed") else "FAIL",
        "detail": evidence_contract.get("summary", "Evidence registry material coverage check failed"),
    })

    calc_val_check = _check_workspace_calculated_valuation(filepath)
    checks.append(calc_val_check)

    fix_required = [c["detail"] for c in checks if c["status"] in {"FAIL", "MISSING"}]

    passed = len(fix_required) == 0

    return {
        "passed": passed,
        "checks": checks,
        "fix_required": fix_required,
        "validation_mode": validation_mode,
        "summary": f"{'ALL CHECKS PASSED' if passed else f'{len(fix_required)} ISSUE(S) FOUND — FIX BEFORE MONTE CARLO'}",
    }


def _classify_step4_blockers(fix_required: list[str]) -> str:
    text = "\n".join(str(f) for f in fix_required).lower()
    data_tokens = [
        "missing",
        "not found",
        "缺少",
        "missing required",
        "evidence",
        "source",
        "calculated_valuation",
        "reviewed assumptions",
    ]
    if any(token in text for token in data_tokens):
        return "DATA_BLOCKED"
    return "MODEL_BLOCKED"


def write_step4_blockers(
    workspace_dir: str | Path,
    validation_result: dict,
    attempt_count: int,
    max_attempts: int,
) -> Path:
    """Write a durable blocker note when Step 4 repeatedly fails validation."""
    workspace = Path(workspace_dir)
    workspace.mkdir(parents=True, exist_ok=True)
    blocker_type = _classify_step4_blockers(validation_result.get("fix_required", []))
    lines = [
        "# Step 4 Blockers",
        "",
        f"**Status**: {blocker_type}",
        f"**Validation attempts**: {attempt_count}/{max_attempts}",
        f"**Summary**: {validation_result.get('summary', '')}",
        "",
        "## Fix Required",
        "",
    ]
    for item in validation_result.get("fix_required", []):
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Handling Rule",
        "",
        "Stop automatic repair attempts. Do not run Monte Carlo or generate the forecast model until these blockers are resolved.",
    ])
    path = workspace / "step4_blockers.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def validate_step4_with_guard(
    filepath: str | Path,
    max_attempts: int = 2,
    reset_on_pass: bool = True,
) -> dict:
    """Validate Step 4 and cap repeated failed repair loops.

    A failed validation increments ``step4_guard_state.json`` in the workspace.
    Once failures reach ``max_attempts``, ``step4_blockers.md`` is written and
    callers should stop automatic repair attempts.
    """
    filepath = Path(filepath)
    workspace = filepath.parent
    result = validate_step4(filepath)
    state_path = workspace / "step4_guard_state.json"

    state = {"attempt_count": 0}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    if result.get("passed"):
        if reset_on_pass:
            state = {"attempt_count": 0, "last_status": "passed"}
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        result["guard"] = {
            "status": "passed",
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "should_stop": False,
        }
        return result

    attempt_count = int(state.get("attempt_count", 0)) + 1
    blocker_type = _classify_step4_blockers(result.get("fix_required", []))
    guard = {
        "status": "failed",
        "attempt_count": attempt_count,
        "max_attempts": max_attempts,
        "blocker_type": blocker_type,
        "should_stop": attempt_count >= max_attempts,
    }
    if guard["should_stop"]:
        blocker_path = write_step4_blockers(workspace, result, attempt_count, max_attempts)
        guard["blocker_path"] = str(blocker_path)

    state = {
        "attempt_count": attempt_count,
        "last_status": "failed",
        "last_blocker_type": blocker_type,
        "last_summary": result.get("summary", ""),
    }
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    result["guard"] = guard
    return result

def validate_workspace_valuation(workspace_dir: str | Path) -> dict:
    """Validate that workspace has self-calculated valuation, not just API-fetched.

    Checks:
    1. calculated_valuation.json exists in workspace
    2. It contains source="calculated" tag
    3. Warns if valuation_*.json files contain pre-computed ratios without
       a corresponding calculated_valuation.json

    Returns dict with passed, warnings, and summary.
    """
    workspace_dir = Path(workspace_dir)
    warnings_list = []
    fix_required = []

    calc_val_path = workspace_dir / "calculated_valuation.json"

    if not calc_val_path.exists():
        fix_required.append(
            "workspace 中缺少 calculated_valuation.json。"
            "请运行 python -m src.cli fetch TICKER -o workspace_dir 重新抓取并自动计算。"
        )
        return {
            "passed": False,
            "warnings": warnings_list,
            "fix_required": fix_required,
            "summary": "calculated_valuation.json not found in workspace",
        }

    try:
        calc_data = json.loads(calc_val_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "passed": False,
            "warnings": warnings_list,
            "fix_required": [f"calculated_valuation.json is invalid JSON: {e}"],
            "summary": "calculated_valuation.json parse error",
        }

    if calc_data.get("source") != "calculated":
        fix_required.append(
            f"calculated_valuation.json 的 source 字段为 '{calc_data.get('source')}'，"
            "期望为 'calculated'。"
        )

    # Check that key ratios are present
    expected_keys = ["pe_trailing", "pb", "ps"]
    missing_ratios = [k for k in expected_keys if k not in calc_data]
    if missing_ratios:
        fix_required.append(
            f"calculated_valuation.json 缺少以下指标: {missing_ratios}"
        )
    for key in expected_keys:
        val = calc_data.get(key)
        if isinstance(val, dict) and not val.get("valid", False):
            fix_required.append(
                f"calculated_valuation.json 中 {key} 无效: {val.get('error', 'invalid')}"
            )

    passed = len(fix_required) == 0
    return {
        "passed": passed,
        "warnings": warnings_list,
        "fix_required": fix_required,
        "summary": (
            "calculated_valuation.json valid with source=calculated"
            if passed and not warnings_list
            else f"{'PASS' if passed else 'FAIL'} with {len(warnings_list)} warning(s)"
        ),
    }


def _check_workspace_calculated_valuation(filepath: str | Path) -> dict:
    """Check 15: verify calculated_valuation.json exists in workspace."""
    filepath = Path(filepath)
    workspace_dir = filepath.parent
    result = validate_workspace_valuation(workspace_dir)
    return {
        "check": "workspace_calculated_valuation",
        "status": "PASS" if result["passed"] else "FAIL",
        "detail": result["summary"],
    }


def validate_contrarian_checks(workspace_dir: str | Path, through_step: int | str = 9) -> dict:
    """Validate that all serial step outputs contain Contrarian Check sections.

    ``through_step`` lets Step 8 audit the pipeline before Step 9 exists while
    keeping full 1-9 validation available after the director review.

    Returns a dict with per-step status and overall passed flag.
    """
    workspace_dir = Path(workspace_dir)
    try:
        through = int(str(through_step))
    except ValueError:
        through = 9
    through = max(1, min(through, 9))
    contrarian_keywords = {
        "1": ["1.8", "逆向检验", "Contrarian Check"],
        "2": ["2.6", "逆向检验", "Contrarian Check"],
        "3": ["3.7", "逆向检验", "Contrarian Check"],
        "4": ["P50", "P10", "逆向检验", "Contrarian Check"],
        "5": ["模型", "公式", "逆向检验", "Contrarian Check"],
        "6": ["P50", "P10", "逆向检验", "压力测试", "场景压力"],
        "7": ["逆向检验", "RRR", "分布错误风险", "Edge Score"],
        "8": ["Red Team", "自我批判", "证伪路径"],
        "9": ["Director", "Override", "否决", "投资委员会"],
    }

    results = {}
    all_passed = True

    for step in CORE_STEP_IDS:
        if int(step) > through:
            continue
        artifact = get_step_contract(step).primary_artifact
        filepath = workspace_dir / artifact
        if not filepath.exists():
            filepath = None
        if filepath is None:
            results[step] = {
                "status": "MISSING_FILE",
                "detail": f"{artifact} not found",
            }
            all_passed = False
            continue

        content = filepath.read_text(encoding="utf-8")
        keywords = contrarian_keywords[step]
        found = any(kw in content for kw in keywords)

        results[step] = {
            "status": "PASS" if found else "MISSING",
            "detail": (
                f"Step {step} contrarian check {'found' if found else 'NOT found'} "
                f"(looked for: {keywords})"
            ),
        }
        if not found:
            all_passed = False

    return {
        "passed": all_passed,
        "steps": results,
        "summary": "All contrarian checks present" if all_passed else "Some contrarian checks missing — review required",
    }
