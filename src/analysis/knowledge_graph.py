"""Cross-Workspace Knowledge Graph — Pattern recognition across research.

Enables learning from past research by connecting companies, industries,
themes, and outcomes. When starting research on a new stock, the system
can find similar historical setups and surface relevant lessons.

Version 2 internal format:
  - Normalized company records (single source of truth per ticker)
  - Explicit graph edges (company→industry, company→theme)
  - Fuzzy matching via difflib (stdlib)
  - Auto-migration from v1 flat-JSON format on first load

Usage:
    from src.analysis.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph()

    # After completing research on a stock:
    kg.record_research(
        workspace="600584.SH",
        ticker="600584",
        industry="半导体封测",
        themes=["先进封装", "Chiplet", "国产替代"],
        thesis="先进封装产能释放 + Chiplet 范式变革",
        rrr=2.3,
        moat_rating="narrow",
        edge_composite=6.5,
    )

    # When starting research on a new stock:
    similar = kg.find_similar(industry="半导体封测", themes=["先进封装"])
    # → returns past research with similar setups

    # Pattern queries:
    kg.query_patterns("高增速板块占比提升")  # search by keyword
    kg.cross_workspace_stats()  # aggregate insights
"""

from __future__ import annotations

from datetime import datetime
from difflib import get_close_matches
import uuid
from config.settings import WORKSPACES_DIR
from src.storage import AtomicJSON


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

# Canonical moat ratings
_MOAT_ALIASES = {
    "wide": "wide",
    "narrow": "narrow",
    "none": "none",
    "narrow_widening": "narrow_widening",
    "narrow-widening": "narrow_widening",
    "narrow widening": "narrow_widening",
    "wide_narrowing": "wide_narrowing",
    "wide-narrowing": "wide_narrowing",
}


def _normalize_moat(rating: str) -> str:
    """Normalize moat rating to canonical lowercase form."""
    if not rating:
        return ""
    key = rating.lower().replace(" ", "_")
    return _MOAT_ALIASES.get(key, rating.lower())


def _migrate_v1_to_v2(data: dict) -> dict:
    """Migrate version-1 flat format to version-2 graph format."""
    if data.get("version") == 2:
        return data

    v2 = {
        "version": 2,
        "companies": {},
        "edges": [],
        "patterns": data.get("patterns", []),
        "lessons": data.get("lessons", []),
    }

    old_companies = data.get("companies", {})
    for ticker, records in old_companies.items():
        if isinstance(records, dict):
            records = [records]
        if not records:
            continue
        latest = records[-1]
        history = records[:-1]

        industry_norm = latest.get("industry", "")
        moat_norm = _normalize_moat(latest.get("moat_rating", ""))

        v2["companies"][ticker] = {
            "workspace": latest.get("workspace", ""),
            "industry_normalized": industry_norm,
            "current": {
                **latest,
                "moat_rating": moat_norm,
            },
            "history": [
                {**h, "moat_rating": _normalize_moat(h.get("moat_rating", ""))}
                for h in history
            ],
        }

        # Rebuild edges from the latest record
        if industry_norm:
            v2["edges"].append({
                "source": ticker, "target": industry_norm,
                "type": "company_industry",
            })
        for theme in latest.get("themes", []):
            v2["edges"].append({
                "source": ticker, "target": theme,
                "type": "company_theme",
            })

    return v2


# ──────────────────────────────────────────────
#  KnowledgeGraph
# ──────────────────────────────────────────────

