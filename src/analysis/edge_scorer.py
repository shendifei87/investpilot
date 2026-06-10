"""Edge Scorer — Classify and quantify the source of investment edge.

Forces intellectual honesty by requiring explicit classification of
where the edge comes from and how sustainable it is.

Usage:
    from src.analysis.edge_scorer import EdgeScorer

    scorer = EdgeScorer()
    scores = scorer.score(
        analytical=7,
        analytical_reason="深控范式变革的产业链分析，卖方尚未更新框架",
        temporal=5,
        temporal_reason="愿意持有到2027E，市场只看2026E",
        informational=2,
        informational_reason="完全依赖公开信息",
        structural=3,
        structural_reason="A股机构偏好短期，对长周期叙事定价不足",
    )
    print(scores["composite"])
    print(scores["sustainability"])
    print(scores["recommendation"])
"""

from __future__ import annotations

import logging
from datetime import datetime

from config.settings import WORKSPACES_DIR
from src.storage import AtomicJSON

logger = logging.getLogger(__name__)


EDGE_TYPES = {
    "analytical": {
        "name": "分析优势 (Analytical Edge)",
        "description": "对公开信息的处理比市场更深入",
        "decay_rate": "high",  # erodes fastest
    },
    "temporal": {
        "name": "时间优势 (Temporal Edge)",
        "description": "愿意等待更久让 thesis 兑现",
        "decay_rate": "none",  # fully in investor's control
    },
    "informational": {
        "name": "信息优势 (Informational Edge)",
        "description": "掌握市场尚未充分消化的信息",
        "decay_rate": "very_high",  # erodes extremely fast
    },
    "structural": {
        "name": "结构优势 (Structural Edge)",
        "description": "市场结构扭曲（被迫卖出、指数调整、被动资金流）",
        "decay_rate": "low",  # most persistent
    },
}


