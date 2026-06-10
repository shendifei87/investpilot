"""Catalyst Tracker — Time-decaying catalyst monitoring with kill switches.

Monitors catalyst events from Step 3, tracks their resolution status,
and applies time-decay logic to thesis conviction.

Usage:
    from src.analysis.catalyst_tracker import CatalystTracker

    tracker = CatalystTracker("600584.SH")
    tracker.add_catalyst("Q2业绩验证", "2026-07-15", impact="high", direction="positive")
    tracker.add_catalyst("麒麟2026发布", "2026-09-30", impact="extreme", direction="positive")
    tracker.add_kill_switch("2026H1毛利率 < 13%")
    tracker.add_kill_switch("先进封装占比连续2Q下降")

    # After catalyst resolves:
    tracker.resolve_catalyst("Q2业绩验证", "2026-07-14", "Q2营收+25% YoY", thesis_impact="positive")

    # Check time decay:
    decay = tracker.time_decay_status()
    # → {"conviction_modifier": 0.85, "days_until_first_catalyst": 47, ...}
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from src.analysis._base import WorkspaceStateBase


class CatalystTracker(WorkspaceStateBase):
    """Tracks catalyst events and applies time-decay logic."""

    _state_file = "catalysts.json"
    _default_state = {"version": 1, "catalysts": [], "kill_switches": []}

    # ── Catalyst CRUD ────────────────────────────────────

    def add_catalyst(
        self,
        event: str,
        expected_date: str,
        impact: str = "medium",
        direction: str = "positive",
        thesis_link: str = "",
    ) -> dict:
        """Add a catalyst event. impact: low/medium/high/extreme."""
        cat = {
            "id": f"C{uuid.uuid4().hex[:6]}",
            "event": event,
            "expected_date": expected_date,
            "actual_date": None,
            "status": "pending",
            "impact": impact,
            "direction": direction,
            "outcome": None,
            "thesis_impact": None,
            "thesis_link": thesis_link,
            "created": datetime.now().strftime("%Y-%m-%d"),
        }
        self._data["catalysts"].append(cat)
        self._save()
        return cat

    def resolve_catalyst(
        self,
        catalyst_id_or_event: str,
        actual_date: str,
        outcome: str,
        thesis_impact: str = "neutral",
    ) -> dict:
        """Record the actual outcome of a catalyst.

        thesis_impact: positive / negative / neutral
        """
        for cat in self._data["catalysts"]:
            if cat["id"] == catalyst_id_or_event or cat["event"] == catalyst_id_or_event:
                cat["actual_date"] = actual_date
                cat["status"] = "resolved"
                cat["outcome"] = outcome
                cat["thesis_impact"] = thesis_impact
                self._save()
                return cat
        raise ValueError(f"Catalyst '{catalyst_id_or_event}' not found.")

    def mark_missed(self, catalyst_id_or_event: str, notes: str = "") -> dict:
        """Mark a catalyst as missed (date passed without resolution)."""
        for cat in self._data["catalysts"]:
            if cat["id"] == catalyst_id_or_event or cat["event"] == catalyst_id_or_event:
                cat["status"] = "missed"
                cat["outcome"] = notes or "Catalyst date passed without expected event"
                cat["thesis_impact"] = "negative"
                self._save()
                return cat
        raise ValueError(f"Catalyst '{catalyst_id_or_event}' not found.")

    # ── Kill switches ────────────────────────────────────

    def add_kill_switch(self, condition: str, severity: str = "critical") -> dict:
        """Add a kill switch condition.

        severity: critical (exit immediately) / major (reduce position) / warning (increase vigilance)
        """
        ks = {
            "condition": condition,
            "severity": severity,
            "triggered": False,
            "evidence": None,
            "triggered_date": None,
        }
        self._data["kill_switches"].append(ks)
        self._save()
        return ks

    def trigger_kill_switch(self, condition: str, evidence: str) -> dict:
        """Trigger a kill switch with evidence."""
        for ks in self._data["kill_switches"]:
            if ks["condition"] == condition:
                ks["triggered"] = True
                ks["evidence"] = evidence
                ks["triggered_date"] = datetime.now().strftime("%Y-%m-%d")
                self._save()
                return ks
        raise ValueError(f"Kill switch '{condition}' not found.")

    def check_kill_switches(self) -> list[dict]:
        """Return all triggered kill switches."""
        return [ks for ks in self._data["kill_switches"] if ks.get("triggered")]

    # ── Time decay logic ─────────────────────────────────

    def time_decay_status(self, thesis_created_date: str = "") -> dict:
        """Calculate time-decay conviction modifier.

        Logic:
        - First 30 days: full conviction (1.0)
        - Day 30-60: linear decay to 0.85
        - Day 60-90: linear decay to 0.65
        - Day 90+: linear decay to 0.40 (thesis needs major re-evaluation)

        These modifiers apply to RRR and Kelly position sizing.
        """
        today = date.today()

        # Use thesis creation date; fall back to earliest catalyst date as rough proxy
        if not thesis_created_date:
            thesis_data = self._store.load("thesis.json")
            if thesis_data and "history" in thesis_data:
                history = thesis_data.get("history", [])
                if history:
                    thesis_created_date = history[0].get("created", "")
        # Fallback: earliest catalyst expected_date as rough proxy
        if not thesis_created_date:
            if self._data["catalysts"]:
                dates = [c["expected_date"] for c in self._data["catalysts"] if c["status"] == "pending"]
                thesis_created_date = min(dates) if dates else today.isoformat()
            else:
                thesis_created_date = today.isoformat()

        created = date.fromisoformat(thesis_created_date) if isinstance(thesis_created_date, str) else thesis_created_date
        days_elapsed = (today - created).days

        if days_elapsed <= 30:
            modifier = 1.0
            phase = "fresh"
        elif days_elapsed <= 60:
            modifier = 1.0 - 0.15 * (days_elapsed - 30) / 30
            phase = "early_decay"
        elif days_elapsed <= 90:
            modifier = 0.85 - 0.20 * (days_elapsed - 60) / 30
            phase = "active_decay"
        else:
            modifier = max(0.40, 0.65 - 0.25 * (days_elapsed - 90) / 90)
            phase = "expired_zone"

        # Pending catalysts
        pending = [c for c in self._data["catalysts"] if c["status"] == "pending"]
        overdue = [c for c in pending if c["expected_date"] < today.isoformat()]
        next_catalyst = None
        if pending:
            future = [c for c in pending if c["expected_date"] >= today.isoformat()]
            if future:
                next_catalyst = min(future, key=lambda c: c["expected_date"])

        days_until_next = None
        if next_catalyst:
            days_until_next = (date.fromisoformat(next_catalyst["expected_date"]) - today).days

        return {
            "days_elapsed": days_elapsed,
            "conviction_modifier": round(modifier, 3),
            "phase": phase,
            "total_catalysts": len(self._data["catalysts"]),
            "pending_catalysts": len(pending),
            "resolved_catalysts": sum(1 for c in self._data["catalysts"] if c["status"] == "resolved"),
            "overdue_catalysts": len(overdue),
            "overdue_details": overdue,
            "next_catalyst": next_catalyst,
            "days_until_next_catalyst": days_until_next,
            "kill_switches_triggered": len(self.check_kill_switches()),
            "recommendation": self._decay_recommendation(modifier, len(overdue), len(self.check_kill_switches())),
        }

    def _decay_recommendation(self, modifier: float, overdue: int, kill_triggered: int) -> str:
        if kill_triggered > 0:
            return "CRITICAL: Kill switch(es) triggered. Re-evaluate thesis immediately."
        if modifier < 0.50:
            return "Thesis significantly decayed. Consider closing or major revision."
        if overdue >= 2:
            return "Multiple overdue catalysts. Thesis weakening — verify or exit."
        if overdue == 1:
            return "One overdue catalyst. Monitor closely for resolution."
        if modifier >= 0.85:
            return "Thesis fresh. Maintain conviction."
        return "Thesis aging. Next catalyst confirmation important."

    # ── Reporting ────────────────────────────────────────

    def catalyst_calendar(self) -> str:
        """Generate a text-based catalyst calendar for display."""
        lines = ["## Catalyst Calendar", ""]

        today_str = date.today().isoformat()
        all_cats = sorted(
            self._data["catalysts"],
            key=lambda c: c.get("actual_date") or c.get("expected_date", ""),
        )

        for cat in all_cats:
            icon = {"pending": "⏳", "resolved": "✅", "missed": "❌"}.get(cat["status"], "?")
            impact_icon = {"low": "·", "medium": "●", "high": "◆", "extreme": "★"}.get(cat["impact"], "·")
            date_str = cat.get("actual_date") or cat["expected_date"]

            line = f"- {icon} {impact_icon} **{cat['event']}** — {date_str}"
            if cat["status"] == "resolved":
                line += f" → {cat['outcome']}"
            elif cat["status"] == "missed":
                line += " → MISSED"
            elif cat["expected_date"] < today_str:
                line += " → OVERDUE"
            lines.append(line)

        # Kill switches
        triggered = self.check_kill_switches()
        if triggered:
            lines.append("")
            lines.append("## 🚨 Kill Switches")
            for ks in triggered:
                lines.append(f"- **{ks['condition']}** — triggered {ks['triggered_date']}: {ks['evidence']}")

        return "\n".join(lines)
