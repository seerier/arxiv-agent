"""Beautiful Click CLI for the Arxiv Intelligence System.

Entry point: ``python run.py <command> [options]``

All commands share a lazily-initialised application context that loads
the config, database, analysers, reporter, and knowledge base once and
reuses them across helper functions.
"""

from __future__ import annotations

import os
import sys
import webbrowser
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import click
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

console = Console()


# ---------------------------------------------------------------------------
# Helpers — visual
# ---------------------------------------------------------------------------

def _score_bar(score: float, width: int = 10) -> str:
    """Return a Unicode block-character bar for a 0–10 score."""
    filled = round((score / 10.0) * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _score_colour(score: float) -> str:
    if score >= 8.0:
        return "bold gold1"
    if score >= 6.0:
        return "bold green"
    if score >= 4.0:
        return "bold yellow"
    return "bold red"


def _status_badge(status: str) -> str:
    mapping = {
        "emerging": "[bold green]● EMERGING[/bold green]",
        "stable": "[bold yellow]● STABLE[/bold yellow]",
        "declining": "[bold red]● DECLINING[/bold red]",
        "dead": "[bold dim]● DEAD[/bold dim]",
    }
    return mapping.get(status.lower(), f"[dim]{status}[/dim]")


def _truncate(text: str, max_len: int = 60) -> str:
    return text[:max_len - 1] + "…" if len(text) > max_len else text


def _paper_link(paper_id: str, title: str, max_len: int = 60) -> str:
    short = _truncate(title, max_len)
    url = f"https://arxiv.org/abs/{paper_id}"
    return f"[link={url}]{short}[/link]"


# ---------------------------------------------------------------------------
# Application context factory
# ---------------------------------------------------------------------------

def _build_app():
    """Lazily build and return the full application object graph."""
    from arxiv_agent.config import get_config
    from arxiv_agent.database import Database
    from arxiv_agent.fetcher import FetchCoordinator
    from arxiv_agent.analyzer import PaperAnalyzer, DirectionAnalyzer, KnowledgeAnalyzer
    from arxiv_agent.reporter import DailyReporter, KnowledgeReporter
    from arxiv_agent.knowledge import KnowledgeBase

    try:
        cfg = get_config()
    except EnvironmentError as exc:
        console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        sys.exit(1)

    db = Database(cfg.db_path)
    coordinator = FetchCoordinator(config=cfg, db=db)
    paper_analyzer = PaperAnalyzer()
    direction_analyzer = DirectionAnalyzer()
    knowledge_analyzer = KnowledgeAnalyzer()
    daily_reporter = DailyReporter(report_dir=cfg.report_dir)
    knowledge_reporter = KnowledgeReporter(report_dir=cfg.report_dir)
    knowledge_base = KnowledgeBase(
        db=db,
        analyzer=knowledge_analyzer,
        direction_analyzer=direction_analyzer,
        reporter=knowledge_reporter,
    )

    return {
        "cfg": cfg,
        "db": db,
        "coordinator": coordinator,
        "paper_analyzer": paper_analyzer,
        "direction_analyzer": direction_analyzer,
        "knowledge_analyzer": knowledge_analyzer,
        "daily_reporter": daily_reporter,
        "knowledge_reporter": knowledge_reporter,
        "knowledge_base": knowledge_base,
    }


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
def cli():
    """Arxiv Intelligence System — AI-powered research monitoring CLI."""


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--since", default=None, help="Fetch since date YYYY-MM-DD (default: 7 days ago)")
@click.option("--analyze/--no-analyze", default=True, help="Analyse new papers with Claude after fetch")
def fetch(since: Optional[str], analyze: bool):
    """Fetch latest papers from all configured sources."""
    app = _build_app()
    db = app["db"]
    coordinator = app["coordinator"]
    paper_analyzer = app["paper_analyzer"]

    since_date: Optional[date] = None
    if since:
        try:
            since_date = date.fromisoformat(since)
        except ValueError:
            console.print(f"[bold red]Invalid date format:[/bold red] {since!r}. Use YYYY-MM-DD.")
            sys.exit(1)

    console.print()
    console.print(Panel("[bold cyan]Arxiv Intelligence — Paper Fetch[/bold cyan]", expand=False))

    try:
        fetch_result = coordinator.run_full_fetch(since_date=since_date)
    except Exception as exc:
        console.print(f"[bold red]Fetch failed:[/bold red] {exc}")
        sys.exit(1)

    # Summary table
    table = Table(title="Fetch Results", box=box.ROUNDED, show_header=False, expand=False)
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", style="bold white")
    table.add_row("Sources used", ", ".join(fetch_result.sources_used) or "none")
    table.add_row("Total fetched (raw)", str(fetch_result.total_fetched))
    table.add_row("New papers saved", f"[bold green]{fetch_result.new_papers}[/bold green]")
    table.add_row("Papers updated", str(fetch_result.updated_papers))
    table.add_row("Errors", f"[red]{len(fetch_result.errors)}[/red]" if fetch_result.errors else "0")
    table.add_row("Duration", f"{fetch_result.duration_seconds:.1f}s")
    console.print(table)

    if fetch_result.errors:
        console.print("\n[bold red]Fetch errors:[/bold red]")
        for err in fetch_result.errors:
            console.print(f"  [red]• {err}[/red]")

    # Analyse
    if analyze:
        unanalyzed = db.get_unanalyzed_papers(limit=100)
        if unanalyzed:
            console.print(f"\n[bold cyan]Analysing {len(unanalyzed)} new paper(s) with Claude…[/bold cyan]")
            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(),
                    TextColumn("{task.completed}/{task.total}"),
                    TimeElapsedColumn(),
                    console=console,
                ) as progress:
                    task = progress.add_task("Analysing papers", total=len(unanalyzed))
                    analyzed_papers = []
                    for paper in unanalyzed:
                        try:
                            paper_analyzer.analyze_paper(paper)
                            db.update_paper(paper)
                        except Exception as exc:
                            console.print(f"  [yellow]Warning: failed to analyse {paper.id}: {exc}[/yellow]")
                        analyzed_papers.append(paper)
                        progress.advance(task)

                success = sum(1 for p in analyzed_papers if p.analyzed_at is not None)
                console.print(
                    Panel(
                        f"[green]Analysis complete:[/green] {success}/{len(unanalyzed)} papers analysed.",
                        expand=False,
                    )
                )
            except Exception as exc:
                console.print(f"[bold red]Analysis step failed:[/bold red] {exc}")
        else:
            console.print("\n[dim]No unanalysed papers found — everything is up to date.[/dim]")
    else:
        console.print("\n[dim]Skipping analysis (--no-analyze).[/dim]")

    # ── Auto-embed new papers (if sentence-transformers installed) ───────
    from arxiv_agent.embedding import embed_batch, is_available, paper_text, vec_to_blob
    if is_available():
        to_embed = db.get_papers_without_embeddings(limit=500)
        if to_embed:
            console.print(f"\n[cyan]Computing embeddings for {len(to_embed)} new paper(s)…[/cyan]")
            try:
                texts = [paper_text(p.title, p.abstract or "") for p in to_embed]
                vecs = embed_batch(texts)
                for paper, vec in zip(to_embed, vecs):
                    db.save_embedding(paper.id, vec_to_blob(vec))
                console.print(f"[dim]Embeddings done — semantic search is active.[/dim]")
            except Exception as exc:
                console.print(f"[yellow]Embedding step failed (non-fatal): {exc}[/yellow]")

    console.print()


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--open/--no-open", "open_browser", default=True, help="Open the HTML report in a browser")
@click.option(
    "--period",
    type=click.Choice(["daily", "weekly", "monthly"], case_sensitive=False),
    default="daily",
    show_default=True,
    help="Report period: daily (today), weekly (last 7 days), monthly (last 30 days)",
)
def report(open_browser: bool, period: str):
    """Generate a research digest (daily, weekly, or monthly)."""
    app = _build_app()
    db = app["db"]
    daily_reporter = app["daily_reporter"]
    knowledge_base = app["knowledge_base"]

    period = period.lower()
    period_labels = {"daily": "Daily Digest", "weekly": "Weekly Digest", "monthly": "Monthly Digest"}
    period_days = {"daily": 1, "weekly": 7, "monthly": 30}
    bt_days = {"daily": 1, "weekly": 7, "monthly": 30}

    console.print()
    console.print(Panel(
        f"[bold cyan]Arxiv Intelligence — {period_labels[period]}[/bold cyan]",
        expand=False,
    ))

    today = date.today()
    if period == "daily":
        papers = db.get_papers_by_date(today)
        if not papers:
            papers = db.get_recent_papers(days=3, limit=50)
    else:
        days = period_days[period]
        limit = 200 if period == "monthly" else 100
        papers = db.get_recent_papers(days=days, limit=limit)

    if not papers:
        console.print(
            "[bold yellow]No papers found.[/bold yellow] "
            "Run [cyan]fetch[/cyan] first to populate the database."
        )
        return

    console.print(f"[dim]Building {period} digest from {len(papers)} paper(s)…[/dim]")

    breakthroughs = knowledge_base.get_breakthroughs(days=bt_days[period])
    db_stats = db.get_stats()

    try:
        daily_report = daily_reporter.generate(
            papers=papers,
            report_date=today,
            breakthroughs=breakthroughs,
            db_stats=db_stats,
            period=period,
        )
        db.insert_daily_report(daily_report)
    except Exception as exc:
        console.print(f"[bold red]Report generation failed:[/bold red] {exc}")
        sys.exit(1)

    # Resolve paper objects for rich terminal render
    sorted_papers = sorted(papers, key=lambda p: p.overall_score, reverse=True)
    top_papers = sorted_papers[:5]
    breakthrough_paper = max(breakthroughs, key=lambda p: p.overall_score) if breakthroughs else None
    if breakthrough_paper is None and top_papers and top_papers[0].is_breakthrough:
        breakthrough_paper = top_papers[0]

    daily_reporter.render_terminal_with_papers(
        report=daily_report,
        top_papers=top_papers,
        breakthrough=breakthrough_paper,
    )

    if open_browser and daily_report.html_path:
        html_path = Path(daily_report.html_path)
        if html_path.exists():
            webbrowser.open(html_path.as_uri())
        else:
            console.print(f"[yellow]HTML file not found at {html_path}[/yellow]")


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("query")
@click.option("--limit", default=20, show_default=True, help="Maximum number of results")
@click.option("--min-score", default=0.0, show_default=True, help="Minimum overall score filter")
def search(query: str, limit: int, min_score: float):
    """Search papers in the local database."""
    app = _build_app()
    db = app["db"]

    console.print()
    results = db.search_papers(query, limit=limit)

    if min_score > 0.0:
        results = [p for p in results if p.overall_score >= min_score]

    if not results:
        console.print(f"[bold yellow]No results found[/bold yellow] for query: [cyan]{query!r}[/cyan]")
        return

    table = Table(
        title=f"Search Results — [cyan]{query!r}[/cyan] ({len(results)} found)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold blue",
        border_style="blue",
        expand=True,
    )
    table.add_column("Score", width=14, no_wrap=True)
    table.add_column("Title", min_width=36)
    table.add_column("Authors", width=22)
    table.add_column("Date", width=11, no_wrap=True)
    table.add_column("Directions", width=22)

    for paper in results:
        score_text = Text()
        score_text.append(f"{paper.overall_score:4.1f} ", style=_score_colour(paper.overall_score))
        score_text.append(_score_bar(paper.overall_score, width=8), style="green")

        authors_str = ", ".join(paper.authors[:2])
        if len(paper.authors) > 2:
            authors_str += f" +{len(paper.authors) - 2}"

        date_str = paper.published_date.isoformat() if paper.published_date else "—"
        directions_str = ", ".join(paper.directions[:2]) if paper.directions else "—"
        if len(paper.directions) > 2:
            directions_str += f" +{len(paper.directions) - 2}"

        title_cell = _paper_link(paper.id, paper.title, max_len=58)

        table.add_row(
            score_text,
            title_cell,
            authors_str,
            date_str,
            directions_str,
        )

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# direction
# ---------------------------------------------------------------------------

