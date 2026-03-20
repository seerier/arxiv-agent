"""Knowledge screen — tabbed view of directions and breakthrough papers."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from textual.app import ComposeResult
from textual.containers import ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Label, Static, TabbedContent, TabPane

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


def _status_markup(status: str) -> str:
    mapping = {
        "emerging": "[bold #4CAF82]EMERGING[/bold #4CAF82]",
        "stable": "[bold #4F8EF7]STABLE[/bold #4F8EF7]",
        "declining": "[bold #F5A623]DECLINING[/bold #F5A623]",
        "dead": "[bold #F76464]DEAD[/bold #F76464]",
    }
    return mapping.get(status.lower(), f"[dim]{status.upper()}[/dim]")


def _truncate(text: str, max_len: int) -> str:
    return text[: max_len - 1] + "…" if len(text) > max_len else text


def _growth_indicator(d: Direction) -> str:
    """A simple visual growth indicator based on key_papers count."""
    count = len(d.key_papers)
    if count >= 10:
        return "[bold #4CAF82]↑↑↑[/bold #4CAF82]"
    if count >= 5:
        return "[#4CAF82]↑↑[/#4CAF82]"
    if count >= 2:
        return "[#4CAF82]↑[/#4CAF82]"
    return "[dim]~[/dim]"


# ---------------------------------------------------------------------------
# KnowledgeScreen
# ---------------------------------------------------------------------------

class KnowledgeScreen(Screen):
    """Tabbed knowledge base view: All / Emerging / Declining / Breakthroughs."""

    BINDINGS = [
        ("r", "refresh_data", "Refresh"),
        ("escape", "app.pop_screen", "Back"),
    ]

    DEFAULT_CSS = """
    KnowledgeScreen {
        layout: vertical;
    }
    #kb-header {
        background: #1A1D27;
        border-bottom: solid #2D3147;
        padding: 1 2;
        height: 3;
    }
    #kb-tabs {
        height: 1fr;
        margin: 0 1;
    }
    #kb-status {
        background: #1A1D27;
        border-top: solid #2D3147;
        padding: 0 2;
        height: 2;
        color: dim;
        content-align: left middle;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._all_directions: List[Direction] = []
        self._breakthroughs: List[Paper] = []

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #4F8EF7]🧠 KNOWLEDGE BASE[/bold #4F8EF7]  [dim]Research intelligence overview[/dim]",
            id="kb-header",
            classes="header-title",
        )
        with TabbedContent(id="kb-tabs"):
            with TabPane("All Directions", id="tab-kb-all"):
                yield DataTable(id="dt-kb-all", zebra_stripes=True, cursor_type="row")
            with TabPane("Emerging", id="tab-kb-emerging"):
                yield DataTable(id="dt-kb-emerging", zebra_stripes=True, cursor_type="row")
            with TabPane("Declining", id="tab-kb-declining"):
                yield DataTable(id="dt-kb-declining", zebra_stripes=True, cursor_type="row")
            with TabPane("Breakthroughs", id="tab-kb-breakthroughs"):
                yield DataTable(id="dt-kb-breakthroughs", zebra_stripes=True, cursor_type="row")

        yield Static("Loading…", id="kb-status")

    def on_mount(self) -> None:
        # Set up columns for each table
        all_cols = [
            ("Direction", 28, "name"),
            ("Status", 12, "status"),
            ("Worthiness", 18, "worth"),
            ("Papers", 8, "papers"),
            ("Analyzed", 20, "analyzed"),
        ]
        emerging_cols = [
            ("Direction", 28, "name"),
            ("Growth", 10, "growth"),
            ("Worthiness", 18, "worth"),
            ("Papers", 8, "papers"),
            ("Overview", 42, "overview"),
        ]
        declining_cols = [
            ("Direction", 28, "name"),
            ("Status", 12, "status"),
            ("Worthiness", 18, "worth"),
            ("Papers", 8, "papers"),
            ("Overview", 42, "overview"),
        ]
        bt_cols = [
            ("Score", 14, "score"),
            ("Title", 44, "title"),
            ("Authors", 22, "authors"),
            ("Date", 12, "date"),
            ("Reason", 36, "reason"),
        ]

        for table_id, cols in [
            ("dt-kb-all", all_cols),
            ("dt-kb-emerging", emerging_cols),
            ("dt-kb-declining", declining_cols),
            ("dt-kb-breakthroughs", bt_cols),
        ]:
            try:
                table = self.query_one(f"#{table_id}", DataTable)
                for col_label, col_width, col_key in cols:
                    table.add_column(col_label, width=col_width, key=col_key)
            except Exception:
                pass

        self._load_data()

    def action_refresh_data(self) -> None:
        self._load_data()

    def _load_data(self) -> None:
        try:
            from arxiv_intel.config import get_config
            cfg = get_config()
            db = Database(cfg.db_path)
            self._all_directions = db.list_directions()
            self._breakthroughs = db.get_breakthrough_papers(days=30)
        except Exception as exc:
            self.query_one("#kb-status", Static).update(f"[red]Error: {exc}[/red]")
            return

        self._populate_all()
        self._populate_emerging()
        self._populate_declining()
        self._populate_breakthroughs()

        emerging_count = sum(1 for d in self._all_directions if d.status == "emerging")
        declining_count = sum(
            1 for d in self._all_directions if d.status in ("declining", "dead")
        )
        self.query_one("#kb-status", Static).update(
            f"[dim]{len(self._all_directions)} directions · "
            f"[#4CAF82]{emerging_count} emerging[/#4CAF82] · "
            f"[#F76464]{declining_count} declining[/#F76464] · "
            f"[#F5A623]{len(self._breakthroughs)} breakthroughs (30d)[/#F5A623] · "
            f"r to refresh[/dim]"
        )

    def _populate_all(self) -> None:
        table = self.query_one("#dt-kb-all", DataTable)
        table.clear()
        for d in self._all_directions:
            analyzed_str = (
                d.analyzed_at.strftime("%Y-%m-%d %H:%M") if d.analyzed_at else "[dim]never[/dim]"
            )
            table.add_row(
                d.name,
                _status_markup(d.status),
                _score_bar(d.worthiness_score, width=8),
                str(len(d.key_papers)),
                analyzed_str,
                key=d.id,
            )

    def _populate_emerging(self) -> None:
        table = self.query_one("#dt-kb-emerging", DataTable)
        table.clear()
        emerging = [d for d in self._all_directions if d.status == "emerging"]
        for d in emerging:
            table.add_row(
                d.name,
                _growth_indicator(d),
                _score_bar(d.worthiness_score, width=8),
                str(len(d.key_papers)),
                _truncate(d.overview, 42) if d.overview else "—",
                key=d.id,
            )

    def _populate_declining(self) -> None:
        table = self.query_one("#dt-kb-declining", DataTable)
        table.clear()
        declining = [d for d in self._all_directions if d.status in ("declining", "dead")]
        for d in declining:
            table.add_row(
                d.name,
                _status_markup(d.status),
                _score_bar(d.worthiness_score, width=8),
                str(len(d.key_papers)),
                _truncate(d.overview, 42) if d.overview else "—",
                key=d.id,
            )

    def _populate_breakthroughs(self) -> None:
        table = self.query_one("#dt-kb-breakthroughs", DataTable)
        table.clear()
        for p in self._breakthroughs:
            score = p.overall_score
            colour = _score_colour(score)
            score_cell = f"[{colour}]{_score_bar(score, width=6)}[/{colour}]"
            title_cell = _truncate(p.title, 44)
            authors_cell = (
                _truncate(p.authors[0], 18) + " et al." if len(p.authors) > 1
                else (p.authors[0] if p.authors else "Unknown")
            )
            date_cell = p.published_date.isoformat() if p.published_date else "—"
            reason_cell = _truncate(p.breakthrough_reason, 36) if p.breakthrough_reason else "—"
            table.add_row(
                score_cell,
                title_cell,
                authors_cell,
                date_cell,
                reason_cell,
                key=p.id,
            )
