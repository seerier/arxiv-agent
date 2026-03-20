"""Papers With Code fetcher module for the Arxiv Intelligence System.

Uses the public Papers With Code REST API to discover papers that have
associated code repositories.  Papers are mapped to our ``Paper`` dataclass
with ``has_code=True`` and ``code_url`` populated.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from arxiv_agent.models import Paper

logger = logging.getLogger(__name__)
console = Console(stderr=True)

_BASE_URL = "https://paperswithcode.com/api/v1"
_PAPERS_ENDPOINT = f"{_BASE_URL}/papers/"
_RESULTS_PER_PAGE = 50
_BETWEEN_PAGE_SLEEP: float = 2.0
_REQUEST_TIMEOUT: int = 30

# Map human-friendly area names to PwC "areas" query param values.
_AREA_MAP: Dict[str, str] = {
    "computer-vision": "computer-vision",
    "machine-learning": "machine-learning",
    "natural-language-processing": "natural-language-processing",
    "medical": "medical",
    "graphs": "graphs",
    "audio": "audio",
    "reinforcement-learning": "reinforcement-learning",
    "robotics": "robotics",
    "adversarial": "adversarial",
    "knowledge-base": "knowledge-base",
    "reasoning": "reasoning",
    "speech": "speech",
    "time-series": "time-series",
}


def _parse_date(value: Optional[str]) -> Optional[date]:
    """Parse a date string in YYYY-MM-DD format, returning None on failure."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _pwc_paper_to_paper(item: Dict[str, Any]) -> Optional[Paper]:
    """Convert a single Papers With Code API response item to a ``Paper``.

    Returns ``None`` if the item lacks a usable identifier.
    """
    # Use arxiv_id when available, otherwise fall back to pwc id
    arxiv_id: str = (item.get("arxiv_id") or "").strip()
    pwc_id: str = (item.get("id") or "").strip()

    paper_id = arxiv_id if arxiv_id else pwc_id
    if not paper_id:
        return None

    # Build URLs
    url = ""
    if arxiv_id:
        url = f"https://arxiv.org/abs/{arxiv_id}"
    elif item.get("url_abs"):
        url = item["url_abs"]

    pdf_url = item.get("url_pdf") or (f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "")

    # Authors: PwC returns a list of author dicts with a "name" key
    raw_authors = item.get("authors") or []
    authors: List[str] = []
    for a in raw_authors:
        if isinstance(a, dict):
            name = a.get("name") or a.get("full_name") or ""
        else:
            name = str(a)
        if name:
            authors.append(name)

    # Code URL — the primary repository
    code_url = ""
    repository = item.get("repository") or item.get("url_code") or ""
    if isinstance(repository, dict):
        code_url = repository.get("url") or repository.get("github_url") or ""
    elif isinstance(repository, str):
        code_url = repository

    published = _parse_date(item.get("published") or item.get("date"))

    return Paper(
        id=paper_id,
        title=(item.get("title") or "").strip(),
        authors=authors,
        abstract=(item.get("abstract") or "").strip(),
        url=url,
        pdf_url=pdf_url,
        published_date=published,
        categories=[],
        source="paperswithcode",
        has_code=True,
        code_url=code_url,
        fetched_at=datetime.now(tz=timezone.utc),
    )


class PapersWithCodeFetcher:
    """Fetches recent papers with code from the Papers With Code public API.

    Parameters
    ----------
    areas:
        List of research areas to filter by (e.g. ``["computer-vision"]``).
        When empty all areas are included.
    results_per_page:
        Number of results to request per API page.
    between_page_sleep:
        Seconds to wait between paginated requests.
    """

    def __init__(
        self,
        areas: Optional[List[str]] = None,
        results_per_page: int = _RESULTS_PER_PAGE,
        between_page_sleep: float = _BETWEEN_PAGE_SLEEP,
    ) -> None:
        self.areas: List[str] = areas or []
        self.results_per_page = results_per_page
        self.between_page_sleep = between_page_sleep
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "ArxivIntelligenceSystem/1.0 (research fetcher)",
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_page(self, page: int, area: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Fetch a single page from the PwC API.

        Returns the parsed JSON dict, or ``None`` on error.
        """
        params: Dict[str, Any] = {
            "ordering": "-published",
            "format": "json",
            "page": page,
            "items_per_page": self.results_per_page,
        }
        if area:
            params["area"] = area

        url = _PAPERS_ENDPOINT + "?" + urlencode(params)
        try:
            resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
            if resp.status_code == 429:
                logger.warning("PwC rate-limited (429) on page %d; sleeping 30s", page)
                time.sleep(30)
                resp = self._session.get(url, timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("PwC API error on page %d: %s", page, exc)
            return None

    def _fetch_area(
        self,
        area: Optional[str],
        cutoff: date,
        progress: Progress,
        task_id: Any,
    ) -> List[Paper]:
        """Fetch all pages for a given area until papers are older than cutoff."""
        papers: List[Paper] = []
        page = 1
        area_label = area or "all"

        while True:
            progress.update(
                task_id,
                description=f"[cyan]PapersWithCode area={area_label} page={page}",
            )
            data = self._get_page(page=page, area=area)
            if data is None:
                break

            results = data.get("results") or []
            if not results:
                break

            found_old = False
            for item in results:
                paper = _pwc_paper_to_paper(item)
                if paper is None:
                    continue
                # Stop paginating once we pass the cutoff date
                if paper.published_date and paper.published_date < cutoff:
                    found_old = True
                    break
                papers.append(paper)

            # Check if there are more pages
            if found_old or not data.get("next"):
                break

            page += 1
            time.sleep(self.between_page_sleep)

        return papers

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_recent(self, days: int = 7) -> List[Paper]:
        """Fetch recently published papers with code.

        Parameters
        ----------
        days:
            Return papers published within the last *days* days.

        Returns
        -------
        List[Paper]
            Papers with ``has_code=True``, deduplicated by ID.
        """
        cutoff = (datetime.now(tz=timezone.utc).date() - timedelta(days=days))
        areas_to_fetch = self.areas if self.areas else [None]  # type: ignore[list-item]

        all_papers: Dict[str, Paper] = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Fetching from PapersWithCode...", total=None)

            for area in areas_to_fetch:
                try:
                    batch = self._fetch_area(
                        area=area,
                        cutoff=cutoff,
                        progress=progress,
                        task_id=task,
                    )
                    for p in batch:
                        if p.id not in all_papers:
                            all_papers[p.id] = p
                except Exception as exc:
                    logger.error("Error fetching PwC area '%s': %s", area, exc)

                if area != areas_to_fetch[-1]:
                    time.sleep(self.between_page_sleep)

        result_list = list(all_papers.values())
        console.print(
            f"[green]PapersWithCode:[/green] fetched [bold]{len(result_list)}[/bold] "
            f"papers with code (last {days} days)."
        )
        return result_list
