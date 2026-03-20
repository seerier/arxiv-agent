"""Dashboard screen — overview of the Arxiv Intelligence System."""
from __future__ import annotations

from datetime import date
from typing import List

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static

from arxiv_intel.database import Database
from arxiv_intel.models import Direction, Paper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_colour(score: float) -> str:
    if score >= 8.0:
        return "#F5A623"
    if score >= 6.5:
        return "#4CAF82"
    if score >= 5.0:
        return "yellow"
    return "#F76464"


def _score_bar(score: float, width: int = 8) -> str:
    filled = round((score / 10.0) * width)
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    colour = _score_colour(score)
    return f"[{colour}]{bar} {score:.1f}[/{colour}]"


def _truncate(text: str, max_len: int) -> str:
    return text[: max_len - 1] + "…" if len(text) > max_len else text


def _dir_bar(count: int, max_count: int, width: int = 12) -> str:
    if max_count == 0:
        return "░" * width
    filled = round((count / max_count) * width)
    filled = max(0, min(width, filled))
    return "[#4F8EF7]" + "█" * filled + "[/#4F8EF7]" + "[dim]" + "░" * (width - filled) + "[/dim]"


# ---------------------------------------------------------------------------
# Stat card
# ---------------------------------------------------------------------------

class StatCard(Static):
    """A small stat widget showing a label + big number."""

    DEFAULT_CSS = """
    StatCard {
        background: #1A1D27;
        border: solid #2D3147;
        padding: 1 2;
        margin: 0 1;
        min-width: 18;
        height: 5;
        content-align: center middle;
    }
    """

    def __init__(self, label: str, value: str, accent: str = "#4F8EF7", **kwargs) -> None:
        self._label = label
        self._value = value
        self._accent = accent
        markup = f"[dim]{label}[/dim]\n[bold {accent}]{value}[/bold {accent}]"
        super().__init__(markup, **kwargs)

    def update_value(self, value: str) -> None:
        self._value = value
        self.update(f"[dim]{self._label}[/dim]\n[bold {self._accent}]{value}[/bold {self._accent}]")


# ---------------------------------------------------------------------------
# DashboardScreen
# ---------------------------------------------------------------------------

