"""Research-direction analysis using Claude.

Provides ``DirectionAnalyzer`` which builds rich ``Direction`` profiles from
a corpus of related papers.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from arxiv_agent.models import Direction, Milestone, Paper
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
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert AI research analyst specialising in research trend analysis.
Your task is to analyse a research direction and produce a comprehensive \
structured profile.

Return ONLY a valid JSON object — no markdown fences, no preamble, no \
trailing text — that strictly conforms to this schema:

{
  "overview": "<2–3 paragraph narrative overview of the direction>",
  "status": "<one of: emerging | stable | declining | dead>",
  "worthiness_score": <integer 1-10>,
  "worthiness_reasoning": "<detailed paragraph: is it worth pursuing? why? ceiling?>",
  "career_score": <integer 1-10>,
  "career_reasoning": "<paragraph: salary outlook, industry demand, top companies hiring, job market trajectory>",
  "top_employers": ["<company 1>", "<company 2>", "<company 3>", ...],
  "key_papers": ["<paper_id_1>", "<paper_id_2>", ...],
  "open_problems": [
    "<open problem 1>",
    "<open problem 2>",
    "<open problem 3>",
    "<open problem 4>",
    "<open problem 5>"
  ],
  "milestones": [
    {"date": "<YYYY or YYYY-MM-DD>", "event": "<milestone description>"},
    ...
  ],
  "related_directions": ["<direction name 1>", "<direction name 2>", ...]
}

Scoring guidelines for worthiness_score (research opportunity):
- 1–3: Not worth pursuing (oversaturated, dying, limited ceiling, dominated by big labs)
- 4–6: Moderate opportunity — real competition or uncertain future; entry-level interest only
- 7–8: Worth pursuing — growing, clear open problems, realistic to contribute
- 9–10: Exceptional — emerging fast, high impact potential, low competition RIGHT NOW

Scoring guidelines for career_score (salary & industry demand for PhD/MSc graduates):
- 1–3: Poor career prospects — niche/academic only, few industry jobs, low salaries, or declining demand
- 4–6: Moderate — some industry interest but competitive market or unclear trajectory
- 7–8: Strong demand — multiple big tech companies hiring, competitive salaries ($150k–$250k+ in US)
- 9–10: Exceptional — highest-paying skills in the market, fierce industry competition for talent

Status definitions — be ACCURATE and CRITICAL:
- emerging: rapidly growing in the LAST 1–2 YEARS, clear upward trajectory in publications and attention
- stable: steady state, established field with consistent publication rate and community
- declining: CLEARLY losing momentum — publication rate dropping, researchers moving away, industry interest waning
- dead: virtually no new activity, field has been abandoned or fully absorbed elsewhere

STATUS CALIBRATION — you MUST follow this:
- Many fields ARE declining or dead. Do NOT default to 'emerging' or 'stable'.
- Assign 'declining' when you see: fewer new papers YoY, researchers pivoting away, major labs abandoning the area.
- Assign 'dead' when the field has stagnated for 2+ years with no meaningful breakthroughs.
- Only use 'emerging' when you have EVIDENCE of rapid recent growth.

WORTHINESS CALIBRATION — you MUST follow this:
- Most directions land in the 4–7 range. Use 8+ only for genuinely high-opportunity directions.
- Use 1–3 when a field is crowded by top labs (e.g. OpenAI, Google), has diminishing returns, \
or a small team cannot realistically compete.
- Be explicit in worthiness_reasoning about WHY something is NOT a good bet, not just why it is.
- Do NOT inflate scores to sound encouraging. Honest, critical assessment is more valuable.

ANTI-HALLUCINATION:
- key_papers: ONLY use paper IDs from the provided list. IDs not in the list will be discarded.
- Do NOT invent or recall paper titles, author names, or venues in overview or reasoning text.
  If you want to reference a paper, use its ID from the list. Do NOT write titles from memory.

Return ONLY the JSON object.
"""