@cli.command("analyze-all-directions")
def analyze_all_directions():
    """Re-analyze every known research direction in the local database.

    Discovers all unique direction tags from papers in the DB and runs
    fresh Claude analysis for each. Useful after a large fetch.
    """
    app = _build_app()
    db = app["db"]
    direction_analyzer = app["direction_analyzer"]

    console.print()
    console.print(Panel("[bold cyan]Batch Direction Analysis[/bold cyan]", expand=False))

    try:
        results = direction_analyzer.analyze_all_directions(db)
        console.print(
            Panel(
                f"[green]Done.[/green] Analysed [bold]{len(results)}[/bold] research direction(s).",
                border_style="green",
                expand=False,
            )
        )
    except Exception as exc:
        console.print(f"[bold red]Batch analysis failed:[/bold red] {exc}")
        sys.exit(1)

    console.print()


@cli.command()
@click.argument("name")
@click.option("--open/--no-open", "open_browser", default=True, help="Open the HTML report in a browser")
@click.option("--refresh", is_flag=True, default=False, help="Force re-analysis even if cached")
@click.option("--no-live", is_flag=True, default=False, help="Skip live internet search, use local DB only")
@click.option("--arxiv-results", default=60, show_default=True, help="Max papers to fetch live from arXiv")
def direction(name: str, open_browser: bool, refresh: bool, no_live: bool, arxiv_results: int):
    """Get a comprehensive analysis of a research direction.

    Searches arXiv live across all time (70%) plus local DB (10%) to give you
    an up-to-date, citation-aware analysis — not just recent fetches.
    """
    from arxiv_agent.fetcher.live_search import live_survey_search, live_to_paper

    app = _build_app()
    db = app["db"]
    knowledge_base = app["knowledge_base"]

    console.print()
    console.print(Panel(
        f"[bold cyan]Direction Analysis:[/bold cyan] {name}\n"
        f"[dim]Live arXiv search + local DB + Claude knowledge[/dim]",
        expand=False,
    ))

    if refresh:
        existing = db.get_direction(name)
        if existing is not None:
            existing.analyzed_at = None
            db.update_direction(existing)
            console.print("[dim]Cache invalidated — running fresh analysis…[/dim]")

    # ── Live internet search (70%) ────────────────────────────────────────
    live_papers = []
    if not no_live:
        with console.status(
            f"[cyan]Searching arXiv live for '{name}'…[/cyan]", spinner="dots"
        ):
            try:
                from arxiv_agent.fetcher.live_search import LivePaper
                live_raw = live_survey_search(name, arxiv_max=arxiv_results, pwc_max=20)
                live_papers = [live_to_paper(p) for p in live_raw]
            except Exception as exc:
                console.print(f"[yellow]Live search failed (non-fatal): {exc}[/yellow]")

        if live_papers:
            years = [p.published_date.year for p in live_papers if p.published_date]
            year_range = f"{min(years)}–{max(years)}" if years else "unknown"
            cited = sum(1 for p in live_papers if p.citations > 0)
            console.print(
                f"[dim]Live search:[/dim] [green]{len(live_papers)} papers[/green] "
                f"spanning [cyan]{year_range}[/cyan]"
                + (f", {cited} with citation data" if cited else "")
            )
        else:
            console.print("[dim]Live search returned no results — using local DB only.[/dim]")

    try:
        with console.status(f"[cyan]Analysing '{name}' with Claude…[/cyan]", spinner="dots"):
            d = knowledge_base.get_or_analyze_direction(
                name, live_papers=live_papers if live_papers else None
            )
    except Exception as exc:
        console.print(f"[bold red]Analysis failed:[/bold red] {exc}")
        sys.exit(1)

    # Terminal overview
    status_badge = _status_badge(d.status)
    score_bar = _score_bar(d.worthiness_score)
    score_colour = _score_colour(d.worthiness_score)

    header_text = Text()
    header_text.append(f"{d.name}\n\n", style="bold white")
    header_text.append("Status: ", style="dim")
    header_text.append_text(Text.from_markup(status_badge))
    header_text.append("  |  Worthiness: ", style="dim")
    header_text.append(f"{d.worthiness_score:.1f}/10 ", style=score_colour)
    header_text.append(score_bar, style="green")

    console.print(Panel(header_text, border_style="blue", padding=(1, 2)))

    if d.overview:
        console.print(Panel(d.overview, title="[bold]Overview[/bold]", border_style="dim blue"))

    if d.worthiness_reasoning:
        console.print(
            Panel(
                d.worthiness_reasoning,
                title="[bold]Worthiness Reasoning[/bold]",
                border_style="dim cyan",
            )
        )

    if d.open_problems:
        problems_text = "\n".join(f"  [cyan]▸[/cyan] {p}" for p in d.open_problems)
        console.print(Panel(problems_text, title="[bold]Open Problems[/bold]", border_style="dim yellow"))

    if d.milestones:
        ms_table = Table(box=box.SIMPLE, show_header=True, header_style="bold", expand=False)
        ms_table.add_column("Date", width=12, style="dim")
        ms_table.add_column("Event")
        for ms in d.milestones:
            ms_table.add_row(ms.date, ms.event)
        console.print(Panel(ms_table, title="[bold]Milestones[/bold]", border_style="dim magenta"))

    # Top papers
    papers = db.get_papers_by_direction(name, limit=10)
    if papers:
        papers_table = Table(
            title="[bold]Top Papers[/bold]",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold blue",
            expand=True,
        )
        papers_table.add_column("Score", width=12)
        papers_table.add_column("Title")
        papers_table.add_column("Date", width=11)
        for p in papers[:8]:
            score_t = Text()
            score_t.append(f"{p.overall_score:.1f} ", style=_score_colour(p.overall_score))
            score_t.append(_score_bar(p.overall_score, width=6), style="green")
            papers_table.add_row(
                score_t,
                _paper_link(p.id, p.title),
                p.published_date.isoformat() if p.published_date else "—",
            )
        console.print(papers_table)

    # HTML report
    try:
        with console.status("[cyan]Generating HTML report…[/cyan]", spinner="dots"):
            html_path = knowledge_base.get_direction_report(name)
        console.print(f"\n[dim]Report saved to:[/dim] [cyan]{html_path}[/cyan]")
        if open_browser:
            webbrowser.open(Path(html_path).as_uri())
    except Exception as exc:
        console.print(f"[yellow]Warning: HTML report generation failed: {exc}[/yellow]")

    console.print()


