"""High-level knowledge base for the Arxiv Intelligence System.

Provides ``KnowledgeBase`` which orchestrates direction analysis, professor
profiles, and trend reporting through a unified, cache-aware interface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from arxiv_agent.database import Database
from arxiv_agent.models import Direction, Paper, Professor
from arxiv_agent.analyzer.knowledge_analyzer import KnowledgeAnalyzer
from arxiv_agent.analyzer.direction_analyzer import DirectionAnalyzer
from arxiv_agent.reporter.knowledge_reporter import KnowledgeReporter

logger = logging.getLogger(__name__)

# How old a cached direction analysis may be before we re-run it
_DIRECTION_STALE_DAYS = 7


class KnowledgeBase:
    """Unified knowledge retrieval and analysis layer.

    Combines the database, Claude-powered analyzers, and the reporter into a
    single interface that handles caching so callers never need to worry about
    staleness.

    Parameters
    ----------
    db:
        Initialised ``Database`` instance.
    analyzer:
        ``KnowledgeAnalyzer`` for breakthroughs and professor profiles.
    direction_analyzer:
        ``DirectionAnalyzer`` for direction profiling.
    reporter:
        ``KnowledgeReporter`` for HTML report generation.
    """

    def __init__(
        self,
        db: Database,
        analyzer: KnowledgeAnalyzer,
        direction_analyzer: DirectionAnalyzer,
        reporter: KnowledgeReporter,
    ) -> None:
        self._db = db
        self._analyzer = analyzer
        self._direction_analyzer = direction_analyzer
        self._reporter = reporter

    # ------------------------------------------------------------------
    # Directions
    # ------------------------------------------------------------------

    def get_or_analyze_direction(
        self,
        name: str,
        live_papers: Optional[List[Paper]] = None,
    ) -> Direction:
        """Return a (possibly freshly generated) ``Direction`` for *name*.

        If *live_papers* are provided (fetched from arXiv live), the cache is
        always bypassed so the analysis reflects the freshest data.  Without
        live_papers, the cached result is returned if < _DIRECTION_STALE_DAYS old.

        Parameters
        ----------
        name:
            Human-readable direction name (case-insensitive lookup).
        live_papers:
            Optional list of Paper objects fetched live from arXiv/PwC.
            When provided, these form the primary corpus (70%) alongside
            local DB papers (10%).
        """
        # If live papers provided, always run fresh analysis
        if live_papers is None:
            existing = self._db.get_direction(name)
            if existing is not None and existing.analyzed_at is not None:
                age = datetime.utcnow() - existing.analyzed_at
                if age < timedelta(days=_DIRECTION_STALE_DAYS):
                    logger.debug("Direction '%s' found in cache (age=%s).", name, age)
                    return existing

        logger.info("Analysing direction '%s'.", name)

        # Local DB papers (10%)
        local_papers = self._db.get_papers_by_direction(name, limit=50)
        if not local_papers:
            local_papers = self._db.search_papers(name, limit=20)

        # Merge: live papers first (primary), then local papers (deduplicated)
        all_papers: List[Paper] = list(live_papers) if live_papers else []
        live_ids = {p.id for p in all_papers}
        for p in local_papers:
            if p.id not in live_ids:
                all_papers.append(p)

        if not all_papers:
            all_papers = local_papers  # last resort

        direction = self._direction_analyzer.analyze_direction(name, all_papers)
        self._db.update_direction(direction)
        return direction

    def search_directions(self, query: str) -> List[Direction]:
        """Return directions whose names fuzzy-match *query*.

        Uses case-insensitive substring matching across both the direction
        name and its aliases.  Results are sorted by worthiness_score desc.

        Parameters
        ----------
        query:
            Substring / keyword to match.

        Returns
        -------
        List[Direction]
        """
        query_lower = query.lower()
        all_directions = self._db.list_directions()
        matched: List[Direction] = []
        for d in all_directions:
            if query_lower in d.name.lower():
                matched.append(d)
                continue
            for alias in d.aliases:
                if query_lower in alias.lower():
                    matched.append(d)
                    break

        matched.sort(key=lambda d: d.worthiness_score, reverse=True)
        return matched

    def get_direction_report(self, name: str) -> str:
        """Return the HTML report path for *name*, generating it if needed.

        Parameters
        ----------
        name:
            Direction name.

        Returns
        -------
        str
            Absolute path to the generated (or pre-existing) HTML file.
        """
        direction = self.get_or_analyze_direction(name)
        papers = self._db.get_papers_by_direction(name, limit=100)
        html_path = self._reporter.generate_direction_report(direction, papers)
        return html_path

    def list_all_directions(self) -> List[Direction]:
        """Return all directions from the DB sorted by worthiness_score desc.

        Returns
        -------
        List[Direction]
        """
        return self._db.list_directions()

    # ------------------------------------------------------------------
    # Professors
    # ------------------------------------------------------------------

    def get_professor_profile(
        self,
        name: str,
        live_papers: Optional[List[Paper]] = None,
    ) -> Professor:
        """Return a ``Professor`` profile for *name*, enriching if needed.

        If *live_papers* are provided (fetched live from arXiv), always runs
        a fresh profile build using those papers as primary source.

        Parameters
        ----------
        name:
            Author / researcher name (case-insensitive substring match).
        live_papers:
            Optional list of Paper objects authored by this person from
            live arXiv search.
        """
        if live_papers is None:
            existing = self._db.get_professor(name)
            if existing is not None:
                return existing

        name_lower = name.lower()

        # Local DB papers by this author
        local_papers = self._db.search_papers(name, limit=100)
        local_authored = [
            p for p in local_papers
            if any(name_lower in a.lower() for a in p.authors)
        ]

        # Merge live + local (live first, deduplicated)
        all_authored: List[Paper] = list(live_papers) if live_papers else []
        live_ids = {p.id for p in all_authored}
        for p in local_authored:
            if p.id not in live_ids:
                all_authored.append(p)

        if not all_authored:
            raise ValueError(
                f"No papers found for '{name}' in the local database or arXiv. "
                "Try a different spelling or run 'fetch' first."
            )

        prof = self._analyzer.extract_professor_profile(
            author_name=name,
            papers=all_authored,
            scholar_info={},
        )
        self._db.update_professor(prof)
        return prof

    # ------------------------------------------------------------------
    # Trend reports
    # ------------------------------------------------------------------

    def get_emerging_directions(self) -> str:
        """Generate and return a markdown report of emerging directions.

        Returns
        -------
        str
            Markdown-formatted report.
        """
        return self._analyzer.generate_emerging_directions_report(self._db)

    def get_dying_directions(self) -> str:
        """Generate and return a markdown report of declining directions.

        Returns
        -------
        str
            Markdown-formatted report.
        """
        return self._analyzer.generate_dying_directions_report(self._db)

    # ------------------------------------------------------------------
    # Breakthroughs
    # ------------------------------------------------------------------

    def get_breakthroughs(self, days: int = 30) -> List[Paper]:
        """Return breakthrough papers from the last *days* days.

        Parameters
        ----------
        days:
            Look-back window in days.

        Returns
        -------
        List[Paper]
            Papers flagged as breakthroughs, sorted by overall_score desc.
        """
        papers = self._db.get_breakthrough_papers(days=days)
        papers.sort(key=lambda p: p.overall_score, reverse=True)
        return papers
