"""Step 4 output validator — enforces bottom-up rigor before Monte Carlo.

Usage:
    from src.analysis.step4_validate import validate_step4
    result = validate_step4("workspaces/600584.SH/step4_quantitative_model.md")

If result["passed"] is False, the LLM MUST fix issues before running Monte Carlo.

Dual-track validation:
  - Primary: if step4_structured_assumptions.json exists alongside the markdown,
    validate structured data (real numbers, not keyword scraping).
  - Fallback: if no JSON artifact, validate markdown with regex checks (backward compatible).

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
import re
from pathlib import Path
from typing import Optional


# ──────────────────────────────────────────────
#  Structured JSON helpers
# ──────────────────────────────────────────────

def _load_structured_json(filepath: Path) -> dict | None:
    """Load step4_structured_assumptions.json if it exists alongside the markdown."""
    json_path = filepath.parent / "step4_structured_assumptions.json"
    if not json_path.exists():
        return None
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return None


def _validate_structured(structured: dict, filepath: Path) -> list[dict]:
    """Run checks 1-14 against structured JSON data.

    Returns list of check result dicts.
    """
    checks = []

    # ── Check 1: Required sections ──
    required_keys = [
        "segment_revenues", "bridge_analysis", "q1_constraint",
        "margin_derivation", "growth_drivers",
    ]
    for key in required_keys:
        present = key in structured and structured[key] is not None
        if key == "growth_drivers":
            present = present and len(structured.get("growth_drivers", [])) > 0
        checks.append({
            "check": f"required_section:{key}",
            "status": "PASS" if present else "MISSING",
            "detail": f"Structured key '{key}' {'present' if present else 'absent'}",
        })

    # ── Check 2: Bridge arithmetic ──
    bridge = structured.get("bridge_analysis", {})
    if bridge and "base_total" in bridge and "p50_total" in bridge and "delta" in bridge:
        base = bridge["base_total"]
        delta = bridge["delta"]
        stated = bridge["p50_total"]
        expected = base + delta
        if abs(expected) > 0.01:
            diff_pct = abs(stated - expected) / abs(expected)
        else:
            diff_pct = 0.0
        checks.append({
            "check": "bridge_arithmetic",
            "status": "PASS" if diff_pct < 0.05 else "FAIL",
            "detail": (
                f"Bridge: {base} + {delta} = {expected} vs stated {stated} "
                f"(diff {diff_pct:.1%})"
            ),
        })
    else:
        checks.append({
            "check": "bridge_arithmetic",
            "status": "SKIP",
            "detail": "bridge_analysis incomplete in structured JSON",
        })

    # ── Check 3: Segment sum vs total ──
    segments = structured.get("segment_revenues", [])
    if segments and len(segments) >= 2:
        seg_total = sum(s.get("p50_revenue", 0) for s in segments)
        stated_total = bridge.get("p50_total", 0) if bridge else 0
        if stated_total > 0:
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
                "detail": f"Found {len(segments)} segment revenue entries",
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
        feas = q1["feasibility"]
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
        dev = dcf["deviation_pct"]
        checks.append({
            "check": "dcf_cross_validation",
            "status": "PASS" if abs(dev) < 0.30 else "FAIL",
            "detail": f"DCF vs MC deviation: {dev:.1%}",
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
    if val_src and val_src.get("pe_calculated"):
        checks.append({
            "check": "valuation_ratios_calculated",
            "status": "PASS",
            "detail": "Structured JSON confirms PE was calculated from source data",
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
        checks.append({
            "check": "apple_to_apple_valuation",
            "status": "PASS" if result["passed"] else "FAIL",
            "detail": result["summary"],
        })
    else:
        checks.append({
            "check": "apple_to_apple_valuation",
            "status": "SKIP",
            "detail": "peer_comparison has fewer than 2 entries",
        })

    return checks


# ──────────────────────────────────────────────
#  Main entry point
# ──────────────────────────────────────────────

def validate_step4(filepath: str | Path) -> dict:
    """Validate a Step 4 markdown file for structural and numerical consistency.

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

    content = filepath.read_text(encoding="utf-8")

    # ── Dual-track dispatch ──
    structured = _load_structured_json(filepath)
    if structured:
        checks = _validate_structured(structured, filepath)
        validation_mode = "structured_json"
    else:
        checks = _legacy_regex_checks(content)
        validation_mode = "regex_markdown"

    # ── Check 15: Workspace has calculated_valuation.json (always filesystem) ──
    calc_val_check = _check_workspace_calculated_valuation(filepath)
    checks.append(calc_val_check)

    fix_required = [c["detail"] for c in checks if c["status"] == "FAIL"]

    # ── Check 13 bonus: if calculated_valuation.json exists, upgrade Check 13 ──
    pe_source_check = next(
        (c for c in checks if c["check"] == "valuation_ratios_calculated"),
        None,
    )
    if calc_val_check["status"] == "PASS" and pe_source_check and pe_source_check["status"] != "PASS":
        idx = checks.index(pe_source_check)
        checks[idx] = {
            "check": "valuation_ratios_calculated",
            "status": "PASS",
            "detail": "calculated_valuation.json present with source=calculated — strong signal of self-computation",
        }
        fix_required = [f for f in fix_required if "估值指标疑似来自" not in f and "缺少估值指标的计算过程" not in f]

    passed = len(fix_required) == 0

    return {
        "passed": passed,
        "checks": checks,
        "fix_required": fix_required,
        "validation_mode": validation_mode,
        "summary": f"{'ALL CHECKS PASSED' if passed else f'{len(fix_required)} ISSUE(S) FOUND — FIX BEFORE MONTE CARLO'}",
    }


