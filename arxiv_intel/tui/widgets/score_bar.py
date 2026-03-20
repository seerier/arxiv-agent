"""ScoreBar widget — a colored block-character bar for 0–10 scores."""
from __future__ import annotations

from textual.widgets import Static


class ScoreBar(Static):
    """Renders a colored block bar + numeric score.

    Example output: ``████████░░ 8.2``

    Colors:
        gold   (>=8.0)
        green  (>=6.5)
        yellow (>=5.0)
        red    (< 5.0)
    """

    def __init__(self, score: float, width: int = 10, **kwargs) -> None:
        self._score = max(0.0, min(10.0, score))
        self._bar_width = width
        super().__init__(self._render_bar(), **kwargs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _render_bar(self) -> str:
        filled = round((self._score / 10.0) * self._bar_width)
        filled = max(0, min(self._bar_width, filled))
        bar = "█" * filled + "░" * (self._bar_width - filled)
        colour = self._colour()
        return f"[{colour}]{bar} {self._score:.1f}[/{colour}]"

    def _colour(self) -> str:
        if self._score >= 8.0:
            return "#F5A623"
        if self._score >= 6.5:
            return "#4CAF82"
        if self._score >= 5.0:
            return "yellow"
        return "#F76464"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_score(self, score: float) -> None:
        """Update the displayed score."""
        self._score = max(0.0, min(10.0, score))
        self.update(self._render_bar())