class EdgeScorer:
    """Classify and score the source of investment edge.

    Note: Unlike ThesisTracker/CatalystTracker, this class does NOT extend
    WorkspaceStateBase because:
    1. It supports stateless mode (workspace_dir="") for ad-hoc scoring
    2. It stores a history list, not a single mutable state dict
    """

    def __init__(self, workspace_dir: str = ""):
        self.workspace = WORKSPACES_DIR / workspace_dir if workspace_dir else None
        self._store = AtomicJSON(self.workspace) if self.workspace else None
        if self.workspace:
            self.workspace.mkdir(parents=True, exist_ok=True)

    def score(
        self,
        analytical: int,
        analytical_reason: str,
        temporal: int,
        temporal_reason: str,
        informational: int,
        informational_reason: str,
        structural: int,
        structural_reason: str,
        analytical_weight: float = 0.35,
        temporal_weight: float = 0.25,
        informational_weight: float = 0.20,
        structural_weight: float = 0.20,
    ) -> dict:
        """Score each edge type and compute composite.

        Each edge type scored 0-10:
        - 0-2: No meaningful edge
        - 3-5: Modest edge
        - 6-8: Strong edge
        - 9-10: Exceptional edge (rare for public markets)

        Weights reflect typical importance for fundamental investors.
        """
        raw = {
            "analytical": {"score": analytical, "reason": analytical_reason},
            "temporal": {"score": temporal, "reason": temporal_reason},
            "informational": {"score": informational, "reason": informational_reason},
            "structural": {"score": structural, "reason": structural_reason},
        }

        weights = {
            "analytical": analytical_weight,
            "temporal": temporal_weight,
            "informational": informational_weight,
            "structural": structural_weight,
        }

        # Validate scores
        for edge_type, data in raw.items():
            if not 0 <= data["score"] <= 10:
                raise ValueError(f"{edge_type} score must be 0-10, got {data['score']}")

        # Composite weighted score
        composite = sum(
            raw[et]["score"] * weights[et] for et in EDGE_TYPES
        )

        # Sustainability assessment
        sustainability = self._assess_sustainability(raw)

        # Edge concentration risk
        concentration = self._check_concentration(raw)

        result = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "raw_scores": raw,
            "weights": weights,
            "composite": round(composite, 2),
            "composite_grade": self._grade(composite),
            "sustainability": sustainability,
            "concentration_risk": concentration,
            "recommendation": self._recommendation(composite, sustainability, concentration),
            "contrarian_challenge": self._contrarian_challenge(raw),
        }

        # Persist if workspace provided
        if self.workspace:
            self._save(result)

        return result

    def _grade(self, composite: float) -> str:
        if composite >= 7.0:
            return "A — Strong edge across multiple dimensions"
        if composite >= 5.5:
            return "B — Meaningful edge with some weaknesses"
        if composite >= 4.0:
            return "C — Marginal edge, thesis is largely consensus"
        return "D — No identifiable edge — why are you different?"

    def _assess_sustainability(self, raw: dict) -> dict:
        """Assess how quickly the edge will decay."""
        # Edges with high decay: informational and analytical
        fast_decay_score = max(raw["informational"]["score"], raw["analytical"]["score"])
        slow_decay_score = max(raw["structural"]["score"], raw["temporal"]["score"])

        if fast_decay_score > 7 and slow_decay_score < 4:
            return {
                "rating": "low",
                "explanation": "Edge relies heavily on fast-decaying sources (informational/analytical). "
                              "Window is narrow — must act quickly.",
                "half_life_months": "1-3",
            }
        elif slow_decay_score >= 6:
            return {
                "rating": "high",
                "explanation": "Edge has durable components (structural/temporal). "
                              "Can afford to wait for better entry.",
                "half_life_months": "6-18",
            }
        else:
            return {
                "rating": "medium",
                "explanation": "Mixed edge sources. Analytical edge will decay but structural/temporal "
                              "provides a floor.",
                "half_life_months": "3-6",
            }

    def _check_concentration(self, raw: dict) -> dict:
        """Check if edge is over-concentrated in one source."""
        scores = {et: raw[et]["score"] for et in EDGE_TYPES}
        total = sum(scores.values())
        if total == 0:
            return {"risk": "critical", "detail": "No edge identified at all."}

        max_score = max(scores.values())
        concentration = max_score / total

        if concentration > 0.60 and max_score > 5:
            dominant = max(scores, key=scores.get)
            return {
                "risk": "high",
                "detail": f"Edge is {concentration:.0%} concentrated in {EDGE_TYPES[dominant]['name']}. "
                         f"If this single source erodes, thesis has no fallback.",
            }
        return {"risk": "low", "detail": "Edge is reasonably diversified across sources."}

    def _recommendation(self, composite: float, sustainability: dict, concentration: dict) -> str:
        parts = []
        if composite < 4.0:
            parts.append("WARNING: No identifiable edge. You are expressing a consensus view.")
            parts.append("Action: Either find a genuine divergence from consensus, or don't trade.")
        elif composite < 5.5:
            parts.append("Edge is marginal. Position size should be reduced (Kelly × 0.5).")
            parts.append("Action: Strengthen analysis or find a structural catalyst before committing.")
        else:
            parts.append(f"Edge is {'strong' if composite >= 7 else 'meaningful'}. Standard position sizing applies.")

        if sustainability["rating"] == "low":
            parts.append(f"Sustainability is LOW (half-life ~{sustainability['half_life_months']}). "
                        "Prioritize speed of execution over optimal entry price.")
        if concentration["risk"] == "high":
            parts.append(concentration["detail"])

        return " | ".join(parts)

    def _contrarian_challenge(self, raw: dict) -> str:
        """Generate the uncomfortable question each edge type should face."""
        challenges = []
        if raw["analytical"]["score"] >= 6:
            challenges.append(
                f"Analytical ({raw['analytical']['score']}/10): "
                "If your analysis is truly superior, why hasn't the market figured it out? "
                "What specific cognitive bias or structural barrier prevents others from seeing this?"
            )
        if raw["temporal"]["score"] >= 6:
            challenges.append(
                f"Temporal ({raw['temporal']['score']}/10): "
                "Are you patient, or are you anchoring? What if the catalyst never comes?"
            )
        if raw["informational"]["score"] >= 5:
            challenges.append(
                f"Informational ({raw['informational']['score']}/10): "
                "Is this truly proprietary, or just information others have chosen to ignore? If the latter, "
                "reclassify as analytical edge."
            )
        if raw["structural"]["score"] >= 5:
            challenges.append(
                f"Structural ({raw['structural']['score']}/10): "
                "Structural edges can reverse quickly. Is the structural force still active, or has it already played out?"
            )
        return "\n".join(challenges) if challenges else "No strong edge to challenge."

    def _save(self, result: dict):
        """Save edge score to workspace."""
        if not self._store:
            return
        history = self._store.load("edge_score.json", default=[])
        if not isinstance(history, list):
            logger.warning(
                "edge_score.json is corrupt (type=%s); resetting to empty list. "
                "Previous history is lost.",
                type(history).__name__,
            )
            history = []
        history.append(result)
        self._store.save("edge_score.json", history)

    @staticmethod
    def load_latest(workspace_dir: str) -> dict | None:
        """Load the most recent edge score for a workspace."""
        store = AtomicJSON(WORKSPACES_DIR / workspace_dir)
        history = store.load("edge_score.json", default=[])
        if isinstance(history, list) and history:
            return history[-1]
        return None