def _build_user_prompt(direction_name: str, papers: List[Paper]) -> str:
    """Build the user prompt with up to 30 most relevant papers as context.

    Papers are ranked by: overall_score (analyzed papers) first, then by
    citations (live papers), ensuring landmark papers appear in context.
    """
    def _rank_key(p: Paper):
        # Analyzed papers with real scores rank first; then by citations
        return (p.overall_score, p.citations)

    top_papers = sorted(papers, key=_rank_key, reverse=True)[:30]

    paper_lines: List[str] = []
    for i, p in enumerate(top_papers, 1):
        summary_text = p.summary if p.summary else (p.abstract[:400] if p.abstract else "")
        pub_date = p.published_date.isoformat() if p.published_date else "unknown"
        cit_str = f" | Citations: {p.citations:,}" if p.citations > 0 else ""
        code_str = f" | Code: {p.code_url}" if p.code_url else ""
        paper_lines.append(
            f"{i}. [{p.id}] \"{p.title}\" ({pub_date}){cit_str}{code_str}\n"
            f"   {summary_text}"
        )

    papers_block = "\n\n".join(paper_lines) if paper_lines else "(no papers available)"

    total = len(papers)
    shown = len(top_papers)
    live_count = sum(1 for p in papers if p.overall_score == 0.0 and p.abstract)
    analyzed_count = total - live_count

    return (
        f"Research Direction: {direction_name}\n\n"
        f"Total papers in corpus: {total} "
        f"({analyzed_count} locally analyzed with AI scores, {live_count} fetched live from arXiv)\n"
        f"Showing top {shown} by relevance/citations:\n\n"
        f"Papers:\n{papers_block}\n\n"
        f"Please analyse this research direction and return the JSON profile."
    )


# ---------------------------------------------------------------------------
# DirectionAnalyzer
# ---------------------------------------------------------------------------


class DirectionAnalyzer:
    """Builds ``Direction`` profiles from paper corpora using Claude.

    Parameters
    ----------
    client:
        ``ClaudeClient`` instance.  If omitted the global singleton is used.
    """

    def __init__(self, client: Optional[ClaudeClient] = None) -> None:
        self._client: ClaudeClient = client or get_client()

    # ------------------------------------------------------------------
    # Single direction
    # ------------------------------------------------------------------

    def analyze_direction(
        self,
        direction_name: str,
        papers: List[Paper],
    ) -> Direction:
        """Analyse *direction_name* using the provided *papers* as context.

        Parameters
        ----------
        direction_name:
            Human-readable name of the research direction (e.g. "diffusion models").
        papers:
            Papers associated with this direction.

        Returns
        -------
        Direction
            A fully populated ``Direction`` object.
        """
        logger.info(
            "Analysing direction '%s' (%d papers)", direction_name, len(papers)
        )

        user_prompt = _build_user_prompt(direction_name, papers)

        try:
            data: Dict[str, Any] = self._client.complete_json(
                system=_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=3000,
            )
        except Exception as exc:
            logger.error(
                "Failed to analyse direction '%s': %s", direction_name, exc
            )
            raise

        # Build the Direction object
        direction = _parse_direction(direction_name, data, papers)
        logger.debug(
            "Direction '%s' analysed: status=%s score=%.1f",
            direction_name,
            direction.status,
            direction.worthiness_score,
        )
        return direction

    # ------------------------------------------------------------------
    # Batch — all directions from DB
    # ------------------------------------------------------------------

    def analyze_all_directions(self, db: Database) -> List[Direction]:
        """Discover all unique directions from the database and analyse each.

        Steps:
        1. Collect every direction tag from all papers in the DB.
        2. For each unique direction, fetch relevant papers.
        3. Call ``analyze_direction`` and save the result to the DB.

        Parameters
        ----------
        db:
            Initialised ``Database`` instance.

        Returns
        -------
        List[Direction]
            All analysed ``Direction`` objects (also persisted to DB).
        """
        # Gather unique direction names from all papers
        direction_names = _collect_directions(db)
        if not direction_names:
            logger.warning("No direction tags found in the database.")
            return []

        logger.info(
            "Found %d unique directions to analyse.", len(direction_names)
        )

        results: List[Direction] = []

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            transient=False,
        )
        task_id = progress.add_task(
            "Analysing directions", total=len(direction_names)
        )

        with progress:
            for name in sorted(direction_names):
                try:
                    papers = db.get_papers_by_direction(name, limit=200)
                    direction = self.analyze_direction(name, papers)
                    db.update_direction(direction)
                    results.append(direction)
                    logger.info(
                        "Saved direction '%s' to DB (score=%.1f)",
                        name,
                        direction.worthiness_score,
                    )
                except Exception as exc:
                    logger.error(
                        "Failed to analyse direction '%s': %s", name, exc
                    )
                progress.advance(task_id)

        logger.info(
            "Direction analysis complete: %d/%d succeeded.",
            len(results),
            len(direction_names),
        )
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_directions(db: Database) -> Set[str]:
    """Return the set of all direction tags present in the papers table."""
    # Use recent papers (last 365 days) as a practical upper bound
    papers = db.get_recent_papers(days=365, limit=10_000)
    directions: Set[str] = set()
    for p in papers:
        for d in p.directions:
            cleaned = d.strip()
            if cleaned:
                directions.add(cleaned)
    return directions


