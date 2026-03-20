"""Daily-job scheduler for the Arxiv Intelligence System.

Uses APScheduler's ``BackgroundScheduler`` to run a daily fetch-analyse-report
pipeline at the configured time.  The scheduler runs in a daemon thread so
it does not block the main process.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from arxiv_agent.config import ConfigLoader
from arxiv_agent.database import Database
from arxiv_agent.fetcher import FetchCoordinator
from arxiv_agent.analyzer import PaperAnalyzer
from arxiv_agent.reporter import DailyReporter
from arxiv_agent.knowledge import KnowledgeBase

logger = logging.getLogger(__name__)


class ArxivScheduler:
    """Wraps APScheduler to run the daily Arxiv Intelligence pipeline.

    Parameters
    ----------
    config:
        Loaded ``ConfigLoader`` instance.
    db:
        Initialised ``Database`` instance.
    coordinator:
        ``FetchCoordinator`` for fetching papers.
    analyzer:
        ``PaperAnalyzer`` for analysing individual papers.
    reporter:
        ``DailyReporter`` for generating the HTML digest.
    knowledge_base:
        ``KnowledgeBase`` for higher-level analysis access.
    """

    def __init__(
        self,
        config: ConfigLoader,
        db: Database,
        coordinator: FetchCoordinator,
        analyzer: PaperAnalyzer,
        reporter: DailyReporter,
        knowledge_base: KnowledgeBase,
    ) -> None:
        self._config = config
        self._db = db
        self._coordinator = coordinator
        self._analyzer = analyzer
        self._reporter = reporter
        self._knowledge_base = knowledge_base
        self._scheduler: Any = None
        self._last_run: Optional[datetime] = None
        self._last_result: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background scheduler with a daily trigger.

        The job fires at ``config.schedule_hour:config.schedule_minute`` every
        day.  If APScheduler is not installed a clear error is raised.
        """
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError as exc:
            raise ImportError(
                "APScheduler is required for the scheduler.  "
                "Install it with:  pip install apscheduler"
            ) from exc

        self._scheduler = BackgroundScheduler(daemon=True)
        trigger = CronTrigger(
            hour=self._config.schedule_hour,
            minute=self._config.schedule_minute,
        )
        self._scheduler.add_job(
            func=self._daily_job,
            trigger=trigger,
            id="daily_arxiv_job",
            name="Arxiv Intelligence Daily Pipeline",
            replace_existing=True,
            misfire_grace_time=3600,  # tolerate up to 1-hour delay
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started — daily job at %02d:%02d.",
            self._config.schedule_hour,
            self._config.schedule_minute,
        )

    def stop(self) -> None:
        """Shut down the background scheduler gracefully."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Scheduler stopped.")

    # ------------------------------------------------------------------
    # Job implementation
    # ------------------------------------------------------------------

    def _daily_job(self) -> None:
        """Execute the full daily pipeline: fetch → analyse → report → save."""
        run_start = datetime.utcnow()
        logger.info("Daily job starting at %s (UTC).", run_start.isoformat())

        result: Dict[str, Any] = {
            "started_at": run_start.isoformat(),
            "new_papers": 0,
            "analyzed_papers": 0,
            "errors": [],
        }

        try:
            # ── 1. Fetch ──────────────────────────────────────────────
            logger.info("Step 1/3 — Fetching papers…")
            fetch_result = self._coordinator.run_full_fetch()
            result["new_papers"] = fetch_result.new_papers
            result["fetch_errors"] = fetch_result.errors

            # ── 2. Analyse new papers ─────────────────────────────────
            logger.info("Step 2/3 — Analysing new papers…")
            unanalyzed: List = self._db.get_unanalyzed_papers(limit=100)
            if unanalyzed:
                analyzed = self._analyzer.analyze_batch(
                    unanalyzed, show_progress=False
                )
                for paper in analyzed:
                    if paper.analyzed_at is not None:
                        self._db.update_paper(paper)
                result["analyzed_papers"] = len(
                    [p for p in analyzed if p.analyzed_at is not None]
                )
                logger.info(
                    "Analysed %d papers.", result["analyzed_papers"]
                )
            else:
                logger.info("No unanalysed papers found.")

            # ── 3. Generate daily report ──────────────────────────────
            logger.info("Step 3/3 — Generating daily report…")
            today = date.today()
            papers_today = self._db.get_papers_by_date(today)
            if not papers_today:
                # Fall back to recent papers from the last 2 days
                papers_today = self._db.get_recent_papers(days=2, limit=50)

            breakthroughs = self._knowledge_base.get_breakthroughs(days=1)
            db_stats = self._db.get_stats()

            if papers_today:
                daily_report = self._reporter.generate(
                    papers=papers_today,
                    report_date=today,
                    breakthroughs=breakthroughs,
                    db_stats=db_stats,
                )
                self._db.insert_daily_report(daily_report)
                result["report_html_path"] = daily_report.html_path
                logger.info(
                    "Daily report generated: %s", daily_report.html_path
                )
            else:
                logger.warning("No papers found for today — skipping report.")

        except Exception as exc:
            logger.error("Daily job failed with error: %s", exc, exc_info=True)
            result["errors"].append(str(exc))

        finally:
            run_end = datetime.utcnow()
            result["finished_at"] = run_end.isoformat()
            result["duration_seconds"] = (run_end - run_start).total_seconds()
            self._last_run = run_start
            self._last_result = result
            logger.info(
                "Daily job finished in %.1fs.", result["duration_seconds"]
            )

    # ------------------------------------------------------------------
    # Manual trigger
    # ------------------------------------------------------------------

    def run_now(self) -> None:
        """Run the daily pipeline immediately (blocking call).

        Useful for manual triggers or first-time setup.
        """
        logger.info("Running daily job immediately (manual trigger).")
        self._daily_job()

    # ------------------------------------------------------------------
    # Status / introspection
    # ------------------------------------------------------------------

    def get_next_run(self) -> Optional[datetime]:
        """Return the next scheduled run time, or ``None`` if not running.

        Returns
        -------
        Optional[datetime]
            Timezone-aware datetime of the next execution, or ``None``.
        """
        if self._scheduler is None:
            return None
        jobs = self._scheduler.get_jobs()
        if not jobs:
            return None
        job = next((j for j in jobs if j.id == "daily_arxiv_job"), None)
        if job is None:
            return None
        return job.next_run_time  # type: ignore[return-value]

    def get_status(self) -> Dict[str, Any]:
        """Return a dictionary describing the current scheduler state.

        Returns
        -------
        dict
            Keys: ``running``, ``next_run``, ``last_run``, ``schedule_time``,
            ``last_result``.
        """
        running = self._scheduler is not None and self._scheduler.running
        next_run = self.get_next_run()

        return {
            "running": running,
            "schedule_time": self._config.schedule_time,
            "next_run": next_run.isoformat() if next_run else None,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "last_result": self._last_result,
        }
