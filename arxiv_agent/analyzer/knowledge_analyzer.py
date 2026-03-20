"""Higher-level knowledge mining and report generation.

Provides ``KnowledgeAnalyzer`` which builds on ``ClaudeClient`` to:
- Surface breakthrough papers
- Generate professor profiles
- Produce markdown trend reports (emerging / dying directions)
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from rich.logging import RichHandler

from arxiv_agent.models import Paper, Professor
from arxiv_agent.database import Database
from arxiv_agent.analyzer.claude_client import ClaudeClient, get_client

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts — professor profile
# ---------------------------------------------------------------------------

_PROFESSOR_SYSTEM_PROMPT = """\
You are an expert academic analyst.  Your task is to create a concise \
researcher profile from the provided list of papers and any available \
bibliometric data.

Return ONLY a valid JSON object with this schema (no markdown, no preamble):
{
  "bio": "<2–3 sentence professional biography>",
  "research_focus": ["<area 1>", "<area 2>", "<area 3>"],
  "directions": ["<direction 1>", "<direction 2>"],
  "rating": <integer 1-10>,
  "rating_reasoning": "<paragraph: overall impact, originality, influence, and whether worth following>"
}

bio: factual 2–3 sentence biography covering their research identity, \
key contributions, and institutional affiliation if known.
research_focus: 3–5 specific research topics/methods they are known for.
directions: 1–4 high-level research directions (field-level tags).
rating: integer 1–10 overall researcher impact/influence score.
  1–3: Limited impact, narrow or declining research, few citations.
  4–6: Solid researcher, moderate impact, reasonable publication record.
  7–8: Strong researcher, high impact, notable contributions, influential papers.
  9–10: Exceptional — field-defining work, thousands of citations, top-tier venues.
rating_reasoning: A paragraph justifying the rating — cover citation impact, \
originality of contributions, influence on the field, publication venues, \
and whether this is someone worth following or collaborating with.
"""

_TREND_SYSTEM_PROMPT = """\
You are an expert AI research trend analyst.  Your task is to interpret \
quantitative paper-count data and write a clear, insightful markdown report.