class DashboardScreen(Screen):
    """Main dashboard: stats overview + top papers + trending directions."""

    BINDINGS = [("r", "refresh_data", "Refresh")]

    def compose(self) -> ComposeResult:
        today_str = date.today().strftime("%A, %B %d %Y")
        yield Static(
            f"[bold #4F8EF7]📡 ARXIV INTELLIGENCE[/bold #4F8EF7]  [dim]{today_str}[/dim]",
            id="dash-header",
            classes="header-title",
        )
        # Stats row
        with Horizontal(id="stats-row"):
            yield StatCard("Total Papers", "…", accent="#4F8EF7", id="stat-total")
            yield StatCard("Analyzed", "…", accent="#4CAF82", id="stat-analyzed")
            yield StatCard("Breakthroughs", "…", accent="#F5A623", id="stat-break")
            yield StatCard("Directions", "…", accent="#4F8EF7", id="stat-dirs")

        # Two-column body
        with Horizontal(id="dash-body"):
            # Left: top papers
            with Vertical(id="papers-col"):
                yield Static(
                    "[bold #4F8EF7]Top Papers[/bold #4F8EF7]",
                    classes="section-title",
                )
                yield ListView(id="top-papers-list")

            # Right: trending directions
            with Vertical(id="dirs-col"):
                yield Static(
                    "[bold #4F8EF7]Trending Directions[/bold #4F8EF7]",
                    classes="section-title",
                )
                yield ScrollableContainer(
                    Static("Loading…", id="dirs-content"),
                    id="dirs-scroll",
                )

        yield Static(
            "[dim]Press [bold]1-5[/bold] to navigate · [bold]r[/bold] refresh · [bold]q[/bold] quit · [bold]?[/bold] help[/dim]",
            id="dash-footer",
        )

    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._load_data()

    def action_refresh_data(self) -> None:
        self._load_data()

    def _load_data(self) -> None:
        try:
            from arxiv_intel.config import get_config
            cfg = get_config()
            db = Database(cfg.db_path)
        except Exception:
            self._show_empty()
            return

        try:
            stats = db.get_stats()
            self._update_stats(stats)

            papers = db.get_recent_papers(days=30, limit=20)
            top_papers = sorted(papers, key=lambda p: p.overall_score, reverse=True)[:10]
            self._populate_papers(top_papers)

            directions = db.list_directions()
            self._populate_directions(directions[:15])
        except Exception as exc:
            self.query_one("#dirs-content", Static).update(
                f"[red]Error loading data: {exc}[/red]"
            )

    def _show_empty(self) -> None:
        for stat_id in ("#stat-total", "#stat-analyzed", "#stat-break", "#stat-dirs"):
            try:
                self.query_one(stat_id, StatCard).update_value("0")
            except Exception:
                pass

    def _update_stats(self, stats: dict) -> None:
        self.query_one("#stat-total", StatCard).update_value(
            f"{stats.get('total_papers', 0):,}"
        )
        self.query_one("#stat-analyzed", StatCard).update_value(
            f"{stats.get('analyzed_papers', 0):,}"
        )
        self.query_one("#stat-break", StatCard).update_value(
            f"{stats.get('breakthrough_papers', 0)}"
        )
        self.query_one("#stat-dirs", StatCard).update_value(
            f"{stats.get('directions_count', 0)}"
        )

    def _populate_papers(self, papers: List[Paper]) -> None:
        lv = self.query_one("#top-papers-list", ListView)
        lv.clear()
        if not papers:
            lv.append(ListItem(Static("[dim]No papers found. Run fetch first.[/dim]")))
            return

        for paper in papers:
            bar = _score_bar(paper.overall_score, width=6)
            title = _truncate(paper.title, 48)
            breakthrough = " [bold #F5A623]★[/bold #F5A623]" if paper.is_breakthrough else ""
            markup = f"{bar}  {title}{breakthrough}"
            lv.append(ListItem(Static(markup), id=f"paper-{paper.id[:16]}"))

    def _populate_directions(self, directions: List[Direction]) -> None:
        content_widget = self.query_one("#dirs-content", Static)
        if not directions:
            content_widget.update("[dim]No directions found.[/dim]")
            return

        # Count papers-per-direction approximation from key_papers list length
        counts = [len(d.key_papers) for d in directions]
        max_count = max(counts) if counts else 1

        status_colours = {
            "emerging": "#4CAF82",
            "stable": "#4F8EF7",
            "declining": "#F5A623",
            "dead": "#F76464",
        }

        lines: List[str] = []
        for d, cnt in zip(directions, counts):
            colour = status_colours.get(d.status, "#E8EAF6")
            bar = _dir_bar(cnt, max_count, width=10)
            name = _truncate(d.name, 28)
            score_colour = _score_colour(d.worthiness_score)
            lines.append(
                f"[{colour}]●[/{colour}] [bold]{name}[/bold]  "
                f"[{score_colour}]{d.worthiness_score:.1f}[/{score_colour}]  {bar}"
            )

        content_widget.update("\n".join(lines))

    # ------------------------------------------------------------------
    # CSS
    # ------------------------------------------------------------------

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
        overflow: hidden hidden;
    }
    #dash-header {
        background: #1A1D27;
        border-bottom: solid #2D3147;
        padding: 1 2;
        height: 3;
    }
    #stats-row {
        height: 7;
        margin: 1 1 0 1;
    }
    StatCard {
        background: #1A1D27;
        border: solid #2D3147;
        padding: 1 2;
        margin: 0 1;
        height: 5;
        content-align: center middle;
    }
    #dash-body {
        height: 1fr;
        margin: 0 1;
    }
    #papers-col {
        width: 3fr;
        margin-right: 1;
    }
    #dirs-col {
        width: 2fr;
    }
    .section-title {
        color: #4F8EF7;
        text-style: bold;
        height: 2;
        padding: 0 1;
    }
    #top-papers-list {
        background: #1A1D27;
        border: solid #2D3147;
        height: 1fr;
    }
    #dirs-scroll {
        background: #1A1D27;
        border: solid #2D3147;
        height: 1fr;
        padding: 1;
    }
    #dash-footer {
        background: #1A1D27;
        border-top: solid #2D3147;
        padding: 0 2;
        height: 2;
        content-align: left middle;
    }
    """
