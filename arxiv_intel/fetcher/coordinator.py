"""Fetch coordinator for the Arxiv Intelligence System.

Orchestrates all enabled fetchers, deduplicates results, persists to the
database, and returns a ``FetchResult`` summary.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from arxiv_intel.config import ConfigLoader
from arxiv_intel.database import Database
from arxiv_intel.models import Paper

from .arxiv_fetcher import ArxivFetcher
from .paperswithcode import PapersWithCodeFetcher
from .semantic_scholar import SemanticScholarFetcher

logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """Summary statistics for a completed fetch cycle.

    Attributes
    ----------
    new_papers:
        Number of papers inserted for the first time.
    updated_papers:
        Number of already-known papers that were updated (e.g. citation count).
    total_fetched:
        Total number of papers retrieved from all sources before dedup.
    errors:
        List of error messages encountered during the fetch.
    sources_used:
        Names of the data sources that were queried.
    duration_seconds:
        Wall-clock time for the entire fetch cycle in seconds.
    """

    new_papers: int = 0
    updated_papers: int = 0
    total_fetched: int = 0
    errors: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Deduplication helpers
# ---------------------------------------------------------------------------


def _normalise_title(title: str) -> str:
    """Return a lowercase, stripped version of a paper title for comparison."""
    return " ".join(title.lower().split())


def _deduplicate(papers: List[Paper]) -> List[Paper]:
    """Deduplicate *papers* by arXiv ID and then by exact (normalised) title.

    When two records share the same ID the first encountered is kept.
    When two records share the same normalised title the first is kept, but
    if the later one has ``has_code=True`` and the earlier one does not, the
    code URL is merged into the earlier record.
    """
    by_id: Dict[str, Paper] = {}
    by_title: Dict[str, str] = {}  # normalised_title -> paper_id

    for paper in papers:
        norm = _normalise_title(paper.title)

        if paper.id in by_id:
            # Same ID — merge code info if useful
            existing = by_id[paper.id]
            if paper.has_code and not existing.has_code:
                existing.has_code = True
                existing.code_url = paper.code_url
            # Update citation count if higher
            if paper.citations > existing.citations:
                existing.citations = paper.citations
            continue

        if norm in by_title:
            # Same title, different ID — merge into the first seen record
            existing = by_id[by_title[norm]]
            if paper.has_code and not existing.has_code:
                existing.has_code = True
                existing.code_url = paper.code_url
            if paper.citations > existing.citations:
                existing.citations = paper.citations
            continue

        by_id[paper.id] = paper
        by_title[norm] = paper.id

    return list(by_id.values())


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


class FetchCoordinator:
    """Orchestrates all fetchers and persists results to the database.

    Parameters
    ----------
    config:
        A loaded ``ConfigLoader`` instance.
    db:
        An initialised ``Database`` instance.
    """

    def __init__(self, config: ConfigLoader, db: Database) -> None:
        self.config = config
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_full_fetch(self, since_date: Optional[date] = None) -> FetchResult:
        """Run all enabled fetchers and persist the results.

        Steps
        -----
        1. Run enabled fetchers (arXiv, PapersWithCode, Semantic Scholar search).
        2. Deduplicate across all results by ID and normalised title.
        3. Optionally enrich citation counts via Semantic Scholar.
        4. Insert new papers and update known ones in the database.
        5. Return a ``FetchResult`` summary.

        Parameters
        ----------
        since_date:
            Only process papers published on or after this date.  Defaults to
            7 days ago when ``None``.

        Returns
        -------
        FetchResult
        """
        start_time = datetime.now(tz=timezone.utc)

        if since_date is None:
            since_date = (datetime.now(tz=timezone.utc).date() - timedelta(days=7))

        result = FetchResult()
        all_papers: List[Paper] = []

        console.print(
            Panel(
                f"[bold cyan]Arxiv Intelligence System — Fetch Cycle[/bold cyan]\n"
                f"Since date: [yellow]{since_date}[/yellow]  |  "
                f"Sources enabled: arxiv={self.config.source_arxiv}, "
                f"pwc={self.config.source_paperswithcode}, "
                f"s2={self.config.source_semantic_scholar}",
                expand=False,
            )
        )

        # ── 1. arXiv ──────────────────────────────────────────────────
        if self.config.source_arxiv:
            console.rule("[bold blue]Step 1/3 — arXiv Fetcher")
            try:
                arxiv_fetcher = ArxivFetcher(
                    max_results_per_query=self.config.max_papers_per_run
                    // max(len(self.config.categories) + len(self.config.custom_queries), 1),
                )
                arxiv_papers = arxiv_fetcher.fetch_all(
                    categories=self.config.categories,
                    custom_queries=self.config.custom_queries,
                    since_date=since_date,
                )
                all_papers.extend(arxiv_papers)
                result.sources_used.append("arxiv")
                logger.info("arXiv fetcher returned %d papers", len(arxiv_papers))
            except Exception as exc:
                msg = f"arXiv fetcher failed: {exc}"
                logger.error(msg)
                result.errors.append(msg)
        else:
            console.print("[dim]arXiv fetcher disabled in config — skipping.[/dim]")

        # ── 2. Papers With Code ────────────────────────────────────────
        if self.config.source_paperswithcode:
            console.rule("[bold blue]Step 2/3 — PapersWithCode Fetcher")
            try:
                pwc_fetcher = PapersWithCodeFetcher()
                days_back = max(
                    1,
                    (datetime.now(tz=timezone.utc).date() - since_date).days,
                )
                pwc_papers = pwc_fetcher.fetch_recent(days=days_back)
                all_papers.extend(pwc_papers)
                result.sources_used.append("paperswithcode")
                logger.info("PapersWithCode fetcher returned %d papers", len(pwc_papers))
            except Exception as exc:
                msg = f"PapersWithCode fetcher failed: {exc}"
                logger.error(msg)
                result.errors.append(msg)
        else:
            console.print("[dim]PapersWithCode fetcher disabled in config — skipping.[/dim]")

        # ── 3. Deduplicate ─────────────────────────────────────────────
        console.rule("[bold blue]Step 3/3 — Deduplication & Persistence")
        result.total_fetched = len(all_papers)
        deduplicated = _deduplicate(all_papers)
        console.print(
            f"[yellow]Deduplication:[/yellow] {result.total_fetched} → "
            f"[bold]{len(deduplicated)}[/bold] unique papers."
        )

        # ── 4. Optional Semantic Scholar enrichment ───────────────────
        if self.config.source_semantic_scholar and deduplicated:
            console.print("[cyan]Enriching citation counts via Semantic Scholar...[/cyan]")
            try:
                s2_fetcher = SemanticScholarFetcher(api_key=os.environ.get("S2_API_KEY"))
                self._enrich_with_s2(deduplicated, s2_fetcher)
                result.sources_used.append("semantic_scholar")
            except Exception as exc:
                msg = f"Semantic Scholar enrichment failed: {exc}"
                logger.error(msg)
                result.errors.append(msg)

        # ── 5. Persist to database ─────────────────────────────────────
        new_count, updated_count = self._persist(deduplicated)
        result.new_papers = new_count
        result.updated_papers = updated_count

        # ── Timing ────────────────────────────────────────────────────
        end_time = datetime.now(tz=timezone.utc)
        result.duration_seconds = (end_time - start_time).total_seconds()

        self._print_summary(result, len(deduplicated))
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _enrich_with_s2(
        self,
        papers: List[Paper],
        fetcher: SemanticScholarFetcher,
        sample_size: int = 30,
    ) -> None:
        """Enrich up to *sample_size* papers with citation counts from S2.

        We only enrich a sample to stay within the public API's rate limits.
        Papers with zero citations are prioritised.
        """
        # Prioritise papers without citation data
        candidates = sorted(papers, key=lambda p: p.citations)[:sample_size]

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
                "[cyan]Enriching via Semantic Scholar...", total=len(candidates)
            )
            for paper in candidates:
                try:
                    fetcher.enrich_paper(paper)
                except Exception as exc:
                    logger.debug("S2 enrichment failed for '%s': %s", paper.title[:50], exc)
                finally:
                    progress.advance(task)

    def _persist(self, papers: List[Paper]) -> tuple[int, int]:
        """Insert or update *papers* in the database.

        Returns
        -------
        tuple[int, int]
            ``(new_count, updated_count)``
        """
        new_count = 0
        updated_count = 0

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
                "[cyan]Saving to database...", total=len(papers)
            )
            for paper in papers:
                try:
                    existing = self.db.get_paper(paper.id)
                    if existing is None:
                        self.db.insert_paper(paper)
                        new_count += 1
                    else:
                        # Preserve analysis data from existing record
                        paper.summary = existing.summary
                        paper.novelty_score = existing.novelty_score
                        paper.impact_score = existing.impact_score
                        paper.reproducibility_score = existing.reproducibility_score
                        paper.relevance_score = existing.relevance_score
                        paper.overall_score = existing.overall_score
                        paper.method_name = existing.method_name
                        paper.method_description = existing.method_description
                        paper.is_breakthrough = existing.is_breakthrough
                        paper.breakthrough_reason = existing.breakthrough_reason
                        paper.directions = existing.directions
                        paper.key_contributions = existing.key_contributions
                        paper.limitations = existing.limitations
                        paper.analyzed_at = existing.analyzed_at
                        paper.is_read = existing.is_read
                        paper.is_starred = existing.is_starred

                        # Upgrade has_code if we now know about a repo
                        if paper.has_code and not existing.has_code:
                            pass  # new has_code=True is already on paper
                        elif not paper.has_code and existing.has_code:
                            paper.has_code = existing.has_code
                            paper.code_url = existing.code_url

                        self.db.update_paper(paper)
                        updated_count += 1
                except Exception as exc:
                    logger.error("Failed to persist paper '%s': %s", paper.id, exc)
                finally:
                    progress.advance(task)

        return new_count, updated_count

    @staticmethod
    def _print_summary(result: FetchResult, unique_count: int) -> None:
        """Print a Rich summary table for the completed fetch cycle."""
        table = Table(title="Fetch Cycle Summary", show_header=False, expand=False)
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Value", style="bold green")

        table.add_row("Sources used", ", ".join(result.sources_used) or "none")
        table.add_row("Total fetched (raw)", str(result.total_fetched))
        table.add_row("Unique papers", str(unique_count))
        table.add_row("New papers saved", str(result.new_papers))
        table.add_row("Papers updated", str(result.updated_papers))
        table.add_row("Errors", str(len(result.errors)))
        table.add_row("Duration", f"{result.duration_seconds:.1f}s")

        console.print(table)

        if result.errors:
            console.print("[bold red]Errors encountered during fetch:[/bold red]")
            for err in result.errors:
                console.print(f"  [red]• {err}[/red]")
