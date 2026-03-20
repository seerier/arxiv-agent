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
  1–3: PhD student / early-career or niche researcher with limited outside impact.
  4–6: Solid researcher — publishes at good venues, moderate citation impact, known in subfield.
  7–8: Strong researcher — multiple high-impact papers, frequently cited, influences the field.
  9–10: Exceptional — field-defining contributions (Turing, NeurIPS Best Paper, 10k+ citations etc.)

WEIGHTING — you MUST follow this:
- Give HEAVY weight to HISTORICAL representative works (their most-cited, most-influential papers \
ever), not just recent activity. A researcher who wrote foundational papers years ago but is less \
active now can still rate 7–8.
- Do NOT rate purely on recency. Recent papers should count for roughly 30% of the rating; \
career-defining historical works count for 70%.
- Use citation counts and h-index heavily if bibliometric data is provided.

CALIBRATION — you MUST follow this:
- Most researchers are 4–6. Do NOT default to 7+ to sound encouraging.
- 7–8 should be reserved for truly influential researchers known outside their immediate subfield.
- 9–10 is for once-in-a-decade contributors only — extremely rare.
- An unknown researcher with a small paper list should score 2–4, not 6.
- Be honest: if someone has mediocre citation numbers and no landmark papers, say so.

ANTI-HALLUCINATION — CRITICAL:
- ONLY reference papers that appear in the provided list. NEVER invent, fabricate, or recall \
paper titles from your training data. If a paper is not in the list, do not mention it by title.
- Do not name specific venues, awards, or institutions unless they appear in the provided data.
- If the paper list is sparse and you cannot reliably assess impact, say so in rating_reasoning \
rather than filling gaps with assumed knowledge.

rating_reasoning: A paragraph justifying the rating. MUST mention:
- Specific papers FROM THE PROVIDED LIST that demonstrate impact (cite by title only if listed).
- Citation counts FROM THE PROVIDED DATA if available.
- Whether this is someone worth collaborating with or following.
- If data is insufficient to assess well, state this honestly.
"""

_RECOMMEND_SYSTEM_PROMPT = """\
You are a blunt, experienced research advisor. Your job is to give an honest ranking \
of research topics — not to be encouraging. A researcher relies on your candour to \
avoid wasting years on a crowded or low-ceiling direction.

Return ONLY a valid JSON object with this schema (no markdown, no preamble):
{
  "field_summary": "<1-2 sentences: honest state of the field — including if it is saturated, dominated by big labs, or past peak>",
  "recommendations": [
    {
      "topic": "<specific, concrete topic name — e.g. 'Flow Matching for Video Generation' not just 'video'>",
      "momentum": <integer 1-10, how fast this topic is growing>,
      "novelty": <integer 1-10, how much open territory remains>,
      "opportunity": <integer 1-10, realistic research opportunity for a small team>,
      "why_promising": "<honest 2-3 sentences: what gap exists and why NOW — but also note if it is already crowded>",
      "caveats": "<1-2 sentences: what makes this hard, risky, or less attractive — be direct>",
      "suggested_angle": "<1 concrete angle a small team could realistically pursue>",
      "representative_papers": ["<paper title 1>", "<paper title 2>"]
    }
  ]
}

Rules:
- Give exactly the number of recommendations requested.
- Topics must be SPECIFIC sub-topics, not entire fields.
- CALIBRATION: opportunity scores must span the realistic range.
  • 8–10: genuinely open, fast-moving, low competition — rare, at most 1–2 topics.
  • 5–7: worthwhile but with real headwinds (competition, uncertainty, difficulty).
  • 1–4: crowded, declining, or dominated by resources a small team cannot match.
- Do NOT give every topic a high score. If most topics in a field are crowded, say so.
- momentum: paper volume trend (10 = explosive growth, 1 = stagnant/declining).
- novelty: unexplored territory (10 = almost no landmark paper, 1 = field is solved).
- opportunity = realistic chance a small team makes a meaningful contribution.
- caveats is REQUIRED — always name a real risk or weakness.
- Rank topics from highest to lowest opportunity.
- representative_papers: ONLY use EXACT titles from the provided paper list. Do NOT invent,
  paraphrase, or recall paper titles from training data. If no paper in the list fits, use [].
"""

_IDEA_SYSTEM_PROMPT = """\
You are a senior research advisor known for brutal honesty. You do NOT hype ideas \
to sound exciting. You generate specific, realistic research ideas AND rate them \
honestly — including their weaknesses.