# ---------------------------------------------------------------------------
# professor
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("name")
@click.option("--no-live", is_flag=True, default=False, help="Skip live internet search, use local DB only")
def professor(name: str, no_live: bool):
    """Look up a researcher profile.

    Searches arXiv live for papers by this researcher (70%), then builds a
    comprehensive profile using Claude — works even for authors not yet in
    your local database.
    """
    from arxiv_agent.fetcher.live_search import search_arxiv_by_author, enrich_with_citations, live_to_paper

    app = _build_app()
    knowledge_base = app["knowledge_base"]
    db = app["db"]

    console.print()
    console.print(Panel(
        f"[bold cyan]Researcher Profile:[/bold cyan] {name}\n"
        f"[dim]Live arXiv author search + local DB + Claude knowledge[/dim]",
        expand=False,
    ))

    # ── Live author search (70%) ───────────────────────────────────────────
    live_papers = []
    if not no_live:
        with console.status(
            f"[cyan]Searching arXiv for papers by '{name}'…[/cyan]", spinner="dots"
        ):
            try:
                live_raw = search_arxiv_by_author(name, max_results=60)
                enrich_with_citations(live_raw)
                live_papers = [live_to_paper(p) for p in live_raw]
            except Exception as exc:
                console.print(f"[yellow]Live author search failed (non-fatal): {exc}[/yellow]")

        if live_papers:
            years = [p.published_date.year for p in live_papers if p.published_date]
            year_range = f"{min(years)}–{max(years)}" if years else "unknown"
            console.print(
                f"[dim]Live search:[/dim] [green]{len(live_papers)} papers[/green] "
                f"by {name}, spanning [cyan]{year_range}[/cyan]"
            )
        else:
            console.print("[dim]Live search returned no results — using local DB only.[/dim]")

    try:
        with console.status(f"[cyan]Building profile for '{name}'…[/cyan]", spinner="dots"):
            prof = knowledge_base.get_professor_profile(
                name, live_papers=live_papers if live_papers else None
            )
    except ValueError as exc:
        console.print(f"[bold yellow]Not found:[/bold yellow] {exc}")
        return
    except Exception as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    # Build info panel
    info_lines = Text()
    info_lines.append(f"{prof.name}\n", style="bold white")
    if prof.institution:
        info_lines.append(f"Institution: ", style="dim")
        info_lines.append(f"{prof.institution}\n", style="white")
    if prof.email:
        info_lines.append(f"Email:       ", style="dim")
        info_lines.append(f"{prof.email}\n", style="cyan")
    if prof.homepage:
        info_lines.append(f"Homepage:    ", style="dim")
        info_lines.append(f"{prof.homepage}\n", style="blue underline")
    if prof.h_index:
        info_lines.append(f"h-index:     ", style="dim")
        info_lines.append(f"{prof.h_index}\n", style="green")
    if prof.citation_count:
        info_lines.append(f"Citations:   ", style="dim")
        info_lines.append(f"{prof.citation_count:,}\n", style="green")
    if prof.rating > 0:
        info_lines.append(f"Rating:      ", style="dim")
        info_lines.append(f"{prof.rating:.1f}/10 ", style=_score_colour(prof.rating))
        info_lines.append(_score_bar(prof.rating) + "\n", style="green")

    console.print(Panel(info_lines, title="[bold]Researcher Profile[/bold]", border_style="blue", padding=(1, 2)))

    if prof.rating_reasoning:
        console.print(
            Panel(
                prof.rating_reasoning,
                title="[bold]Impact Assessment[/bold]",
                border_style="dim cyan",
            )
        )

    if prof.bio:
        console.print(Panel(prof.bio, title="[bold]Bio[/bold]", border_style="dim blue"))

    if prof.research_focus:
        focus_text = "  " + "\n  ".join(f"[cyan]▸[/cyan] {f}" for f in prof.research_focus)
        console.print(Panel(focus_text, title="[bold]Research Focus[/bold]", border_style="dim cyan"))

    if prof.directions:
        dirs_text = "  " + "  ".join(f"[bold]{d}[/bold]" for d in prof.directions)
        console.print(Panel(dirs_text, title="[bold]Research Directions[/bold]", border_style="dim yellow"))

    # Top papers from DB
    if prof.top_papers:
        papers_table = Table(
            title="[bold]Top Papers[/bold]",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold",
            expand=True,
        )
        papers_table.add_column("Score", width=12)
        papers_table.add_column("Title")
        papers_table.add_column("Date", width=11)

        for paper_id in prof.top_papers[:8]:
            p = db.get_paper(paper_id)
            if p:
                score_t = Text()
                score_t.append(f"{p.overall_score:.1f} ", style=_score_colour(p.overall_score))
                score_t.append(_score_bar(p.overall_score, width=6), style="green")
                papers_table.add_row(
                    score_t,
                    _paper_link(p.id, p.title),
                    p.published_date.isoformat() if p.published_date else "—",
                )
            else:
                papers_table.add_row("—", paper_id, "—")
        console.print(papers_table)

    console.print()


