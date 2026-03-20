"""Semantic Scholar fetcher / enrichment module for the Arxiv Intelligence System.

Provides three capabilities:
1. ``enrich_paper`` — looks up a paper by arXiv ID or title to add citation count.
2. ``get_author_info`` — retrieves h-index, citation count, and affiliation.
3. ``search_papers`` — searches the S2 graph for papers matching a query.

All methods handle 429 rate-limiting with exponential back-off.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from rich.console import Console

from arxiv_intel.models import Paper

logger = logging.getLogger(__name__)
console = Console(stderr=True)

_GRAPH_BASE = "https://api.semanticscholar.org/graph/v1"
_PAPER_SEARCH_URL = f"{_GRAPH_BASE}/paper/search"
_PAPER_LOOKUP_URL = f"{_GRAPH_BASE}/paper/{{paper_id}}"
_AUTHOR_SEARCH_URL = f"{_GRAPH_BASE}/author/search"
_AUTHOR_DETAIL_URL = f"{_GRAPH_BASE}/author/{{author_id}}"

# Fields to request for paper lookups
_PAPER_FIELDS = "title,authors,year,citationCount,externalIds,abstract,publicationDate"
# Fields to request for author searches
_AUTHOR_SEARCH_FIELDS = "name,hIndex,citationCount,affiliations,papers"
_AUTHOR_DETAIL_FIELDS = "name,hIndex,citationCount,affiliations,papers"

_REQUEST_TIMEOUT: int = 20
_INITIAL_BACKOFF: float = 2.0
_MAX_RETRIES: int = 5


def _backoff_get(
    session: requests.Session,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = _MAX_RETRIES,
) -> Optional[Dict[str, Any]]:
    """GET *url* with exponential back-off on 429 / 5xx responses.

    Returns parsed JSON dict on success, or ``None`` on permanent failure.
    """
    backoff = _INITIAL_BACKOFF
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("S2 request error (attempt %d/%d): %s", attempt, max_retries, exc)
            if attempt == max_retries:
                return None
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                logger.error("S2 non-JSON response from %s", url)
                return None

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", backoff))
            logger.warning(
                "S2 rate-limited (429) on attempt %d/%d; sleeping %.1fs",
                attempt,
                max_retries,
                retry_after,
            )
            time.sleep(retry_after)
            backoff = max(backoff * 2, retry_after)
            continue

        if resp.status_code in (500, 502, 503, 504):
            logger.warning(
                "S2 server error %d (attempt %d/%d); sleeping %.1fs",
                resp.status_code,
                attempt,
                max_retries,
                backoff,
            )
            time.sleep(backoff)
            backoff *= 2
            continue

        # 4xx other than 429 → give up immediately
        logger.debug("S2 returned %d for %s", resp.status_code, url)
        return None

    return None


def _s2_paper_to_paper(item: Dict[str, Any]) -> Optional[Paper]:
    """Convert a Semantic Scholar paper record to a ``Paper`` dataclass."""
    title = (item.get("title") or "").strip()
    if not title:
        return None

    external_ids: Dict[str, str] = item.get("externalIds") or {}
    arxiv_id = external_ids.get("ArXiv") or external_ids.get("arxiv") or ""
    s2_id = item.get("paperId") or ""

    paper_id = arxiv_id if arxiv_id else s2_id
    if not paper_id:
        return None

    url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else f"https://www.semanticscholar.org/paper/{s2_id}"

    raw_authors = item.get("authors") or []
    authors: List[str] = [
        a.get("name") or "" for a in raw_authors if isinstance(a, dict) and a.get("name")
    ]

    year = item.get("year")
    pub_date_str = item.get("publicationDate") or ""
    published: Optional[date] = None
    if pub_date_str:
        try:
            published = date.fromisoformat(pub_date_str[:10])
        except ValueError:
            pass
    if published is None and year:
        try:
            published = date(int(year), 1, 1)
        except (ValueError, TypeError):
            pass

    citations = int(item.get("citationCount") or 0)

    return Paper(
        id=paper_id,
        title=title,
        authors=authors,
        abstract=(item.get("abstract") or "").strip(),
        url=url,
        published_date=published,
        source="semantic_scholar",
        citations=citations,
        fetched_at=datetime.now(tz=timezone.utc),
    )


class SemanticScholarFetcher:
    """Enriches papers and fetches data from the Semantic Scholar Graph API.

    Parameters
    ----------
    api_key:
        Optional Semantic Scholar API key for higher rate limits.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": "ArxivIntelligenceSystem/1.0",
                "Accept": "application/json",
            }
        )
        if api_key:
            self._session.headers["x-api-key"] = api_key

    # ------------------------------------------------------------------
    # Paper enrichment
    # ------------------------------------------------------------------

    def enrich_paper(self, paper: Paper) -> Paper:
        """Look up *paper* on Semantic Scholar and add citation count.

        The lookup uses the arXiv ID when available, otherwise falls back
        to a title search.  The original ``Paper`` object is returned
        (mutated in-place) whether or not enrichment data was found.

        Parameters
        ----------
        paper:
            A ``Paper`` instance whose ``citations`` field may be 0.

        Returns
        -------
        Paper
            The same paper with ``citations`` updated if data was found.
        """
        data: Optional[Dict[str, Any]] = None

        # 1. Try lookup by arXiv ID
        if paper.id and not paper.id.startswith("pwc-"):
            lookup_id = f"ARXIV:{paper.id}"
            url = _PAPER_LOOKUP_URL.format(paper_id=lookup_id)
            data = _backoff_get(
                self._session,
                url,
                params={"fields": _PAPER_FIELDS},
            )

        # 2. Fall back to title search
        if data is None and paper.title:
            results = _backoff_get(
                self._session,
                _PAPER_SEARCH_URL,
                params={
                    "query": paper.title,
                    "fields": _PAPER_FIELDS,
                    "limit": 3,
                },
            )
            if results:
                items = results.get("data") or []
                # Pick the best match by exact (lowercased) title comparison
                for item in items:
                    if (item.get("title") or "").lower().strip() == paper.title.lower().strip():
                        data = item
                        break
                if data is None and items:
                    data = items[0]  # Best-effort: take the top result

        if data:
            citations = int(data.get("citationCount") or 0)
            if citations > paper.citations:
                paper.citations = citations
                logger.debug(
                    "Enriched '%s' with %d citations from S2", paper.title[:60], citations
                )

        return paper

    # ------------------------------------------------------------------
    # Author info
    # ------------------------------------------------------------------

    def get_author_info(self, author_name: str) -> Dict[str, Any]:
        """Retrieve h-index, citation count, and affiliation for an author.

        Parameters
        ----------
        author_name:
            Full name string to search for.

        Returns
        -------
        dict
            Keys: ``name``, ``h_index``, ``citation_count``, ``affiliation``,
            ``author_id``.  All values default to safe empty values if not found.
        """
        default: Dict[str, Any] = {
            "name": author_name,
            "h_index": 0,
            "citation_count": 0,
            "affiliation": "",
            "author_id": "",
        }

        results = _backoff_get(
            self._session,
            _AUTHOR_SEARCH_URL,
            params={
                "query": author_name,
                "fields": _AUTHOR_SEARCH_FIELDS,
                "limit": 5,
            },
        )
        if not results:
            return default

        items = results.get("data") or []
        if not items:
            return default

        # Pick best match by name similarity (exact first, then first result)
        match: Optional[Dict[str, Any]] = None
        for item in items:
            if (item.get("name") or "").lower().strip() == author_name.lower().strip():
                match = item
                break
        if match is None:
            match = items[0]

        author_id = match.get("authorId") or ""

        # Fetch full detail for accurate h-index and affiliations
        detail: Optional[Dict[str, Any]] = None
        if author_id:
            detail = _backoff_get(
                self._session,
                _AUTHOR_DETAIL_URL.format(author_id=author_id),
                params={"fields": _AUTHOR_DETAIL_FIELDS},
            )

        source = detail if detail else match

        affiliations = source.get("affiliations") or []
        affiliation = affiliations[0] if affiliations else ""
        if isinstance(affiliation, dict):
            affiliation = affiliation.get("name") or ""

        return {
            "name": source.get("name") or author_name,
            "h_index": int(source.get("hIndex") or 0),
            "citation_count": int(source.get("citationCount") or 0),
            "affiliation": affiliation,
            "author_id": author_id,
        }

    # ------------------------------------------------------------------
    # Paper search
    # ------------------------------------------------------------------

    def search_papers(self, query: str, limit: int = 20) -> List[Paper]:
        """Search Semantic Scholar for papers matching *query*.

        Parameters
        ----------
        query:
            Free-text search string.
        limit:
            Maximum number of papers to return.

        Returns
        -------
        List[Paper]
            Papers mapped to our dataclass, ordered by S2 relevance.
        """
        if not query.strip():
            return []

        data = _backoff_get(
            self._session,
            _PAPER_SEARCH_URL,
            params={
                "query": query,
                "fields": _PAPER_FIELDS,
                "limit": min(limit, 100),
            },
        )
        if not data:
            return []

        items = data.get("data") or []
        papers: List[Paper] = []
        for item in items:
            paper = _s2_paper_to_paper(item)
            if paper is not None:
                papers.append(paper)

        logger.debug("S2 search '%s' → %d papers", query, len(papers))
        return papers