Return ONLY a valid JSON object (no markdown, no preamble) with this schema:
{
  "field_pulse": "<2-3 sentences: honest state of the field — including if it is saturated, moving too fast for small teams, or if big labs dominate>",
  "trend_summary": "<1-2 sentences: what macro shift is happening and what it means for newcomers>",
  "ideas": [
    {
      "title": "<specific idea title — e.g. 'Efficient Diffusion Sampling via Learned Score Caching' not 'improve diffusion'>",
      "one_liner": "<one honest sentence: what you do and what realistic impact it has>",
      "feasibility": <integer 1-10, can a small team (1-2 people, 1 GPU) do this in 6-12 months?>,
      "impact": <integer 1-10, how much would this move the field if it worked?>,
      "novelty": <integer 1-10, how unexplored is this specific angle right now?>,
      "time_horizon": "<'near (1-3 months)' | 'mid (3-9 months)' | 'long (9-18 months)'>",
      "why_now": "<2-3 sentences: concrete evidence this is the right moment — cite specific recent papers or gaps>",
      "approach": "<3-5 sentences: concrete technical plan — method, baseline, dataset, metric>",
      "key_challenge": "<the single hardest obstacle — be specific, not generic>",
      "risks": "<1-2 sentences: what could make this idea fail or become irrelevant — be honest>",
      "build_on": ["<paper title or tool 1>", "<paper title or tool 2>"],
      "novelty_gap": "<exactly what gap this fills — if the gap is small, say so>"
    }
  ]
}

ANTI-HALLUCINATION — CRITICAL:
- build_on: ONLY list paper titles that appear VERBATIM in the provided papers list. Do NOT invent,
  paraphrase, or recall titles from training data. Tools and libraries (e.g. "PyTorch", "DDPM codebase")
  are allowed. If no paper fits, use a short list of only real ones.
- why_now: when citing papers as evidence, use ONLY titles from the provided list. You may describe
  a concept or gap without citing a specific paper if you don't have one in the list.
- Do NOT fabricate author names, paper titles, or publication venues.