def _parse_direction(
    direction_name: str,
    data: Dict[str, Any],
    papers: List[Paper],
) -> Direction:
    """Construct a ``Direction`` from Claude's JSON response."""
    # Build paper ID set for validation
    paper_ids: Set[str] = {p.id for p in papers}

    # Key papers — keep only IDs that actually exist in our corpus
    raw_key_papers: List[str] = _ensure_str_list(data.get("key_papers", []))
    key_papers = [pid for pid in raw_key_papers if pid in paper_ids]
    # If Claude returned none that match, fall back to top-5 by score
    if not key_papers and papers:
        key_papers = [
            p.id
            for p in sorted(papers, key=lambda x: x.overall_score, reverse=True)[:5]
        ]

    # Milestones
    raw_milestones = data.get("milestones", [])
    milestones: List[Milestone] = []
    if isinstance(raw_milestones, list):
        for m in raw_milestones:
            if isinstance(m, dict):
                milestones.append(
                    Milestone(
                        date=str(m.get("date", "")).strip(),
                        event=str(m.get("event", "")).strip(),
                    )
                )

    # Status validation
    raw_status = str(data.get("status", "stable")).lower().strip()
    valid_statuses = {"emerging", "stable", "declining", "dead"}
    status = raw_status if raw_status in valid_statuses else "stable"

    # Worthiness score
    try:
        worthiness_score = float(data.get("worthiness_score", 5.0))
        worthiness_score = max(0.0, min(10.0, worthiness_score))
    except (TypeError, ValueError):
        worthiness_score = 5.0

    # Career score
    try:
        career_score = float(data.get("career_score", 5.0))
        career_score = max(0.0, min(10.0, career_score))
    except (TypeError, ValueError):
        career_score = 5.0

    direction_id = _slugify(direction_name)

    return Direction(
        id=direction_id,
        name=direction_name,
        aliases=[],
        overview=str(data.get("overview", "")).strip(),
        status=status,
        worthiness_score=worthiness_score,
        worthiness_reasoning=str(data.get("worthiness_reasoning", "")).strip(),
        career_score=career_score,
        career_reasoning=str(data.get("career_reasoning", "")).strip(),
        top_employers=_ensure_str_list(data.get("top_employers", [])),
        key_papers=key_papers,
        key_authors=[],  # populated separately if needed
        open_problems=_ensure_str_list(data.get("open_problems", [])),
        milestones=milestones,
        related_directions=_ensure_str_list(data.get("related_directions", [])),
        analyzed_at=datetime.utcnow(),
    )


def _ensure_str_list(value: Any) -> List[str]:
    """Coerce *value* to a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _slugify(name: str) -> str:
    """Convert a direction name to a stable lowercase slug ID."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or str(uuid.uuid4())
