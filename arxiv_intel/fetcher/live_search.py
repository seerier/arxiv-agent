"""Live internet search for the survey command.

Searches arXiv and Papers With Code in real time for any free-form query,
spanning multiple years of history.  Results are lightweight dicts — they
are NOT stored in the local database; they are used only as survey context.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import List, Optional
from urllib.parse import urlencode

import os

import arxiv
import requests

logger = logging.getLogger(__name__)


def live_to_paper(lp: "LivePaper") -> "Paper":
    """Convert a LivePaper (from live search) to a Paper model object.

    Only fills fields available from arXiv metadata — scores stay at 0.
    This lets live papers flow into analyzers that expect Paper objects.
    """
    from arxiv_intel.models import Paper
    from datetime import datetime, timezone
    return Paper(
        id=lp.id,
        title=lp.title,
        authors=lp.authors,
        abstract=lp.abstract,
        url=lp.url,
        pdf_url=lp.pdf_url,
        published_date=lp.published_date,
        source=lp.source,
        has_code=bool(lp.code_url),
        code_url=lp.code_url,
        citations=lp.citations,
        fetched_at=datetime.now(tz=timezone.utc),
    )


def _s2_headers() -> dict:
    """Return request headers for Semantic Scholar, including API key if set."""
    headers = {"User-Agent": "arxiv-intel-survey/1.0"}
    key = os.environ.get("S2_API_KEY", "").strip()
    if key:
        headers["x-api-key"] = key
    return headers

_PWC_BASE = "https://paperswithcode.com/api/v1"
_S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
_REQUEST_TIMEOUT = 20
_S2_BATCH_SIZE = 100  # S2 allows up to 500 per batch but we keep it conservative


# ---------------------------------------------------------------------------
# Lightweight result type (no DB model dependency)
# ---------------------------------------------------------------------------

@dataclass
class LivePaper:
    """Minimal paper record returned by live search — not stored in DB."""
    id: str
    title: str
    authors: List[str]
    abstract: str
    url: str
    pdf_url: str = ""
    published_date: Optional[date] = None
    code_url: str = ""
    source: str = "arxiv"
    citations: int = 0                  # filled by S2 enrichment
    influential_citations: int = 0      # highly-weighted citations per S2

    @property
    def year(self) -> str:
        return str(self.published_date.year) if self.published_date else "?"

    @property
    def authors_short(self) -> str:
        if not self.authors:
            return "Unknown"
        s = ", ".join(self.authors[:3])
        return s + " et al." if len(self.authors) > 3 else s

    def influence_score(self) -> float:
        """A single float that balances recency and citation impact.

        Logic:
        - Papers < 12 months old: recency matters most (citations haven't
          accumulated yet), scored primarily by how new they are.
        - Papers 1–3 years old: blend of citations and recency.
        - Papers > 3 years old: citations dominate — a landmark paper
          should rank above a mediocre recent one.
        """
        today = date.today()
        age_days = (today - self.published_date).days if self.published_date else 3650

        # Citation signal: log-scale so 10k citations isn't 1000× better than 10
        import math
        cit_score = math.log1p(self.citations) * 10 + math.log1p(self.influential_citations) * 5

        if age_days < 365:
            # Very recent: weight recency 80%, citations 20%
            recency = max(0, 1.0 - age_days / 365)
            return recency * 80 + cit_score * 0.2
        elif age_days < 3 * 365:
            # 1–3 years: 50/50
            recency = max(0, 1.0 - age_days / (3 * 365))
            return recency * 40 + cit_score * 0.6
        else:
            # Older: citations dominate
            return cit_score


# ---------------------------------------------------------------------------
# arXiv live search
# ---------------------------------------------------------------------------

def search_arxiv_live(
    query: str,
    max_results: int = 60,
    sort_by: arxiv.SortCriterion = arxiv.SortCriterion.Relevance,
) -> List[LivePaper]:
    """Search arXiv by free-form query, sorted by relevance across all time.

    Uses title+abstract+all search so results span the full arXiv history.
    """
    # Build a combined title+abstract query for better precision
    ti_ab_query = f'ti:"{query}" OR abs:"{query}"'

    client = arxiv.Client(page_size=min(max_results, 100), delay_seconds=1.0, num_retries=3)
    search = arxiv.Search(
        query=ti_ab_query,
        max_results=max_results,
        sort_by=sort_by,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: List[LivePaper] = []
    try:
        for result in client.results(search):
            arxiv_id = result.entry_id.split("/abs/")[-1].split("v")[0]
            published = result.published.date() if result.published else None
            authors = [a.name for a in result.authors]
            papers.append(LivePaper(
                id=arxiv_id,
                title=result.title.strip(),
                authors=authors,
                abstract=(result.summary or "").strip(),
                url=result.entry_id,
                pdf_url=result.pdf_url or "",
                published_date=published,
                source="arxiv",
            ))
    except Exception as exc:
        logger.warning("arXiv live search error: %s", exc)

    return papers


def search_arxiv_live_broad(
    query: str,
    max_results: int = 40,
) -> List[LivePaper]:
    """Broader arXiv search using all-fields matching (catches more synonyms)."""
    client = arxiv.Client(page_size=min(max_results, 100), delay_seconds=1.0, num_retries=3)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers: List[LivePaper] = []
    try:
        for result in client.results(search):
            arxiv_id = result.entry_id.split("/abs/")[-1].split("v")[0]
            published = result.published.date() if result.published else None
            papers.append(LivePaper(
                id=arxiv_id,
                title=result.title.strip(),
                authors=[a.name for a in result.authors],
                abstract=(result.summary or "").strip(),
                url=result.entry_id,
                pdf_url=result.pdf_url or "",
                published_date=published,
                source="arxiv",
            ))
    except Exception as exc:
        logger.warning("arXiv broad search error: %s", exc)

    return papers


# ---------------------------------------------------------------------------
# Papers With Code live search
# ---------------------------------------------------------------------------

def search_pwc_live(query: str, max_results: int = 20) -> List[LivePaper]:
    """Search Papers With Code for papers matching the query."""
    params = urlencode({"q": query, "page": 1, "items_per_page": max_results})
    url = f"{_PWC_BASE}/papers/?{params}"

    papers: List[LivePaper] = []
    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT)
        if not resp.ok or not resp.text.strip():
            return []
        data = resp.json()
        results = data.get("results", [])
        for item in results:
            arxiv_id = item.get("arxiv_id") or item.get("id") or ""
            title = item.get("title") or ""
            abstract = item.get("abstract") or ""
            authors = [a.get("name", "") for a in item.get("authors", [])]
            date_str = item.get("published") or item.get("date") or ""
            published = None
            if date_str:
                try:
                    published = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    pass
            code_url = ""
            repos = item.get("repositories") or []
            if repos:
                code_url = repos[0].get("url", "")

            if not title:
                continue
            papers.append(LivePaper(
                id=arxiv_id or title[:20].lower().replace(" ", "-"),
                title=title,
                authors=authors,
                abstract=abstract,
                url=f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                code_url=code_url,
                published_date=published,
                source="paperswithcode",
            ))
    except Exception as exc:
        logger.warning("PwC live search error: %s", exc)

    return papers


# ---------------------------------------------------------------------------
# Semantic Scholar citation enrichment
# ---------------------------------------------------------------------------

def enrich_with_citations(papers: List[LivePaper]) -> None:
    """Batch-fetch citation counts from Semantic Scholar and fill them in-place.

    Uses the S2 batch endpoint — much faster than one request per paper.
    Silently skips on any error (citations are optional enrichment).
    """
    ids_with_arxiv = [p for p in papers if p.id and p.source == "arxiv"]
    if not ids_with_arxiv:
        return

    # S2 batch in chunks
    for i in range(0, len(ids_with_arxiv), _S2_BATCH_SIZE):
        chunk = ids_with_arxiv[i : i + _S2_BATCH_SIZE]
        s2_ids = [f"arXiv:{p.id}" for p in chunk]
        try:
            resp = requests.post(
                _S2_BATCH_URL,
                json={"ids": s2_ids},
                params={"fields": "citationCount,influentialCitationCount,externalIds"},
                timeout=_REQUEST_TIMEOUT,
                headers=_s2_headers(),
            )
            if not resp.ok:
                logger.debug("S2 batch returned %s", resp.status_code)
                continue
            data = resp.json()
            # data is a list aligned with s2_ids
            id_to_paper = {p.id: p for p in chunk}
            for item in data:
                if not item:
                    continue
                ext_ids = item.get("externalIds") or {}
                arxiv_id = ext_ids.get("ArXiv") or ""
                if arxiv_id and arxiv_id in id_to_paper:
                    paper = id_to_paper[arxiv_id]
                    paper.citations = item.get("citationCount") or 0
                    paper.influential_citations = item.get("influentialCitationCount") or 0
        except Exception as exc:
            logger.debug("S2 citation enrichment error: %s", exc)
            break  # don't hammer S2 if it's down
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# Author-specific arXiv search
# ---------------------------------------------------------------------------

def search_arxiv_by_author(
    author_name: str,
    max_results: int = 60,
) -> List[LivePaper]:
    """Search arXiv for papers authored by *author_name*.

    Uses both ``au:"name"`` (exact author field) and ``au:last_name`` (broad)
    queries merged and deduplicated to maximise recall.
    """
    parts = author_name.strip().split()
    last_name = parts[-1] if parts else author_name

    papers: List[LivePaper] = []
    seen: set = set()

    for query in (f'au:"{author_name}"', f"au:{last_name}"):
        client = arxiv.Client(page_size=min(max_results, 100), delay_seconds=1.0, num_retries=3)
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
            sort_order=arxiv.SortOrder.Descending,
        )
        try:
            for result in client.results(search):
                arxiv_id = result.entry_id.split("/abs/")[-1].split("v")[0]
                if arxiv_id in seen:
                    continue
                seen.add(arxiv_id)
                # Only keep if author name actually appears in the author list
                result_authors = [a.name for a in result.authors]
                name_lower = author_name.lower()
                if not any(name_lower in a.lower() or last_name.lower() in a.lower()
                           for a in result_authors):
                    continue
                published = result.published.date() if result.published else None
                papers.append(LivePaper(
                    id=arxiv_id,
                    title=result.title.strip(),
                    authors=result_authors,
                    abstract=(result.summary or "").strip(),
                    url=result.entry_id,
                    pdf_url=result.pdf_url or "",
                    published_date=published,
                    source="arxiv",
                ))
        except Exception as exc:
            logger.warning("arXiv author search error for '%s': %s", author_name, exc)
        time.sleep(1.0)

    return papers


# ---------------------------------------------------------------------------
# Combined live search
# ---------------------------------------------------------------------------

def live_survey_search(
    query: str,
    arxiv_max: int = 60,
    pwc_max: int = 20,
) -> List[LivePaper]:
    """Run all live searches, enrich with citation counts, return ranked list.

    Ranking balances recency and citation influence:
    - Recent papers (< 1 year): ranked mostly by recency
    - Older papers: ranked mostly by citation count
    This ensures landmark papers from 5+ years ago surface alongside
    the latest work, weighted by their real-world impact.
    """
    results: List[LivePaper] = []

    # 1. Precise arXiv title+abstract search (high precision, all years)
    precise = search_arxiv_live(query, max_results=arxiv_max)
    results.extend(precise)
    if precise:
        time.sleep(1.0)

    # 2. Broad all-fields arXiv search (catches synonyms)
    broad = search_arxiv_live_broad(query, max_results=30)
    results.extend(broad)
    if broad:
        time.sleep(1.0)

    # 3. Papers With Code (code links + any unique papers)
    pwc = search_pwc_live(query, max_results=pwc_max)
    pwc_by_id = {p.id: p for p in pwc if p.id}
    for p in results:
        if p.id in pwc_by_id and pwc_by_id[p.id].code_url:
            p.code_url = pwc_by_id[p.id].code_url
    existing_ids = {p.id for p in results}
    for p in pwc:
        if p.id not in existing_ids:
            results.append(p)

    # Deduplicate by ID
    seen: set = set()
    unique: List[LivePaper] = []
    for p in results:
        if p.id not in seen:
            seen.add(p.id)
            unique.append(p)

    # 4. Enrich with Semantic Scholar citation counts
    try:
        enrich_with_citations(unique)
    except Exception as exc:
        logger.debug("Citation enrichment skipped: %s", exc)

    # 5. Rank by influence score (recency + citations blended by age)
    unique.sort(key=lambda p: p.influence_score(), reverse=True)

    return unique
