"""Fetcher sub-package for the Arxiv Intelligence System.

Public exports
--------------
FetchResult
    Dataclass summarising the outcome of a full fetch cycle.

ArxivFetcher
    Fetches papers from the arXiv API by category and/or custom query.

PapersWithCodeFetcher
    Fetches recently published papers-with-code from the PwC REST API.

SemanticScholarFetcher
    Enriches papers with citation counts and provides author/paper search
    via the Semantic Scholar Graph API.

FetchCoordinator
    Orchestrates all fetchers, deduplicates results, and persists to the DB.
"""

from .arxiv_fetcher import ArxivFetcher
from .coordinator import FetchCoordinator, FetchResult
from .paperswithcode import PapersWithCodeFetcher
from .semantic_scholar import SemanticScholarFetcher

__all__ = [
    "FetchResult",
    "ArxivFetcher",
    "PapersWithCodeFetcher",
    "SemanticScholarFetcher",
    "FetchCoordinator",
]
