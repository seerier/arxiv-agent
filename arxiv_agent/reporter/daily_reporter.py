"""Daily report generator for the Arxiv Intelligence System.

Generates a rich HTML digest and a beautiful terminal rendering of the
day's top research papers, breakthroughs, and trending topics.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from arxiv_agent.models import DailyReport, Paper

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SCORE_CHARS = "▁▂▃▄▅▆▇█"


def _score_bar(score: float, width: int = 8) -> str:
    """Return a Unicode block-character bar for a 0–10 score."""
    filled = round((score / 10.0) * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _score_colour(score: float) -> str:
    """Return a Rich colour name based on the score value."""
    if score >= 8.0:
        return "bold gold1"
    if score >= 6.0:
        return "bold green"
    if score >= 4.0:
        return "bold yellow"
    return "bold red"


# ---------------------------------------------------------------------------
# DailyReporter
# ---------------------------------------------------------------------------


class DailyReporter:
    """Generates daily digest reports as both HTML files and Rich terminal output.

    Parameters
    ----------
    report_dir:
        Root directory where HTML reports are saved.  Defaults to
        ``./reports`` relative to the current working directory.
    """

    def __init__(self, report_dir: Optional[Path] = None) -> None:
        self.report_dir = Path(report_dir or "./reports")
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        # Custom filters
        self._jinja_env.filters["score_bar"] = _score_bar
        self._jinja_env.filters["score_color_css"] = self._score_color_css

    # ------------------------------------------------------------------
    # Static / helper filters
    # ------------------------------------------------------------------

    @staticmethod
    def _score_color_css(score: float) -> str:
        """Map a 0–10 score to a CSS hex colour string."""
        if score >= 8.0:
            return "#F5A623"   # gold
        if score >= 6.0:
            return "#4CAF82"   # green
        if score >= 4.0:
            return "#F5C842"   # yellow
        return "#F76464"       # red

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        papers: List[Paper],
        report_date: date,
        breakthroughs: List[Paper],
        db_stats: dict,
        period: str = "daily",
    ) -> DailyReport:
        """Generate a DailyReport, render its HTML, and save it to disk.

        Parameters
        ----------
        papers:
            Full list of papers available for today.  The top 5 by
            ``overall_score`` will be selected.
        report_date:
            The date the report covers.
        breakthroughs:
            Papers flagged as breakthroughs (``is_breakthrough=True``).
        db_stats:
            Arbitrary statistics dict surfaced in the report header
            (e.g. ``{"total_papers": 1234, "categories": 5}``).

        Returns
        -------
        DailyReport
            Fully-populated report object with ``html_path`` set.
        """
        # ── Select top 5 papers ──────────────────────────────────────────
        sorted_papers = sorted(papers, key=lambda p: p.overall_score, reverse=True)
        top_papers: List[Paper] = sorted_papers[:5]

        # ── Pick the single best breakthrough ────────────────────────────
        breakthrough: Optional[Paper] = None
        if breakthroughs:
            breakthrough = max(breakthroughs, key=lambda p: p.overall_score)
        elif top_papers and top_papers[0].is_breakthrough:
            breakthrough = top_papers[0]

        # ── Trending topics from directions ──────────────────────────────
        topic_counter: Counter = Counter()
        for p in papers:
            for d in p.directions:
                if d:
                    topic_counter[d] += 1
        trending_topics = [topic for topic, _ in topic_counter.most_common(12)]

        # ── New code releases ────────────────────────────────────────────
        new_code_releases = [p.id for p in sorted_papers if p.has_code and p.code_url][:10]

        # ── Build report object ──────────────────────────────────────────
        report = DailyReport(
            id=str(uuid.uuid4()),
            date=report_date,
            papers=[p.id for p in top_papers],
            breakthrough_paper=breakthrough.id if breakthrough else None,
            trending_topics=trending_topics,
            new_code_releases=new_code_releases,
            word_count=sum(len((p.summary or "").split()) for p in top_papers),
            created_at=datetime.utcnow(),
        )

        # ── Render and save HTML ─────────────────────────────────────────
        html_path = self._render_html(
            report=report,
            top_papers=top_papers,
            breakthrough=breakthrough,
            papers_with_code=[p for p in sorted_papers if p.has_code and p.code_url][:10],
            topic_counts=topic_counter,
            db_stats=db_stats,
            period=period,
        )
        report.html_path = str(html_path)

        return report

    def render_terminal(self, report: DailyReport) -> None:
        """Render a beautiful Rich terminal version of the report.

        Parameters
        ----------
        report:
            The DailyReport to render.  The terminal output includes a
            score-bar table, breakthrough callout, and trending topics.
        """
        # Lazy import so the module is usable even without Rich installed.
        try:
            from rich import box
            from rich.columns import Columns
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table
            from rich.text import Text
        except ImportError:
            logger.warning("Rich is not installed; skipping terminal render.")
            return

        console = Console()
        date_str = report.date.strftime("%A, %B %-d %Y")

        # ── Outer header panel ───────────────────────────────────────────
        header = Text()
        header.append("RESEARCH INTELLIGENCE DAILY", style="bold white")
        header.append(f"  ·  {date_str}", style="dim white")
        console.print()
        console.print(Panel(header, style="bold blue", padding=(0, 2)))

        # ── Breakthrough callout ─────────────────────────────────────────
        if report.breakthrough_paper:
            bt_text = Text()
            bt_text.append(" BREAKTHROUGH  ", style="bold black on gold1")
            bt_text.append(f"  {report.breakthrough_paper}", style="italic gold1")
            console.print(Panel(bt_text, border_style="gold1", title="[bold gold1]Today's Breakthrough[/]"))

        # ── Top papers table ─────────────────────────────────────────────
        table = Table(
            title="[bold]Top Papers Today[/]",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold blue",
            border_style="blue",
            min_width=80,
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Score", width=12)
        table.add_column("Title", style="bold white", min_width=40)
        table.add_column("Method", style="cyan", width=18)
        table.add_column("Code", width=5)

        for idx, paper_id in enumerate(report.papers, start=1):
            # In a live system paper objects would be looked up; we use IDs here
            # since DailyReport only stores IDs.
            score_placeholder = "—"
            bar_placeholder = "········"
            code_marker = ""
            table.add_row(
                str(idx),
                f"{bar_placeholder}",
                paper_id,
                score_placeholder,
                code_marker,
            )

        console.print(table)

        # ── Trending topics ──────────────────────────────────────────────
        if report.trending_topics:
            topic_text = Text()
            for topic in report.trending_topics:
                topic_text.append(f" {topic} ", style="bold white on dark_blue")
                topic_text.append("  ")
            console.print(Panel(topic_text, title="[bold]Trending Topics[/]", border_style="dim blue"))

        # ── Footer ───────────────────────────────────────────────────────
        console.print(f"\n[dim]Report saved to:[/] [cyan]{report.html_path}[/]")
        console.print()

    def render_terminal_with_papers(
        self,
        report: DailyReport,
        top_papers: List[Paper],
        breakthrough: Optional[Paper] = None,
    ) -> None:
        """Richer terminal render when actual Paper objects are available.

        Parameters
        ----------
        report:
            The DailyReport metadata.
        top_papers:
            Resolved Paper objects (must correspond to ``report.papers``).
        breakthrough:
            The breakthrough Paper object, if any.
        """
        try:
            from rich import box
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table
            from rich.text import Text
        except ImportError:
            logger.warning("Rich is not installed; skipping terminal render.")
            return

        console = Console()
        date_str = report.date.strftime("%A, %B %-d %Y")

        # Header
        header = Text()
        header.append("RESEARCH INTELLIGENCE DAILY", style="bold white")
        header.append(f"  ·  {date_str}", style="dim white")
        console.print()
        console.print(Panel(header, style="bold blue", padding=(0, 2)))

        # Breakthrough callout
        if breakthrough:
            bt_lines = Text()
            bt_lines.append(f"  {breakthrough.title}\n", style="bold gold1")
            bt_lines.append(
                f"  {breakthrough.breakthrough_reason or 'Flagged as a major breakthrough.'}",
                style="italic white",
            )
            console.print(
                Panel(
                    bt_lines,
                    border_style="gold1",
                    title="[bold gold1] BREAKTHROUGH [/]",
                    padding=(1, 2),
                )
            )

        # Top papers table
        table = Table(
            title="[bold]Top 5 Papers[/]",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold blue",
            border_style="blue",
            min_width=90,
        )
        table.add_column("#", style="dim", width=3)
        table.add_column("Score", width=14)
        table.add_column("Title", style="bold white", min_width=38)
        table.add_column("Method", style="cyan", width=20)
        table.add_column("Code", width=5, justify="center")

        for idx, paper in enumerate(top_papers, start=1):
            bar = _score_bar(paper.overall_score)
            colour = _score_colour(paper.overall_score)
            score_cell = Text()
            score_cell.append(f"{paper.overall_score:4.1f} ", style=colour)
            score_cell.append(bar, style="green")

            title_short = paper.title[:55] + "…" if len(paper.title) > 56 else paper.title
            code_mark = "[green]✓[/]" if paper.has_code else "[dim]·[/]"

            table.add_row(
                str(idx),
                score_cell,
                title_short,
                paper.method_name or "—",
                code_mark,
            )

        console.print(table)

        # Trending topics
        if report.trending_topics:
            topic_text = Text()
            for topic in report.trending_topics[:10]:
                topic_text.append(f" {topic} ", style="bold white on dark_blue")
                topic_text.append("  ")
            console.print(
                Panel(
                    topic_text,
                    title="[bold]Trending Topics[/]",
                    border_style="dim blue",
                    padding=(1, 2),
                )
            )

        # Code releases summary
        code_papers = [p for p in top_papers if p.has_code and p.code_url]
        if code_papers:
            code_lines = "\n".join(
                f"  [cyan]▸[/] [bold]{p.title[:60]}[/]  [dim]{p.code_url}[/]"
                for p in code_papers
            )
            console.print(
                Panel(
                    code_lines,
                    title="[bold green]New Code Releases[/]",
                    border_style="dim green",
                )
            )

        console.print(f"\n[dim]HTML report:[/] [cyan]{report.html_path}[/]")
        console.print()

    # ------------------------------------------------------------------
    # Private rendering
    # ------------------------------------------------------------------

    def _render_html(
        self,
        report: DailyReport,
        top_papers: List[Paper],
        breakthrough: Optional[Paper],
        papers_with_code: List[Paper],
        topic_counts: Counter,
        db_stats: dict,
        period: str = "daily",
    ) -> Path:
        """Render the Jinja2 template and write the HTML file to disk."""
        template = self._jinja_env.get_template("daily_report.html")

        context = {
            "report": report,
            "top_papers": top_papers,
            "breakthrough": breakthrough,
            "papers_with_code": papers_with_code,
            "topic_counts": dict(topic_counts.most_common(20)),
            "db_stats": db_stats,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "period": period,
        }
        html_content = template.render(**context)

        # Ensure output directory exists
        output_dir = self.report_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        if period == "weekly":
            # ISO week number: 2025-W12-weekly.html
            iso = report.date.isocalendar()
            filename = f"{iso[0]}-W{iso[1]:02d}-weekly.html"
        elif period == "monthly":
            filename = f"{report.date.strftime('%Y-%m')}-monthly.html"
        else:
            filename = f"{report.date.strftime('%Y-%m-%d')}-daily.html"
        output_path = output_dir / filename

        output_path.write_text(html_content, encoding="utf-8")
        logger.info("HTML report saved to %s", output_path)

        return output_path
