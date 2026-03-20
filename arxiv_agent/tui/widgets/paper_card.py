"""PaperCard widget — compact card view for a single Paper object."""
from __future__ import annotations

from textual.widgets import Static

from arxiv_agent.models import Paper


def _score_colour(score: float) -> str:
    if score >= 8.0:
        return "#F5A623"
    if score >= 6.5:
        return "#4CAF82"
    if score >= 5.0:
        return "yellow"
    return "#F76464"


def _score_bar(score: float, width: int = 10) -> str:
    filled = round((score / 10.0) * width)
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    colour = _score_colour(score)
    return f"[{colour}]{bar} {score:.1f}[/{colour}]"


def _truncate(text: str, max_len: int) -> str:
    return text[: max_len - 1] + "…" if len(text) > max_len else text


class PaperCard(Static):
    """A Rich-markup card that displays a paper summary.

    Parameters
    ----------
    paper:
        The Paper dataclass instance to display.
    max_title_len:
        Maximum characters for the title before truncating.
    """

    def __init__(self, paper: Paper, max_title_len: int = 70, **kwargs) -> None:
        self._paper = paper
        self._max_title_len = max_title_len
        super().__init__(self._render_card(), classes="card", **kwargs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _render_card(self) -> str:
        p = self._paper
        title = _truncate(p.title, self._max_title_len)
        authors_list = p.authors[:3]
        authors_str = ", ".join(authors_list)
        if len(p.authors) > 3:
            authors_str += f" et al."

        date_str = p.published_date.isoformat() if p.published_date else "unknown date"
        bar = _score_bar(p.overall_score, width=10)

        directions_str = ""
        if p.directions:
            tags = p.directions[:3]
            directions_str = "  " + "  ".join(f"[#4F8EF7]#{t}[/#4F8EF7]" for t in tags)

        breakthrough_badge = ""
        if p.is_breakthrough:
            breakthrough_badge = "  [bold #F5A623]★ BREAKTHROUGH[/bold #F5A623]"

        summary_excerpt = ""
        if p.summary:
            summary_excerpt = "\n" + _truncate(p.summary, 160)
        elif p.abstract:
            summary_excerpt = "\n" + _truncate(p.abstract, 160)

        lines = [
            f"[bold #E8EAF6]{title}[/bold #E8EAF6]{breakthrough_badge}",
            f"[dim]{authors_str}  ·  {date_str}[/dim]",
            f"{bar}{directions_str}",
        ]
        if summary_excerpt:
            lines.append(f"[dim]{summary_excerpt}[/dim]")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh_paper(self, paper: Paper) -> None:
        """Replace the displayed paper and re-render."""
        self._paper = paper
        self.update(self._render_card())
