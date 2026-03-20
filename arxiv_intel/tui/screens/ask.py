"""Ask screen — interactive Q&A with Claude about the research database."""
from __future__ import annotations

from typing import List

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RichLog, Static
from textual.worker import get_current_worker
from textual import work

from arxiv_intel.database import Database
from arxiv_intel.models import Paper


# ---------------------------------------------------------------------------
# Example questions
# ---------------------------------------------------------------------------

_EXAMPLE_QUESTIONS: List[str] = [
    "What is the current state of event cameras?",
    "What are the most promising directions in CV?",
    "Is diffusion model research saturated?",
    "What are the open problems in neuromorphic computing?",
    "Compare transformer vs CNN architectures in 2024",
]


# ---------------------------------------------------------------------------
# AskScreen
# ---------------------------------------------------------------------------

class AskScreen(Screen):
    """Research Q&A powered by Claude, grounded in the local paper database."""

    BINDINGS = [
        ("ctrl+enter", "submit_question", "Ask"),
        ("escape", "app.pop_screen", "Back"),
        ("ctrl+l", "clear_answer", "Clear"),
    ]

    DEFAULT_CSS = """
    AskScreen {
        layout: vertical;
    }
    #ask-header {
        background: #1A1D27;
        border-bottom: solid #2D3147;
        padding: 1 2;
        height: 3;
    }
    #ask-body {
        height: 1fr;
        margin: 0 1;
    }
    #left-panel {
        width: 2fr;
        margin-right: 1;
    }
    #right-panel {
        width: 1fr;
    }
    #question-input {
        margin-bottom: 1;
        border: solid #2D3147;
        background: #1A1D27;
    }
    #ask-btn {
        background: #4F8EF7;
        border: solid #4F8EF7;
        min-width: 18;
        margin-bottom: 1;
    }
    #examples-label {
        color: #4F8EF7;
        text-style: bold;
        margin-bottom: 1;
        padding: 0 1;
    }
    #examples-box {
        background: #1A1D27;
        border: solid #2D3147;
        padding: 1;
        height: 1fr;
    }
    .example-btn {
        background: #1A1D27;
        border: solid #2D3147;
        width: 100%;
        margin-bottom: 1;
        color: #E8EAF6;
    }
    .example-btn:hover {
        background: #2D3147;
        border: solid #4F8EF7;
    }
    #answer-label {
        color: #4F8EF7;
        text-style: bold;
        height: 2;
        padding: 0 1;
    }
    #answer-log {
        background: #1A1D27;
        border: solid #2D3147;
        height: 1fr;
        padding: 1;
    }
    #ask-status {
        background: #1A1D27;
        border-top: solid #2D3147;
        padding: 0 2;
        height: 2;
        content-align: left middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[bold #4F8EF7]💬 ASK CLAUDE[/bold #4F8EF7]  [dim]Research Q&A powered by AI[/dim]",
            id="ask-header",
            classes="header-title",
        )
        with Horizontal(id="ask-body"):
            with Vertical(id="left-panel"):
                yield Static("[bold #4F8EF7]Your Question[/bold #4F8EF7]", classes="section-title")
                yield Input(
                    placeholder="Ask anything about the research database…",
                    id="question-input",
                )
                with Horizontal():
                    yield Button("Ask Claude", id="ask-btn", variant="primary")
                    yield Button("Clear", id="clear-btn", variant="default")

                yield Static("[bold #4F8EF7]Answer[/bold #4F8EF7]", id="answer-label")
                yield RichLog(id="answer-log", highlight=True, markup=True, wrap=True)

            with Vertical(id="right-panel"):
                yield Static("[bold #4F8EF7]Example Questions[/bold #4F8EF7]", id="examples-label")
                with ScrollableContainer(id="examples-box"):
                    for i, q in enumerate(_EXAMPLE_QUESTIONS):
                        yield Button(q, id=f"example-{i}", classes="example-btn")

        yield Static(
            "[dim]Press [bold]Ask Claude[/bold] or [bold]Ctrl+Enter[/bold] to submit · [bold]Ctrl+L[/bold] to clear[/dim]",
            id="ask-status",
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_submit_question(self) -> None:
        self._submit()

    def action_clear_answer(self) -> None:
        log = self.query_one("#answer-log", RichLog)
        log.clear()

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "ask-btn":
            self._submit()
        elif btn_id == "clear-btn":
            self.query_one("#answer-log", RichLog).clear()
        elif btn_id.startswith("example-"):
            idx = int(btn_id.split("-")[1])
            if 0 <= idx < len(_EXAMPLE_QUESTIONS):
                inp = self.query_one("#question-input", Input)
                inp.value = _EXAMPLE_QUESTIONS[idx]
                inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "question-input":
            self._submit()

    # ------------------------------------------------------------------
    # Core: async Claude query
    # ------------------------------------------------------------------

    def _submit(self) -> None:
        question = self.query_one("#question-input", Input).value.strip()
        if not question:
            return
        log = self.query_one("#answer-log", RichLog)
        log.clear()
        log.write(f"[bold #4F8EF7]Q: {question}[/bold #4F8EF7]\n")
        log.write("[dim]Searching relevant papers…[/dim]")
        status = self.query_one("#ask-status", Static)
        status.update("[dim]Querying Claude — please wait…[/dim]")
        self._run_query(question)

    @work(thread=True)
    def _run_query(self, question: str) -> None:
        """Worker: runs in a background thread to avoid blocking the UI."""
        log = self.query_one("#answer-log", RichLog)
        status = self.query_one("#ask-status", Static)

        try:
            from arxiv_intel.config import get_config
            cfg = get_config()
            db = Database(cfg.db_path)
            papers = db.search_papers(question, limit=15)
        except Exception as exc:
            self.app.call_from_thread(log.write, f"[red]Database error: {exc}[/red]")
            self.app.call_from_thread(
                status.update, "[dim]Error retrieving papers.[/dim]"
            )
            return

        if not papers:
            self.app.call_from_thread(
                log.write,
                "[bold yellow]No relevant papers found in the database.[/bold yellow]\n"
                "Run [cyan]fetch[/cyan] first to populate the database.",
            )
            self.app.call_from_thread(
                status.update, "[dim]No papers found for this query.[/dim]"
            )
            return

        self.app.call_from_thread(
            log.write, f"\n[dim]Found {len(papers)} relevant paper(s). Querying Claude…[/dim]\n"
        )

        # Build context block
        context_parts: List[str] = []
        for i, p in enumerate(papers, 1):
            authors_str = ", ".join(p.authors[:4])
            if len(p.authors) > 4:
                authors_str += " et al."
            year = p.published_date.year if p.published_date else "?"
            summary_text = p.summary if p.summary else p.abstract[:300]
            context_parts.append(
                f"[{i}] \"{p.title}\" — {authors_str} ({year})\n"
                f"    Score: {p.overall_score:.1f}/10\n"
                f"    {summary_text}"
            )
        context_block = "\n\n".join(context_parts)

        system_prompt = (
            "You are an expert AI research analyst with deep knowledge of computer science, "
            "machine learning, and related fields. Answer the question comprehensively using "
            "the provided papers as evidence. Structure your answer with clear sections "
            "using markdown-style bold headers (**Section Name**). "
            "Cite papers by [Author et al., YEAR] format referencing the numbered list. "
            "Be thorough, precise, and insightful. Conclude with open research questions."
        )
        user_prompt = (
            f"Question: {question}\n\n"
            f"Relevant papers from our database:\n\n{context_block}\n\n"
            f"Please provide a comprehensive, well-structured answer based on these papers."
        )

        try:
            from arxiv_intel.analyzer.claude_client import get_client
            client = get_client()
            answer = client.complete(
                system=system_prompt,
                user=user_prompt,
                max_tokens=3000,
            )
        except Exception as exc:
            self.app.call_from_thread(
                log.write, f"[bold red]Claude API error:[/bold red] {exc}"
            )
            self.app.call_from_thread(
                status.update, "[dim]Claude API error.[/dim]"
            )
            return

        # Format and display the answer
        formatted = self._format_answer(answer)
        self.app.call_from_thread(log.clear)
        self.app.call_from_thread(
            log.write, f"[bold #4F8EF7]Q: {question}[/bold #4F8EF7]\n"
        )
        self.app.call_from_thread(log.write, formatted)
        self.app.call_from_thread(
            status.update,
            f"[dim]Answer complete · {len(papers)} papers consulted · Ctrl+L to clear[/dim]",
        )

    @staticmethod
    def _format_answer(text: str) -> str:
        """Apply Rich markup to the answer text for display in RichLog."""
        lines: List[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            # Convert **bold** headers to colored section titles
            if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
                heading = stripped[2:-2]
                lines.append(f"\n[bold #4F8EF7]{heading}[/bold #4F8EF7]")
            elif stripped.startswith("## "):
                heading = stripped[3:]
                lines.append(f"\n[bold #4F8EF7]{heading}[/bold #4F8EF7]")
            elif stripped.startswith("### "):
                heading = stripped[4:]
                lines.append(f"\n[bold #4CAF82]{heading}[/bold #4CAF82]")
            elif stripped.startswith("- ") or stripped.startswith("* "):
                content = stripped[2:]
                lines.append(f"  [#4CAF82]•[/#4CAF82] {content}")
            elif stripped.startswith("[") and "]" in stripped:
                # Likely a citation reference line — dim it
                lines.append(f"[dim]{line}[/dim]")
            else:
                lines.append(line)
        return "\n".join(lines)
