#!/usr/bin/env python3
"""InvestPilot CLI — data fetching and analysis tools."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from config.settings import MONTE_CARLO_SIMULATIONS, WORKSPACES_DIR
from config.ticker_rules import detect_market, normalize_ticker
from src.data.market_detector import get_fetcher

logger = logging.getLogger(__name__)


def cmd_detect(args):
    market = detect_market(args.ticker)
    normalized, market = normalize_ticker(args.ticker, market)
    result = {
        "ticker": args.ticker,
        "normalized": normalized,
        "market": market,
    }
    if getattr(args, "create_workspace", False) is True:
        ws_dir = WORKSPACES_DIR / normalized.replace(".", "_")
        ws_dir.mkdir(parents=True, exist_ok=True)
        result["workspace"] = str(ws_dir)
        result["workspace_created"] = ws_dir.exists()
        print(f"Workspace ready: {ws_dir}")
    print(json.dumps(result, indent=2))


def cmd_fetch(args):
    fetcher, normalized, market = get_fetcher(args.ticker)
    output_dir = Path(args.output) if args.output else WORKSPACES_DIR / normalized.replace(".", "_")
    output_dir.mkdir(parents=True, exist_ok=True)

    results = fetcher.fetch_all(normalized, period=getattr(args, "period", "5y"))
    for name, result in results.items():
        print(f"\n--- {name} ---")
        print(f"Source: {result.source}")
        print(f"Success: {result.success}")
        if result.warnings:
            for w in result.warnings:
                logger.warning(w)

        if result.data is not None:
            if isinstance(result.data, dict):
                for key, val in result.data.items():
                    if hasattr(val, "to_csv"):
                        path = output_dir / f"{name}_{key}.csv"
                        val.to_csv(path)
                        print(f"Saved: {path}")
                    else:
                        path = output_dir / f"{name}_{key}.json"
                        path.write_text(
                            json.dumps(val if not hasattr(val, "__dict__") else str(val), default=str, indent=2),
                            encoding="utf-8",
                        )
                        print(f"Saved: {path}")
            elif hasattr(result.data, "to_csv"):
                path = output_dir / f"{name}.csv"
                result.data.to_csv(path)
                print(f"Saved: {path}")

    # ── Auto-calculate valuation ratios from raw financial data ──
    _auto_calculate_valuation(results, output_dir)

    print(f"\nAll data saved to: {output_dir}")


def cmd_analyze(args):
    import pandas as pd

    from src.analysis.technical import calc_ma, calc_macd, calc_rsi

    input_dir = Path(args.input) if args.input else WORKSPACES_DIR / args.ticker.replace(".", "_")
    output_dir = Path(args.output) if args.output else input_dir / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load price data
    price_file = input_dir / "price_history.csv"
    if price_file.exists():
        prices = pd.read_csv(price_file, index_col=0, parse_dates=True)
        # Normalize column names to title case for compatibility
        prices.columns = [c.strip().title() if isinstance(c, str) else c for c in prices.columns]
        if "Close" in prices.columns:
            close = prices["Close"]

            ma = calc_ma(close)
            rsi = calc_rsi(close)
            macd = calc_macd(close)

            technical = pd.concat([ma, rsi.rename("RSI"), macd], axis=1)
            technical.to_csv(output_dir / "technical_indicators.csv")
            print(f"Technical analysis saved to {output_dir / 'technical_indicators.csv'}")
    else:
        logger.warning("No price data found at %s", price_file)

    print(f"Analysis output: {output_dir}")


def cmd_thesis(args):
    from src.analysis.thesis_tracker import ThesisTracker

    workspace = args.workspace
    action = args.action

    tracker = ThesisTracker(workspace)

    if action == "snapshot":
        snap = tracker.snapshot()
        print(json.dumps(snap, ensure_ascii=False, indent=2))

    elif action == "brief":
        print(tracker.generate_update_brief())

    elif action == "create":
        thesis = tracker.create(
            core_thesis=args.thesis,
            hold_period_months=int(args.hold_months or 12),
        )
        print("Thesis created (revision 1)")
        print(json.dumps(thesis, ensure_ascii=False, indent=2, default=str))

    elif action == "add-hypothesis":
        hyp = tracker.add_hypothesis(
            description=args.description,
            catalyst_date=args.date or "",
            impact=args.impact or "medium",
        )
        print(f"Hypothesis added: {hyp['id']}")

    elif action == "confirm":
        tracker.confirm_hypothesis(args.hypothesis, actual_result=args.result or "")
        print(f"Hypothesis confirmed: {args.hypothesis}")

    elif action == "invalidate":
        tracker.invalidate_hypothesis(args.hypothesis, actual_result=args.result or "")
        print(f"Hypothesis invalidated: {args.hypothesis}")

    elif action == "close":
        from src.analysis.thesis_tracker import ThesisStatus
        status = ThesisStatus(args.status) if args.status else ThesisStatus.CLOSED_WON
        tracker.close_thesis(status, reason=args.reason or "")
        print(f"Thesis closed: {status}")

    else:
        print(f"Unknown action: {action}")
        print("Available: snapshot, brief, create, add-hypothesis, confirm, invalidate, close")


def cmd_catalyst(args):
    from src.analysis.catalyst_tracker import CatalystTracker

    workspace = args.workspace
    action = args.action

    tracker = CatalystTracker(workspace)

    if action == "list":
        print(tracker.catalyst_calendar())

    elif action == "add":
        cat = tracker.add_catalyst(
            event=args.event,
            expected_date=args.date,
            impact=args.impact or "medium",
            direction=args.direction or "positive",
        )
        print(f"Catalyst added: {cat['id']}")

    elif action == "resolve":
        tracker.resolve_catalyst(
            catalyst_id_or_event=args.catalyst,
            actual_date=args.actual_date,
            outcome=args.outcome,
            thesis_impact=args.impact or "neutral",
        )
        print(f"Catalyst resolved: {args.catalyst}")

    elif action == "decay":
        decay = tracker.time_decay_status()
        print(json.dumps(decay, ensure_ascii=False, indent=2, default=str))

    elif action == "kill-switch":
        if args.trigger:
            if not args.condition:
                print("Error: --condition is required for kill-switch trigger")
                return
            tracker.trigger_kill_switch(args.condition, args.evidence or "")
            print(f"Kill switch triggered: {args.condition}")
        else:
            if not args.condition:
                print("Error: --condition is required for kill-switch add")
                return
            tracker.add_kill_switch(args.condition, severity=args.severity or "critical")
            print(f"Kill switch added: {args.condition}")

    else:
        print(f"Unknown action: {action}")
        print("Available: list, add, resolve, decay, kill-switch")


def _parse_json_arg(raw, default):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON argument: {e}") from e


def cmd_consensus(args):
    from src.analysis.consensus_tracker import ConsensusTracker

    tracker = ConsensusTracker(args.workspace)
    action = args.action

    if action == "snapshot":
        print(json.dumps(tracker.snapshot(), ensure_ascii=False, indent=2, default=str))

    elif action == "brief":
        print(tracker.generate_step3_brief())

    elif action == "add-snapshot":
        metrics = _parse_json_arg(args.metrics_json, {})
        rating_distribution = _parse_json_arg(args.rating_json, {})
        snap = tracker.record_snapshot(
            source=args.source,
            metrics=metrics,
            as_of=args.as_of or None,
            source_type=args.source_type or "sell_side",
            rating_distribution=rating_distribution,
            target_price=args.target_price,
            confidence=args.confidence or "medium",
            notes=args.notes or "",
        )
        print(f"Consensus snapshot recorded: {snap['id']}")
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))

    elif action == "add-gap":
        gap = tracker.add_expectation_gap(
            metric=args.metric,
            period=args.period or "",
            consensus_value=args.consensus,
            our_value=args.our,
            unit=args.unit or "",
            consensus_source=args.consensus_source or "",
            our_source=args.our_source or "",
            catalyst=args.catalyst or "",
            confidence=args.confidence or "medium",
            notes=args.notes or "",
            higher_is_better=not bool(args.lower_is_better),
        )
        print(f"Expectation gap recorded: {gap['id']}")
        print(json.dumps(gap, ensure_ascii=False, indent=2, default=str))

    elif action == "revise":
        rev = tracker.record_revision(
            metric=args.metric,
            period=args.period or "",
            old_value=args.old,
            new_value=args.new,
            source=args.source,
            as_of=args.as_of or None,
            reason=args.reason or "",
        )
        print(f"Consensus revision recorded: {rev['id']}")
        print(json.dumps(rev, ensure_ascii=False, indent=2, default=str))

    elif action == "resolve-gap":
        gap = tracker.resolve_gap(
            gap_id=args.gap,
            outcome=args.outcome,
            actual_value=args.actual,
            status=args.status or "resolved",
            notes=args.notes or "",
        )
        print(f"Expectation gap resolved: {gap['id']}")
        print(json.dumps(gap, ensure_ascii=False, indent=2, default=str))

    else:
        print(f"Unknown action: {action}")
        print("Available: snapshot, brief, add-snapshot, add-gap, revise, resolve-gap")


def cmd_materials(args):
    from src.analysis.material_tracker import MaterialTracker

    tracker = MaterialTracker(args.workspace)
    action = args.action

    if action == "snapshot":
        print(json.dumps(tracker.snapshot(), ensure_ascii=False, indent=2, default=str))

    elif action == "brief":
        print(tracker.generate_research_brief(focus=args.focus or "all"))

    elif action == "index":
        result = tracker.index_workspace_files()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    elif action == "add-doc":
        doc = tracker.add_document(
            filename=args.file,
            doc_type=args.doc_type or "other",
            title=args.title or "",
            issuer=args.issuer or "",
            publish_date=args.publish_date or "",
            period=args.period or "",
            source_path=args.source_path or args.file,
            pages=int(args.pages) if args.pages else None,
            language=args.language or "",
            notes=args.notes or "",
            source_url=getattr(args, "url", "") or "",
            source_kind=getattr(args, "source_kind", "") or "",
            is_complete_report=True if getattr(args, "complete_report", False) is True else None,
        )
        print(f"Document recorded: {doc['id']}")
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))

    elif action == "add-extract":
        tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
        ext = tracker.record_extraction(
            document_ref=args.document,
            extraction_type=args.extract_type or "other",
            topic=args.topic,
            value=args.value,
            evidence=args.evidence,
            page=args.page,
            confidence=args.confidence or "medium",
            impact=args.impact or "neutral",
            tags=tags,
            source_quote=args.quote or "",
            notes=args.notes or "",
        )
        print(f"Extraction recorded: {ext['id']}")
        print(json.dumps(ext, ensure_ascii=False, indent=2, default=str))

    elif action == "read-attempt":
        doc = tracker.record_read_attempt(
            document_ref=args.document,
            status=args.status,
            method=getattr(args, "method", "pdf_text_extract") or "pdf_text_extract",
            error=getattr(args, "error", "") or "",
            max_attempts=int(getattr(args, "max_attempts", 2) or 2),
            notes=args.notes or "",
        )
        print(f"Read attempt recorded: {doc['id']}")
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))

    elif action == "web-fallback":
        doc = tracker.record_web_fallback(
            document_ref=args.document,
            url=getattr(args, "url", ""),
            source_kind=getattr(args, "source_kind", "official_complete_report") or "official_complete_report",
            is_complete_report=bool(getattr(args, "complete_report", False)),
            notes=args.notes or "",
        )
        print(f"Web fallback recorded: {doc['id']}")
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))

    else:
        print(f"Unknown action: {action}")
        print("Available: snapshot, brief, index, add-doc, add-extract, read-attempt, web-fallback")


def cmd_knowledge(args):
    from src.analysis.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph()
    action = args.action

    if action == "stats":
        stats = kg.cross_workspace_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))

    elif action == "similar":
        results = kg.find_similar(
            industry=args.industry or "",
            themes=args.themes.split(",") if args.themes else [],
        )
        for r in results[:10]:
            print(f"  {r['ticker']} (similarity: {r['similarity']:.0%}) — {r['record'].get('industry', '')}")

    elif action == "brief":
        brief = kg.generate_research_brief(
            ticker=args.ticker or "",
            industry=args.industry or "",
            themes=args.themes.split(",") if args.themes else [],
        )
        print(brief)

    elif action == "record-outcome":
        kg.record_outcome(
            ticker=args.ticker,
            outcome=args.outcome,
            return_pct=float(args.return_pct) if args.return_pct else None,
            hold_days=int(args.hold_days) if args.hold_days else None,
            notes=args.notes or "",
        )
        print(f"Outcome recorded for {args.ticker}")

    elif action == "lesson":
        kg.add_lesson(
            lesson=args.lesson,
            context=args.context or "",
            tickers=args.tickers.split(",") if args.tickers else [],
        )
        print("Lesson recorded")

    else:
        print(f"Unknown action: {action}")
        print("Available: stats, similar, brief, record-outcome, lesson")


def cmd_report(args):
    from src.report.generator import generate_report_html, generate_summary_md

    ws_path = _resolve_workspace(args.workspace)

    if not ws_path.exists():
        logger.error("Workspace not found: %s", ws_path)
        sys.exit(1)

    # Extract clean ticker name: strip "workspaces/" prefix and any path separators
    raw_ticker = args.ticker or args.workspace
    ticker = raw_ticker.replace("workspaces/", "").replace("workspaces\\", "")
    ticker = ticker.rstrip("/\\")
    company_name = args.name or ""

    lang = getattr(args, 'lang', 'zh') or 'zh'

    # ── Generate auto-summary MD ──
    if not getattr(args, 'no_summary', False):
        summary_path = generate_summary_md(
            workspace_dir=str(ws_path),
            ticker=ticker,
            company_name=company_name,
            lang=lang,
        )
        print(f"Summary generated: {summary_path}")

    # ── Generate full HTML ──
    output = generate_report_html(
        workspace_dir=str(ws_path),
        ticker=ticker,
        company_name=company_name,
    )
    print(f"HTML report generated: {output}")


def cmd_step4_template(args):
    """Print a minimal valid Step 4 structured assumptions JSON template."""
    import json

    from src.analysis.step4_schema import generate_step4_template
    template = generate_step4_template()
    print(json.dumps(template, ensure_ascii=False, indent=2))


def cmd_sync_reviewed(args):
    """Auto-generate _reviewed_assumptions.json skeleton from step4_structured_assumptions.json.

    Extracts p50 and evidence from each assumption_matrix variable so the analyst
    only needs to fill in confidence / risk / verdict.
    """
    import json

    ws_path = _resolve_workspace(args.workspace)
    structured_path = ws_path / "step4_structured_assumptions.json"
    reviewed_path = ws_path / "_reviewed_assumptions.json"

    if not structured_path.exists():
        print(f"Error: {structured_path} not found")
        sys.exit(1)

    with open(structured_path, encoding="utf-8") as f:
        structured = json.load(f)

    # Load existing reviewed file to preserve hand-written entries
    existing: dict = {}
    if reviewed_path.exists():
        with open(reviewed_path, encoding="utf-8") as f:
            existing = json.load(f)

    # Normalize assumption_matrix to list of rows
    raw_matrix = structured.get("assumption_matrix", [])
    if isinstance(raw_matrix, dict):
        rows = []
        for _period, variables in raw_matrix.items():
            if not isinstance(variables, dict):
                continue
            for var_name, pct_dict in variables.items():
                if not isinstance(pct_dict, dict):
                    continue
                row = dict(pct_dict)
                row["variable"] = var_name
                rows.append(row)
    else:
        rows = raw_matrix

    existing_assumptions = existing.get("assumptions", {})
    added = []

    for row in rows:
        label = row.get("variable", "")
        if not label:
            continue
        if label in existing_assumptions:
            continue  # preserve hand-written entry

        p50 = row.get("p50")
        evidence_ids = row.get("evidence_ids", [])
        evidence_str = ", ".join(str(e) for e in evidence_ids) if isinstance(evidence_ids, list) else str(evidence_ids)

        existing_assumptions[label] = {
            "p50": p50,
            "confidence": "medium",
            "evidence": evidence_str,
            "risk": "TODO: fill in key risk",
            "verdict": "pending",
        }
        added.append(label)

    output = {
        "reviewed_at": existing.get("reviewed_at", ""),
        "reviewer": existing.get("reviewer", "analyst"),
        "status": "pending_user_review",
        "valuation_mode": existing.get("valuation_mode", ""),
        "assumptions": existing_assumptions,
    }

    with open(reviewed_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Synced {len(added)} new variables into {reviewed_path.name}")
    if added:
        print(f"Added: {', '.join(added)}")
    existing_count = len(existing_assumptions) - len(added)
    if existing_count > 0:
        print(f"Preserved {existing_count} existing entries")


def cmd_validate_step4(args):
    """Validate Step 4 assumptions before model build or Monte Carlo."""
    from src.analysis.step4_validate import validate_step4_with_guard

    ws_path = _resolve_workspace(args.workspace)

    step4_path = _resolve_step4_validation_path(ws_path)
    result = validate_step4_with_guard(
        step4_path,
        max_attempts=int(args.max_attempts or 2),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("passed"):
        sys.exit(1)


def cmd_validate_materials(args):
    """Validate structured source-material coverage."""
    from src.analysis.material_tracker import MaterialTracker

    required = [t.strip() for t in args.required.split(",")] if args.required else None
    tracker = MaterialTracker(args.workspace)
    result = tracker.validate_coverage(
        required_extraction_types=required,
        require_annual_mda=not args.no_annual_mda,
        require_broker_assumptions=args.require_broker,
    )

    # --no-pdf-tolerance: when set, tolerate missing PDF report requirement
    # as long as extraction types are covered (pure API/MCP research mode)
    if args.no_pdf_tolerance and not result.get("passed"):
        blockers = result.get("fix_required", [])
        pdf_blockers = [b for b in blockers if "annual/interim report" in b.lower() or "md&a" in b.lower()]
        non_pdf_blockers = [b for b in blockers if b not in pdf_blockers]
        if not non_pdf_blockers:
            result["passed"] = True
            result["fix_required"] = []
            result["warnings"] = result.get("warnings", []) + [
                "PDF tolerance mode: annual/interim report requirement waived "
                "(extraction types covered by API/MCP data)"
            ]
            result["summary"] = "Material coverage sufficient (no-PDF tolerance)"

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("passed"):
        sys.exit(1)


def cmd_model(args):
    """Generate formula-linked forecast model artifacts."""
    from src.analysis.financial_model import generate_financial_model_artifacts
    from src.analysis.step4_validate import validate_step4_with_guard

    ws_path = _resolve_workspace(args.workspace)

    validation = validate_step4_with_guard(
        _resolve_step4_validation_path(ws_path),
        max_attempts=int(args.max_attempts or 2),
    )
    if not validation.get("passed"):
        print(json.dumps({
            "error": "Step 4 assumption validation failed. Forecast model generation blocked.",
            "validation": validation,
        }, ensure_ascii=False, indent=2, default=str))
        sys.exit(1)

    artifacts = generate_financial_model_artifacts(args.workspace, ticker=args.ticker or args.workspace)
    print(json.dumps({
        "json_path": str(artifacts["json_path"]),
        "html_path": str(artifacts["html_path"]),
    }, ensure_ascii=False, indent=2))


def cmd_excel_model(args):
    """Generate professional three-statement Excel model from forecast_model.json.

    Automatically routes to bank Excel model if forecast_model.json has
    model_type == "bank_nim_driven". Standard companies use excel_model.py.
    """
    ws_path = _resolve_workspace(args.workspace)

    # Detect bank model via forecast_model.json → model_type
    forecast_path = ws_path / "forecast_model.json"
    if forecast_path.exists():
        try:
            forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
            if forecast.get("model_type") == "bank_nim_driven":
                from src.analysis.bank_excel_model import build_bank_excel
                ticker = args.ticker or forecast.get("ticker", "").replace(".SH", "").replace(".SZ", "")
                output_path = build_bank_excel(ws_path, ticker)
                print(json.dumps({
                    "excel_path": str(output_path),
                    "model_type": "bank_nim_driven",
                }, ensure_ascii=False, indent=2))
                return
        except (json.JSONDecodeError, KeyError):
            pass  # fall through to standard model

    from src.analysis.excel_model import generate_excel_model
    output_path = generate_excel_model(ws_path, ticker=args.ticker or "")
    print(json.dumps({
        "excel_path": str(output_path),
    }, ensure_ascii=False, indent=2))


def cmd_verify_model(args):
    """Run post-model validation checks on an existing forecast_model.json."""
    from src.analysis.financial_model import validate_financial_model

    ws_path = _resolve_workspace(args.workspace)
    model_path = ws_path / "forecast_model.json"
    if not model_path.exists():
        print(json.dumps({"error": f"forecast_model.json not found in {ws_path}"}))
        sys.exit(1)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    results = validate_financial_model(model, workspace=ws_path)
    fails = [v for v in results if v["status"] == "FAIL"]
    warns = [v for v in results if v["status"] == "WARN"]
    ok_count = sum(1 for v in results if v["status"] == "OK")
    output = {
        "total": len(results),
        "ok": ok_count,
        "warn": len(warns),
        "fail": len(fails),
        "passed": len(fails) == 0,
        "results": results if args.verbose else [v for v in results if v["status"] != "OK"],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    if fails:
        sys.exit(1)


def cmd_workflow(args):
    """Manage sequential research workflow state."""
    from src.analysis.research_workflow import ResearchWorkflow

    wf = ResearchWorkflow(args.workspace)
    action = args.action

    if action == "status":
        result = wf.snapshot()
    elif action == "sync":
        result = wf.sync_from_files()
    elif action == "start":
        if args.step is None:
            result = {"error": "--step is required for workflow start"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)
        result = wf.start_step(args.step, force=args.force)
    elif action == "complete":
        if args.step is None:
            result = {"error": "--step is required for workflow complete"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)
        result = wf.complete_step(
            args.step,
            artifact=args.artifact,
            validation_summary=args.summary or "",
            force=args.force,
        )
    elif action == "block":
        if args.step is None:
            result = {"error": "--step is required for workflow block"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)
        result = wf.block_step(args.step, reason=args.reason or "")
    elif action == "can-start":
        if args.step is None:
            result = {"error": "--step is required for workflow can-start"}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(1)
        result = wf.can_start(args.step)
    else:
        result = {"error": f"Unknown workflow action: {action}"}

    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    should_exit = (
        result.get("allowed") is False
        or result.get("started") is False
        or result.get("completed") is False
        or bool(result.get("error"))
    )
    if should_exit:
        sys.exit(1)


# ── Helper functions ──────────────────────────────────────────────


def _resolve_workspace(workspace: str) -> Path:
    """Resolve a workspace name or path to an absolute Path.

    Handles both canonical names ("600584.SH") and prefixed paths
    ("workspaces/600584.SH"). Absolute paths are preserved.
    """
    from src.analysis._base import resolve_workspace_path
    return resolve_workspace_path(workspace)


def _resolve_step4_validation_path(workspace: Path) -> Path:
    """Return the canonical Step 4 artifact for assumption validation."""
    from src.contracts import get_step_contract

    return workspace / get_step_contract("4").primary_artifact


def _auto_calculate_valuation(results, output_dir):
    """After fetching raw data, auto-calculate all valuation ratios locally.

    Saves calculated_valuation.json (source: "calculated") and
    valuation_raw_inputs.json to the workspace.
    """
    from src.data.base import FetchResult

    val_result = results.get("valuation", FetchResult())
    fin_result = results.get("financials", FetchResult())

    if not val_result.success or not fin_result.success:
        print("\nSkipping auto-calculation: valuation or financials data missing")
        return

    try:
        from src.analysis.financial import (
            calc_all_valuation_ratios,
            calc_ev_ebitda,
            calc_pb,
            calc_pe,
            calc_ps,
        )

        val_data = val_result.data
        fin_data = fin_result.data

        if not isinstance(val_data, dict) or not isinstance(fin_data, dict):
            return

        def _float_or_none(value):
            try:
                if value is None or value == "":
                    return None
                return float(value)
            except (TypeError, ValueError):
                return None

        def _valid_metric(metric, value_key):
            return (
                isinstance(metric, dict)
                and metric.get("valid") is True
                and metric.get(value_key) is not None
            )

        price = val_data.get("current_price")
        shares = val_data.get("shares_outstanding")
        eps_fwd = val_data.get("eps_forward")

        # Resolve income DataFrame (yfinance uses "financials", akshare uses "income")
        income = fin_data.get("financials")
        if income is None:
            income = fin_data.get("income")
        balance = fin_data.get("balance_sheet")
        cashflow = fin_data.get("cashflow")

        if price is None or shares is None or income is None or balance is None:
            print("\nSkipping auto-calculation: missing price/shares/income/balance")
            return

        calculated = calc_all_valuation_ratios(
            price=price,
            shares=shares,
            income=income,
            balance=balance,
            cashflow=cashflow,
            eps_estimate=eps_fwd,
            forward_label="T+1",
        )

        fallback_warnings = calculated.setdefault("warnings", [])
        price_f = _float_or_none(price)
        shares_f = _float_or_none(shares)
        if price_f is None and _float_or_none(val_data.get("market_cap")) and shares_f:
            price_f = _float_or_none(val_data.get("market_cap")) / shares_f

        eps_ttm = _float_or_none(val_data.get("eps_ttm"))
        if price_f is not None and eps_ttm is not None and not _valid_metric(calculated.get("pe_trailing"), "pe"):
            pe_res = calc_pe(
                price_f,
                eps_ttm,
                label=str(val_data.get("eps_ttm_basis") or "TTM raw input"),
            )
            pe_res["input_source"] = "valuation_raw_inputs.eps_ttm"
            calculated["pe_trailing"] = pe_res
            if pe_res.get("valid"):
                fallback_warnings.append("PE trailing calculated from raw eps_ttm input fallback.")

        bvps = _float_or_none(val_data.get("book_value_per_share"))
        minority_per_share = _float_or_none(val_data.get("minority_interest_per_share"))
        if price_f is not None and bvps is not None and not _valid_metric(calculated.get("pb"), "pb"):
            # For banks/financials, BPS may include minority interest — deduct if available
            if minority_per_share and minority_per_share > 0:
                bvps_attributable = bvps - minority_per_share
                fallback_warnings.append(
                    f"BPS adjusted: {bvps:.4f} - minority {minority_per_share:.4f} = {bvps_attributable:.4f}"
                )
                bvps = bvps_attributable
            pb_res = calc_pb(price_f, bvps, label="MRQ raw input")
            pb_res["input_source"] = "valuation_raw_inputs.book_value_per_share"
            if minority_per_share and minority_per_share > 0:
                pb_res["equity_basis"] = "attributable_equity_excluding_minority"
            calculated["pb"] = pb_res
            if pb_res.get("valid"):
                fallback_warnings.append("PB calculated from raw book_value_per_share input fallback.")

        revenue_ttm = _float_or_none(val_data.get("revenue_ttm"))
        if (
            price_f is not None and shares_f and revenue_ttm is not None
            and not _valid_metric(calculated.get("ps"), "ps")
        ):
            ps_res = calc_ps(price_f, revenue_ttm / shares_f, label="TTM raw input")
            ps_res["total_revenue"] = revenue_ttm
            ps_res["shares"] = shares_f
            ps_res["input_source"] = "valuation_raw_inputs.revenue_ttm"
            calculated["ps"] = ps_res
            if ps_res.get("valid"):
                fallback_warnings.append("PS calculated from raw revenue_ttm input fallback.")

        market_cap = _float_or_none(val_data.get("market_cap"))
        if market_cap is None and price_f is not None and shares_f:
            market_cap = price_f * shares_f
        ebitda = _float_or_none(val_data.get("ebitda"))
        if market_cap is not None and ebitda is not None and not _valid_metric(calculated.get("ev_ebitda"), "ev_ebitda"):
            total_debt = _float_or_none(val_data.get("total_debt"))
            total_cash = _float_or_none(val_data.get("total_cash"))
            if total_debt is None:
                total_debt = 0.0
                fallback_warnings.append("EV/EBITDA raw fallback: total_debt missing; using 0, not total liabilities.")
            if total_cash is None:
                total_cash = 0.0
                fallback_warnings.append("EV/EBITDA raw fallback: total_cash missing; using 0 cash.")
            ev_res = calc_ev_ebitda(
                market_cap,
                total_debt,
                total_cash,
                ebitda,
                label="TTM raw input",
            )
            ev_res["input_source"] = "valuation_raw_inputs.market_cap/debt/cash/ebitda"
            calculated["ev_ebitda"] = ev_res
            if ev_res.get("valid"):
                fallback_warnings.append("EV/EBITDA calculated from raw EV inputs fallback.")

        # Save calculated valuation
        calc_path = output_dir / "calculated_valuation.json"
        calc_path.write_text(
            json.dumps(calculated, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\nSaved calculated valuation: {calc_path}")

        # Save raw valuation inputs (exclude DataFrames and reference notes)
        raw_keys = [
            "current_price", "shares_outstanding", "eps_ttm", "eps_forward",
            "book_value_per_share", "revenue_ttm", "market_cap", "enterprise_value",
            "total_debt", "total_cash", "ebitda", "target_mean_price",
            "recommendation", "dividend_yield", "beta",
            "eps_ttm_basis", "financial_currency", "price_currency", "price_date",
            "net_income_ttm",
        ]
        raw_inputs = {k: val_data[k] for k in raw_keys if k in val_data and val_data[k] is not None}
        raw_path = output_dir / "valuation_raw_inputs.json"
        raw_path.write_text(
            json.dumps(raw_inputs, default=str, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Saved raw valuation inputs: {raw_path}")

    except Exception as e:
        logger.warning("Auto-calculation failed: %s", e)


def cmd_verify_news(args):
    """验证 WebSearch 结果的发布日期，防止过期新闻误引。"""
    from src.utils.web_date_verifier import (
        print_verification_report,
        verify_evidence_list,
        verify_url,
    )

    if args.url:
        from dataclasses import asdict
        result = verify_url(args.url, max_age_days=args.max_age, timeout=args.timeout)
        if args.json:
            print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        else:
            print_verification_report([asdict(result)])
    elif args.input:
        with open(args.input, encoding="utf-8") as f:
            evidence = json.load(f)
        results = verify_evidence_list(evidence, max_age_days=args.max_age, timeout=args.timeout)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_verification_report(results)
    else:
        # Read from stdin
        import sys
        evidence = json.load(sys.stdin)
        results = verify_evidence_list(evidence, max_age_days=args.max_age, timeout=args.timeout)
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_verification_report(results)


def cmd_fetch_peers(args):
    """Fetch financial data for peer companies for comparison."""
    fetcher, normalized, market = get_fetcher(args.target)
    output_dir = Path(args.output) if args.output else WORKSPACES_DIR / normalized.replace(".", "_")
    peers_dir = output_dir / "peers"
    peers_dir.mkdir(parents=True, exist_ok=True)

    peer_tickers = [t.strip() for t in args.peers.split(",")]
    summary = {}
    for peer_ticker in peer_tickers:
        print(f"\nFetching peer: {peer_ticker}")
        try:
            peer_fetcher, peer_norm, peer_market = get_fetcher(peer_ticker)
            peer_results = peer_fetcher.fetch_all(peer_norm, period="3y")
            peer_dir = peers_dir / peer_norm.replace(".", "_")
            peer_dir.mkdir(parents=True, exist_ok=True)

            for name, result in peer_results.items():
                if result.data is not None:
                    if isinstance(result.data, dict):
                        for key, val in result.data.items():
                            if hasattr(val, "to_csv"):
                                val.to_csv(peer_dir / f"{name}_{key}.csv")
                            else:
                                (peer_dir / f"{name}_{key}.json").write_text(
                                    json.dumps(val, default=str, indent=2),
                                    encoding="utf-8",
                                )
                    elif hasattr(result.data, "to_csv"):
                        result.data.to_csv(peer_dir / f"{name}.csv")

            # Auto-calculate peer valuation
            _auto_calculate_valuation(peer_results, peer_dir)
            summary[peer_ticker] = {"success": True, "dir": str(peer_dir)}
            print(f"  Saved to: {peer_dir}")
        except Exception as e:
            summary[peer_ticker] = {"success": False, "error": str(e)}
            print(f"  Failed: {e}")

    print("\nPeer data summary:")
    print(json.dumps(summary, indent=2))


def cmd_comps(args):
    """Generate comps xlsx + summary md from step2_comps_data.json."""
    from src.analysis.comps import run_comps

    ws_path = _resolve_workspace(args.workspace)
    if not (ws_path / "step2_comps_data.json").exists():
        print(f"Error: step2_comps_data.json not found in {ws_path}")
        print("Create it first with peer financial data (see prompts/02_competitive_moat.md).")
        return 1

    try:
        result = run_comps(ws_path)
        mode = result.get("mode", "PE")
        is_bank = mode == "bank_PB"
        metric_label = "PB" if is_bank else "PE"
        metric_key = "pb" if is_bank else "pe"
        print(f"✅ Comps generated successfully ({'🏦 Bank ' if is_bank else ''}{metric_label} mode):")
        print(f"   XLSX:    {result['xlsx']}")
        print(f"   Summary: {result['summary_md']}")
        print(f"   Benchmark: {result['benchmark']}")
        target_val = result.get(f"target_{metric_key}")
        median_val = result.get(f"peer_median_{metric_key}")
        if target_val is not None:
            print(f"   Target {metric_label}: {target_val}x | Peer Median: {median_val}x")
            if result["premium_pct"] is not None:
                direction = "premium" if result["premium_pct"] > 0 else "discount"
                print(f"   Target {direction}: {abs(result['premium_pct']):.1f}% vs peer median")
        return 0
    except Exception as e:
        print(f"Error generating comps: {e}")
        return 1


def cmd_mc(args):
    """Run Monte Carlo simulation from reviewed assumptions."""
    import numpy as np

    from src.analysis.monte_carlo import (
        calc_rrr,
        fit_distribution_from_percentiles,
        run_monte_carlo_cumulative,
    )
    from src.storage import AtomicJSON

    ws_path = _resolve_workspace(args.workspace)
    store = AtomicJSON(ws_path)

    # ── Load reviewed assumptions ──
    reviewed = store.load("_reviewed_assumptions.json")
    if not reviewed:
        print(f"Error: _reviewed_assumptions.json not found in {ws_path}")
        print("Run Step 4 and lock assumptions first.")
        return 1

    matrix = reviewed.get("assumption_matrix", [])
    if not matrix:
        print("Error: assumption_matrix is empty in _reviewed_assumptions.json")
        return 1

    # Default dist_type per variable (can be overridden by schema field)
    default_dist_types = reviewed.get("dist_types", {})
    lognormal_keywords = {"pe", "pb", "ps", "ev/", "multiple", "market_cap", "mv"}

    def infer_dist_type(var_name: str) -> str:
        """Infer distribution type from variable name or explicit schema."""
        if var_name in default_dist_types:
            return default_dist_types[var_name]
        name_lower = var_name.lower()
        if any(kw in name_lower for kw in lognormal_keywords):
            return "lognormal"
        return "normal"

    # ── Group assumptions by year ──
    yearly_rows: dict[str, list[dict]] = {}
    for row in matrix:
        year = row.get("year")
        if year:
            yearly_rows.setdefault(year, []).append(row)

    years = sorted(yearly_rows.keys())
    if not years:
        print("Error: no years found in assumption_matrix")
        return 1

    print(f"Years: {years}")
    print(f"Variables per year: {len(yearly_rows[years[0]])}")

    # ── PE coverage check ──
    pe_var_names = {r["variable"] for r in matrix
                    if " pe" in f" {r['variable'].lower()}"}
    for yr in years:
        yr_vars = {r["variable"] for r in yearly_rows[yr]}
        missing_pe = pe_var_names - yr_vars
        if missing_pe:
            print(f"⚠️  {yr}: PE variable(s) {missing_pe} missing — "
                  f"target price will be unreliable for this year")

    # ── Build distributions per year ──
    yearly_dists: dict[str, dict] = {}
    for yr in years:
        dists = {}
        for row in yearly_rows[yr]:
            var = row["variable"]
            pcts = {k: v for k, v in row.items() if k.startswith("p") and k[1:].isdigit()}
            # Convert percentile keys to int levels
            pct_dict = {}
            for k, v in pcts.items():
                level = int(k[1:])
                pct_dict[level] = v
            if not pct_dict:
                continue
            dt = infer_dist_type(var)
            dists[var] = fit_distribution_from_percentiles(pct_dict, dist_type=dt)
        yearly_dists[yr] = dists

    # ── Validate: all years must have same variables ──
    var_sets = [set(d.keys()) for d in yearly_dists.values()]
    if len(set(frozenset(s) for s in var_sets)) > 1:
        print("⚠️  Variable sets differ across years:")
        for yr, vs in zip(years, var_sets):
            print(f"   {yr}: {sorted(vs)}")

    # ── Load model parameters from reviewed assumptions ──
    reviewed.get("eps_bridge_p50", {})
    shares_m = reviewed.get("shares_m")
    fx = reviewed.get("fx_rmb_to_hkd", 1.0)
    current_price = reviewed.get("current_price_hkd", 0.0)

    if not shares_m:
        print("Error: shares_m not in _reviewed_assumptions.json")
        return 1
    if not current_price:
        print("Error: current_price_hkd not in _reviewed_assumptions.json")
        return 1

    # ── Build base_state from forecast_model.json segments ──
    forecast_model = store.load("forecast_model.json")
    base_state = {"shares_m": float(shares_m), "fx_rmb_to_hkd": float(fx)}

    # Collect unique revenue growth variable names
    rev_growth_vars = set()
    for row in matrix:
        var = row["variable"]
        if "growth" in var.lower() and "revenue" in var.lower():
            rev_growth_vars.add(var)

    # Build segment slug → base_revenue from forecast_model.json
    seg_slug_to_base: dict[str, float] = {}
    if forecast_model and "segments" in forecast_model:
        for seg in forecast_model["segments"]:
            seg_name = seg["name"].lower().replace(" ", "_")
            base_rev = seg.get("base_revenue", 0)
            key = f"base_revenue_{seg_name}"
            base_state[key] = float(base_rev)
            seg_slug_to_base[seg_name] = float(base_rev)
            print(f"   Segment: {seg['name']} → {key} = {base_rev:.0f} RMB M")

    # Build var_to_seg_key with fuzzy matching
    var_to_seg_key: dict[str, str] = {}
    for var in rev_growth_vars:
        var_slug = var.lower().replace("revenue growth", "").strip().replace(" ", "_")
        candidate_key = f"base_revenue_{var_slug}"

        if candidate_key in base_state:
            # Exact match (e.g. "China Domestic Revenue Growth" → "china_domestic")
            var_to_seg_key[var] = candidate_key
        else:
            # Fuzzy: check if any segment slug is contained in the var slug or vice versa
            matched = False
            for seg_slug in seg_slug_to_base:
                if seg_slug in var_slug or var_slug in seg_slug:
                    match_key = f"base_revenue_{seg_slug}"
                    var_to_seg_key[var] = match_key
                    matched = True
                    break
            if not matched and var_slug == "total":
                # "Total Revenue Growth" → aggregate all segment bases
                total_base = sum(seg_slug_to_base.values())
                base_state["base_revenue_total"] = total_base
                var_to_seg_key[var] = "base_revenue_total"
                print(f"   Total base revenue (sum of segments): {total_base:.0f} RMB M")
                matched = True
            if not matched:
                print(f"⚠️  {var}: no matching segment base revenue — will default to 0")

    # Fallback: no segments but has "Total Revenue Growth" → try total_base_revenue
    if not seg_slug_to_base and rev_growth_vars:
        total_base = forecast_model.get("total_base_revenue", 0) if forecast_model else 0
        if not total_base and forecast_model:
            # Try periods[0].revenue as base
            periods = forecast_model.get("periods", [])
            if periods and "revenue" in periods[0]:
                total_base = periods[0]["revenue"]
        if total_base:
            base_state["base_revenue_total"] = float(total_base)
            for var in rev_growth_vars:
                var_slug = var.lower().replace("revenue growth", "").strip().replace(" ", "_")
                var_to_seg_key[var] = f"base_revenue_{var_slug}"
                if f"base_revenue_{var_slug}" not in base_state:
                    base_state[f"base_revenue_{var_slug}"] = float(total_base)
            print(f"   Total base revenue (fallback): {total_base:.0f} RMB M")

    print(f"   Var→seg mapping: {var_to_seg_key}")

    def default_model_fn(inputs, prev_state):
        """Default P&L model: Revenue → GP → EBIT → NI → EPS → TP.

        Handles three valuation approaches (first match wins):
        1. PE × EPS (standard)
        2. PB × BPS (for banks / financials)
        3. PS × Revenue/shares (for pre-profit companies)

        Revenue segments chain cumulatively: each year's revenue becomes
        next year's base. Growth-rate variables map to segments via
        var_to_seg_key.
        """
        prev = prev_state if prev_state is not None else base_state

        shares = prev.get("shares_m", base_state["shares_m"])
        fx_rate = prev.get("fx_rmb_to_hkd", base_state["fx_rmb_to_hkd"])
        n = len(next(iter(inputs.values())))

        # Build revenue from growth-rate variables
        total_revenue = np.zeros(n)
        revenue_by_seg: dict[str, np.ndarray] = {}
        for var_name, values in inputs.items():
            seg_key = var_to_seg_key.get(var_name)
            if seg_key is None:
                continue  # not a revenue growth variable

            # Get base from prev_state (chained) or initial base_state
            seg_base = prev.get(seg_key, base_state.get(seg_key, 0))
            if isinstance(seg_base, (int, float)):
                seg_base = np.full(n, float(seg_base))

            seg_rev = seg_base * (1 + values)
            revenue_by_seg[var_name] = seg_rev
            total_revenue += seg_rev

        # If no revenue growth vars at all, try using prev_state's total revenue
        if not revenue_by_seg and "total_revenue_rmb_m" in prev:
            total_revenue = prev["total_revenue_rmb_m"]
            if isinstance(total_revenue, (int, float)):
                total_revenue = np.full(n, float(total_revenue))

        # Gross margin
        gm_key = next((k for k in inputs if "gross margin" in k.lower()), None)
        gm = inputs[gm_key] if gm_key else np.full(n, 0.50)
        gross_profit = total_revenue * gm

        # OpEx
        opex_key = next((k for k in inputs if "opex" in k.lower()), None)
        opex_ratio = inputs[opex_key] if opex_key else np.full(n, 0.30)
        ebit = gross_profit - total_revenue * opex_ratio

        # Tax
        tax_key = next((k for k in inputs if "tax" in k.lower()), None)
        tax_rate = inputs[tax_key] if tax_key else np.full(n, 0.25)
        net_income = ebit * (1 - tax_rate)

        # EPS = NI_RMB_M / shares_M (same unit → RMB per share)
        eps_rmb = net_income / shares

        # BPS = total equity / shares (for PB valuation)
        bps_rmb = prev.get("bps_rmb", 0)
        if isinstance(bps_rmb, (int, float)):
            bps_rmb = np.full(n, float(bps_rmb)) if bps_rmb else None
        elif isinstance(bps_rmb, np.ndarray):
            pass
        else:
            bps_rmb = None

        # Target price — try PE first, then PB, then PS
        # PE: match "PE" as a word, not substring of "opex"
        pe_key = next((k for k in inputs
                       if k.lower() in ("forward pe", "pe", "trailing pe")
                       or " pe" in f" {k.lower()}"), None)
        # PB: match "PB" as a word
        pb_key = next((k for k in inputs
                       if k.lower() in ("forward pb", "pb", "trailing pb")
                       or " pb" in f" {k.lower()}"), None)
        # PS: match "PS" as a word
        ps_key = next((k for k in inputs
                       if k.lower() in ("forward ps", "ps", "trailing ps")
                       or " ps" in f" {k.lower()}"), None)

        if pe_key:
            pe = inputs[pe_key]
            target_price_hkd = eps_rmb * pe * fx_rate
        elif pb_key and bps_rmb is not None:
            pb = inputs[pb_key]
            target_price_hkd = bps_rmb * pb * fx_rate
        elif ps_key:
            ps = inputs[ps_key]
            rev_per_share = total_revenue / shares
            target_price_hkd = rev_per_share * ps * fx_rate
        else:
            target_price_hkd = np.full(n, np.nan)

        outputs = {
            "target_price_hkd": target_price_hkd,
            "eps_rmb": eps_rmb,
            "revenue_rmb_m": total_revenue,
            "net_income_rmb_m": net_income,
        }
        # State for next year: updated revenue bases
        state = {
            "shares_m": shares if isinstance(shares, np.ndarray) else np.full(n, float(shares)),
            "fx_rmb_to_hkd": fx_rate if isinstance(fx_rate, np.ndarray) else np.full(n, float(fx_rate)),
            "total_revenue_rmb_m": total_revenue,
        }
        for var_name, seg_rev in revenue_by_seg.items():
            seg_key = var_to_seg_key[var_name]
            state[seg_key] = seg_rev

        return outputs, state

    # ── Build correlation matrix from reviewed assumptions ──
    corr_matrix = None
    corr_defs = reviewed.get("correlations_defined", [])
    var_order = reviewed.get("variable_order", [])

    if corr_defs and var_order:
        n_vars = len(var_order)
        corr_matrix = np.eye(n_vars)
        var_idx = {v: i for i, v in enumerate(var_order)}
        for v1, v2, rho in corr_defs:
            if v1 in var_idx and v2 in var_idx:
                i, j = var_idx[v1], var_idx[v2]
                corr_matrix[i, j] = rho
                corr_matrix[j, i] = rho

        # Validate
        try:
            np.linalg.cholesky(corr_matrix)
            print(f"   Correlation matrix: {n_vars}×{n_vars}, PD ✓")
        except np.linalg.LinAlgError:
            print("⚠️  Correlation matrix not positive-definite — falling back to independent")
            corr_matrix = None
    else:
        print("   No correlations_defined in reviewed assumptions — running independent")

    # ── Run simulation ──
    n_sims = int(args.sims) if args.sims is not None else MONTE_CARLO_SIMULATIONS
    seed = int(args.seed) if args.seed else None

    print(f"Running {n_sims} simulations per year (cumulative mode)...")

    results = run_monte_carlo_cumulative(
        yearly_dists,
        default_model_fn,
        base_state=base_state,
        correlation_matrix=corr_matrix,
        n_simulations=n_sims,
        copula_df=6,
        seed=seed,
    )

    # ── Compute percentiles and RRR ──
    output = {
        "ticker": reviewed.get("ticker", str(ws_path.name)),
        "current_price_hkd": current_price,
        "fx_rmb_to_hkd": fx,
        "n_simulations": n_sims,
        "copula_df": 6,
        "mode": "cumulative",
        "variable_order": var_order,
        "correlations_defined": corr_defs,
        "dist_types": {k: infer_dist_type(k) for k in (var_order or yearly_dists.get(years[0], {}).keys())},
        "per_year": {},
    }

    for yr in years:
        yr_result = results[yr]
        tp = yr_result["target_price_hkd"]
        eps = yr_result["eps_rmb"]
        rev = yr_result["revenue_rmb_m"]

        # Handle years without PE (NaN target prices)
        valid_tp = tp[~np.isnan(tp)]
        has_tp = len(valid_tp) > 0

        if has_tp:
            rrr_result = calc_rrr(valid_tp, current_price)
            yr_output_tp = {
                "p5": round(float(np.percentile(valid_tp, 5)), 2),
                "p10": round(float(np.percentile(valid_tp, 10)), 2),
                "p25": round(float(np.percentile(valid_tp, 25)), 2),
                "p50": round(float(np.percentile(valid_tp, 50)), 2),
                "p75": round(float(np.percentile(valid_tp, 75)), 2),
                "p90": round(float(np.percentile(valid_tp, 90)), 2),
                "p95": round(float(np.percentile(valid_tp, 95)), 2),
                "mean": round(float(np.mean(valid_tp)), 2),
                "std": round(float(np.std(valid_tp)), 2),
            }
            yr_rrr = {
                "rrr": round(rrr_result["rrr"], 4),
                "p_up": round(rrr_result["p_up"], 4),
                "p_down": round(rrr_result["p_down"], 4),
                "e_upside": round(rrr_result["e_upside"], 2),
                "e_downside": round(rrr_result["e_downside"], 2),
                "kelly_full": round(rrr_result["kelly_full"], 4),
                "kelly_half": round(rrr_result["kelly_half"], 4),
            }
        else:
            yr_output_tp = {"note": "No PE variable for this year — target price not computable"}
            yr_rrr = {
                "rrr": 0.0, "p_up": 0.0, "p_down": 0.0,
                "e_upside": 0.0, "e_downside": 0.0,
                "kelly_full": 0.0, "kelly_half": 0.0,
                "note": "No PE — RRR not applicable",
            }

        output["per_year"][yr] = {
            "target_price_hkd": yr_output_tp,
            "eps_rmb": {
                "p10": round(float(np.percentile(eps, 10)), 2),
                "p50": round(float(np.percentile(eps, 50)), 2),
                "p90": round(float(np.percentile(eps, 90)), 2),
                "mean": round(float(np.mean(eps)), 2),
            },
            "revenue_rmb_m": {
                "p10": round(float(np.percentile(rev, 10)), 1),
                "p50": round(float(np.percentile(rev, 50)), 1),
                "p90": round(float(np.percentile(rev, 90)), 1),
                "mean": round(float(np.mean(rev)), 1),
            },
            "rrr": yr_rrr,
            "seed": yr_result["seed"],
        }

    # ── Save results ──
    store.save("monte_carlo_results.json", output)
    results_path = ws_path / "monte_carlo_results.json"

    # ── Print summary ──
    print("\n✅ Monte Carlo simulation complete (cumulative mode)")
    print(f"   Output: {results_path}")
    print(f"   Simulations: {n_sims:,}")
    print()
    for yr in years:
        yr_data = output["per_year"][yr]
        tp_dict = yr_data["target_price_hkd"]
        rrr_val = yr_data["rrr"]["rrr"]
        kelly = yr_data["rrr"]["kelly_half"]
        if "p50" in tp_dict:
            print(f"   {yr}: P50 TP = HK${tp_dict['p50']:.0f} | RRR = {rrr_val:.2f} | Kelly½ = {kelly:.1%}")
        else:
            print(f"   {yr}: [No PE] P50 EPS = ¥{yr_data['eps_rmb']['p50']:.2f} | Revenue = {yr_data['revenue_rmb_m']['p50']:.0f}")

    return 0


def main():
    parser = argparse.ArgumentParser(description="InvestPilot — Investment Research Tools")
    subparsers = parser.add_subparsers(dest="command")

    p_detect = subparsers.add_parser("detect", help="Detect market from ticker")
    p_detect.add_argument("ticker")
    p_detect.add_argument("--create-workspace", action="store_true", help="Create workspace directory if it doesn't exist")
    p_detect.set_defaults(func=cmd_detect)

    p_fetch = subparsers.add_parser("fetch", help="Fetch stock data")
    p_fetch.add_argument("ticker")
    p_fetch.add_argument("--output", "-o", help="Output directory")
    p_fetch.add_argument("--period", default="5y", help="Price history period: 1y/2y/3y/5y/10y")
    p_fetch.set_defaults(func=cmd_fetch)

    p_analyze = subparsers.add_parser("analyze", help="Run analysis")
    p_analyze.add_argument("ticker")
    p_analyze.add_argument("--input", "-i", help="Input data directory")
    p_analyze.add_argument("--output", "-o", help="Output directory")
    p_analyze.set_defaults(func=cmd_analyze)

    # ── Peer fetching ─────────────────────────────────
    p_peers = subparsers.add_parser("fetch-peers", help="Fetch peer company data for comparison")
    p_peers.add_argument("--target", "-t", required=True, help="Target ticker")
    p_peers.add_argument("--peers", "-p", required=True, help="Comma-separated peer tickers")
    p_peers.add_argument("--output", "-o", help="Output directory (default: target workspace)")
    p_peers.set_defaults(func=cmd_fetch_peers)

    # ── Thesis commands ──────────────────────────────
    p_thesis = subparsers.add_parser("thesis", help="Manage investment thesis")
    p_thesis.add_argument("workspace", help="Workspace directory name")
    p_thesis.add_argument("action", choices=["snapshot", "brief", "create", "add-hypothesis", "confirm", "invalidate", "close"])
    p_thesis.add_argument("--thesis", "-t", help="Core thesis text (for create)")
    p_thesis.add_argument("--description", "-d", help="Hypothesis description")
    p_thesis.add_argument("--date", help="Catalyst/hypothesis date")
    p_thesis.add_argument("--impact", help="Impact: low/medium/high/extreme")
    p_thesis.add_argument("--result", help="Actual result")
    p_thesis.add_argument("--status", help="Close status: closed_won/closed_lost/expired")
    p_thesis.add_argument("--reason", help="Close reason")
    p_thesis.add_argument("--hypothesis", help="Hypothesis ID or description")
    p_thesis.add_argument("--hold-months", help="Hold period in months")
    p_thesis.set_defaults(func=cmd_thesis)

    # ── Catalyst commands ────────────────────────────
    p_catalyst = subparsers.add_parser("catalyst", help="Track catalysts and time decay")
    p_catalyst.add_argument("workspace", help="Workspace directory name")
    p_catalyst.add_argument("action", choices=["list", "add", "resolve", "decay", "kill-switch"])
    p_catalyst.add_argument("--event", "-e", help="Catalyst event name")
    p_catalyst.add_argument("--date", help="Expected date")
    p_catalyst.add_argument("--impact", help="Impact: low/medium/high/extreme")
    p_catalyst.add_argument("--direction", help="Direction: positive/negative")
    p_catalyst.add_argument("--catalyst", help="Catalyst ID or event name (for resolve)")
    p_catalyst.add_argument("--actual-date", help="Actual date")
    p_catalyst.add_argument("--outcome", help="Outcome description")
    p_catalyst.add_argument("--condition", help="Kill switch condition")
    p_catalyst.add_argument("--trigger", action="store_true", help="Trigger (vs add) kill switch")
    p_catalyst.add_argument("--evidence", help="Evidence for trigger")
    p_catalyst.add_argument("--severity", help="Kill switch severity: critical/major/warning")
    p_catalyst.set_defaults(func=cmd_catalyst)

    # ── Consensus commands ───────────────────────────
    p_consensus = subparsers.add_parser("consensus", help="Track market consensus and expectation gaps")
    p_consensus.add_argument("workspace", help="Workspace directory name")
    p_consensus.add_argument(
        "action",
        choices=["snapshot", "brief", "add-snapshot", "add-gap", "revise", "resolve-gap"],
    )
    p_consensus.add_argument("--source", help="Consensus source name")
    p_consensus.add_argument("--source-type", help="sell_side/web/implied/filing/other")
    p_consensus.add_argument("--as-of", help="As-of date YYYY-MM-DD")
    p_consensus.add_argument("--metrics-json", help="Consensus metrics as JSON")
    p_consensus.add_argument("--rating-json", help="Rating distribution as JSON")
    p_consensus.add_argument("--target-price", help="Consensus target price")
    p_consensus.add_argument("--confidence", help="low/medium/high")
    p_consensus.add_argument("--notes", help="Notes")
    p_consensus.add_argument("--metric", help="Metric name, e.g. eps")
    p_consensus.add_argument("--period", help="Metric period, e.g. 2026E")
    p_consensus.add_argument("--consensus", help="Consensus value for add-gap")
    p_consensus.add_argument("--our", help="Our value for add-gap")
    p_consensus.add_argument("--unit", help="Metric unit")
    p_consensus.add_argument("--consensus-source", help="Source for consensus value")
    p_consensus.add_argument("--our-source", help="Source for our value")
    p_consensus.add_argument("--catalyst", help="Catalyst that can verify the gap")
    p_consensus.add_argument("--lower-is-better", action="store_true", help="For metrics where lower value is favorable")
    p_consensus.add_argument("--old", help="Old consensus value for revise")
    p_consensus.add_argument("--new", help="New consensus value for revise")
    p_consensus.add_argument("--reason", help="Reason for revision")
    p_consensus.add_argument("--gap", help="Expectation gap ID for resolve-gap")
    p_consensus.add_argument("--outcome", help="Resolution outcome")
    p_consensus.add_argument("--actual", help="Actual value after resolution")
    p_consensus.add_argument("--status", help="Resolution status")
    p_consensus.set_defaults(func=cmd_consensus)

    # ── Source material commands ─────────────────────
    p_materials = subparsers.add_parser("materials", help="Track source material extraction from reports/PDFs")
    p_materials.add_argument("workspace", help="Workspace directory name")
    p_materials.add_argument("action", choices=[
        "snapshot",
        "brief",
        "index",
        "add-doc",
        "add-extract",
        "read-attempt",
        "web-fallback",
    ])
    p_materials.add_argument("--focus", help="Brief focus extraction type")
    p_materials.add_argument("--file", help="Source filename for add-doc")
    p_materials.add_argument("--doc-type", help="annual_report/broker_report/etc.")
    p_materials.add_argument("--title", help="Document title")
    p_materials.add_argument("--issuer", help="Document issuer")
    p_materials.add_argument("--publish-date", help="Publication date YYYY-MM-DD")
    p_materials.add_argument("--period", help="Reporting/forecast period")
    p_materials.add_argument("--source-path", help="Workspace-relative source path")
    p_materials.add_argument("--pages", help="Number of pages")
    p_materials.add_argument("--language", help="Document language")
    p_materials.add_argument("--document", help="Document ID or filename for add-extract")
    p_materials.add_argument("--extract-type", help="management_guidance/segment_forecast/etc.")
    p_materials.add_argument("--topic", help="Extraction topic")
    p_materials.add_argument("--value", help="Extracted value")
    p_materials.add_argument("--evidence", help="Evidence summary")
    p_materials.add_argument("--page", help="Page or section reference")
    p_materials.add_argument("--confidence", help="low/medium/high")
    p_materials.add_argument("--impact", help="positive/negative/neutral")
    p_materials.add_argument("--tags", help="Comma-separated tags")
    p_materials.add_argument("--quote", help="Short direct quote or excerpt")
    p_materials.add_argument("--notes", help="Notes")
    p_materials.add_argument("--status", help="Read attempt status: success/failed/encoding_error/etc.")
    p_materials.add_argument("--method", help="PDF read method used")
    p_materials.add_argument("--error", help="Read attempt error message")
    p_materials.add_argument("--max-attempts", help="Maximum failed PDF read attempts before fallback is required")
    p_materials.add_argument("--url", help="Official complete-report source URL")
    p_materials.add_argument("--source-kind", help="official_ir/exchange_filing/company_website/etc.; not news")
    p_materials.add_argument("--complete-report", action="store_true", help="Mark source as a complete annual/interim report")
    p_materials.set_defaults(func=cmd_materials)

    # ── Knowledge graph commands ─────────────────────
    p_knowledge = subparsers.add_parser("knowledge", help="Cross-workspace knowledge graph")
    p_knowledge.add_argument("action", choices=["stats", "similar", "brief", "record-outcome", "lesson"])
    p_knowledge.add_argument("--ticker", help="Ticker symbol")
    p_knowledge.add_argument("--industry", help="Industry name")
    p_knowledge.add_argument("--themes", help="Comma-separated themes")
    p_knowledge.add_argument("--outcome", help="Outcome description")
    p_knowledge.add_argument("--return-pct", help="Return percentage")
    p_knowledge.add_argument("--hold-days", help="Hold period in days")
    p_knowledge.add_argument("--notes", help="Notes")
    p_knowledge.add_argument("--lesson", help="Lesson text")
    p_knowledge.add_argument("--context", help="Lesson context")
    p_knowledge.add_argument("--tickers", help="Comma-separated related tickers")
    p_knowledge.set_defaults(func=cmd_knowledge)

    # ── Report commands ─────────────────────────────
    p_report = subparsers.add_parser("report", help="Generate HTML research report + auto-summary MD")
    p_report.add_argument("workspace", help="Workspace directory name (e.g. 09992.HK)")
    p_report.add_argument("--ticker", "-t", help="Ticker symbol (default: workspace name)")
    p_report.add_argument("--name", "-n", help="Company display name")
    p_report.add_argument("--lang", choices=["zh", "en"], default="zh", help="Report language (default: zh)")
    p_report.add_argument("--no-summary", action="store_true", help="Skip auto-summary MD generation")
    p_report.set_defaults(func=cmd_report)

    # ── Step validation commands ────────────────────
    p_step4_template = subparsers.add_parser(
        "step4-template",
        help="Print a minimal valid Step 4 structured assumptions JSON template",
    )
    p_step4_template.set_defaults(func=cmd_step4_template)

    p_sync_reviewed = subparsers.add_parser(
        "sync-reviewed",
        help="Sync _reviewed_assumptions.json from step4_structured_assumptions.json",
    )
    p_sync_reviewed.add_argument("workspace", help="Workspace directory name or path")
    p_sync_reviewed.set_defaults(func=cmd_sync_reviewed)

    p_validate_step4 = subparsers.add_parser(
        "validate-step4",
        help="Validate Step 4 structured assumptions before Monte Carlo",
    )
    p_validate_step4.add_argument("workspace", help="Workspace directory name or path")
    p_validate_step4.add_argument("--max-attempts", type=int, default=2, help="Failed validation attempts before writing step4_blockers.md")
    p_validate_step4.set_defaults(func=cmd_validate_step4)

    p_validate_materials = subparsers.add_parser(
        "validate-materials",
        help="Validate source material extraction coverage",
    )
    p_validate_materials.add_argument("workspace", help="Workspace directory name or path")
    p_validate_materials.add_argument("--required", help="Comma-separated required extraction types")
    p_validate_materials.add_argument("--no-annual-mda", action="store_true", help="Do not require annual/interim MD&A coverage")
    p_validate_materials.add_argument("--require-broker", action="store_true", help="Require broker_assumption if broker PDFs are indexed")
    p_validate_materials.add_argument("--no-pdf-tolerance", action="store_true", help="Tolerate missing PDF if extraction types covered (pure API research)")
    p_validate_materials.set_defaults(func=cmd_validate_materials)

    p_model = subparsers.add_parser("model", help="Generate forecast_model.json/html from Step 4 assumptions")
    p_model.add_argument("workspace", help="Workspace directory name or path")
    p_model.add_argument("--ticker", "-t", help="Ticker symbol")
    p_model.add_argument("--max-attempts", type=int, default=2, help="Failed validation attempts before writing step4_blockers.md")
    p_model.set_defaults(func=cmd_model)

    p_excel = subparsers.add_parser("excel-model", help="Generate professional three-statement Excel from forecast_model.json")
    p_excel.add_argument("workspace", help="Workspace directory name or path")
    p_excel.add_argument("--ticker", "-t", help="Ticker symbol")
    p_excel.set_defaults(func=cmd_excel_model)

    p_verify_model = subparsers.add_parser(
        "verify-model",
        help="Run post-model validation checks on forecast_model.json",
    )
    p_verify_model.add_argument("workspace", help="Workspace directory name or path")
    p_verify_model.add_argument("--verbose", "-v", action="store_true", help="Show all checks including OK")
    p_verify_model.set_defaults(func=cmd_verify_model)

    p_workflow = subparsers.add_parser("workflow", help="Guard sequential research workflow")
    p_workflow.add_argument("workspace", help="Workspace directory name or path")
    p_workflow.add_argument("action", choices=["status", "sync", "can-start", "start", "complete", "block"])
    p_workflow.add_argument("--step", help="Step number: 0-9")
    p_workflow.add_argument("--artifact", help="Step artifact filename for complete")
    p_workflow.add_argument("--summary", help="Validation or completion summary")
    p_workflow.add_argument("--reason", help="Block reason")
    p_workflow.add_argument("--force", action="store_true", help="Override workflow guard intentionally")
    p_workflow.set_defaults(func=cmd_workflow)

    # ── Web date verification ────────────────────────
    p_verify = subparsers.add_parser(
        "verify-news",
        help="验证 WebSearch 结果的实际发布日期，防止过期新闻误引",
    )
    p_verify.add_argument("input", nargs="?", help="JSON 文件路径（证据列表）")
    p_verify.add_argument("--url", help="单个 URL 验证")
    p_verify.add_argument("--max-age", type=int, default=90, help="最大允许天数 (default: 90)")
    p_verify.add_argument("--timeout", type=int, default=15, help="HTTP 超时秒数")
    p_verify.add_argument("--json", action="store_true", help="输出 JSON 格式")
    p_verify.set_defaults(func=cmd_verify_news)

    # ── Comps generation ─────────────────────────────
    p_comps = subparsers.add_parser(
        "comps",
        help="Generate peer comps xlsx + summary from step2_comps_data.json",
    )
    p_comps.add_argument("workspace", help="Workspace directory name or path")
    p_comps.set_defaults(func=cmd_comps)

    # ── Monte Carlo simulation ──────────────────────
    p_mc = subparsers.add_parser(
        "mc",
        help="Run cumulative Monte Carlo simulation from reviewed assumptions",
    )
    p_mc.add_argument("workspace", help="Workspace directory name or path")
    p_mc.add_argument("--sims", type=int, default=None, help="Number of simulations (default: 20000)")
    p_mc.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    p_mc.set_defaults(func=cmd_mc)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