CALIBRATION — you MUST follow this:
- feasibility: most ideas are 5–7. Use 9–10 only for truly simple extensions. Use 1–3 for ideas \
requiring infrastructure only top labs have.
- impact: most work has modest impact (4–6). Use 8–10 only for ideas that could redefine the subfield.
- novelty: if similar ideas appear in the paper list, score low (2–4). Score 8–10 only if genuinely \
unexplored.
- Do NOT give every idea a high score. Honest variation is required.
- If an idea is risky or incremental, the scores must reflect that.
- risks is REQUIRED — every idea has real risks. Do not write "limited" or "none".
- Rank ideas from best to worst by (feasibility + impact + novelty) combined.
- Generate exactly the number of ideas requested.
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
    # Topic recommendations
    # ------------------------------------------------------------------

    def recommend_topics(
        self,
        field_description: str,
        papers: List[Paper],
        n: int = 8,
    ) -> Dict[str, Any]:
        """Identify the most promising research topics in a field.

        Parameters
        ----------
        field_description:
            Human-readable description of the researcher's field (used in the prompt).
        papers:
            Recent papers from the field (should be sorted by recency).
        n:
            Number of topic recommendations to return.

        Returns
        -------
        dict with keys:
          - "field_summary": str
          - "recommendations": list of dicts, each with:
              topic, momentum, novelty, opportunity, why_promising,
              suggested_angle, representative_papers
        """
        logger.info(
            "Generating %d topic recommendations for field '%s' using %d papers.",
            n, field_description, len(papers),
        )

        # Build paper list for the prompt (title + abstract excerpt)
        paper_lines = []
        for i, p in enumerate(papers[:120], 1):
            year = p.published_date.year if p.published_date else "?"
            authors_str = ", ".join(p.authors[:2])
            if len(p.authors) > 2:
                authors_str += " et al."
            abstract_snip = (p.abstract or p.summary or "")[:200].strip()
            paper_lines.append(
                f"[{i}] \"{p.title}\" — {authors_str} ({year})\n"
                f"    {abstract_snip}"
            )

        papers_block = "\n\n".join(paper_lines)

        user_prompt = (
            f"Field: {field_description}\n\n"
            f"I am analyzing {len(papers)} recent papers published in this field "
            f"(sorted newest first). Please identify the {n} most promising specific "
            f"research topics a researcher in this field should explore.\n\n"
            f"Recent papers:\n\n{papers_block}\n\n"
            f"Return exactly {n} recommendations as JSON."
        )

        try:
            data = self._client.complete_json(
                system=_RECOMMEND_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=3000,
            )
        except Exception as exc:
            logger.error("Failed to generate topic recommendations: %s", exc)
            raise

        # Normalize and clamp scores
        recs = data.get("recommendations", [])
        for rec in recs:
            for key in ("momentum", "novelty", "opportunity"):
                try:
                    rec[key] = max(1, min(10, int(rec.get(key, 5))))
                except (TypeError, ValueError):
                    rec[key] = 5

        return {
            "field_summary": str(data.get("field_summary", "")).strip(),
            "recommendations": recs,
        }

    # ------------------------------------------------------------------
    # Research idea generation
    # ------------------------------------------------------------------

    def generate_research_ideas(
        self,
        field: str,
        papers: list,
        web_snippets: List[dict],
        n: int = 6,
    ) -> Dict[str, Any]:
        """Generate specific, actionable research ideas for a field.

        Parameters
        ----------
        field:
            Target research direction (free-form string).
        papers:
            Recent LivePaper objects fetched from arXiv (sorted newest-first).
        web_snippets:
            List of dicts with keys title/url/body from DuckDuckGo web search.
        n:
            Number of ideas to generate.

        Returns
        -------
        dict with keys:
          - "field_pulse": str
          - "trend_summary": str
          - "ideas": list of idea dicts
        """
        logger.info(
            "Generating %d research ideas for '%s' using %d papers + %d web signals.",
            n, field, len(papers), len(web_snippets),
        )

        # Build paper block (newest first, up to 100)
        paper_lines = []
        for i, p in enumerate(papers[:100], 1):
            year = p.published_date.year if p.published_date else "?"
            authors_str = ", ".join((p.authors or [])[:2])
            if len(p.authors or []) > 2:
                authors_str += " et al."
            abstract_snip = (getattr(p, "abstract", "") or "")[:250].strip()
            citations = getattr(p, "citations", 0)
            cit_str = f" [{citations} citations]" if citations else ""
            paper_lines.append(
                f"[{i}] \"{p.title}\" — {authors_str} ({year}){cit_str}\n"
                f"    {abstract_snip}"
            )
        papers_block = "\n\n".join(paper_lines)

        # Build web signal block
        web_lines = []
        for j, s in enumerate(web_snippets[:20], 1):
            snippet = (s.get("body") or "")[:200].strip()
            web_lines.append(f"[W{j}] {s.get('title', '')} — {s.get('url', '')}\n    {snippet}")
        web_block = "\n\n".join(web_lines) if web_lines else "(no web results)"

        user_prompt = (
            f"Target field: {field}\n\n"
            f"=== RECENT ARXIV PAPERS ({len(papers)} total, newest first) ===\n\n"
            f"{papers_block}\n\n"
            f"=== WEB / COMMUNITY SIGNALS ===\n\n"
            f"{web_block}\n\n"
            f"Generate exactly {n} research ideas as JSON."
        )

        data = self._client.complete_json(
            system=_IDEA_SYSTEM_PROMPT,
            user=user_prompt,
            max_tokens=4000,
        )

        # Normalize scores
        for idea in data.get("ideas", []):
            for key in ("feasibility", "impact", "novelty"):
                try:
                    idea[key] = max(1, min(10, int(idea.get(key, 5))))
                except (TypeError, ValueError):
                    idea[key] = 5

        return {
            "field_pulse": str(data.get("field_pulse", "")).strip(),
            "trend_summary": str(data.get("trend_summary", "")).strip(),
            "ideas": data.get("ideas", []),
        }

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
    # Surface historical representative work by citation count (heavy weight)
    # and also include recent high-scored papers, then deduplicate.
    by_citations = sorted(papers, key=lambda p: p.citations, reverse=True)[:10]
    by_score = sorted(papers, key=lambda p: p.overall_score, reverse=True)[:10]
    # Merge: citations-ranked first, fill remaining slots with score-ranked
    seen_ids = {p.id for p in by_citations}
    extra = [p for p in by_score if p.id not in seen_ids]
    combined = (by_citations + extra)[:20]
    # Sort merged list: most-cited first so Claude sees landmark papers up top
    top_papers = sorted(combined, key=lambda p: p.citations, reverse=True)

    paper_lines: List[str] = []
    for i, p in enumerate(top_papers, 1):
        summary = p.summary if p.summary else p.abstract[:200]
        pub = p.published_date.isoformat() if p.published_date else "?"
        cit_str = f" | Citations: {p.citations:,}" if p.citations > 0 else ""
        paper_lines.append(
            f"{i}. \"{p.title}\" ({pub}){cit_str}\n"
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
        f"Papers (top {len(top_papers)} — sorted by citation count to surface "
        f"historical representative works first):\n\n"
        f"{papers_block}\n\n"
        f"IMPORTANT: Base your analysis ONLY on the papers listed above and the "
        f"bibliometric data provided. Do NOT invent, recall, or fabricate paper "
        f"titles, venues, or awards that are not in this list. If you cannot "
        f"assess the researcher well from this data, say so honestly.\n\n"
        f"Give heavy weight to historically influential papers (high citations). "
        f"Recent activity is secondary. Please generate the researcher profile JSON."
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
