"""Knowledge reporter for the Arxiv Intelligence System.

Generates direction deep-dive reports and Q&A answer pages as
self-contained, beautiful HTML files.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from arxiv_agent.models import Direction, Paper

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"

# Sanitise a direction name into a safe filesystem slug
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Convert a string to a lowercase URL/filename-safe slug."""
    return _SLUG_RE.sub("-", text.lower()).strip("-")


class KnowledgeReporter:
    """Generates HTML reports for research directions and Q&A responses.

    Parameters
    ----------
    report_dir:
        Root directory for output HTML files.  Defaults to ``./reports``.
    """

    def __init__(self, report_dir: Optional[Path] = None) -> None:
        self.report_dir = Path(report_dir or "./reports")
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        self._jinja_env.filters["slugify"] = _slugify
        self._jinja_env.filters["score_color_css"] = self._score_color_css

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_color_css(score: float) -> str:
        """Map a 0–10 score to a CSS hex colour."""
        if score >= 8.0:
            return "#F5A623"
        if score >= 6.0:
            return "#4CAF82"
        if score >= 4.0:
            return "#F5C842"
        return "#F76464"

    # ------------------------------------------------------------------
    # Direction Report
    # ------------------------------------------------------------------

    def generate_direction_report(
        self,
        direction: Direction,
        papers: List[Paper],
    ) -> str:
        """Render a full deep-dive HTML report for a research direction.

        Parameters
        ----------
        direction:
            The Direction object (with milestones, open problems, etc.).
        papers:
            All Paper objects whose IDs appear in ``direction.key_papers``,
            plus any recent papers tagged to this direction.

        Returns
        -------
        str
            Absolute path to the generated HTML file.
        """
        template = self._jinja_env.get_template("direction_report.html")

        # Build a quick-lookup map by paper ID
        paper_map: dict = {p.id: p for p in papers}

        # Resolved key papers (only those we actually have objects for)
        key_papers: List[Paper] = [
            paper_map[pid] for pid in direction.key_papers if pid in paper_map
        ]

        context = {
            "direction": direction,
            "key_papers": key_papers,
            "all_papers": papers,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        }
        html_content = template.render(**context)

        # Ensure output directory
        output_dir = self.report_dir / "directions"
        output_dir.mkdir(parents=True, exist_ok=True)

        slug = _slugify(direction.name)
        output_path = output_dir / f"{slug}.html"
        output_path.write_text(html_content, encoding="utf-8")

        logger.info("Direction report saved to %s", output_path)
        return str(output_path.resolve())

    # ------------------------------------------------------------------
    # Ask / Q&A Report
    # ------------------------------------------------------------------

    def generate_ask_report(
        self,
        question: str,
        answer: str,
        papers: List[Paper],
    ) -> str:
        """Render a self-contained HTML page for a Q&A response.

        The ``answer`` string may include ``[N]`` style citation markers that
        correspond to the 1-based index of ``papers``.  The rendered page
        displays the answer, a numbered reference list, and all paper links.

        Parameters
        ----------
        question:
            The user's natural-language question.
        answer:
            Claude's answer (may be plain text or lightweight HTML paragraphs).
        papers:
            Papers cited or relevant to the answer.

        Returns
        -------
        str
            Absolute path to the generated HTML file.
        """
        template = self._jinja_env.get_template("ask_report.html")

        # Optionally convert plain-text paragraph breaks to <p> tags
        formatted_answer = self._format_answer(answer)

        context = {
            "question": question,
            "answer_raw": formatted_answer,
            "papers": papers,
            "generated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "report_id": str(uuid.uuid4())[:8],
        }
        html_content = template.render(**context)

        # Ensure output directory
        output_dir = self.report_dir / "ask"
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        slug = _slugify(question)[:48]
        output_path = output_dir / f"{timestamp}-{slug}.html"
        output_path.write_text(html_content, encoding="utf-8")

        logger.info("Ask report saved to %s", output_path)
        return str(output_path.resolve())

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _format_answer(text: str) -> str:
        """Convert a plain-text answer to basic HTML paragraphs.

        If the text already contains HTML tags it is returned as-is.
        Otherwise double-newlines become ``<p>`` tags.
        """
        if "<p>" in text or "<ul>" in text or "<h" in text:
            return text

        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return "\n".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{text}</p>"