# ---------------------------------------------------------------------------
# ask
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("question")
@click.option("--open/--no-open", "open_browser", default=True, help="Open the HTML report in a browser")
@click.option("--no-live", is_flag=True, default=False, help="Skip live internet search, use local DB only")
@click.option("--arxiv-results", default=50, show_default=True, help="Max papers to fetch live from arXiv")
def ask(question: str, open_browser: bool, no_live: bool, arxiv_results: int):
    """Ask a research question and get a comprehensive AI answer.

    Searches arXiv live (70%) plus your local DB (10%) for relevant papers,
    then synthesizes a deep answer with Claude's knowledge (20%).
    """
    from arxiv_agent.analyzer.claude_client import get_client
    from arxiv_agent.fetcher.live_search import live_survey_search, live_to_paper

    app = _build_app()
    db = app["db"]
    knowledge_reporter = app["knowledge_reporter"]

    console.print()
    console.print(Panel(
        f"[bold cyan]Research Q&A[/bold cyan]\n{question}\n"
        f"[dim]Live arXiv search + local DB + Claude knowledge[/dim]",
        expand=False,
    ))

    # ── 1. Live internet search (70%) ─────────────────────────────────────
    live_papers = []
    if not no_live:
        with console.status(
            f"[cyan]Searching arXiv live for relevant papers…[/cyan]", spinner="dots"
        ):
            try:
                live_raw = live_survey_search(question, arxiv_max=arxiv_results, pwc_max=15)
                live_papers = [live_to_paper(p) for p in live_raw]
            except Exception as exc:
                console.print(f"[yellow]Live search failed (non-fatal): {exc}[/yellow]")

        if live_papers:
            years = [p.published_date.year for p in live_papers if p.published_date]
            year_range = f"{min(years)}–{max(years)}" if years else "unknown"
            console.print(
                f"[dim]Live search:[/dim] [green]{len(live_papers)} papers[/green] "
                f"spanning [cyan]{year_range}[/cyan]"
            )

    # ── 2. Local DB (10%) ─────────────────────────────────────────────────
    with console.status("[cyan]Searching local database…[/cyan]", spinner="dots"):
        local_papers = db.search_papers(question, limit=20)

    # Merge: live first, then unique local
    live_ids = {p.id for p in live_papers}
    local_unique = [p for p in local_papers if p.id not in live_ids]
    all_papers = live_papers[:40] + local_unique[:10]

    if not all_papers:
        console.print("[bold yellow]No relevant papers found.[/bold yellow]")
        console.print("Try [cyan]arxiv fetch[/cyan] first, or check your query wording.")
        return

    console.print(
        f"[dim]Context: [bold]{len(all_papers)}[/bold] papers "
        f"({len(live_papers[:40])} live + {len(local_unique[:10])} local analyzed)[/dim]"
    )

    # Build context
    context_parts: List[str] = []
    for i, p in enumerate(all_papers, 1):
        authors_str = ", ".join(p.authors[:4])
        if len(p.authors) > 4:
            authors_str += " et al."
        year = p.published_date.year if p.published_date else "?"
        cit = f" | Citations: {p.citations:,}" if p.citations > 0 else ""
        summary_text = p.summary if p.summary else (p.abstract[:350] if p.abstract else "")
        context_parts.append(
            f"[{i}] \"{p.title}\" — {authors_str} ({year}){cit}\n"
            f"    {summary_text}"
        )
    context_block = "\n\n".join(context_parts)

    system_prompt = (
        "You are an expert AI research analyst. Answer the question comprehensively "
        "using the provided papers as evidence. Structure your answer with clear sections "
        "using markdown headings (## for major sections, ### for sub-sections). "
        "Cite papers by [Author et al., YEAR] format referencing the numbered list. "
        "Also draw on your own training knowledge for historical context. "
        "Be thorough, deep, and precise. Conclude with open research questions."
    )
    user_prompt = (
        f"Question: {question}\n\n"
        f"Relevant papers ({len(all_papers)} total — {len(live_papers[:40])} from live arXiv search, "
        f"{len(local_unique[:10])} from local database):\n\n{context_block}\n\n"
        f"Please provide a comprehensive, well-structured answer."
    )

    with console.status("[cyan]Consulting Claude…[/cyan]", spinner="dots"):
        try:
            client = get_client()
            answer = client.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=4000,
            )
        except Exception as exc:
            console.print(f"[bold red]Claude API error:[/bold red] {exc}")
            sys.exit(1)

    # Display answer
    console.print()
    console.print(Panel(
        Markdown(answer),
        title="[bold green]Research Answer[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))

    # Generate and open HTML report
    try:
        with console.status("[cyan]Generating HTML report…[/cyan]", spinner="dots"):
            html_path = knowledge_reporter.generate_ask_report(
                question=question,
                answer=answer,
                papers=papers,
            )
        console.print(f"\n[dim]Report saved to:[/dim] [cyan]{html_path}[/cyan]")
        if open_browser:
            webbrowser.open(Path(html_path).as_uri())
    except Exception as exc:
        console.print(f"[yellow]Warning: HTML report generation failed: {exc}[/yellow]")

    console.print()


# ---------------------------------------------------------------------------
# survey
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("area")
@click.option("--open/--no-open", "open_browser", default=True, help="Open the HTML report in a browser")
@click.option("--arxiv-results", default=60, show_default=True, help="Max papers to fetch live from arXiv")
@click.option("--no-live", is_flag=True, default=False, help="Skip live internet search, use local DB only")
def survey(area: str, open_browser: bool, arxiv_results: int, no_live: bool):
    """Generate a comprehensive survey by searching arXiv live + local DB.

    Searches arXiv across ALL time (not just recent papers), Papers With Code,
    and your local database, then synthesizes everything with Claude.

    Examples:

      arxiv survey "event cameras"

      arxiv survey "event based optical flow"

      arxiv survey "neural path guiding"

      arxiv survey "diffusion models" --arxiv-results 80
    """
    from arxiv_agent.analyzer.claude_client import get_client
    from arxiv_agent.fetcher.live_search import LivePaper, live_survey_search

    app = _build_app()
    db = app["db"]
    knowledge_reporter = app["knowledge_reporter"]

    console.print()
    console.print(Panel(
        f"[bold cyan]Area Survey:[/bold cyan] {area}\n"
        f"[dim]Live arXiv search + local DB + Claude knowledge[/dim]",
        expand=False,
    ))

    # ── 1. Live internet search (70%) ────────────────────────────────────
    live_papers: List[LivePaper] = []
    if not no_live:
        with console.status(
            f"[cyan]Searching arXiv live for '{area}'…[/cyan]", spinner="dots"
        ):
            try:
                live_papers = live_survey_search(
                    area, arxiv_max=arxiv_results, pwc_max=20
                )
            except Exception as exc:
                console.print(f"[yellow]Live search failed (non-fatal): {exc}[/yellow]")

        if live_papers:
            years = [p.published_date.year for p in live_papers if p.published_date]
            cited = [p for p in live_papers if p.citations > 0]
            top_cited = sorted(live_papers, key=lambda p: p.citations, reverse=True)
            year_range = f"{min(years)}–{max(years)}" if years else "unknown"
            console.print(
                f"[dim]Live search:[/dim] [green]{len(live_papers)} papers[/green] "
                f"spanning [cyan]{year_range}[/cyan]"
                + (f", {len(cited)} with citation data" if cited else "")
            )
            if top_cited and top_cited[0].citations > 0:
                t = top_cited[0]
                console.print(
                    f"[dim]Most cited:[/dim] \"{t.title[:60]}\" "
                    f"[cyan]{t.citations:,} citations[/cyan] ({t.year})"
                )
        else:
            console.print("[dim]Live search returned no results — using local DB only.[/dim]")

    # ── 2. Local DB (10%) ────────────────────────────────────────────────
    with console.status("[cyan]Searching local database…[/cyan]", spinner="dots"):
        local_papers = db.search_papers(area, limit=20)

    local_analyzed = [p for p in local_papers if p.analyzed_at]
    if local_analyzed:
        console.print(
            f"[dim]Local DB:[/dim] [green]{len(local_analyzed)} analyzed paper(s)[/green] "
            "with AI scores and summaries"
        )

    # ── 3. Build unified context ─────────────────────────────────────────
    # Live papers form the bulk; local analyzed papers add AI-generated summaries
    # Limit to top 50 live + 10 local for context window manageability
    live_for_context = live_papers[:50]
    local_for_context = local_analyzed[:10]

    # Deduplicate local vs live by arXiv ID
    live_ids = {p.id for p in live_for_context}
    local_unique = [p for p in local_for_context if p.id not in live_ids]

    # ── Build context block ──────────────────────────────────────────────
    context_parts: List[str] = []

    # Live papers (title + abstract + citation signal)
    for i, p in enumerate(live_for_context, 1):
        code = f" | Code: {p.code_url}" if p.code_url else ""
        cit = f" | Citations: {p.citations:,}" if p.citations > 0 else ""
        influential = f" ({p.influential_citations} influential)" if p.influential_citations > 0 else ""
        body = p.abstract[:500] if p.abstract else "(no abstract)"
        context_parts.append(
            f"[{i}] \"{p.title}\" — {p.authors_short} ({p.year}){cit}{influential}{code}\n"
            f"    {body}"
        )

    # Local analyzed papers (use AI summary if available)
    offset = len(live_for_context)
    for i, p in enumerate(local_unique, offset + 1):
        authors_str = ", ".join(p.authors[:3])
        if len(p.authors) > 3:
            authors_str += " et al."
        year = p.published_date.year if p.published_date else "?"
        body = p.summary if p.summary else (p.abstract[:400] if p.abstract else "")
        score = f" | Score: {p.overall_score:.1f}/10" if p.overall_score > 0 else ""
        code = f" | Code: {p.code_url}" if p.code_url else ""
        context_parts.append(
            f"[{i}] \"{p.title}\" — {authors_str} ({year}){score}{code}\n"
            f"    {body}"
        )

    context_block = "\n\n".join(context_parts)
    total_papers = len(live_for_context) + len(local_unique)

    console.print(
        f"\n[dim]Sending [bold]{total_papers}[/bold] papers to Claude "
        f"({len(live_for_context)} live + {len(local_unique)} local analyzed)…[/dim]"
    )

    # ── 4. Claude survey synthesis ───────────────────────────────────────
    system_prompt = (
        "You are an expert AI research analyst writing a comprehensive academic survey. "
        "You have been given a list of real papers fetched live from arXiv. "
        "Structure your survey with these sections using markdown headings:\n\n"
        "## Overview\n"
        "## History & Evolution\n"
        "## Key Methods & Techniques\n"
        "## Landmark Papers\n"
        "## Current State of the Art\n"
        "## Open Problems & Challenges\n"
        "## Emerging Directions\n"
        "## Practical Applications\n"
        "## Worthiness Assessment\n\n"
        "Rules:\n"
        "- Cite papers from the provided list as [Author et al., YEAR]\n"
        "- Also draw on your own training knowledge for context and history\n"
        "- Be comprehensive, deep, and technically precise\n"
        "- Include benchmark results, dataset names, and specific numbers where known\n"
        "- The Worthiness Assessment should answer: Is this area worth pursuing? "
        "What is the ceiling? What are the open opportunities?"
    )
    user_prompt = (
        f"Write a comprehensive survey of: \"{area}\"\n\n"
        f"I have fetched {total_papers} papers from arXiv and my local database "
        f"({len(live_for_context)} live from arXiv, {len(local_unique)} locally analyzed).\n\n"
        f"Papers:\n\n{context_block}\n\n"
        "Please write a thorough, well-structured survey. Use the papers above as primary "
        "evidence and your training knowledge for historical context and anything not covered "
        "by the papers."
    )

    with console.status("[cyan]Claude is writing the survey…[/cyan]", spinner="dots"):
        try:
            client = get_client()
            survey_text = client.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=6000,
            )
        except Exception as exc:
            console.print(f"[bold red]Claude API error:[/bold red] {exc}")
            sys.exit(1)

    # ── 5. Display + save ────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        Markdown(survey_text),
        title=f"[bold green]Survey: {area}[/bold green]",
        border_style="green",
        padding=(1, 2),
    ))

    # For HTML report, convert live papers to minimal Paper-like objects
    # so the existing template can render reference links
    html_papers = local_papers[:10]  # local papers have full Paper objects

    try:
        with console.status("[cyan]Generating HTML report…[/cyan]", spinner="dots"):
            html_path = knowledge_reporter.generate_ask_report(
                question=f"Comprehensive Survey: {area}",
                answer=survey_text,
                papers=html_papers,
            )
        survey_filename = f"survey-{area.lower().replace(' ', '-')}.html"
        survey_path = Path(html_path).parent / survey_filename
        if Path(html_path) != survey_path:
            Path(html_path).rename(survey_path)
        console.print(f"\n[dim]Survey report saved to:[/dim] [cyan]{survey_path}[/cyan]")
        if open_browser:
            webbrowser.open(survey_path.as_uri())
    except Exception as exc:
        console.print(f"[yellow]Warning: HTML report generation failed: {exc}[/yellow]")

    console.print()


