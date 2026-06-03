"""Thesis Tracker — Living thesis management with hypothesis tracking.

Turns one-off research into a persistent, evolving thesis that can be
updated incrementally instead of rebuilt from scratch.

Usage:
    from src.analysis.thesis_tracker import ThesisTracker

    tracker = ThesisTracker("600584.SH")
    tracker.create("韬定律范式变革受益 + 先进封装产能释放", hold_period_months=12)
    tracker.add_hypothesis("运算电子 Q2 增速 >20%", catalyst_date="2026-07-15", impact="high")
    tracker.confirm_hypothesis("运算电子 Q2 增速 >20%", actual_result="+25% YoY", notes="超预期")
    tracker.snapshot()  # returns current thesis state
"""

from __future__ import annotations

import calendar
from datetime import datetime, date
from enum import Enum
from typing import Optional
import uuid

from src.analysis._base import WorkspaceStateBase
from src.analysis.catalyst_tracker import CatalystTracker


class HypothesisStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    PARTIAL = "partial"


class ThesisStatus(str, Enum):
    OPEN = "open"
    CLOSING = "closing"      # catalyst window ending, thesis weakening
    CLOSED_WON = "closed_won"   # thesis confirmed, position profitable
    CLOSED_LOST = "closed_lost" # thesis invalidated
    EXPIRED = "expired"         # catalyst window passed without confirmation


