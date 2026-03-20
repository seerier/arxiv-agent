"""ArXiv fetcher module for the Arxiv Intelligence System.

Fetches papers from the arXiv API using the ``arxiv`` Python library,
filtering by category codes and/or free-text custom queries.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import arxiv
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from arxiv_intel.models import Paper

logger = logging.getLogger(__name__)
console = Console(stderr=True)

# Seconds to sleep between consecutive arxiv API calls to stay polite.
_BETWEEN_QUERY_SLEEP: float = 3.0
# Maximum results to request per single Search call.
_DEFAULT_MAX_RESULTS: int = 50


def _arxiv_id_from_entry(result: arxiv.Result) -> str:
    """Return a stable short arxiv ID (e.g. ``2401.12345``) from a Result."""
    # result.entry_id looks like "http://arxiv.org/abs/2401.12345v1"
    entry = result.entry_id
    short = entry.split("/abs/")[-1]
    # Strip version suffix
    short = short.split("v")[0]
    return short


def _result_to_paper(result: arxiv.Result) -> Paper:
    """Convert an ``arxiv.Result`` object to our ``Paper`` dataclass."""
    arxiv_id = _arxiv_id_from_entry(result)

    published: Optional[date] = None
    updated: Optional[date] = None

    if result.published:
        published = result.published.date()
    if result.updated:
        updated = result.updated.date()

    authors = [a.name for a in result.authors]

    # Prefer the PDF link
    pdf_url = ""
    try:
        pdf_url = result.pdf_url or ""
    except Exception:
        pass

    categories = list(result.categories) if result.categories else []

    return Paper(
        id=arxiv_id,
        title=result.title.strip(),
        authors=authors,
        abstract=(result.summary or "").strip(),
        url=result.entry_id,
        pdf_url=pdf_url,
        published_date=published,
        updated_date=updated,
        categories=categories,
        source="arxiv",
        fetched_at=datetime.now(tz=timezone.utc),
    )


class ArxivFetcher:
    """Fetches research papers from arXiv.

    Parameters
    ----------
    max_results_per_query:
        How many results to request per individual Search call.
    between_query_sleep:
        Seconds to pause between consecutive API calls.
    """

    def __init__(
        self,
        max_results_per_query: int = _DEFAULT_MAX_RESULTS,
        between_query_sleep: float = _BETWEEN_QUERY_SLEEP,
    ) -> None:
        self.max_results_per_query = max_results_per_query
        self.between_query_sleep = between_query_sleep
        self._client = arxiv.Client(
            page_size=min(max_results_per_query, 100),
            delay_seconds=between_query_sleep,
            num_retries=3,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_category(
        self,
        category: str,
        since_date: Optional[date] = None,
        max_results: Optional[int] = None,
    ) -> List[Paper]:
        """Fetch the most recently submitted papers in a single arXiv category.

        Parameters
        ----------
        category:
            Category code, e.g. ``"cs.AI"``.
        since_date:
            If given, only papers published on or after this date are returned.
        max_results:
            Override the default max-results limit for this call.
        """
        limit = max_results or self.max_results_per_query
        query = f"cat:{category}"
        logger.debug("Fetching category %s (max_results=%d)", category, limit)

        papers: List[Paper] = []
        try:
            search = arxiv.Search(
                query=query,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
                max_results=limit,
            )
            for result in self._client.results(search):
                paper = _result_to_paper(result)
                if since_date and paper.published_date and paper.published_date < since_date:
                    # Results are sorted by submission date descending; once we
                    # fall below the cutoff we can stop early.
                    break
                papers.append(paper)
        except Exception as exc:
            logger.error("Error fetching category %s: %s", category, exc)

        logger.debug("Category %s → %d papers", category, len(papers))
        return papers

    def fetch_query(
        self,
        query: str,
        since_date: Optional[date] = None,
        max_results: Optional[int] = None,
    ) -> List[Paper]:
        """Fetch papers matching a free-text query string.

        Parameters
        ----------
        query:
            Free-text search string, e.g. ``"event camera"``.
        since_date:
            If given, only papers published on or after this date are returned.
        max_results:
            Override the default max-results limit for this call.
        """
        limit = max_results or self.max_results_per_query
        logger.debug("Fetching query '%s' (max_results=%d)", query, limit)

        papers: List[Paper] = []
        try:
            search = arxiv.Search(
                query=query,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending,
                max_results=limit,
            )
            for result in self._client.results(search):
                paper = _result_to_paper(result)
                if since_date and paper.published_date and paper.published_date < since_date:
                    break
                papers.append(paper)
        except Exception as exc:
            logger.error("Error fetching query '%s': %s", query, exc)

        logger.debug("Query '%s' → %d papers", query, len(papers))
        return papers

    def fetch_all(
        self,
        categories: List[str],
        custom_queries: List[str],
        since_date: Optional[date] = None,
        max_results_per_query: Optional[int] = None,
    ) -> List[Paper]:
        """Fetch papers from all given categories and custom queries.

        Deduplication by arXiv ID is performed here so that papers
        matching multiple queries are not duplicated in the output.

        Parameters
        ----------
        categories:
            List of arXiv category codes (e.g. ``["cs.AI", "cs.CV"]``).
        custom_queries:
            List of free-text search strings (e.g. ``["event camera"]``).
        since_date:
            Only return papers published on or after this date.
        max_results_per_query:
            Per-query limit override.

        Returns
        -------
        List[Paper]
            Deduplicated list of papers, ordered by fetch order.
        """
        all_papers: Dict[str, Paper] = {}  # id -> Paper (preserves insertion order in Py3.7+)

        total_tasks = len(categories) + len(custom_queries)

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                "[cyan]Fetching from arXiv...", total=total_tasks
            )

            for cat in categories:
                progress.update(task, description=f"[cyan]arXiv category: {cat}")
                papers = self.fetch_category(
                    cat, since_date=since_date, max_results=max_results_per_query
                )
                for p in papers:
                    if p.id not in all_papers:
                        all_papers[p.id] = p
                progress.advance(task)

                if categories.index(cat) < len(categories) - 1 or custom_queries:
                    time.sleep(self.between_query_sleep)

            for query in custom_queries:
                short_q = query[:40]
                progress.update(task, description=f"[cyan]arXiv query: '{short_q}'")
                papers = self.fetch_query(
                    query, since_date=since_date, max_results=max_results_per_query
                )
                for p in papers:
                    if p.id not in all_papers:
                        all_papers[p.id] = p
                progress.advance(task)

                if custom_queries.index(query) < len(custom_queries) - 1:
                    time.sleep(self.between_query_sleep)

        result_list = list(all_papers.values())
        console.print(
            f"[green]arXiv:[/green] fetched [bold]{len(result_list)}[/bold] unique papers "
            f"from {len(categories)} categories + {len(custom_queries)} custom queries."
        )
        return result_list