# ---------------------------------------------------------------------------
# knowledge
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--emerging", is_flag=True, default=False, help="Show only emerging directions")
@click.option("--dying", is_flag=True, default=False, help="Show only declining/dead directions")
@click.option("--all", "show_all", is_flag=True, default=False, help="Show all directions (default)")
def knowledge(emerging: bool, dying: bool, show_all: bool):
    """Browse the research knowledge base."""
    app = _build_app()
    db = app["db"]
    knowledge_base = app["knowledge_base"]

    console.print()
    console.print(Panel("[bold cyan]Research Knowledge Base[/bold cyan]", expand=False))

    all_directions = knowledge_base.list_all_directions()

    if not all_directions:
        console.print(
            "[bold yellow]No directions found.[/bold yellow] "
            "Run [cyan]fetch[/cyan] and then [cyan]direction <name>[/cyan] to populate the knowledge base."
        )
        return

    # Filter
    if emerging:
        filtered = [d for d in all_directions if d.status == "emerging"]
        title_suffix = " (Emerging Only)"
    elif dying:
        filtered = [d for d in all_directions if d.status in ("declining", "dead")]
        title_suffix = " (Declining/Dead Only)"
    else:
        filtered = all_directions
        title_suffix = ""

    if not filtered:
        console.print("[bold yellow]No directions match the selected filter.[/bold yellow]")
        return

    # Count papers per direction
    def _paper_count(direction_name: str) -> int:
        papers = db.get_papers_by_direction(direction_name, limit=1000)
        return len(papers)

    table = Table(
        title=f"[bold]Research Directions{title_suffix}[/bold] ({len(filtered)} total)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold blue",
        border_style="blue",
        expand=True,
    )
    table.add_column("Name", min_width=24)
    table.add_column("Status", width=18)
    table.add_column("Worthiness", width=20)
    table.add_column("Papers", width=8, justify="right")
    table.add_column("Analysed", width=20)

    for d in filtered:
        name_text = Text(d.name, style="bold white")

        status_text = Text.from_markup(_status_badge(d.status))

        score_text = Text()
        score_text.append(f"{d.worthiness_score:.1f} ", style=_score_colour(d.worthiness_score))
        score_text.append(_score_bar(d.worthiness_score, width=8), style="green")

        papers = db.get_papers_by_direction(d.name, limit=1000)
        paper_count = str(len(papers))

        analyzed_str = (
            d.analyzed_at.strftime("%Y-%m-%d %H:%M")
            if d.analyzed_at else "[dim]never[/dim]"
        )

        table.add_row(name_text, status_text, score_text, paper_count, analyzed_str)

    console.print(table)
    console.print()


