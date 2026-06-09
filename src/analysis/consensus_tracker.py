"""Consensus Tracker — structured market consensus and expectation gaps.

Turns Step 3's consensus work into durable workspace data:
- consensus snapshots from sell-side reports, web sources, or implied market views
- estimate revisions over time
- our view vs consensus expectation gaps with catalyst links

The module intentionally keeps metric schemas flexible because consensus data
arrives in uneven shapes across A-share, HK, and US research workflows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from src.analysis._base import WorkspaceStateBase
from src.analysis._utils import coerce_float as _coerce_number


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


# _coerce_number is imported from src.analysis._utils


def _normalize_metric_entry(metric: str, period: str, raw: Any) -> dict:
    if isinstance(raw, dict) and "value" in raw:
        entry = {
            "metric": raw.get("metric", metric),
            "period": raw.get("period", period),
            "value": raw.get("value"),
            "unit": raw.get("unit", ""),
            "basis": raw.get("basis", ""),
            "notes": raw.get("notes", ""),
        }
        for key, val in raw.items():
            if key not in entry:
                entry[key] = val
        return entry
    return {
        "metric": metric,
        "period": period,
        "value": raw,
        "unit": "",
        "basis": "",
        "notes": "",
    }


def normalize_metrics(metrics: dict | list | None) -> list[dict]:
    """Normalize flexible metric inputs into a list of metric records.

    Accepted examples:
        {"eps": {"2026E": 1.2, "2027E": 1.5}}
        {"eps_2026E": {"metric": "eps", "period": "2026E", "value": 1.2}}
        [{"metric": "eps", "period": "2026E", "value": 1.2}]
    """
    if not metrics:
        return []

    if isinstance(metrics, list):
        normalized = []
        for item in metrics:
            if isinstance(item, dict):
                normalized.append(_normalize_metric_entry(
                    item.get("metric", ""),
                    item.get("period", ""),
                    item,
                ))
        return normalized

    if not isinstance(metrics, dict):
        return []

    normalized = []
    for metric, raw in metrics.items():
        if isinstance(raw, dict) and "value" not in raw:
            for period, value in raw.items():
                normalized.append(_normalize_metric_entry(metric, str(period), value))
        else:
            normalized.append(_normalize_metric_entry(metric, "", raw))
    return normalized


class ConsensusTracker(WorkspaceStateBase):
    """Manages structured consensus snapshots and expectation gaps."""

    _state_file = "consensus_snapshot.json"
    _default_state = {
        "version": 1,
        "snapshots": [],
        "revisions": [],
        "expectation_gaps": [],
    }

    def record_snapshot(
        self,
        source: str,
        metrics: dict | list,
        as_of: str | None = None,
        source_type: str = "sell_side",
        rating_distribution: dict | None = None,
        target_price: float | int | str | None = None,
        confidence: str = "medium",
        notes: str = "",
    ) -> dict:
        """Record a market consensus snapshot.

        `metrics` should contain raw consensus assumptions, not our estimates.
        """
        snapshot = {
            "id": _id("CS"),
            "as_of": as_of or _today(),
            "recorded_at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            "source_type": source_type,
            "confidence": confidence,
            "target_price": target_price,
            "rating_distribution": rating_distribution or {},
            "metrics": normalize_metrics(metrics),
            "notes": notes,
        }
        self._data["snapshots"].append(snapshot)
        self._save()
        return snapshot

    def latest_snapshot(self) -> dict | None:
        snapshots = self._data.get("snapshots", [])
        return snapshots[-1] if snapshots else None

    def latest_metric(self, metric: str, period: str = "") -> dict | None:
        """Find the latest matching consensus metric record."""
        metric_key = metric.lower()
        period_key = period.lower()
        for snapshot in reversed(self._data.get("snapshots", [])):
            for entry in reversed(snapshot.get("metrics", [])):
                if entry.get("metric", "").lower() != metric_key:
                    continue
                if period_key and entry.get("period", "").lower() != period_key:
                    continue
                return {
                    **entry,
                    "snapshot_id": snapshot["id"],
                    "as_of": snapshot["as_of"],
                    "source": snapshot["source"],
                    "source_type": snapshot["source_type"],
                    "confidence": snapshot.get("confidence", ""),
                }
        return None

    def record_revision(
        self,
        metric: str,
        period: str,
        old_value: Any,
        new_value: Any,
        source: str,
        as_of: str | None = None,
        reason: str = "",
    ) -> dict:
        """Record a consensus estimate revision."""
        old_num = _coerce_number(old_value)
        new_num = _coerce_number(new_value)
        delta = None
        pct_change = None
        direction = "unknown"
        if old_num is not None and new_num is not None:
            delta = new_num - old_num
            pct_change = delta / abs(old_num) if old_num else None
            if delta > 0:
                direction = "up"
            elif delta < 0:
                direction = "down"
            else:
                direction = "flat"

        revision = {
            "id": _id("CR"),
            "as_of": as_of or _today(),
            "metric": metric,
            "period": period,
            "old_value": old_value,
            "new_value": new_value,
            "delta": delta,
            "pct_change": pct_change,
            "direction": direction,
            "source": source,
            "reason": reason,
        }
        self._data["revisions"].append(revision)
        self._save()
        return revision

    def add_expectation_gap(
        self,
        metric: str,
        period: str,
        consensus_value: Any,
        our_value: Any,
        unit: str = "",
        consensus_source: str = "",
        our_source: str = "",
        catalyst: str = "",
        confidence: str = "medium",
        notes: str = "",
        higher_is_better: bool = True,
        lower_is_better: bool = False,
    ) -> dict:
        """Record an explicit our-view-vs-consensus gap."""
        if lower_is_better:
            higher_is_better = False

        consensus_num = _coerce_number(consensus_value)
        our_num = _coerce_number(our_value)
        magnitude = None
        pct_gap = None
        direction = "unknown"

        if consensus_num is not None and our_num is not None:
            raw_delta = our_num - consensus_num
            signal_delta = raw_delta if higher_is_better else -raw_delta
            magnitude = raw_delta
            pct_gap = raw_delta / abs(consensus_num) if consensus_num else None
            if signal_delta > 0:
                direction = "positive"
            elif signal_delta < 0:
                direction = "negative"
            else:
                direction = "neutral"

        gap = {
            "id": _id("EG"),
            "as_of": _today(),
            "metric": metric,
            "period": period,
            "consensus_value": consensus_value,
            "our_value": our_value,
            "unit": unit,
            "magnitude": magnitude,
            "pct_gap": pct_gap,
            "direction": direction,
            "consensus_source": consensus_source,
            "our_source": our_source,
            "catalyst": catalyst,
            "confidence": confidence,
            "higher_is_better": higher_is_better,
            "notes": notes,
            "status": "open",
        }
        self._data["expectation_gaps"].append(gap)
        self._save()
        return gap

    def resolve_gap(
        self,
        gap_id: str,
        outcome: str,
        actual_value: Any = None,
        status: str = "resolved",
        notes: str = "",
    ) -> dict:
        """Resolve an expectation gap after the relevant catalyst or filing."""
        for gap in self._data.get("expectation_gaps", []):
            if gap["id"] == gap_id:
                gap["status"] = status
                gap["resolved_at"] = _today()
                gap["actual_value"] = actual_value
                gap["outcome"] = outcome
                gap["resolution_notes"] = notes
                self._save()
                return gap
        raise ValueError(f"Expectation gap '{gap_id}' not found.")

    def gap_summary(self, status: str = "open") -> list[dict]:
        gaps = [
            g for g in self._data.get("expectation_gaps", [])
            if status == "all" or g.get("status") == status
        ]
        return sorted(
            gaps,
            key=lambda g: abs(g.get("pct_gap") or 0),
            reverse=True,
        )

    def snapshot(self) -> dict:
        import copy
        return copy.deepcopy(self._data)

    def generate_step3_brief(self) -> str:
        """Generate a markdown brief for Step 3 to consume."""
        lines = ["## Consensus & Expectation Gap Brief", ""]

        latest = self.latest_snapshot()
        if latest:
            lines.append(
                f"**Latest snapshot**: {latest['as_of']} | "
                f"{latest['source']} ({latest['source_type']}, confidence={latest.get('confidence', 'medium')})"
            )
            if latest.get("target_price") is not None:
                lines.append(f"**Consensus target price**: {latest['target_price']}")
            if latest.get("rating_distribution"):
                lines.append(f"**Rating distribution**: {latest['rating_distribution']}")
            lines.append("")
            lines.append("| Metric | Period | Consensus | Unit | Basis |")
            lines.append("|:--|:--|--:|:--|:--|")
            for entry in latest.get("metrics", []):
                lines.append(
                    f"| {entry.get('metric', '')} | {entry.get('period', '')} | "
                    f"{entry.get('value', '')} | {entry.get('unit', '')} | {entry.get('basis', '')} |"
                )
        else:
            lines.append("No structured consensus snapshot recorded yet.")

        revisions = self._data.get("revisions", [])
        if revisions:
            lines.extend(["", "### Estimate Revisions", ""])
            lines.append("| Date | Metric | Period | Old | New | Direction | Source |")
            lines.append("|:--|:--|:--|--:|--:|:--|:--|")
            for rev in revisions[-10:]:
                lines.append(
                    f"| {rev['as_of']} | {rev['metric']} | {rev['period']} | "
                    f"{rev['old_value']} | {rev['new_value']} | {rev['direction']} | {rev['source']} |"
                )

        gaps = self.gap_summary(status="open")
        if gaps:
            lines.extend(["", "### Open Expectation Gaps", ""])
            lines.append("| Metric | Period | Consensus | Our View | Gap | Direction | Catalyst | Confidence |")
            lines.append("|:--|:--|--:|--:|--:|:--|:--|:--|")
            for gap in gaps:
                pct = gap.get("pct_gap")
                pct_text = f"{pct:+.1%}" if pct is not None else ""
                lines.append(
                    f"| {gap['metric']} | {gap['period']} | {gap['consensus_value']} | "
                    f"{gap['our_value']} | {pct_text} | {gap['direction']} | "
                    f"{gap.get('catalyst', '')} | {gap.get('confidence', '')} |"
                )
        else:
            lines.extend(["", "No open structured expectation gaps recorded yet."])

        lines.extend([
            "",
            "### Step 3 Instructions",
            "",
            "- Use this brief as the structured baseline for section 3.4.",
            "- If Step 3 changes any consensus or our-view numbers, update `consensus_snapshot.json` instead of leaving changes only in markdown.",
            "- Treat missing consensus fields as explicit research gaps, not as permission to infer numbers.",
        ])
        return "\n".join(lines)