class ThesisTracker(WorkspaceStateBase):
    """Manages a living investment thesis for a single stock."""

    _state_file = "thesis.json"
    _default_state = {"version": 1, "history": []}

    def __init__(self, workspace_dir: str):
        super().__init__(workspace_dir)
        self._catalyst_tracker = CatalystTracker(workspace_dir)

    def _current(self) -> Optional[dict]:
        """Return the latest thesis revision, or None."""
        h = self._data.get("history", [])
        return h[-1] if h else None

    # ── Core operations ──────────────────────────────────

    def create(
        self,
        core_thesis: str,
        hold_period_months: int = 12,
        edge_type: str = "",
        edge_score: dict | None = None,
        kill_switches: list[str] | None = None,
    ) -> dict:
        """Create a new thesis (first revision)."""
        if self._current() and self._current()["status"] == ThesisStatus.OPEN:
            raise ValueError(
                "An open thesis already exists. Close it before creating a new one."
            )

        now = datetime.now()
        # Add 3 months safely, clamping day to the target month's max days
        target_month = now.month + 3
        target_year = now.year
        if target_month > 12:
            target_month -= 12
            target_year += 1
        max_day = calendar.monthrange(target_year, target_month)[1]
        time_decay_start = date(target_year, target_month, min(now.day, max_day)).isoformat()

        revision = {
            "revision": 1,
            "created": now.strftime("%Y-%m-%d"),
            "updated": now.strftime("%Y-%m-%d"),
            "status": ThesisStatus.OPEN,
            "core_thesis": core_thesis,
            "hold_period_months": hold_period_months,
            "time_decay_start": time_decay_start,
            "edge_type": edge_type,
            "edge_score": edge_score or {},
            "kill_switches": kill_switches or [],
            "hypotheses": [],
            "catalysts": [],
            "changelog": [
                {
                    "date": now.strftime("%Y-%m-%d"),
                    "action": "thesis_created",
                    "detail": core_thesis,
                }
            ],
        }
        self._data["history"].append(revision)
        self._save()
        return revision

    def revise_thesis(self, new_core_thesis: str, reason: str) -> dict:
        """Create a new revision by evolving the core thesis."""
        current = self._current()
        if not current:
            raise ValueError("No thesis to revise. Call create() first.")
        if current["status"] != ThesisStatus.OPEN:
            raise ValueError("Cannot revise a closed thesis.")

        now = datetime.now()
        new_revision = {
            "revision": current["revision"] + 1,
            "created": current["created"],
            "updated": now.strftime("%Y-%m-%d"),
            "status": ThesisStatus.OPEN,
            "core_thesis": new_core_thesis,
            "hold_period_months": current["hold_period_months"],
            "time_decay_start": current["time_decay_start"],
            "edge_type": current.get("edge_type", ""),
            "edge_score": current.get("edge_score", {}),
            "kill_switches": current.get("kill_switches", []),
            "hypotheses": list(current.get("hypotheses", [])),
            "catalysts": list(current.get("catalysts", [])),
            "changelog": list(current.get("changelog", [])) + [
                {
                    "date": now.strftime("%Y-%m-%d"),
                    "action": "thesis_revised",
                    "detail": reason,
                    "old_thesis": current["core_thesis"],
                }
            ],
        }
        self._data["history"].append(new_revision)
        self._save()
        return new_revision

    # ── Hypothesis management ────────────────────────────

    def add_hypothesis(
        self,
        description: str,
        catalyst_date: str = "",
        impact: str = "medium",
        category: str = "",
    ) -> dict:
        """Add a testable hypothesis to the current thesis."""
        current = self._current()
        if not current:
            raise ValueError("No open thesis.")
        if current["status"] != ThesisStatus.OPEN:
            raise ValueError("Thesis is not open.")

        hyp = {
            "id": f"H{uuid.uuid4().hex[:6]}",
            "description": description,
            "status": HypothesisStatus.PENDING,
            "catalyst_date": catalyst_date,
            "impact": impact,
            "category": category,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "resolved": None,
            "actual_result": None,
            "notes": "",
        }
        current["hypotheses"].append(hyp)
        current["updated"] = datetime.now().strftime("%Y-%m-%d")
        current["changelog"].append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "action": "hypothesis_added",
            "detail": description,
        })
        self._save()
        return hyp

    def resolve_hypothesis(
        self,
        hypothesis_id_or_desc: str,
        status: HypothesisStatus,
        actual_result: str = "",
        notes: str = "",
    ) -> dict:
        """Resolve a hypothesis (confirm, invalidate, or mark expired).

        Prevents pre-confirmation: if the hypothesis has a future catalyst_date
        and status is CONFIRMED, raises ValueError unless force=True is passed
        via notes='force'.
        """
        current = self._current()
        if not current:
            raise ValueError("No open thesis.")

        for hyp in current["hypotheses"]:
            if hyp["id"] == hypothesis_id_or_desc or hyp["description"] == hypothesis_id_or_desc:
                # Guard against pre-confirmation
                if status == HypothesisStatus.CONFIRMED and hyp.get("catalyst_date"):
                    today = datetime.now().strftime("%Y-%m-%d")
                    if hyp["catalyst_date"] > today and notes != "force":
                        raise ValueError(
                            f"Cannot confirm hypothesis '{hyp['id']}' before its catalyst date "
                            f"({hyp['catalyst_date']}). The data to verify this hypothesis "
                            f"is not yet available. Pass notes='force' to override."
                        )

                hyp["status"] = status
                hyp["resolved"] = datetime.now().strftime("%Y-%m-%d")
                hyp["actual_result"] = actual_result
                hyp["notes"] = notes
                current["updated"] = datetime.now().strftime("%Y-%m-%d")
                current["changelog"].append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "action": f"hypothesis_{status.value}",
                    "detail": f"{hyp['id']}: {hyp['description']} → {actual_result}",
                })
                self._save()
                return hyp

        raise ValueError(f"Hypothesis '{hypothesis_id_or_desc}' not found.")

    def confirm_hypothesis(self, hypothesis_id_or_desc: str, actual_result: str = "", notes: str = "") -> dict:
        return self.resolve_hypothesis(hypothesis_id_or_desc, HypothesisStatus.CONFIRMED, actual_result, notes)

    def invalidate_hypothesis(self, hypothesis_id_or_desc: str, actual_result: str = "", notes: str = "") -> dict:
        return self.resolve_hypothesis(hypothesis_id_or_desc, HypothesisStatus.INVALIDATED, actual_result, notes)

    # ── Catalyst management (delegates to CatalystTracker) ─────

    def add_catalyst(
        self,
        event: str,
        expected_date: str,
        impact: str = "medium",
        direction: str = "positive",
    ) -> dict:
        """Add a catalyst event — delegates to CatalystTracker."""
        return self._catalyst_tracker.add_catalyst(
            event, expected_date, impact=impact,
            direction=direction, thesis_link="",
        )

    def resolve_catalyst(
        self,
        catalyst_id_or_event: str,
        actual_date: str,
        outcome: str,
        thesis_impact: str = "neutral",
    ) -> dict:
        """Record the actual outcome of a catalyst event — delegates to CatalystTracker."""
        return self._catalyst_tracker.resolve_catalyst(
            catalyst_id_or_event, actual_date, outcome, thesis_impact=thesis_impact,
        )

    # ── Kill switch (delegates to CatalystTracker) ──────────────

    def check_kill_switches(self) -> list[dict]:
        """Check if any kill switch has been triggered — delegates to CatalystTracker."""
        return self._catalyst_tracker.check_kill_switches()

    def trigger_kill_switch(self, condition: str, evidence: str) -> dict:
        """Manually trigger a kill switch — delegates to CatalystTracker."""
        return self._catalyst_tracker.trigger_kill_switch(condition, evidence)

    # ── Close thesis ─────────────────────────────────────

    def close_thesis(self, status: ThesisStatus, reason: str) -> dict:
        """Close the current thesis."""
        current = self._current()
        if not current:
            raise ValueError("No thesis to close.")

        current["status"] = status
        current["closed_date"] = datetime.now().strftime("%Y-%m-%d")
        current["close_reason"] = reason
        current["changelog"].append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "action": f"thesis_{status.value}",
            "detail": reason,
        })
        self._save()
        return current

    # ── Snapshot & reporting ─────────────────────────────

    def snapshot(self) -> dict:
        """Return the current thesis state for display/reporting."""
        current = self._current()
        if not current:
            return {"status": "no_thesis"}

        total = len(current.get("hypotheses", []))
        confirmed = sum(1 for h in current["hypotheses"] if h["status"] == HypothesisStatus.CONFIRMED)
        invalidated = sum(1 for h in current["hypotheses"] if h["status"] == HypothesisStatus.INVALIDATED)
        pending = sum(1 for h in current["hypotheses"] if h["status"] == HypothesisStatus.PENDING)

        overdue_catalysts = []
        today = datetime.now().strftime("%Y-%m-%d")
        for c in self._catalyst_tracker._data.get("catalysts", []):
            if c["status"] == "pending" and c["expected_date"] < today:
                overdue_catalysts.append(c)

        time_decay_active = current.get("time_decay_start", "") <= today

        return {
            "ticker_workspace": self.workspace.name,
            "revision": current["revision"],
            "created": current["created"],
            "updated": current["updated"],
            "status": current["status"],
            "core_thesis": current["core_thesis"],
            "hold_period_months": current["hold_period_months"],
            "time_decay_start": current.get("time_decay_start", ""),
            "time_decay_active": time_decay_active,
            "hypotheses_summary": {
                "total": total,
                "confirmed": confirmed,
                "invalidated": invalidated,
                "pending": pending,
                "confirmation_rate": f"{confirmed}/{confirmed + invalidated}" if (confirmed + invalidated) > 0 else "N/A",
            },
            "overdue_catalysts": overdue_catalysts,
            "kill_switches": current.get("kill_switches", []),
            "edge_score": current.get("edge_score", {}),
        }

    def generate_update_brief(self) -> str:
        """Generate a brief summary for the next research update.

        This is what gets shown when re-visiting a stock — tells the analyst
        exactly what changed and what needs updating.
        """
        snap = self.snapshot()
        if snap["status"] == "no_thesis":
            return "No thesis exists. Run the full 6-step research process."

        current = self._current()
        lines = [
            f"# Thesis Update Brief: {snap['ticker_workspace']}",
            f"",
            f"**Core Thesis** (v{snap['revision']}): {snap['core_thesis']}",
            f"**Status**: {snap['status']} | Created: {snap['created']} | Last update: {snap['updated']}",
            f"**Time Decay**: {'ACTIVE' if snap['time_decay_active'] else 'Not yet'} (starts {snap['time_decay_start']})",
            f"",
            f"## Hypothesis Tracker ({snap['hypotheses_summary']['confirmation_rate']} confirmed)",
            f"",
        ]

        for hyp in current.get("hypotheses", []):
            icon = {"confirmed": "✅", "invalidated": "❌", "pending": "⏳", "expired": "⌛", "partial": "⚠️"}.get(hyp["status"], "?")
            line = f"- {icon} **{hyp['id']}**: {hyp['description']}"
            if hyp["actual_result"]:
                line += f" → {hyp['actual_result']}"
            if hyp["status"] == HypothesisStatus.PENDING and hyp.get("catalyst_date"):
                line += f" (验证日期: {hyp['catalyst_date']})"
            lines.append(line)

        if snap["overdue_catalysts"]:
            lines.append(f"\n## ⚠️ Overdue Catalysts")
            for c in snap["overdue_catalysts"]:
                lines.append(f"- **{c['event']}** — expected {c['expected_date']}, still pending")

        kill_switches = snap.get("kill_switches", [])
        triggered = [ks for ks in kill_switches if isinstance(ks, dict) and ks.get("triggered")]
        if triggered:
            lines.append(f"\n## 🚨 Triggered Kill Switches")
            for ks in triggered:
                lines.append(f"- **{ks['condition']}** — {ks.get('evidence', '')}")

        lines.append(f"\n## Next Steps")
        pending_hyps = [h for h in current.get("hypotheses", []) if h["status"] == HypothesisStatus.PENDING]
        if pending_hyps:
            lines.append(f"- {len(pending_hyps)} hypotheses pending — check if any new data resolves them")
        if snap["time_decay_active"]:
            lines.append(f"- Time decay active — prioritize thesis validation or revision")
        lines.append(f"- Only update changed sections (no need to redo all 6 steps)")

        return "\n".join(lines)
