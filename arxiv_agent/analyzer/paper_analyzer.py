"""Paper analysis using Claude.

Provides ``PaperAnalyzer`` which fills in all AI-generated fields on
``Paper`` objects by calling Claude via ``ClaudeClient``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from rich.logging import RichHandler
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from arxiv_agent.models import Paper
from arxiv_agent.analyzer.claude_client import ClaudeClient, get_client

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert AI research analyst.  Your task is to analyse a research \
paper and return a structured JSON object — and ONLY that JSON object, with no \
markdown fences, no preamble, and no trailing commentary.

The JSON MUST conform exactly to this schema:
{
  "summary": "<2-sentence TL;DR of the paper>",
  "novelty_score": <integer 1-10>,
  "impact_score": <integer 1-10>,
  "reproducibility_score": <integer 1-10>,
  "relevance_score": <integer 1-10>,
  "method_name": "<short name of the core method or contribution>",
  "method_description": "<one sentence describing the core method>",
  "is_breakthrough": <true|false>,
  "breakthrough_reason": "<reason if breakthrough, otherwise null>",
  "directions": ["<tag1>", "<tag2>", ...],
  "key_contributions": ["<contribution 1>", "<contribution 2>", "<contribution 3>"],
  "limitations": "<brief description of limitations>"
}

Scoring guidelines:
- novelty_score: how novel is the core idea? (1=incremental, 10=groundbreaking)
- impact_score: expected real-world / field impact (1=low, 10=transformative)
- reproducibility_score: how easy is it to reproduce? (1=very hard, 10=trivial)
- relevance_score: relevance to the field of the paper (1=peripheral, 10=core)
- is_breakthrough: set to true only if this paper represents a significant \
paradigm shift or enables something previously impossible.

CALIBRATION — you MUST follow this:
- Most papers are average: novelty 4–6, impact 4–6. Only use 8+ for genuinely \
exceptional work. Only use 1–3 for clearly weak or incremental work.
- Do NOT inflate scores to be encouraging. Honest assessment only.
- is_breakthrough should be true for fewer than 5% of papers — it means the field \
will look different because of this paper. Do not use it for solid incremental work.

Return ONLY the JSON object.  Do not wrap it in markdown.
"""


def _build_user_prompt(paper: Paper) -> str:
    authors_str = ", ".join(paper.authors[:8])
    if len(paper.authors) > 8:
        authors_str += f" et al. ({len(paper.authors)} total)"

    categories_str = ", ".join(paper.categories) if paper.categories else "N/A"

    return (
        f"Title: {paper.title}\n\n"
        f"Authors: {authors_str}\n\n"
        f"Categories: {categories_str}\n\n"
        f"Abstract:\n{paper.abstract}"
    )


# ---------------------------------------------------------------------------
# PaperAnalyzer
# ---------------------------------------------------------------------------


class PaperAnalyzer:
    """Analyses individual ``Paper`` objects using Claude.

    Parameters
    ----------
    client:
        ``ClaudeClient`` instance.  If omitted the global singleton is used.
    """

    def __init__(self, client: Optional[ClaudeClient] = None) -> None:
        self._client: ClaudeClient = client or get_client()

    # ------------------------------------------------------------------
    # Single-paper analysis
    # ------------------------------------------------------------------

    def analyze_paper(self, paper: Paper) -> Paper:
        """Fill in all Claude-generated analysis fields on *paper*.

        The paper object is mutated **and** returned for convenience.

        Parameters
        ----------
        paper:
            A ``Paper`` that has at minimum ``title`` and ``abstract`` set.

        Returns
        -------
        Paper
            The same object with all analysis fields populated.
        """
        logger.info("Analysing paper: %s", paper.title[:80])

        user_prompt = _build_user_prompt(paper)

        try:
            data: Dict[str, Any] = self._client.complete_json(
                system=_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=2000,
            )
        except Exception as exc:
            logger.error(
                "Failed to analyse paper %s: %s", paper.id, exc
            )
            raise

        # Populate scalar fields
        paper.summary = str(data.get("summary", "")).strip()
        paper.method_name = str(data.get("method_name", "")).strip()
        paper.method_description = str(data.get("method_description", "")).strip()
        paper.limitations = str(data.get("limitations", "")).strip()
        paper.is_breakthrough = bool(data.get("is_breakthrough", False))

        breakthrough_reason = data.get("breakthrough_reason")
        if breakthrough_reason and str(breakthrough_reason).lower() not in ("null", "none", ""):
            paper.breakthrough_reason = str(breakthrough_reason).strip()
        else:
            paper.breakthrough_reason = ""

        # Scores — clamp to [0, 10]
        paper.novelty_score = _clamp(float(data.get("novelty_score", 0)))
        paper.impact_score = _clamp(float(data.get("impact_score", 0)))
        paper.reproducibility_score = _clamp(
            float(data.get("reproducibility_score", 0))
        )
        paper.relevance_score = _clamp(float(data.get("relevance_score", 0)))

        # Weighted overall score: 30% novelty + 30% impact + 20% reproducibility + 20% relevance
        paper.overall_score = round(
            0.3 * paper.novelty_score
            + 0.3 * paper.impact_score
            + 0.2 * paper.reproducibility_score
            + 0.2 * paper.relevance_score,
            2,
        )

        # List fields
        paper.directions = _ensure_str_list(data.get("directions", []))
        paper.key_contributions = _ensure_str_list(
            data.get("key_contributions", [])
        )

        # Timestamp
        paper.analyzed_at = datetime.utcnow()

        logger.debug(
            "Paper analysed: score=%.2f breakthrough=%s",
            paper.overall_score,
            paper.is_breakthrough,
        )
        return paper

    # ------------------------------------------------------------------
    # Batch analysis
    # ------------------------------------------------------------------

    def analyze_batch(
        self,
        papers: List[Paper],
        show_progress: bool = True,
    ) -> List[Paper]:
        """Analyse a list of papers, optionally showing a Rich progress bar.

        Papers that fail to analyse are logged and skipped; they are
        still included in the returned list (unchanged).

        Parameters
        ----------
        papers:
            List of ``Paper`` objects to analyse.
        show_progress:
            If ``True`` a Rich progress bar is displayed in the terminal.

        Returns
        -------
        List[Paper]
            The same list with all successfully analysed papers updated.
        """
        if not papers:
            logger.info("No papers to analyse.")
            return papers

        results: List[Paper] = []

        if show_progress:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                transient=False,
            )
            task_id = progress.add_task(
                "Analysing papers", total=len(papers)
            )
            with progress:
                for paper in papers:
                    try:
                        self.analyze_paper(paper)
                    except Exception as exc:
                        logger.error(
                            "Skipping paper %s due to error: %s",
                            paper.id,
                            exc,
                        )
                    results.append(paper)
                    progress.advance(task_id)
        else:
            for paper in papers:
                try:
                    self.analyze_paper(paper)
                except Exception as exc:
                    logger.error(
                        "Skipping paper %s due to error: %s",
                        paper.id,
                        exc,
                    )
                results.append(paper)

        analyzed_count = sum(1 for p in results if p.analyzed_at is not None)
        logger.info(
            "Batch analysis complete: %d/%d papers analysed successfully.",
            analyzed_count,
            len(papers),
        )
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float = 0.0, hi: float = 10.0) -> float:
    """Clamp *value* to the range [*lo*, *hi*]."""
    return max(lo, min(hi, value))


def _ensure_str_list(value: Any) -> List[str]:
    """Coerce *value* to a list of non-empty strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