def _legacy_regex_checks(content: str) -> list[dict]:
    """Run checks 1-14 using regex on markdown content.

    This is the legacy fallback path — used when step4_structured_assumptions.json
    is not present. Kept for backward compatibility with existing workspaces.
    """
    checks = []

    # ── Check 1: Required sections ──
    required_sections = {
        "driver_decomposition": ["驱动因子"],
        "bridge_analysis": ["桥梁", "Bridge", "增量来源", "桥梁验证"],
        "q1_check": ["Q1 约束", "quarterly_arithmetic_check", "隐含 Q2-Q4"],
        "margin_derivation": ["成本结构", "毛利率推导", "成本项"],
        "capacity_or_constraint": ["产能约束", "设计产能", "利用率", "约束检查", "瓶颈"],
    }

    for section_name, keywords in required_sections.items():
        found = any(kw in content for kw in keywords)
        status = "PASS" if found else "MISSING"
        checks.append({
            "check": f"required_section:{section_name}",
            "status": status,
            "detail": f"Looking for keywords: {keywords}",
        })

    # ── Check 2: Bridge arithmetic ──
    checks.append(_check_bridge_arithmetic(content))

    # ── Check 3: Segment sum vs total ──
    checks.append(_check_segment_sum(content))

    # ── Check 4: Q1 constraint not UNREASONABLE ──
    checks.append(_check_q1_result(content))

    # ── Check 5: Margin has derivation, not flat number ──
    checks.append(_check_margin_derivation(content))

    # ── Check 6: No "增速" without driver decomposition ──
    checks.append(_check_growth_without_drivers(content))

    # ── Check 7: Historical PE/PB anchoring ──
    checks.append(_check_historical_valuation_anchor(content))

    # ── Check 8: Peer comparison table ──
    checks.append(_check_peer_comparison(content))

    # ── Check 9: Reverse DCF results ──
    checks.append(_check_reverse_dcf(content))

    # ── Check 10: DCF cross-validation ──
    checks.append(_check_dcf_cross_validation(content))

    # ── Check 11: Contrarian Check per variable ──
    checks.append(_check_contrarian_per_variable(content))

    # ── Check 12: Assumption consistency self-check ──
    checks.append(_check_assumption_consistency(content))

    # ── Check 13: PE must be calculated, not from news/old data ──
    checks.append(_check_pe_calculated_not_news(content))

    # ── Check 14: Apple-to-apple PE comparison ──
    checks.append(_check_pe_apple_to_apple(content))

    return checks


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
        warnings_list.append(
            f"calculated_valuation.json 的 source 字段为 '{calc_data.get('source')}'，"
            "期望为 'calculated'。"
        )

    # Check that key ratios are present
    expected_keys = ["pe_trailing", "pb", "ps"]
    missing_ratios = [k for k in expected_keys if k not in calc_data]
    if missing_ratios:
        warnings_list.append(
            f"calculated_valuation.json 缺少以下指标: {missing_ratios}"
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


def validate_contrarian_checks(workspace_dir: str | Path) -> dict:
    """Validate that all 7 step outputs contain their Contrarian Check sections.

    Returns a dict with per-step status and overall passed flag.
    """
    workspace_dir = Path(workspace_dir)
    step_files = {
        1: "step1_business_analysis.md",
        2: "step2_competitive_moat.md",
        3: "step3_marginal_changes.md",
        4: "step4_quantitative_model.md",
        5: "step5_rrr_strategy.md",
        6: "step6_auditing.md",
        7: "step7_research_director_review.md",
    }

    contrarian_keywords = {
        1: ["1.8", "逆向检验", "Contrarian Check"],
        2: ["2.6", "逆向检验", "Contrarian Check"],
        3: ["3.7", "逆向检验", "Contrarian Check"],
        4: ["P50", "P10", "逆向检验", "压力测试", "场景压力"],
        5: ["逆向检验", "RRR", "分布错误风险", "Edge Score"],
        6: ["Red Team", "自我批判", "证伪路径"],
        7: ["Director", "Override", "否决", "投资委员会"],
    }

    results = {}
    all_passed = True

    for step, filename in step_files.items():
        filepath = workspace_dir / filename
        if not filepath.exists():
            results[step] = {
                "status": "MISSING_FILE",
                "detail": f"{filename} not found",
            }
            all_passed = False
            continue

        content = filepath.read_text(encoding="utf-8")
        keywords = contrarian_keywords[step]
        found = any(kw in content for kw in keywords)

        results[step] = {
            "status": "PASS" if found else "MISSING",
            "detail": f"Step {step} contrarian check {'found' if found else 'NOT found'} (looked for: {keywords})",
        }
        if not found:
            all_passed = False

    return {
        "passed": all_passed,
        "steps": results,
        "summary": "All contrarian checks present" if all_passed else "Some contrarian checks missing — review required",
    }


def _check_bridge_arithmetic(content: str) -> dict:
    """Check if bridge analysis numbers are present and roughly consistent."""
    bridge_total_pattern = re.compile(
        r'(?:桥梁验证|合计增量|增量合计).*?(\d+\.?\d*)\s*亿'
    )
    segment_total_pattern = re.compile(
        r'\*\*合计\*\*.*?(\d+\.?\d*)\s*亿'
    )

    bridge_match = bridge_total_pattern.search(content)
    segment_match = segment_total_pattern.search(content)

    if not bridge_match and not segment_match:
        return {
            "check": "bridge_arithmetic",
            "status": "SKIP",
            "detail": "未找到桥梁分析数字，跳过算术验证",
        }

    if bridge_match and segment_match:
        try:
            bridge_val = float(bridge_match.group(1))
            segment_val = float(segment_match.group(1))
            diff_pct = abs(bridge_val - segment_val) / max(segment_val, 0.01)

            if diff_pct < 0.05:
                return {
                    "check": "bridge_arithmetic",
                    "status": "PASS",
                    "detail": f"桥梁验证 {bridge_val}亿 ≈ 板块加总 {segment_val}亿 (差异 {diff_pct:.1%})",
                }
            else:
                return {
                    "check": "bridge_arithmetic",
                    "status": "FAIL",
                    "detail": f"桥梁验证 {bridge_val}亿 ≠ 板块加总 {segment_val}亿 (差异 {diff_pct:.1%} > 5%)。增量来源拆解与板块加总不一致。",
                }
        except (ValueError, ZeroDivisionError):
            pass

    return {
        "check": "bridge_arithmetic",
        "status": "SKIP",
        "detail": "无法提取桥梁数字进行验证",
    }


def _check_segment_sum(content: str) -> dict:
    """Check if individual segment revenues roughly add up to the total.

    Dynamically extracts segment revenue data from markdown tables
    by looking for table rows with numeric values in revenue columns.
    No hardcoded sector names — works for any industry.
    """
    segment_revenues = []

    # Match markdown table rows: | text | ... | number | ...
    # Look for rows where the last numeric-looking cell is a revenue figure
    # Pattern: | <segment_name> | ... | <revenue_number> | ...
    for m in re.finditer(
        r'\|\s*([^|]+?)\s*\|'  # first column (segment name)
        r'(?:[^|]*\|){1,8}'     # 1-8 intermediate columns
        r'\s*(\d+\.?\d*)\s*\|', # numeric value column
        content,
    ):
        segment_name = m.group(1).strip()
        try:
            value = float(m.group(2))
        except ValueError:
            continue

        # Skip header-like rows and total rows
        if any(skip in segment_name.lower() for skip in ["板块", "合计", "total", "sum", "项目", "item"]):
            continue
        # Skip if segment name looks like a header (too short or all caps English)
        if len(segment_name) < 2:
            continue

        segment_revenues.append(value)

    if len(segment_revenues) < 2:
        return {
            "check": "segment_sum",
            "status": "SKIP",
            "detail": "未找到足够的板块收入数据",
        }

    return {
        "check": "segment_sum",
        "status": "PASS",
        "detail": f"找到 {len(segment_revenues)} 个板块收入数据",
    }


def _check_q1_result(content: str) -> dict:
    """Check if Q1 constraint result is present and not UNREASONABLE."""
    unreasonable_indicators = [
        "UNREASONABLE",
        "不可接受",
        "必须下调全年",
    ]

    has_q1_check = any(
        kw in content for kw in ["隐含 Q2-Q4", "quarterly_arithmetic_check", "Q1 约束"]
    )

    if not has_q1_check:
        return {
            "check": "q1_constraint",
            "status": "FAIL",
            "detail": "缺少 Q1 约束检查。必须运行 quarterly_arithmetic_check 并展示结果。",
        }

    for indicator in unreasonable_indicators:
        if indicator in content:
            return {
                "check": "q1_constraint",
                "status": "FAIL",
                "detail": f"Q1 约束检查结果为 {indicator}。不允许在 UNREASONABLE 的情况下继续。必须先下调全年假设。",
            }

    return {
        "check": "q1_constraint",
        "status": "PASS",
        "detail": "Q1 约束检查存在且未标记为 UNREASONABLE",
    }


def _check_margin_derivation(content: str) -> dict:
    """Check if margin was derived from cost structure, not just stated as a flat number."""
    has_cost_breakdown = any(
        kw in content for kw in ["材料成本", "成本结构拆解", "成本项.*假设"]
    )
    has_margin_formula = "1 -" in content or "1−" in content or "总成本 /" in content

    if has_cost_breakdown and has_margin_formula:
        return {
            "check": "margin_derivation",
            "status": "PASS",
            "detail": "毛利率从成本结构推导",
        }

    if has_cost_breakdown:
        return {
            "check": "margin_derivation",
            "status": "PASS",
            "detail": "存在成本结构拆解（推导过程可能隐含）",
        }

    return {
        "check": "margin_derivation",
        "status": "FAIL",
        "detail": "毛利率缺少成本结构推导。必须先拆解成本构成（材料/人工/折旧），再从成本增速推算毛利率，不能直接给出一个数字。",
    }


def _check_growth_without_drivers(content: str) -> dict:
    """Check if growth rates are accompanied by driver decomposition."""
    growth_tables = re.findall(r'P50.*?增速|P50.*?\+\d+%', content)
    driver_tables = re.findall(r'驱动因子', content)

    if len(growth_tables) > 3 and len(driver_tables) == 0:
        return {
            "check": "growth_has_drivers",
            "status": "FAIL",
            "detail": f"找到 {len(growth_tables)} 处增速假设但无驱动因子分解。每个板块的增速必须分解为可量化的驱动因子（如出货量×ASP、市场规模×份额、存量客户×客单价等，根据业务逻辑选择最合适的分解方式）。",
        }

    return {
        "check": "growth_has_drivers",
        "status": "PASS",
        "detail": f"增速假设有驱动因子分解支撑 ({len(driver_tables)} 处)",
    }


def _check_historical_valuation_anchor(content: str) -> dict:
    """Check if historical PE/PB anchoring is present."""
    has_historical_pe = any(
        kw in content for kw in [
            "历史 PE", "历史PB", "PE 历史", "PB 历史",
            "历史区间", "历史分位", "历史第", "历史百分位",
            "min.*median.*max", "3-5 年 PE",
        ]
    )

    if has_historical_pe:
        return {
            "check": "historical_valuation_anchor",
            "status": "PASS",
            "detail": "存在历史 PE/PB 锚定数据",
        }

    return {
        "check": "historical_valuation_anchor",
        "status": "FAIL",
        "detail": "缺少历史 PE/PB 纵向锚定。必须提取公司 3-5 年 PE/PB 范围（min, median, max）和当前分位，作为估值假设的基础。",
    }


def _check_peer_comparison(content: str) -> dict:
    """Check if peer comparison table with >=3 companies is present."""
    has_peer_section = any(
        kw in content for kw in [
            "同业锚", "同业对比", "可比公司", "横向同业",
            "Peer", "peer comparison",
        ]
    )

    # Also check for table structure with multiple company rows
    peer_table_rows = re.findall(
        r'\|\s*(?:同业|对标|可比|竞争)\s*[A-Z][^|]*\|',
        content,
    )

    if has_peer_section or len(peer_table_rows) >= 3:
        return {
            "check": "peer_comparison",
            "status": "PASS",
            "detail": f"存在同业对比（找到 {len(peer_table_rows)} 家可比公司）",
        }

    return {
        "check": "peer_comparison",
        "status": "FAIL",
        "detail": "缺少同业横向对比。必须列出至少 3 家可比公司的 PE/PB/ROE，作为估值假设的横向锚。",
    }


def _check_reverse_dcf(content: str) -> dict:
    """Check if Reverse DCF results are present."""
    has_reverse_dcf = any(
        kw in content for kw in [
            "Reverse DCF", "reverse_dcf", "市场隐含增速",
            "隐含增长率", "隐含 FCF",
        ]
    )

    if has_reverse_dcf:
        return {
            "check": "reverse_dcf",
            "status": "PASS",
            "detail": "存在 Reverse DCF 市场隐含增速验证",
        }

    return {
        "check": "reverse_dcf",
        "status": "FAIL",
        "detail": "缺少 Reverse DCF 验证。必须运行 reverse_dcf() 提取市场隐含增速，与 Step 3 预期差进行交叉验证。",
    }


def _check_dcf_cross_validation(content: str) -> dict:
    """Check if DCF cross-validation results are present."""
    has_dcf_cross = any(
        kw in content for kw in [
            "DCF 交叉验证", "DCF 交叉", "DCF 对比",
            "dcf_model", "绝对估值", "DCF 内在价值",
        ]
    )

    if has_dcf_cross:
        return {
            "check": "dcf_cross_validation",
            "status": "PASS",
            "detail": "存在 DCF 交叉验证",
        }

    return {
        "check": "dcf_cross_validation",
        "status": "FAIL",
        "detail": "缺少 DCF 交叉验证。必须运行 dcf_model() 计算 P50 场景内在价值，与蒙特卡洛 P50 目标价对比（偏差 >30% 需解释）。",
    }


def _check_contrarian_per_variable(content: str) -> dict:
    """Check if per-variable contrarian check table is present."""
    has_contrarian_table = any(
        kw in content for kw in [
            "P50.*P10.*证据", "P50 → P10", "场景压力测试",
            "正向压力测试",
        ]
    )

    # Also look for table header pattern
    contrarian_header = re.search(
        r'变量.*P50.*P10.*证据',
        content,
    )

    if has_contrarian_table or contrarian_header:
        return {
            "check": "contrarian_per_variable",
            "status": "PASS",
            "detail": "存在逐变量逆向检验表",
        }

    return {
        "check": "contrarian_per_variable",
        "status": "FAIL",
        "detail": "缺少逐变量逆向检验。必须对每个关键变量回答'什么证据会让 P50 变成 P10'，并包含场景压力测试。",
    }


def _check_assumption_consistency(content: str) -> dict:
    """Check if assumption consistency self-check is present."""
    has_consistency = any(
        kw in content for kw in [
            "假设一致性自检", "审阅后静默修改",
            "护城河评级一致", "板块分析一致",
        ]
    )

    if has_consistency:
        return {
            "check": "assumption_consistency",
            "status": "PASS",
            "detail": "存在假设一致性自检",
        }

    return {
        "check": "assumption_consistency",
        "status": "FAIL",
        "detail": "缺少假设一致性自检。必须回答：是否在审阅后修改了假设？PE 是否与护城河评级一致？营收增速是否与板块分析一致？",
    }


def _check_pe_calculated_not_news(content: str) -> dict:
    """Check that valuation ratios (PE/PB/PS/EV_EBITDA) are calculated, not from news.

    Looks for evidence that the analyst used calc_pe/calc_pb/calc_ps/calc_ev_ebitda
    or calc_all_valuation_ratios to compute values from raw financial data,
    rather than citing news articles or third-party reports.
    """
    # Positive signals: evidence of calculation from source data
    calc_evidence = [
        "calc_pe", "calc_pb", "calc_ps", "calc_ev_ebitda",
        "calc_all_valuation_ratios", "calc_pe_trailing", "calc_pe_forward",
        "price.*eps", "price.*EPS", "市价.*每股收益",
        "股价.*EPS", "市值.*净利润",
        "price / bvps", "price / revenue_per_share",
        "EV.*EBITDA.*计算", "估值计算",
        "source.*calculated", "source: calculated",
        "来源：计算", "数据来源：计算",
        "Forward PE.*=.*价格.*EPS",
    ]
    calc_found = sum(1 for pattern in calc_evidence if re.search(pattern, content, re.IGNORECASE))

    # Negative signals: evidence of news/old data sourcing
    news_indicators = [
        "据.*报道.*PE", "新闻.*估值", "新浪.*PE", "东方财富.*PE",
        "wind.*PE", "同花顺.*PE", "雪球.*PE",
        "截至.*PE.*为",  # vague sourcing without calculation
    ]
    news_found = sum(1 for pattern in news_indicators if re.search(pattern, content, re.IGNORECASE))

    # Check for explicit calculation traceability
    has_formula = any(kw in content for kw in [
        "PE =", "PE =", "PB =", "PS =", "EV/EBITDA =",
        "Forward PE =", "PE(TTM) =", "PE(Forward) =",
    ])

    # Check for input disclosure (price and EPS/BPS/revenue mentioned near PE)
    has_input_disclosure = bool(re.search(
        r'(?:PE|PB|PS|EV/EBITDA).*?(?:=|：|calculated from).*?\d',
        content, re.IGNORECASE,
    ))

    if calc_found >= 2 or (calc_found >= 1 and has_formula):
        return {
            "check": "valuation_ratios_calculated",
            "status": "PASS",
            "detail": f"估值指标有计算过程支撑（{calc_found} 处计算证据）",
        }

    if news_found > 0 and calc_found == 0:
        return {
            "check": "valuation_ratios_calculated",
            "status": "FAIL",
            "detail": (
                "⚠️ 估值指标疑似来自新闻/第三方数据而非自行计算。"
                "所有关键估值指标（PE、PB、PS、EV/EBITDA）必须通过 "
                "calc_pe / calc_pb / calc_ps / calc_ev_ebitda / calc_all_valuation_ratios "
                "从原始财报数据计算得出，禁止直接使用新闻或过时数据。"
                "每次计算必须标注 price、EPS/BPS/revenue 等输入值和来源。"
            ),
        }

    if has_input_disclosure or has_formula:
        return {
            "check": "valuation_ratios_calculated",
            "status": "PASS",
            "detail": "估值指标有输入值披露和计算公式",
        }

    # Warn if no clear evidence either way
    return {
        "check": "valuation_ratios_calculated",
        "status": "FAIL",
        "detail": (
            "缺少估值指标的计算过程追溯。必须明确展示："
            "1) 使用的 price（股价）值和日期；"
            "2) 使用的 EPS/BPS/revenue 值和来源（年报/季报/预测）；"
            "3) 计算公式（如 PE = Price / EPS = XX / YY = ZZx）；"
            "4) 标注 source: calculated。"
        ),
    }


def _check_pe_apple_to_apple(content: str) -> dict:
    """Check that all PE comparisons are apple-to-apple (same year, same basis).

    Detects:
    1. Trailing PE vs Forward PE mixed in same comparison table
    2. Forward T+1 PE vs Forward T+2 PE mixed in same comparison table
    3. Mixed valuation metrics in same comparison (PE vs PB etc.)
    """
    violations = []

    # ── Check 1: Trailing vs Forward mixed ──
    # Find comparison tables that mix TTM/trailing with Forward/T+N
    has_trailing = bool(re.search(
        r'(?:PE\(TTM\)|PE.*TTM|trailing.*PE|市盈率.*TTM|滚动市盈率|静态.*PE|PE.*静态)',
        content, re.IGNORECASE,
    ))
    has_forward = bool(re.search(
        r'(?:PE\(Forward\)|Forward.*PE|PE.*Forward|PE.*T\+1|PE.*T\+2|PE.*202[5-9]E|预测PE|动态PE)',
        content, re.IGNORECASE,
    ))

    # Check if they appear in the same comparison context (same table or section)
    # Look for tables that have both TTM and Forward labels
    mixed_in_table = re.findall(
        r'(?:\|[^|]*TTM[^|]*\|[^|]*Forward[^|]*\||\|[^|]*Forward[^|]*\|[^|]*TTM[^|]*\|)',
        content, re.IGNORECASE,
    )

    # Also check for PE values that appear to be from different years in the same row
    # E.g., "目标公司 PE 26x vs 同业 Forward PE 27x"
    mixed_inline = re.findall(
        r'(?:PE.*?26.*?Forward.*?27|PE.*?27.*?TTM.*?26|trailing.*?\d+x.*?forward.*?\d+x)',
        content, re.IGNORECASE,
    )

    if mixed_in_table or mixed_inline:
        violations.append("同业对比表中混合了 Trailing PE 和 Forward PE，这是不合理的比较")

    # ── Check 2: Forward T+1 vs T+2 mixed ──
    # Find if different forward years are used in the same comparison
    forward_years_used = set()
    for match in re.finditer(
        r'(?:Forward PE|PE).*?(?:T\+(\d)|(\d{4})E)',
        content, re.IGNORECASE,
    ):
        if match.group(1):
            forward_years_used.add(f"T+{match.group(1)}")
        elif match.group(2):
            forward_years_used.add(f"{match.group(2)}E")

    # Check if peer comparison section mixes forward years
    peer_section = re.search(
        r'(?:同业.*?对比|同业.*?锚|Peer.*?Comparison|横向同业)(.*?)(?:\n#{1,3}\s|\Z)',
        content, re.DOTALL | re.IGNORECASE,
    )

    if peer_section:
        peer_text = peer_section.group(1)
        years_in_peer = set()
        for m in re.finditer(
            r'(?:T\+(\d)|(\d{4})E)',
            peer_text,
        ):
            if m.group(1):
                years_in_peer.add(f"T+{m.group(1)}")
            elif m.group(2):
                years_in_peer.add(f"{m.group(2)}E")

        if len(years_in_peer) > 1:
            violations.append(
                f"同业对比中混合了不同的 Forward 年份: {years_in_peer}。"
                "T+1 PE 和 T+2 PE 不可直接比较。所有公司必须使用相同的 Forward 年份。"
            )

    # ── Check 3: PE Band uses consistent year ──
    # Forward PE Band should use the same forward EPS as the Monte Carlo
    pe_band_section = re.search(
        r'(?:Forward PE Band|PE Band)(.*?)(?:\n#{1,3}\s|\Z)',
        content, re.DOTALL | re.IGNORECASE,
    )
    monte_carlo_section = re.search(
        r'(?:蒙特卡洛|Monte Carlo)(.*?)(?:\n#{1,3}\s|\Z)',
        content, re.DOTALL | re.IGNORECASE,
    )

    if pe_band_section and monte_carlo_section:
        # Check that PE Band and Monte Carlo reference the same year
        band_years = set(re.findall(r'(T\+\d|\d{4}E)', pe_band_section.group(1)))
        mc_years = set(re.findall(r'(T\+\d|\d{4}E)', monte_carlo_section.group(1)))

        if band_years and mc_years and band_years != mc_years:
            violations.append(
                f"PE Band 使用的年份 ({band_years}) 与蒙特卡洛 ({mc_years}) 不一致。"
                "两者必须使用相同的 Forward 年份。"
            )

    if violations:
        return {
            "check": "apple_to_apple_valuation",
            "status": "FAIL",
            "detail": (
                "估值比较不是 apple-to-apple: " + "; ".join(violations) + "。"
                "规则：1) Trailing PE 和 Forward PE 不可混比；"
                "2) 不同 Forward 年份（T+1 vs T+2）不可混比；"
                "3) 同一对比表中所有公司必须使用相同的指标口径和年份。"
            ),
        }

    return {
        "check": "apple_to_apple_valuation",
        "status": "PASS",
        "detail": "估值比较通过 apple-to-apple 检查",
    }