Guidelines:
- Use concrete numbers from the data provided.
- Be specific about what each direction is and why the trend matters.
- Suggest potential causes for the trend where applicable.
- Write in an accessible, professional tone.
- Use markdown headings (##, ###) and bullet lists where appropriate.
- Do NOT wrap output in code fences.
"""

# ---------------------------------------------------------------------------
# KnowledgeAnalyzer
# ---------------------------------------------------------------------------


class KnowledgeAnalyzer:
    """Higher-level knowledge mining on top of a paper corpus.

    Parameters
    ----------
    client:
        ``ClaudeClient`` instance.  If omitted the global singleton is used.
    """

    def __init__(self, client: Optional[ClaudeClient] = None) -> None:
        self._client: ClaudeClient = client or get_client()

    # ------------------------------------------------------------------
    # Breakthroughs
    # ------------------------------------------------------------------

    def find_breakthroughs(self, papers: List[Paper]) -> List[Paper]:
        """Return all papers flagged as breakthroughs, sorted by overall_score.

        Parameters
        ----------
        papers:
            Candidate paper list (typically from the last N days).

        Returns
        -------
        List[Paper]
            Subset of *papers* where ``is_breakthrough == True``, ordered by
            ``overall_score`` descending.
        """
        breakthroughs = [p for p in papers if p.is_breakthrough]
        breakthroughs.sort(key=lambda p: p.overall_score, reverse=True)
        logger.info(
            "Found %d breakthrough papers out of %d candidates.",
            len(breakthroughs),
            len(papers),
        )
        return breakthroughs

    # ------------------------------------------------------------------
    # Professor profile
    # ------------------------------------------------------------------

    def extract_professor_profile(
        self,
        author_name: str,
        papers: List[Paper],
        scholar_info: Dict[str, Any],
    ) -> Professor:
        """Generate a ``Professor`` profile using Claude.

        Parameters
        ----------
        author_name:
            Full name of the researcher.
        papers:
            Papers authored by this researcher (already fetched).
        scholar_info:
            Bibliometric data dict, e.g. from Google Scholar.  Expected keys
            (all optional): ``institution``, ``email``, ``homepage``,
            ``h_index``, ``citation_count``.

        Returns
        -------
        Professor
            A fully populated ``Professor`` object.
        """
        logger.info(
            "Generating profile for '%s' (%d papers).", author_name, len(papers)
        )

        user_prompt = _build_professor_prompt(author_name, papers, scholar_info)

        try:
            data: Dict[str, Any] = self._client.complete_json(
                system=_PROFESSOR_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=1500,
            )
        except Exception as exc:
            logger.error(
                "Failed to generate profile for '%s': %s", author_name, exc
            )
            raise

        # Derive top_papers from the supplied list (up to 10 by overall_score)
        top_papers = [
            p.id
            for p in sorted(papers, key=lambda x: x.overall_score, reverse=True)[:10]
        ]

        professor_id = _slugify(author_name)

        try:
            rating = float(data.get("rating", 0.0))
            rating = max(0.0, min(10.0, rating))
        except (TypeError, ValueError):
            rating = 0.0

        prof = Professor(
            id=professor_id,
            name=author_name,
            institution=str(scholar_info.get("institution", "")).strip(),
            email=str(scholar_info.get("email", "")).strip(),
            homepage=str(scholar_info.get("homepage", "")).strip(),
            research_focus=_ensure_str_list(data.get("research_focus", [])),
            top_papers=top_papers,
            h_index=int(scholar_info.get("h_index", 0)),
            citation_count=int(scholar_info.get("citation_count", 0)),
            directions=_ensure_str_list(data.get("directions", [])),
            bio=str(data.get("bio", "")).strip(),
            rating=rating,
            rating_reasoning=str(data.get("rating_reasoning", "")).strip(),
            analyzed_at=datetime.utcnow(),
        )
        logger.debug("Profile built for '%s'.", author_name)
        return prof

    # ------------------------------------------------------------------
    # Trend reports
    # ------------------------------------------------------------------

    def generate_emerging_directions_report(self, db: Database) -> str:
        """Generate a markdown report highlighting emerging research directions.

        Methodology: compares paper counts per direction in the last 30 days
        vs the prior 30 days and asks Claude to interpret the trends.

        Parameters
        ----------
        db:
            Initialised ``Database`` instance.

        Returns
        -------
        str
            A markdown-formatted report string.
        """
        logger.info("Generating emerging directions report…")
        recent, prior = _compute_direction_counts(db, window_days=30)
        growth = _compute_growth(recent, prior)

        # Keep only directions with positive growth
        emerging = {k: v for k, v in growth.items() if v["delta"] > 0}
        if not emerging:
            return (
                "## Emerging Directions Report\n\n"
                "_No emerging directions detected in the past 30 days._\n"
            )

        # Sort by absolute delta descending
        sorted_emerging = sorted(
            emerging.items(), key=lambda x: x[1]["delta"], reverse=True
        )[:20]

        user_prompt = _build_trend_prompt(
            title="Emerging Research Directions",
            sorted_directions=sorted_emerging,
            window_days=30,
            trend_type="emerging",
        )

        try:
            report = self._client.complete(
                system=_TREND_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=2500,
            )
        except Exception as exc:
            logger.error("Failed to generate emerging directions report: %s", exc)
            raise

        return report.strip()

    def generate_dying_directions_report(self, db: Database) -> str:
        """Generate a markdown report highlighting declining research directions.

        Methodology: compares paper counts per direction in the last 30 days
        vs the prior 30 days and asks Claude to interpret the declining trends.

        Parameters
        ----------
        db:
            Initialised ``Database`` instance.

        Returns
        -------
        str
            A markdown-formatted report string.
        """
        logger.info("Generating dying directions report…")
        recent, prior = _compute_direction_counts(db, window_days=30)
        growth = _compute_growth(recent, prior)

        # Keep only directions with negative growth (declining)
        declining = {k: v for k, v in growth.items() if v["delta"] < 0}
        if not declining:
            return (
                "## Dying/Declining Directions Report\n\n"
                "_No declining directions detected in the past 30 days._\n"
            )

        # Sort by absolute delta ascending (most declined first)
        sorted_declining = sorted(
            declining.items(), key=lambda x: x[1]["delta"]
        )[:20]

        user_prompt = _build_trend_prompt(
            title="Declining/Dying Research Directions",
            sorted_directions=sorted_declining,
            window_days=30,
            trend_type="declining",
        )

        try:
            report = self._client.complete(
                system=_TREND_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=2500,
            )
        except Exception as exc:
            logger.error("Failed to generate dying directions report: %s", exc)
            raise

        return report.strip()


# ---------------------------------------------------------------------------
# Internal helpers — trend counting
# ---------------------------------------------------------------------------


def _compute_direction_counts(
    db: Database, window_days: int = 30
) -> tuple[Dict[str, int], Dict[str, int]]:
    """Return per-direction paper counts for the recent and prior windows.

    Returns
    -------
    tuple[Dict[str, int], Dict[str, int]]
        ``(recent_counts, prior_counts)`` — both dicts map direction name
        to paper count.
    """
    now = datetime.utcnow()
    recent_start = now - timedelta(days=window_days)
    prior_start = now - timedelta(days=window_days * 2)

    # We fetch a generous window and split in Python to avoid extra DB queries
    all_papers = db.get_recent_papers(days=window_days * 2, limit=10_000)

    recent_counts: Dict[str, int] = defaultdict(int)
    prior_counts: Dict[str, int] = defaultdict(int)

    for paper in all_papers:
        if not paper.published_date:
            continue
        pub_dt = datetime.combine(paper.published_date, datetime.min.time())
        in_recent = pub_dt >= recent_start
        in_prior = prior_start <= pub_dt < recent_start

        for direction in paper.directions:
            tag = direction.strip()
            if not tag:
                continue
            if in_recent:
                recent_counts[tag] += 1
            elif in_prior:
                prior_counts[tag] += 1

    return dict(recent_counts), dict(prior_counts)


def _compute_growth(
    recent: Dict[str, int],
    prior: Dict[str, int],
) -> Dict[str, Dict[str, Any]]:
    """Compute delta and growth rate for each direction."""
    all_directions = set(recent) | set(prior)
    growth: Dict[str, Dict[str, Any]] = {}
    for direction in all_directions:
        r = recent.get(direction, 0)
        p = prior.get(direction, 0)
        delta = r - p
        # Growth rate: avoid division by zero
        if p > 0:
            rate = round((r - p) / p * 100, 1)
        elif r > 0:
            rate = 100.0  # new direction
        else:
            rate = 0.0
        growth[direction] = {
            "recent": r,
            "prior": p,
            "delta": delta,
            "rate_pct": rate,
        }
    return growth


# ---------------------------------------------------------------------------
# Internal helpers — prompts
# ---------------------------------------------------------------------------


def _build_professor_prompt(
    author_name: str,
    papers: List[Paper],
    scholar_info: Dict[str, Any],
) -> str:
    top_papers = sorted(papers, key=lambda p: p.overall_score, reverse=True)[:15]

    paper_lines: List[str] = []
    for i, p in enumerate(top_papers, 1):
        summary = p.summary if p.summary else p.abstract[:200]
        pub = p.published_date.isoformat() if p.published_date else "?"
        paper_lines.append(
            f"{i}. \"{p.title}\" ({pub})\n"
            f"   {summary}"
        )

    papers_block = "\n\n".join(paper_lines) if paper_lines else "(no papers available)"

    scholar_block = ""
    if scholar_info:
        lines = []
        for k, v in scholar_info.items():
            if v:
                lines.append(f"  {k}: {v}")
        if lines:
            scholar_block = "Scholar / bibliometric data:\n" + "\n".join(lines) + "\n\n"

    return (
        f"Researcher: {author_name}\n\n"
        f"{scholar_block}"
        f"Papers (top {len(top_papers)} by score):\n\n"
        f"{papers_block}\n\n"
        f"Please generate the researcher profile JSON."
    )


def _build_trend_prompt(
    title: str,
    sorted_directions: List[tuple],
    window_days: int,
    trend_type: str,
) -> str:
    rows: List[str] = []
    for direction, stats in sorted_directions:
        rows.append(
            f"- **{direction}**: {stats['recent']} papers (last {window_days}d) "
            f"vs {stats['prior']} papers (prior {window_days}d), "
            f"delta={stats['delta']:+d}, growth={stats['rate_pct']:+.1f}%"
        )

    data_block = "\n".join(rows)

    qualifier = "growing/new" if trend_type == "emerging" else "declining/disappearing"
    return (
        f"# {title}\n\n"
        f"Analysis window: {window_days} days (recent) vs prior {window_days} days.\n\n"
        f"Directions ranked by paper-count change ({qualifier}):\n\n"
        f"{data_block}\n\n"
        f"Please write a comprehensive markdown report interpreting these trends.  "
        f"Explain what each direction is, why its activity might be {trend_type}, "
        f"and what it means for researchers in the field."
    )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _ensure_str_list(value: Any) -> List[str]:
    """Coerce *value* to a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _slugify(name: str) -> str:
    """Convert a name to a stable lowercase slug ID."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or str(uuid.uuid4())
