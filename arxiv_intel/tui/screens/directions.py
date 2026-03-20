"""Directions screen — browse, filter and inspect research directions."""
from __future__ import annotations

from typing import List

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Label, Static, TabbedContent, TabPane

from arxiv_intel.database import Database
from arxiv_intel.models import Direction


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


# ---------------------------------------------------------------------------
# Direction detail modal
# ---------------------------------------------------------------------------

class DirectionModal(ModalScreen):
    """Full-detail view for a single research direction."""

    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close")]

    DEFAULT_CSS = """
    DirectionModal {
        align: center middle;
    }
    #dir-modal-container {
        background: #1A1D27;
        border: double #4F8EF7;
        width: 90%;
        max-width: 120;
        height: 90%;
        padding: 1 2;
    }
    #dir-modal-title {
        color: #E8EAF6;
        text-style: bold;
        border-bottom: solid #2D3147;
        padding-bottom: 1;
        margin-bottom: 1;
    }
    #dir-modal-scroll {
        height: 1fr;
    }
    #dir-modal-close-row {
        height: 3;
        margin-top: 1;
        align: center middle;
    }
    """

    def __init__(self, direction: Direction, **kwargs) -> None:
        super().__init__(**kwargs)
        self._direction = direction

    def compose(self) -> ComposeResult:
        d = self._direction
        with Container(id="dir-modal-container"):
            status_badge = _status_markup(d.status)
            yield Static(
                f"[bold #E8EAF6]{d.name}[/bold #E8EAF6]  {status_badge}",
                id="dir-modal-title",
            )
            with ScrollableContainer(id="dir-modal-scroll"):
                # Score
                bar = _score_bar(d.worthiness_score, width=12)
                yield Static(f"[dim]Worthiness:[/dim]  {bar}\n")

                # Worthiness reasoning
                if d.worthiness_reasoning:
                    yield Static("[bold #4F8EF7]Worthiness Reasoning[/bold #4F8EF7]")
                    yield Static(f"  {d.worthiness_reasoning}\n")

                # Overview
                if d.overview:
                    yield Static("[bold #4F8EF7]Overview[/bold #4F8EF7]")
                    yield Static(f"  {d.overview}\n")

                # Open problems
                if d.open_problems:
                    yield Static("[bold #4F8EF7]Open Problems[/bold #4F8EF7]")
                    for i, prob in enumerate(d.open_problems, 1):
                        yield Static(f"  [#4CAF82]{i}.[/#4CAF82] {prob}")
                    yield Static("")

                # Milestones
                if d.milestones:
                    yield Static("[bold #4F8EF7]Key Milestones[/bold #4F8EF7]")
                    for ms in d.milestones:
                        yield Static(f"  [dim]{ms.date}[/dim]  {ms.event}")
                    yield Static("")

                # Key authors
                if d.key_authors:
                    authors_str = ", ".join(d.key_authors[:6])
                    yield Static(f"[dim]Key Authors:[/dim] [#E8EAF6]{authors_str}[/#E8EAF6]\n")

                # Related directions
                if d.related_directions:
                    related_str = "  ".join(
                        f"[#4F8EF7]→ {r}[/#4F8EF7]" for r in d.related_directions[:5]
                    )
                    yield Static(f"[dim]Related:[/dim]  {related_str}\n")

                # Key papers
                if d.key_papers:
                    yield Static("[bold #4F8EF7]Key Papers[/bold #4F8EF7]")
                    for kp in d.key_papers[:8]:
                        yield Static(f"  [dim]·[/dim] {kp}")

            with Horizontal(id="dir-modal-close-row"):
                yield Button("Close  [ESC]", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()


# ---------------------------------------------------------------------------
# Helper: build a directions DataTable from a list
# ---------------------------------------------------------------------------

def _build_directions_table(table: DataTable, directions: List[Direction]) -> None:
    table.clear()
    for d in directions:
        status_cell = _status_markup(d.status)
        bar_str = _score_bar(d.worthiness_score, width=8)
        overview_excerpt = _truncate(d.overview, 50) if d.overview else "—"
        papers_count = str(len(d.key_papers))
        table.add_row(
            d.name,
            status_cell,
            bar_str,
            papers_count,
            overview_excerpt,
            key=d.id,
        )


# ---------------------------------------------------------------------------
# DirectionsScreen
# ---------------------------------------------------------------------------

class DirectionsScreen(Screen):
    """Research directions browser with status-filtered tabs."""

    BINDINGS = [
        ("r", "refresh_data", "Refresh"),
        ("escape", "app.pop_screen", "Back"),
    ]

    DEFAULT_CSS = """
    DirectionsScreen {
        layout: vertical;
    }
    #dirs-screen-header {
        background: #1A1D27;
        border-bottom: solid #2D3147;
        padding: 1 2;
        height: 3;
    }
    #dirs-tabs {
        height: 1fr;
        margin: 0 1;
    }
    #dirs-status {
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

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #4F8EF7]🔭 DIRECTIONS[/bold #4F8EF7]  [dim]Research direction trend analysis[/dim]",
            id="dirs-screen-header",
            classes="header-title",
        )
        with TabbedContent(id="dirs-tabs"):
            with TabPane("All", id="tab-all"):
                yield DataTable(
                    id="dt-all",
                    zebra_stripes=True,
                    cursor_type="row",
                )
            with TabPane("Emerging", id="tab-emerging"):
                yield DataTable(
                    id="dt-emerging",
                    zebra_stripes=True,
                    cursor_type="row",
                )
            with TabPane("Stable", id="tab-stable"):
                yield DataTable(
                    id="dt-stable",
                    zebra_stripes=True,
                    cursor_type="row",
                )
            with TabPane("Declining", id="tab-declining"):
                yield DataTable(
                    id="dt-declining",
                    zebra_stripes=True,
                    cursor_type="row",
                )

        yield Static("Loading…", id="dirs-status")

    def on_mount(self) -> None:
        for table_id in ("dt-all", "dt-emerging", "dt-stable", "dt-declining"):
            try:
                table = self.query_one(f"#{table_id}", DataTable)
                table.add_column("Direction", width=28, key="name")
                table.add_column("Status", width=14, key="status")
                table.add_column("Worthiness", width=18, key="worth")
                table.add_column("Papers", width=8, key="papers")
                table.add_column("Overview", width=50, key="overview")
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
        except Exception as exc:
            self.query_one("#dirs-status", Static).update(f"[red]Error: {exc}[/red]")
            self._all_directions = []
            return

        all_d = self._all_directions
        emerging = [d for d in all_d if d.status == "emerging"]
        stable = [d for d in all_d if d.status == "stable"]
        declining = [d for d in all_d if d.status in ("declining", "dead")]

        for table_id, dirs in [
            ("dt-all", all_d),
            ("dt-emerging", emerging),
            ("dt-stable", stable),
            ("dt-declining", declining),
        ]:
            try:
                table = self.query_one(f"#{table_id}", DataTable)
                _build_directions_table(table, dirs)
            except Exception:
                pass

        self.query_one("#dirs-status", Static).update(
            f"[dim]{len(all_d)} directions · "
            f"[#4CAF82]{len(emerging)} emerging[/#4CAF82] · "
            f"[#4F8EF7]{len(stable)} stable[/#4F8EF7] · "
            f"[#F76464]{len(declining)} declining[/#F76464] · "
            f"Enter to view details · r to refresh[/dim]"
        )

    def _get_direction_by_row_key(self, key: str) -> Direction | None:
        return next((d for d in self._all_directions if d.id == key), None)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = event.row_key.value if event.row_key else None
        if row_key is None:
            return
        direction = self._get_direction_by_row_key(row_key)
        if direction:
            self.app.push_screen(DirectionModal(direction))
