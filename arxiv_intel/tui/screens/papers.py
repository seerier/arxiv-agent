"""Papers screen — searchable, filterable table of all research papers."""
from __future__ import annotations

from typing import List, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from arxiv_intel.database import Database
from arxiv_intel.models import Paper


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
    return f"{bar} {score:.1f}"


def _truncate(text: str, max_len: int) -> str:
    return text[: max_len - 1] + "…" if len(text) > max_len else text


def _authors_short(authors: List[str]) -> str:
    if not authors:
        return "Unknown"
    if len(authors) == 1:
        return authors[0][:24]
    return _truncate(authors[0], 18) + " et al."


# ---------------------------------------------------------------------------
# Paper detail modal
# ---------------------------------------------------------------------------

class PaperModal(ModalScreen):
    """Full-screen modal with all details for a single paper."""

    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close")]

    DEFAULT_CSS = """
    PaperModal {
        align: center middle;
    }
    #modal-container {
        background: #1A1D27;
        border: double #4F8EF7;
        width: 90%;
        max-width: 120;
        height: 90%;
        padding: 1 2;
    }
    #modal-title {
        color: #E8EAF6;
        text-style: bold;
        border-bottom: solid #2D3147;
        padding-bottom: 1;
        margin-bottom: 1;
    }
    #modal-scroll {
        height: 1fr;
    }
    #modal-close-row {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    #modal-close-btn {
        background: #2D3147;
        border: solid #4F8EF7;
        min-width: 16;
    }
    """

    def __init__(self, paper: Paper, **kwargs) -> None:
        super().__init__(**kwargs)
        self._paper = paper

    def compose(self) -> ComposeResult:
        p = self._paper
        with Container(id="modal-container"):
            bt_badge = "  [bold #F5A623]★ BREAKTHROUGH[/bold #F5A623]" if p.is_breakthrough else ""
            yield Static(
                f"[bold #E8EAF6]{p.title}[/bold #E8EAF6]{bt_badge}",
                id="modal-title",
            )
            with ScrollableContainer(id="modal-scroll"):
                # Authors
                authors_str = ", ".join(p.authors) if p.authors else "Unknown"
                yield Static(f"[dim]Authors:[/dim] [#E8EAF6]{authors_str}[/#E8EAF6]\n")

                # Date + Method
                date_str = p.published_date.isoformat() if p.published_date else "—"
                yield Static(
                    f"[dim]Published:[/dim] {date_str}   "
                    f"[dim]Method:[/dim] [#4F8EF7]{p.method_name or '—'}[/#4F8EF7]\n"
                )

                # Score breakdown
                yield Static("[bold #4F8EF7]Score Breakdown[/bold #4F8EF7]")
                scores = [
                    ("Overall", p.overall_score),
                    ("Novelty", p.novelty_score),
                    ("Impact", p.impact_score),
                    ("Reproducibility", p.reproducibility_score),
                    ("Relevance", p.relevance_score),
                ]
                for label, sc in scores:
                    bar = _score_bar(sc, width=10)
                    colour = _score_colour(sc)
                    yield Static(
                        f"  [{colour}]{label:<20} {bar}[/{colour}]"
                    )
                yield Static("")

                # Summary
                if p.summary:
                    yield Static("[bold #4F8EF7]Summary[/bold #4F8EF7]")
                    yield Static(f"  {p.summary}\n")

                # Key contributions
                if p.key_contributions:
                    yield Static("[bold #4F8EF7]Key Contributions[/bold #4F8EF7]")
                    for i, kc in enumerate(p.key_contributions, 1):
                        yield Static(f"  [#4CAF82]{i}.[/#4CAF82] {kc}")
                    yield Static("")

                # Breakthrough reason
                if p.is_breakthrough and p.breakthrough_reason:
                    yield Static("[bold #F5A623]Breakthrough Reason[/bold #F5A623]")
                    yield Static(f"  {p.breakthrough_reason}\n")

                # Limitations
                if p.limitations:
                    yield Static("[bold #F76464]Limitations[/bold #F76464]")
                    yield Static(f"  {p.limitations}\n")

                # Directions
                if p.directions:
                    tags = "  ".join(f"[#4F8EF7]#{d}[/#4F8EF7]" for d in p.directions)
                    yield Static(f"[dim]Directions:[/dim]  {tags}\n")

                # Has code
                if p.has_code and p.code_url:
                    yield Static(f"[dim]Code:[/dim] [#4CAF82]{p.code_url}[/#4CAF82]\n")

                # ArXiv URL
                arxiv_url = p.url or f"https://arxiv.org/abs/{p.id}"
                yield Static(f"[dim]ArXiv URL:[/dim] [bold #4F8EF7]{arxiv_url}[/bold #4F8EF7]\n")

            with Horizontal(id="modal-close-row"):
                yield Button("Close  [ESC]", id="modal-close-btn", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-close-btn":
            self.dismiss()


# ---------------------------------------------------------------------------
# PapersScreen
# ---------------------------------------------------------------------------

_MIN_SCORE_OPTIONS = [
    ("Any score", "0"),
    ("5.0+", "5"),
    ("7.0+", "7"),
    ("9.0+", "9"),
]

_MIN_SCORE_VALUES = {"0": 0.0, "5": 5.0, "7": 7.0, "9": 9.0}


class PapersScreen(Screen):
    """Searchable, filterable DataTable of all papers in the database."""

    BINDINGS = [
        ("r", "refresh_data", "Refresh"),
        ("escape", "app.pop_screen", "Back"),
    ]

    DEFAULT_CSS = """
    PapersScreen {
        layout: vertical;
    }
    #papers-header {
        background: #1A1D27;
        border-bottom: solid #2D3147;
        padding: 1 2;
        height: 3;
    }
    #filter-row {
        height: 4;
        padding: 0 1;
        margin: 0 0 1 0;
        background: #1A1D27;
        border-bottom: solid #2D3147;
    }
    #search-input {
        width: 3fr;
        margin-right: 2;
    }
    #score-select {
        width: 1fr;
    }
    #papers-table {
        height: 1fr;
        margin: 0 1;
    }
    #papers-status {
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
        self._all_papers: List[Paper] = []
        self._filtered_papers: List[Paper] = []

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #4F8EF7]📄 PAPERS[/bold #4F8EF7]  [dim]All research papers in the database[/dim]",
            id="papers-header",
            classes="header-title",
        )
        with Horizontal(id="filter-row"):
            yield Input(placeholder="Search papers by title, abstract, author…", id="search-input")
            yield Select(
                options=[(label, val) for label, val in _MIN_SCORE_OPTIONS],
                value="0",
                id="score-select",
            )
        yield DataTable(id="papers-table", zebra_stripes=True, cursor_type="row")
        yield Static("Loading…", id="papers-status")

    def on_mount(self) -> None:
        table = self.query_one("#papers-table", DataTable)
        table.add_column("Score", width=14, key="score")
        table.add_column("Title", width=45, key="title")
        table.add_column("Authors", width=22, key="authors")
        table.add_column("Date", width=12, key="date")
        table.add_column("Directions", width=24, key="directions")
        self._load_data()

    def action_refresh_data(self) -> None:
        self._load_data()

    def _load_data(self) -> None:
        try:
            from arxiv_intel.config import get_config
            cfg = get_config()
            db = Database(cfg.db_path)
            self._all_papers = db.get_recent_papers(days=365, limit=500)
        except Exception as exc:
            self.query_one("#papers-status", Static).update(f"[red]Error: {exc}[/red]")
            self._all_papers = []

        self._apply_filters()

    def _apply_filters(self) -> None:
        query = self.query_one("#search-input", Input).value.strip().lower()
        score_val = self.query_one("#score-select", Select).value
        min_score = _MIN_SCORE_VALUES.get(str(score_val), 0.0)

        papers = self._all_papers
        if query:
            papers = [
                p for p in papers
                if query in p.title.lower()
                or query in p.abstract.lower()
                or any(query in a.lower() for a in p.authors)
            ]
        if min_score > 0.0:
            papers = [p for p in papers if p.overall_score >= min_score]

        self._filtered_papers = papers
        self._populate_table(papers)

    def _populate_table(self, papers: List[Paper]) -> None:
        table = self.query_one("#papers-table", DataTable)
        table.clear()

        for paper in papers:
            score = paper.overall_score
            colour = _score_colour(score)
            bar_str = _score_bar(score, width=6)
            score_cell = f"[{colour}]{bar_str}[/{colour}]"

            title_cell = _truncate(paper.title, 45)
            if paper.is_breakthrough:
                title_cell = f"★ {title_cell}"

            authors_cell = _authors_short(paper.authors)
            date_cell = paper.published_date.isoformat() if paper.published_date else "—"
            dirs = paper.directions[:2]
            dirs_cell = ", ".join(dirs) if dirs else "—"

            table.add_row(
                score_cell,
                title_cell,
                authors_cell,
                date_cell,
                dirs_cell,
                key=paper.id,
            )

        count = len(papers)
        total = len(self._all_papers)
        self.query_one("#papers-status", Static).update(
            f"[dim]Showing {count} of {total} papers · Enter to view details · r to refresh[/dim]"
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._apply_filters()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "score-select":
            self._apply_filters()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key.value if event.row_key else None
        if row_key is None:
            return
        paper = next((p for p in self._filtered_papers if p.id == row_key), None)
        if paper:
            self.app.push_screen(PaperModal(paper))