class KnowledgeGraph:
    """Cross-workspace knowledge accumulation and pattern matching.

    Internal format (v2):
      companies: {ticker: {workspace, industry_normalized, current, history}}
      edges: [{source, target, type}, ...]
      patterns: [{id, pattern, setup_conditions, ...}, ...]
      lessons: [{id, lesson, context, ...}, ...]
    """

    def __init__(self):
        self._store = AtomicJSON(WORKSPACES_DIR)
        self._data = self._load()

    def _load(self) -> dict:
        raw = self._store.load("_knowledge_graph.json", default=None)
        if raw is None:
            return {
                "version": 2,
                "companies": {},
                "edges": [],
                "patterns": [],
                "lessons": [],
            }
        migrated = _migrate_v1_to_v2(raw)
        if migrated is not raw:
            # Migration happened — persist the new format
            self._store.save("_knowledge_graph.json", migrated)
        return migrated

    def _save(self):
        self._store.save("_knowledge_graph.json", self._data)

    # ── Record research outcomes ─────────────────────────

    def record_research(
        self,
        workspace: str,
        ticker: str,
        industry: str,
        themes: list[str],
        thesis: str,
        rrr: float | None = None,
        moat_rating: str = "",
        edge_composite: float | None = None,
        eqc_grade: str = "",
        key_metrics: dict | None = None,
        outcome: str = "",
    ) -> dict:
        """Record a completed research session into the knowledge graph."""
        record = {
            "workspace": workspace,
            "ticker": ticker,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "industry": industry,
            "themes": themes,
            "thesis": thesis,
            "rrr": rrr,
            "moat_rating": _normalize_moat(moat_rating),
            "edge_composite": edge_composite,
            "eqc_grade": eqc_grade,
            "key_metrics": key_metrics or {},
            "outcome": outcome,
        }

        # Remove old edges for this ticker (dedup)
        self._data["edges"] = [
            e for e in self._data["edges"]
            if not (e["source"] == ticker and e["type"] in ("company_industry", "company_theme"))
        ]

        # Add new edges
        if industry:
            self._data["edges"].append({
                "source": ticker, "target": industry,
                "type": "company_industry",
            })
        for theme in themes:
            self._data["edges"].append({
                "source": ticker, "target": theme,
                "type": "company_theme",
            })

        # Update company record (single source of truth)
        if ticker in self._data["companies"]:
            existing = self._data["companies"][ticker]
            old_current = dict(existing.get("current", {}))
            if old_current:
                existing.setdefault("history", []).append(old_current)
            existing["current"] = record
            existing["workspace"] = workspace
            existing["industry_normalized"] = industry
        else:
            self._data["companies"][ticker] = {
                "workspace": workspace,
                "industry_normalized": industry,
                "current": record,
                "history": [],
            }

        self._save()
        return record

    def record_outcome(
        self,
        ticker: str,
        outcome: str,
        return_pct: float | None = None,
        hold_days: int | None = None,
        notes: str = "",
    ) -> dict:
        """Record the actual outcome of a past research thesis."""
        if ticker not in self._data["companies"]:
            raise ValueError(f"No research record for {ticker}")

        current = self._data["companies"][ticker].get("current", {})
        current["outcome"] = outcome
        current["return_pct"] = return_pct
        current["hold_days"] = hold_days
        current["outcome_date"] = datetime.now().strftime("%Y-%m-%d")
        current["outcome_notes"] = notes

        self._save()
        return current

    def add_lesson(
        self,
        lesson: str,
        context: str,
        tickers: list[str] | None = None,
        category: str = "general",
    ) -> dict:
        """Record a cross-stock lesson or pattern."""
        entry = {
            "id": f"L{uuid.uuid4().hex[:6]}",
            "lesson": lesson,
            "context": context,
            "tickers": tickers or [],
            "category": category,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        self._data["lessons"].append(entry)
        self._save()
        return entry

    def add_pattern(
        self,
        pattern: str,
        setup_conditions: list[str],
        historical_outcomes: list[str],
        reliability: str = "untested",
    ) -> dict:
        """Record a repeatable pattern across stocks."""
        entry = {
            "id": f"P{uuid.uuid4().hex[:6]}",
            "pattern": pattern,
            "setup_conditions": setup_conditions,
            "historical_outcomes": historical_outcomes,
            "reliability": reliability,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        self._data["patterns"].append(entry)
        self._save()
        return entry

    # ── Query & pattern matching ─────────────────────────

    def find_similar(
        self,
        industry: str = "",
        themes: list[str] | None = None,
        moat_rating: str = "",
        min_rrr: float | None = None,  # deprecated, kept for API compat
    ) -> list[dict]:
        """Find historical research with similar characteristics.

        Uses fuzzy matching via difflib for industry and theme names,
        so "半导体封测" will partially match "半导体封装测试".
        """
        results = []
        moat_norm = _normalize_moat(moat_rating) if moat_rating else ""

        for ticker, company_data in self._data["companies"].items():
            record = company_data.get("current", {})
            if not record:
                continue
            score = 0
            max_score = 0

            # Industry match (with fuzzy matching)
            if industry:
                max_score += 3
                rec_industry = (
                    company_data.get("industry_normalized", "")
                    or record.get("industry", "")
                )
                if rec_industry == industry:
                    score += 3
                elif industry in rec_industry or rec_industry in industry:
                    score += 2
                elif get_close_matches(industry, [rec_industry], n=1, cutoff=0.6):
                    score += 2

            # Theme overlap (with fuzzy matching)
            if themes:
                max_score += 2 * len(themes)
                record_themes = set(record.get("themes", []))
                for t in themes:
                    if t in record_themes:
                        score += 2
                    elif any(t in rt for rt in record_themes):
                        score += 1
                    elif get_close_matches(t, list(record_themes), n=1, cutoff=0.6):
                        score += 1

            # Moat match (normalized)
            if moat_norm:
                max_score += 1
                if record.get("moat_rating") == moat_norm:
                    score += 1

            if max_score == 0:
                continue

            similarity = score / max_score
            if similarity >= 0.3:
                results.append({
                    "ticker": ticker,
                    "record": record,
                    "similarity": round(similarity, 2),
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results

    def get_industry_insights(self, industry: str) -> dict:
        """Get aggregated insights for an industry.

        Reconstructs ticker list from edges (not a stored dict).
        """
        # Find all tickers connected to this industry via edges
        industry_tickers = set()
        for edge in self._data.get("edges", []):
            if edge["type"] == "company_industry" and edge["target"] == industry:
                industry_tickers.add(edge["source"])

        # Fuzzy fallback for near-matches
        if not industry_tickers:
            all_industries = {
                e["target"] for e in self._data.get("edges", [])
                if e["type"] == "company_industry"
            }
            matches = get_close_matches(industry, list(all_industries), n=1, cutoff=0.6)
            if matches:
                matched = matches[0]
                for edge in self._data.get("edges", []):
                    if edge["type"] == "company_industry" and edge["target"] == matched:
                        industry_tickers.add(edge["source"])

        if not industry_tickers:
            return {"industry": industry, "n_research": 0}

        records = []
        for ticker in industry_tickers:
            if ticker in self._data["companies"]:
                records.append(self._data["companies"][ticker].get("current", {}))

        rrrs = [r["rrr"] for r in records if r.get("rrr")]
        outcomes = [r.get("outcome", "") for r in records]

        related_themes = set()
        for edge in self._data.get("edges", []):
            if edge["source"] in industry_tickers and edge["type"] == "company_theme":
                related_themes.add(edge["target"])

        return {
            "industry": industry,
            "n_research": len(records),
            "tickers_analyzed": list(industry_tickers),
            "avg_rrr": round(sum(rrrs) / len(rrrs), 2) if rrrs else None,
            "known_outcomes": outcomes,
            "related_themes": sorted(related_themes),
        }

    def get_theme_insights(self, theme: str) -> dict:
        """Get aggregated insights for a theme.

        Reconstructs from edges.
        """
        theme_tickers = set()
        theme_industries = set()
        for edge in self._data.get("edges", []):
            if edge["type"] == "company_theme" and edge["target"] == theme:
                theme_tickers.add(edge["source"])
                if edge["source"] in self._data["companies"]:
                    ind = self._data["companies"][edge["source"]].get(
                        "industry_normalized", "",
                    )
                    if ind:
                        theme_industries.add(ind)

        if not theme_tickers:
            return {"theme": theme, "n_research": 0}

        records = []
        for ticker in theme_tickers:
            if ticker in self._data["companies"]:
                records.append(self._data["companies"][ticker].get("current", {}))

        return {
            "theme": theme,
            "n_research": len(records),
            "tickers": list(theme_tickers),
            "industries": sorted(theme_industries),
            "outcomes": [r.get("outcome", "") for r in records],
        }

    def query_patterns(self, keyword: str = "") -> list[dict]:
        """Search patterns and lessons by keyword."""
        results = []

        for p in self._data.get("patterns", []):
            if keyword.lower() in p["pattern"].lower() or keyword.lower() in " ".join(p.get("setup_conditions", [])).lower():
                results.append({"type": "pattern", **p})

        for l in self._data.get("lessons", []):
            if keyword.lower() in l["lesson"].lower() or keyword.lower() in l["context"].lower():
                results.append({"type": "lesson", **l})

        return results

    def cross_workspace_stats(self) -> dict:
        """Aggregate statistics across all workspaces."""
        companies = self._data.get("companies", {})
        total = len(companies)
        if total == 0:
            return {"total_research": 0}

        all_current = [c.get("current", {}) for c in companies.values()]
        rrrs = [c["rrr"] for c in all_current if c.get("rrr")]
        with_outcome = [c for c in all_current if c.get("outcome")]
        returns = [c.get("return_pct") for c in with_outcome if c.get("return_pct") is not None]

        industries = set()
        all_themes = set()
        for edge in self._data.get("edges", []):
            if edge["type"] == "company_industry":
                industries.add(edge["target"])
            elif edge["type"] == "company_theme":
                all_themes.add(edge["target"])

        return {
            "total_research": total,
            "with_outcome": len(with_outcome),
            "industries_covered": sorted(industries),
            "themes_covered": sorted(all_themes),
            "avg_rrr": round(sum(rrrs) / len(rrrs), 2) if rrrs else None,
            "median_rrr": sorted(rrrs)[len(rrrs) // 2] if rrrs else None,
            "win_rate": f"{sum(1 for r in returns if r > 0)}/{len(returns)}" if returns else "N/A",
            "avg_return_pct": round(sum(returns) / len(returns), 1) if returns else None,
            "n_patterns": len(self._data.get("patterns", [])),
            "n_lessons": len(self._data.get("lessons", [])),
        }

    def generate_research_brief(self, ticker: str, industry: str, themes: list[str]) -> str:
        """Generate a brief for the analyst before starting research.

        Surfaces relevant historical research, patterns, and lessons.
        """
        lines = ["# Pre-Research Brief", ""]

        # Similar past research
        similar = self.find_similar(industry=industry, themes=themes)
        if similar:
            lines.append("## Similar Past Research")
            for s in similar[:5]:
                r = s["record"]
                outcome_str = f" → {r['outcome']}" if r.get("outcome") else ""
                lines.append(
                    f"- **{s['ticker']}** (similarity: {s['similarity']:.0%}) "
                    f"— {r.get('industry', '')} — RRR: {r.get('rrr', 'N/A')}{outcome_str}"
                )
                if r.get("thesis"):
                    lines.append(f"  Thesis: {r['thesis']}")
            lines.append("")

        # Industry insights
        industry_data = self.get_industry_insights(industry)
        if industry_data.get("n_research", 0) > 0:
            lines.append(f"## Industry: {industry}")
            lines.append(f"- Previously analyzed: {industry_data['tickers_analyzed']}")
            if industry_data.get("avg_rrr"):
                lines.append(f"- Average RRR: {industry_data['avg_rrr']}")
            lines.append(f"- Related themes: {', '.join(industry_data.get('related_themes', []))}")
            lines.append("")

        # Theme insights
        for theme in themes:
            theme_data = self.get_theme_insights(theme)
            if theme_data.get("n_research", 0) > 0:
                lines.append(f"## Theme: {theme}")
                lines.append(f"- Related tickers: {theme_data['tickers']}")
                lines.append(f"- Cross-industry: {theme_data['industries']}")
                lines.append("")

        # Relevant patterns and lessons
        all_insights = []
        for keyword in [industry] + themes:
            all_insights.extend(self.query_patterns(keyword))

        if all_insights:
            lines.append("## Relevant Patterns & Lessons")
            for insight in all_insights[:5]:
                icon = "P" if insight["type"] == "pattern" else "L"
                lines.append(f"- [{icon}] {insight.get('lesson') or insight.get('pattern', '')}")
            lines.append("")

        if len(lines) <= 2:
            lines.append("No prior research found for this industry/theme combination. This is a new area.")

        lines.append("---")
        lines.append("*Use these insights to inform your research, but don't anchor on past conclusions.*")

        return "\n".join(lines)