# ---------------------------------------------------------------------------
# schedule
# ---------------------------------------------------------------------------

@cli.command()
def schedule():
    """View scheduler status and next run time."""
    app = _build_app()
    cfg = app["cfg"]
    db = app["db"]

    console.print()

    # Try to import APScheduler; if not available, show config info only
    try:
        from arxiv_agent.scheduler import ArxivScheduler
        from arxiv_agent.reporter import DailyReporter
        from arxiv_agent.fetcher import FetchCoordinator
        from arxiv_agent.analyzer import PaperAnalyzer
        from arxiv_agent.knowledge import KnowledgeBase
        scheduler_available = True
    except ImportError:
        scheduler_available = False

    db_stats = db.get_stats()
    latest_report = db.get_latest_daily_report()

    info_text = Text()
    info_text.append("Schedule time:   ", style="dim")
    info_text.append(f"{cfg.schedule_time}\n", style="bold white")
    info_text.append("Schedule hour:   ", style="dim")
    info_text.append(f"{cfg.schedule_hour:02d}:{cfg.schedule_minute:02d} UTC\n", style="white")
    info_text.append("Papers in DB:    ", style="dim")
    info_text.append(f"{db_stats.get('total_papers', 0):,}\n", style="bold green")
    info_text.append("Reports in DB:   ", style="dim")
    info_text.append(f"{db_stats.get('reports_count', 0)}\n", style="white")

    if latest_report:
        info_text.append("Last report:     ", style="dim")
        info_text.append(f"{latest_report.date.isoformat()}\n", style="cyan")
        if latest_report.html_path:
            info_text.append("Report path:     ", style="dim")
            info_text.append(f"{latest_report.html_path}\n", style="blue underline")

    if not scheduler_available:
        info_text.append("\n[yellow]APScheduler not installed[/yellow] — background scheduling unavailable.\n", style="")
        info_text.append("Install with: [cyan]pip install apscheduler[/cyan]", style="")

    console.print(
        Panel(
            info_text,
            title="[bold]Arxiv Intelligence Scheduler[/bold]",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Upcoming run info
    next_run_table = Table(box=box.SIMPLE, show_header=False, expand=False)
    next_run_table.add_column("Key", style="dim", width=20)
    next_run_table.add_column("Value", style="white")
    next_run_table.add_row("Configured time", f"{cfg.schedule_time} daily")
    next_run_table.add_row("Claude model", cfg.claude_model)
    next_run_table.add_row("DB path", str(cfg.db_path))
    next_run_table.add_row("Report dir", str(cfg.report_dir))
    next_run_table.add_row("Max papers/run", str(cfg.max_papers_per_run))

    console.print(
        Panel(
            next_run_table,
            title="[bold]Configuration[/bold]",
            border_style="dim",
            padding=(0, 1),
        )
    )
    console.print()


# ---------------------------------------------------------------------------
# web
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind the web server to")
@click.option("--port", default=8080, show_default=True, help="Port to listen on")
def web(host: str, port: int):
    """Launch the web dashboard at http://localhost:8080."""
    import uvicorn
    from arxiv_agent.web.app import create_app as create_web_app
    from arxiv_agent.config import get_config
    from arxiv_agent.database import Database

    cfg = get_config()
    db = Database(cfg.db_path)
    app = create_web_app(db, cfg)

    url = f"http://{host}:{port}"
    console.print()
    console.print(
        Panel(
            f"[bold cyan]Arxiv Intelligence — Web Dashboard[/bold cyan]\n\n"
            f"  [dim]Opening:[/dim] [bold blue underline]{url}[/bold blue underline]\n\n"
            f"  Press [bold]Ctrl+C[/bold] to stop.",
            border_style="blue",
            expand=False,
        )
    )
    webbrowser.open(url)
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ---------------------------------------------------------------------------
# tui
# ---------------------------------------------------------------------------

@cli.command()
def tui():
    """Launch the interactive terminal UI."""
    try:
        from arxiv_agent.tui.app import ArxivTUI
    except ImportError as exc:
        console.print(
            Panel(
                f"[bold red]Textual not installed:[/bold red] {exc}\n\n"
                "Install with: [cyan]pip install textual[/cyan]",
                border_style="red",
            )
        )
        return

    app = ArxivTUI()
    app.run()


# ---------------------------------------------------------------------------
# embed
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--batch-size", default=64, show_default=True, help="Embedding batch size")
def embed(batch_size: int):
    """Compute semantic embeddings for all papers that don't have one yet.

    Run this once after 'fetch' to enable AI-powered search. The embedding
    model (~90 MB) is downloaded automatically on first use.
    """
    from arxiv_agent.embedding import embed_batch, is_available, paper_text, vec_to_blob

    if not is_available():
        console.print(
            "[bold red]sentence-transformers not installed.[/bold red]\n"
            "Install it with:\n"
            "  [cyan]conda install -n claudecode -c conda-forge sentence-transformers[/cyan]\n"
            "  or: [cyan]pip install sentence-transformers[/cyan]"
        )
        return

    app = _build_app()
    db = app["db"]

    papers = db.get_papers_without_embeddings(limit=2000)
    if not papers:
        console.print("[green]All papers already have embeddings.[/green]")
        return

    console.print(f"[cyan]Computing embeddings for {len(papers)} paper(s)…[/cyan]")

    texts = [paper_text(p.title, p.abstract or "") for p in papers]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Embedding…", total=len(papers))
        for i in range(0, len(papers), batch_size):
            batch_papers = papers[i : i + batch_size]
            batch_texts = texts[i : i + batch_size]
            vecs = embed_batch(batch_texts, batch_size=batch_size)
            for paper, vec in zip(batch_papers, vecs):
                db.save_embedding(paper.id, vec_to_blob(vec))
            progress.advance(task, len(batch_papers))

    console.print(f"[green]Done.[/green] Embeddings stored for {len(papers)} papers.")
    console.print("[dim]Semantic search is now active for 'search', 'survey', and 'ask'.[/dim]")


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------

@cli.command()
def stats():
    """Show database statistics."""
    app = _build_app()
    db = app["db"]

    console.print()

    try:
        s = db.get_stats()
    except Exception as exc:
        console.print(f"[bold red]Failed to retrieve stats:[/bold red] {exc}")
        sys.exit(1)

    # Main stats panel
    stats_table = Table(
        title="[bold]Database Statistics[/bold]",
        box=box.ROUNDED,
        show_header=False,
        expand=False,
        border_style="blue",
    )
    stats_table.add_column("Metric", style="cyan", no_wrap=True, width=28)
    stats_table.add_column("Value", style="bold white")

    total = s.get("total_papers", 0)
    analyzed = s.get("analyzed_papers", 0)
    analyzed_pct = f"{analyzed / total * 100:.1f}%" if total else "—"

    stats_table.add_row("Total papers", f"{total:,}")
    stats_table.add_row("Analysed papers", f"{analyzed:,}  ({analyzed_pct})")
    stats_table.add_row("Unanalysed papers", f"{s.get('unanalyzed_papers', 0):,}")
    stats_table.add_row("Breakthrough papers", f"[bold gold1]{s.get('breakthrough_papers', 0)}[/bold gold1]")
    stats_table.add_row("Papers with code", f"{s.get('papers_with_code', 0):,}")
    stats_table.add_row("Papers today", f"[bold green]{s.get('papers_today', 0)}[/bold green]")
    stats_table.add_row("", "")
    stats_table.add_row("Research directions", f"{s.get('directions_count', 0)}")
    stats_table.add_row("  Emerging", f"[green]{s.get('emerging_directions', 0)}[/green]")
    stats_table.add_row("  Declining", f"[red]{s.get('declining_directions', 0)}[/red]")
    stats_table.add_row("", "")
    stats_table.add_row("Researcher profiles", f"{s.get('professors_count', 0)}")
    stats_table.add_row("Conferences", f"{s.get('conferences_count', 0)}")
    stats_table.add_row("Reports generated", f"{s.get('reports_count', 0)}")
    stats_table.add_row("", "")
    stats_table.add_row("Avg overall score", f"{s.get('avg_overall_score', 0.0):.2f} / 10.0")
    latest_date = s.get("latest_paper_date") or "—"
    stats_table.add_row("Latest paper date", latest_date)

    console.print(stats_table)

    # Sources breakdown
    sources: dict = s.get("sources", {})
    if sources:
        src_table = Table(
            title="[bold]Papers by Source[/bold]",
            box=box.SIMPLE,
            show_header=True,
            header_style="bold",
            expand=False,
        )
        src_table.add_column("Source", style="cyan")
        src_table.add_column("Count", style="bold white", justify="right")
        src_table.add_column("Bar", width=20)
        max_count = max(sources.values()) if sources else 1
        for source, count in sorted(sources.items(), key=lambda x: x[1], reverse=True):
            bar_width = int((count / max_count) * 18)
            bar = "█" * bar_width + "░" * (18 - bar_width)
            src_table.add_row(source, f"{count:,}", f"[green]{bar}[/green]")
        console.print()
        console.print(src_table)

    console.print()


# ---------------------------------------------------------------------------
# setup — one-time API key configuration
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--key", default=None, help="Anthropic API key (or omit to be prompted)")
def setup(key: Optional[str]):
    """One-time setup: save your Anthropic API key so you never type it again."""
    console.print()
    console.print(
        Panel(
            "[bold cyan]Arxiv Intelligence — First-Time Setup[/bold cyan]\n\n"
            "Your API key is saved to [bold].env[/bold] in the project root.\n"
            "It is loaded automatically on every run — no more manual exports.",
            border_style="cyan",
            expand=False,
        )
    )

    # Get key interactively if not provided
    if not key:
        console.print(
            "\nGet your key at [bold blue underline]https://console.anthropic.com[/bold blue underline] "
            "→ API Keys → Create Key\n"
        )
        key = click.prompt("Paste your Anthropic API key", hide_input=True)

    key = key.strip().strip('"').strip("'")
    if not key.startswith("sk-"):
        console.print("[bold red]Error:[/bold red] That doesn't look like a valid Anthropic key (should start with 'sk-').")
        return

    # Write to .env in project root
    env_path = Path(__file__).parent.parent / ".env"
    lines: list[str] = []

    # Preserve any existing lines that aren't ANTHROPIC_API_KEY
    if env_path.exists():
        with open(env_path) as f:
            lines = [l for l in f.readlines() if not l.startswith("ANTHROPIC_API_KEY")]

    lines.append(f'ANTHROPIC_API_KEY="{key}"\n')

    with open(env_path, "w") as f:
        f.writelines(lines)

    # Also set in current process so the rest of this session works
    os.environ["ANTHROPIC_API_KEY"] = key

    console.print(
        Panel(
            f"[bold green]✓ API key saved to {env_path}[/bold green]\n\n"
            f"You're all set! Start with:\n\n"
            f"  [cyan]arxiv fetch[/cyan]    ← pull today's papers\n"
            f"  [cyan]arxiv report[/cyan]   ← generate your digest\n"
            f"  [cyan]arxiv web[/cyan]      ← open the dashboard\n"
            f"  [cyan]arxiv tui[/cyan]      ← terminal UI",
            border_style="green",
            expand=False,
        )
    )
    console.print()
