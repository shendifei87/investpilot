#!/usr/bin/env python3
"""InvestPilot CLI — data fetching and analysis tools."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.ticker_rules import detect_market, normalize_ticker
from src.data.market_detector import get_fetcher
from config.settings import WORKSPACES_DIR


def cmd_detect(args):
    market = detect_market(args.ticker)
    normalized, market = normalize_ticker(args.ticker, market)
    print(json.dumps({
        "ticker": args.ticker,
        "normalized": normalized,
        "market": market,
    }, indent=2))


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
                print(f"Warning: {w}")

        if result.data is not None:
            if isinstance(result.data, dict):
                for key, val in result.data.items():
                    if hasattr(val, "to_csv"):
                        path = output_dir / f"{name}_{key}.csv"
                        val.to_csv(path)
                        print(f"Saved: {path}")
                    else:
                        path = output_dir / f"{name}_{key}.json"
                        path.write_text(json.dumps(val if not hasattr(val, "__dict__") else str(val), default=str, indent=2))
                        print(f"Saved: {path}")
            elif hasattr(result.data, "to_csv"):
                path = output_dir / f"{name}.csv"
                result.data.to_csv(path)
                print(f"Saved: {path}")

    # ── Auto-calculate valuation ratios from raw financial data ──
    _auto_calculate_valuation(results, output_dir)

    print(f"\nAll data saved to: {output_dir}")


def cmd_analyze(args):
    from src.analysis.technical import calc_ma, calc_rsi, calc_macd
    import pandas as pd

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
        print(f"No price data found at {price_file}")

    # Load financial statements
    for stmt_key in ["financials_income", "financials_balance_sheet"]:
        stmt_file = input_dir / f"{stmt_key}.csv"
        if stmt_file.exists():
            print(f"Found {stmt_key}, analysis would run here")

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
        print(f"Thesis created (revision 1)")
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
            ks = tracker.trigger_kill_switch(args.condition, args.evidence or "")
            print(f"Kill switch triggered: {args.condition}")
        else:
            if not args.condition:
                print("Error: --condition is required for kill-switch add")
                return
            ks = tracker.add_kill_switch(args.condition, severity=args.severity or "critical")
            print(f"Kill switch added: {args.condition}")

    else:
        print(f"Unknown action: {action}")
        print("Available: list, add, resolve, decay, kill-switch")


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
    from src.report.generator import generate_report_html

    workspace = args.workspace
    ws_path = WORKSPACES_DIR / workspace

    if not ws_path.exists():
        print(f"Error: Workspace not found: {ws_path}")
        sys.exit(1)

    ticker = args.ticker or workspace
    company_name = args.name or ""

    output = generate_report_html(
        workspace_dir=str(ws_path),
        ticker=ticker,
        company_name=company_name,
    )
    print(f"HTML report generated: {output}")


# ── Helper functions ──────────────────────────────────────────────


def _make_serializable(obj):
    """Convert dicts with non-JSON types (numpy, pandas) to JSON-safe types."""
    import numpy as np
    import pandas as pd
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.Series):
        return obj.to_dict()
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict()
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    return str(obj)


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
        from src.analysis.financial import calc_all_valuation_ratios

        val_data = val_result.data
        fin_data = fin_result.data

        if not isinstance(val_data, dict) or not isinstance(fin_data, dict):
            return

        price = val_data.get("current_price")
        shares = val_data.get("shares_outstanding")
        eps_fwd = val_data.get("eps_forward")

        # Resolve income DataFrame (yfinance uses "financials", akshare uses "income")
        income = fin_data.get("financials") or fin_data.get("income")
        balance = fin_data.get("balance_sheet")
        cashflow = fin_data.get("cashflow")

        if not price or not shares or income is None or balance is None:
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

        # Save calculated valuation
        calc_path = output_dir / "calculated_valuation.json"
        calc_path.write_text(
            json.dumps(_make_serializable(calculated), indent=2, ensure_ascii=False)
        )
        print(f"\nSaved calculated valuation: {calc_path}")

        # Save raw valuation inputs (exclude DataFrames and reference notes)
        raw_keys = [
            "current_price", "shares_outstanding", "eps_ttm", "eps_forward",
            "book_value_per_share", "revenue_ttm", "market_cap", "enterprise_value",
            "total_debt", "total_cash", "ebitda", "target_mean_price",
            "recommendation", "dividend_yield", "beta",
        ]
        raw_inputs = {k: val_data[k] for k in raw_keys if k in val_data and val_data[k] is not None}
        raw_path = output_dir / "valuation_raw_inputs.json"
        raw_path.write_text(
            json.dumps(raw_inputs, default=str, indent=2, ensure_ascii=False)
        )
        print(f"Saved raw valuation inputs: {raw_path}")

    except Exception as e:
        print(f"\nWarning: Auto-calculation failed: {e}")


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
                                    json.dumps(val, default=str, indent=2)
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

    print(f"\nPeer data summary:")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description="InvestPilot — Investment Research Tools")
    subparsers = parser.add_subparsers(dest="command")

    p_detect = subparsers.add_parser("detect", help="Detect market from ticker")
    p_detect.add_argument("ticker")
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
    p_report = subparsers.add_parser("report", help="Generate HTML research report")
    p_report.add_argument("workspace", help="Workspace directory name (e.g. 09992.HK)")
    p_report.add_argument("--ticker", "-t", help="Ticker symbol (default: workspace name)")
    p_report.add_argument("--name", "-n", help="Company display name")
    p_report.set_defaults(func=cmd_report)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
