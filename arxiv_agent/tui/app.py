"""ArxivTUI — main Textual application for the Arxiv Intelligence System."""
from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Label, Static
from textual.containers import Container, Vertical, Horizontal

from arxiv_agent.tui.screens.dashboard import DashboardScreen
from arxiv_agent.tui.screens.papers import PapersScreen
from arxiv_agent.tui.screens.directions import DirectionsScreen
from arxiv_agent.tui.screens.ask import AskScreen
from arxiv_agent.tui.screens.knowledge import KnowledgeScreen


# ---------------------------------------------------------------------------
# Help modal
# ---------------------------------------------------------------------------

class HelpModal(ModalScreen):
    """Keyboard shortcut reference."""

    BINDINGS = [("escape", "dismiss", "Close"), ("?", "dismiss", "Close"), ("q", "dismiss", "Close")]

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    #help-container {
        background: #1A1D27;
        border: double #4F8EF7;
        width: 60;
        height: auto;
        padding: 2 3;
    }
    #help-title {
        color: #4F8EF7;
        text-style: bold;
        border-bottom: solid #2D3147;
        padding-bottom: 1;
        margin-bottom: 1;
        text-align: center;
    }
    """

    _HELP_TEXT = """
[bold #4F8EF7]Navigation[/bold #4F8EF7]
  [bold]1[/bold]  Dashboard — overview & stats
  [bold]2[/bold]  Papers — search all papers
  [bold]3[/bold]  Directions — research trends
  [bold]4[/bold]  Ask — Q&A with Claude
  [bold]5[/bold]  Knowledge — full KB view

[bold #4F8EF7]Global[/bold #4F8EF7]
  [bold]q[/bold]  Quit the application
  [bold]?[/bold]  Show this help dialog
  [bold]ESC[/bold]  Close modal / go back
  [bold]r[/bold]  Refresh current screen data

[bold #4F8EF7]Papers screen[/bold #4F8EF7]
  Type to search · Score filter via dropdown
  [bold]Enter[/bold]  View paper details

[bold #4F8EF7]Ask screen[/bold #4F8EF7]
  [bold]Ctrl+Enter[/bold]  Submit question
  [bold]Ctrl+L[/bold]     Clear answer

[bold #4F8EF7]Modals[/bold #4F8EF7]
  [bold]ESC[/bold] or [bold]q[/bold]  Close modal
"""

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Static("[bold]📡 ARXIV INTELLIGENCE — Help[/bold]", id="help-title")
            yield Static(self._HELP_TEXT.strip())
            yield Static("\n[dim]Press ESC or ? to close[/dim]", id="help-close-hint")

    def on_key(self, event) -> None:
        self.dismiss()


# ---------------------------------------------------------------------------
# ArxivTUI Application
# ---------------------------------------------------------------------------

class ArxivTUI(App):
    """Main TUI application for the Arxiv Intelligence System."""

    TITLE = "Arxiv Intelligence"
    SUB_TITLE = "AI-powered research monitoring"

    BINDINGS = [
        Binding("1", "switch_screen('dashboard')", "Dashboard", show=True),
        Binding("2", "switch_screen('papers')", "Papers", show=True),
        Binding("3", "switch_screen('directions')", "Directions", show=True),
        Binding("4", "switch_screen('ask')", "Ask", show=True),
        Binding("5", "switch_screen('knowledge')", "Knowledge", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("?", "show_help", "Help", show=True),
    ]

    SCREENS = {
        "dashboard": DashboardScreen,
        "papers": PapersScreen,
        "directions": DirectionsScreen,
        "ask": AskScreen,
        "knowledge": KnowledgeScreen,
    }

    CSS = """
    Screen {
        background: #0F1117;
    }
    .card {
        background: #1A1D27;
        border: solid #2D3147;
        padding: 1 2;
        margin: 0 0 1 0;
    }
    .score-high { color: #F5A623; }
    .score-mid  { color: #4CAF82; }
    .score-low  { color: #F76464; }
    .badge-emerging  { color: #4CAF82; }
    .badge-stable    { color: #4F8EF7; }
    .badge-declining { color: #F5A623; }
    .badge-dead      { color: #F76464; }
    .header-title {
        color: #E8EAF6;
        text-style: bold;
    }
    .section-title {
        color: #4F8EF7;
        text-style: bold;
        margin: 1 0;
    }
    Footer {
        background: #1A1D27;
        color: #6B7280;
        border-top: solid #2D3147;
    }
    Footer > FooterKey {
        background: #2D3147;
        color: #E8EAF6;
    }
    Footer > FooterKey:hover {
        background: #4F8EF7;
    }
    TabbedContent {
        background: #0F1117;
    }
    TabbedContent > TabPane {
        background: #0F1117;
        padding: 0;
    }
    Tabs {
        background: #1A1D27;
        border-bottom: solid #2D3147;
    }
    Tab {
        color: #6B7280;
        background: #1A1D27;
    }
    Tab.-active {
        color: #4F8EF7;
        background: #0F1117;
        border-bottom: solid #4F8EF7;
        text-style: bold;
    }
    DataTable {
        background: #1A1D27;
        border: solid #2D3147;
    }
    DataTable > .datatable--header {
        background: #2D3147;
        color: #4F8EF7;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: #2D3147;
        color: #E8EAF6;
    }
    DataTable > .datatable--odd-row {
        background: #1A1D27;
    }
    DataTable > .datatable--even-row {
        background: #161924;
    }
    Input {
        background: #1A1D27;
        border: solid #2D3147;
        color: #E8EAF6;
    }
    Input:focus {
        border: solid #4F8EF7;
    }
    Select {
        background: #1A1D27;
        border: solid #2D3147;
        color: #E8EAF6;
    }
    Button {
        background: #2D3147;
        border: solid #4F8EF7;
        color: #E8EAF6;
    }
    Button:hover {
        background: #4F8EF7;
        color: #0F1117;
    }
    Button.-primary {
        background: #4F8EF7;
        color: #0F1117;
        text-style: bold;
    }
    Button.-primary:hover {
        background: #6BA3FF;
    }
    ListView {
        background: #1A1D27;
        border: solid #2D3147;
    }
    ListItem {
        color: #E8EAF6;
        padding: 0 1;
    }
    ListItem:hover {
        background: #2D3147;
    }
    RichLog {
        background: #1A1D27;
        border: solid #2D3147;
        color: #E8EAF6;
    }
    ScrollableContainer {
        background: #1A1D27;
    }
    """

    def on_mount(self) -> None:
        self.push_screen("dashboard")

    def action_switch_screen(self, screen_name: str) -> None:
        """Pop all modals and switch to the named base screen."""
        # Clear the screen stack down to a fresh instance of the target
        self.switch_screen(screen_name)

    def action_show_help(self) -> None:
        self.push_screen(HelpModal())
