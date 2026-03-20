"""SQLite persistence layer for the Arxiv Intelligence System.

Schema overview
---------------
- ``papers``      — research papers with all analysis fields
- ``directions``  — research direction / subfield profiles
- ``professors``  — researcher / professor profiles
- ``conferences`` — conference calendar entries
- ``reports``     — generated daily/direction reports

All list-typed columns are stored as JSON strings.
Boolean columns use INTEGER (0 / 1).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Generator, List, Optional, Tuple

from arxiv_intel.models import (
    Conference,
    DailyReport,
    Direction,
    DirectionReport,
    Milestone,
    Paper,
    Professor,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DDL — CREATE TABLE statements
# ---------------------------------------------------------------------------

_DDL_PAPERS = """
CREATE TABLE IF NOT EXISTS papers (
    id                      TEXT PRIMARY KEY,
    title                   TEXT NOT NULL DEFAULT '',
    authors                 TEXT NOT NULL DEFAULT '[]',
    abstract                TEXT NOT NULL DEFAULT '',
    url                     TEXT NOT NULL DEFAULT '',
    pdf_url                 TEXT NOT NULL DEFAULT '',
    published_date          TEXT,
    updated_date            TEXT,
    categories              TEXT NOT NULL DEFAULT '[]',
    source                  TEXT NOT NULL DEFAULT 'arxiv',
    citations               INTEGER NOT NULL DEFAULT 0,
    has_code                INTEGER NOT NULL DEFAULT 0,
    code_url                TEXT NOT NULL DEFAULT '',
    summary                 TEXT NOT NULL DEFAULT '',
    novelty_score           REAL NOT NULL DEFAULT 0.0,
    impact_score            REAL NOT NULL DEFAULT 0.0,
    reproducibility_score   REAL NOT NULL DEFAULT 0.0,
    relevance_score         REAL NOT NULL DEFAULT 0.0,
    overall_score           REAL NOT NULL DEFAULT 0.0,
    method_name             TEXT NOT NULL DEFAULT '',
    method_description      TEXT NOT NULL DEFAULT '',
    is_breakthrough         INTEGER NOT NULL DEFAULT 0,
    breakthrough_reason     TEXT NOT NULL DEFAULT '',
    directions              TEXT NOT NULL DEFAULT '[]',
    key_contributions       TEXT NOT NULL DEFAULT '[]',
    limitations             TEXT NOT NULL DEFAULT '',
    fetched_at              TEXT,
    analyzed_at             TEXT,
    is_read                 INTEGER NOT NULL DEFAULT 0,
    is_starred              INTEGER NOT NULL DEFAULT 0
)
"""

_DDL_DIRECTIONS = """
CREATE TABLE IF NOT EXISTS directions (
    id                      TEXT PRIMARY KEY,
    name                    TEXT NOT NULL UNIQUE,
    aliases                 TEXT NOT NULL DEFAULT '[]',
    overview                TEXT NOT NULL DEFAULT '',
    status                  TEXT NOT NULL DEFAULT 'stable',
    worthiness_score        REAL NOT NULL DEFAULT 0.0,
    worthiness_reasoning    TEXT NOT NULL DEFAULT '',
    key_papers              TEXT NOT NULL DEFAULT '[]',
    key_authors             TEXT NOT NULL DEFAULT '[]',
    open_problems           TEXT NOT NULL DEFAULT '[]',
    milestones              TEXT NOT NULL DEFAULT '[]',
    related_directions      TEXT NOT NULL DEFAULT '[]',
    analyzed_at             TEXT
)
"""

_DDL_PROFESSORS = """
CREATE TABLE IF NOT EXISTS professors (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    institution     TEXT NOT NULL DEFAULT '',
    email           TEXT NOT NULL DEFAULT '',
    homepage        TEXT NOT NULL DEFAULT '',
    research_focus  TEXT NOT NULL DEFAULT '[]',
    top_papers      TEXT NOT NULL DEFAULT '[]',
    h_index         INTEGER NOT NULL DEFAULT 0,
    citation_count  INTEGER NOT NULL DEFAULT 0,
    directions      TEXT NOT NULL DEFAULT '[]',
    bio             TEXT NOT NULL DEFAULT '',
    rating          REAL NOT NULL DEFAULT 0.0,
    rating_reasoning TEXT NOT NULL DEFAULT '',
    analyzed_at     TEXT
)
"""

_DDL_CONFERENCES = """
CREATE TABLE IF NOT EXISTS conferences (
    id                  TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    full_name           TEXT NOT NULL DEFAULT '',
    website             TEXT NOT NULL DEFAULT '',
    submission_deadline TEXT,
    notification_date   TEXT,
    conference_date     TEXT,
    location            TEXT NOT NULL DEFAULT '',
    year                INTEGER NOT NULL DEFAULT 0,
    field               TEXT NOT NULL DEFAULT ''
)
"""

_DDL_REPORTS = """
CREATE TABLE IF NOT EXISTS reports (
    id                  TEXT PRIMARY KEY,
    report_type         TEXT NOT NULL DEFAULT 'daily',
    date                TEXT,
    direction_name      TEXT NOT NULL DEFAULT '',
    papers              TEXT NOT NULL DEFAULT '[]',
    breakthrough_paper  TEXT,
    trending_topics     TEXT NOT NULL DEFAULT '[]',
    new_code_releases   TEXT NOT NULL DEFAULT '[]',
    related_papers      TEXT NOT NULL DEFAULT '[]',
    word_count          INTEGER NOT NULL DEFAULT 0,
    html_path           TEXT NOT NULL DEFAULT '',
    direction_json      TEXT,
    created_at          TEXT
)
"""

_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_papers_published ON papers(published_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_papers_overall_score ON papers(overall_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_papers_analyzed ON papers(analyzed_at)",
    "CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source)",
    "CREATE INDEX IF NOT EXISTS idx_papers_breakthrough ON papers(is_breakthrough)",
    "CREATE INDEX IF NOT EXISTS idx_directions_name ON directions(name)",
    "CREATE INDEX IF NOT EXISTS idx_professors_name ON professors(name)",
    "CREATE INDEX IF NOT EXISTS idx_reports_type ON reports(report_type, date)",
]


# ---------------------------------------------------------------------------
# Helper: JSON round-trip for list fields
# ---------------------------------------------------------------------------

def _jdump(value) -> str:
    """Serialise a Python list/dict to a compact JSON string."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value) if value is not None else "[]"


def _jload(value) -> list:
    """Deserialise a JSON string back to a Python list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            return []
    return []


# ---------------------------------------------------------------------------
# Row converters
# ---------------------------------------------------------------------------

def _row_to_paper(row: sqlite3.Row) -> Paper:
    d = dict(row)
    d["authors"] = _jload(d.get("authors", "[]"))
    d["categories"] = _jload(d.get("categories", "[]"))
    d["directions"] = _jload(d.get("directions", "[]"))
    d["key_contributions"] = _jload(d.get("key_contributions", "[]"))
    d["has_code"] = bool(d.get("has_code", 0))
    d["is_breakthrough"] = bool(d.get("is_breakthrough", 0))
    d["is_read"] = bool(d.get("is_read", 0))
    d["is_starred"] = bool(d.get("is_starred", 0))
    return Paper.from_dict(d)


def _row_to_direction(row: sqlite3.Row) -> Direction:
    d = dict(row)
    d["aliases"] = _jload(d.get("aliases", "[]"))
    d["key_papers"] = _jload(d.get("key_papers", "[]"))
    d["key_authors"] = _jload(d.get("key_authors", "[]"))
    d["open_problems"] = _jload(d.get("open_problems", "[]"))
    d["milestones"] = _jload(d.get("milestones", "[]"))
    d["related_directions"] = _jload(d.get("related_directions", "[]"))
    return Direction.from_dict(d)


def _row_to_professor(row: sqlite3.Row) -> Professor:
    d = dict(row)
    d["research_focus"] = _jload(d.get("research_focus", "[]"))
    d["top_papers"] = _jload(d.get("top_papers", "[]"))
    d["directions"] = _jload(d.get("directions", "[]"))
    return Professor.from_dict(d)


def _row_to_conference(row: sqlite3.Row) -> Conference:
    return Conference.from_dict(dict(row))


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------


class Database:
    """SQLite-backed persistence layer for the Arxiv Intelligence System.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  The parent directories are created
        automatically if they do not exist.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info("Database initialised at %s", self.db_path)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Yield a connection with row_factory set and WAL journal mode."""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Schema initialisation
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Create all tables and indexes if they do not exist."""
        with self._connect() as conn:
            for ddl in [
                _DDL_PAPERS,
                _DDL_DIRECTIONS,
                _DDL_PROFESSORS,
                _DDL_CONFERENCES,
                _DDL_REPORTS,
            ]:
                conn.execute(ddl)
            for idx in _DDL_INDEXES:
                conn.execute(idx)
            # Migration: add embedding column if absent (existing DBs)
            try:
                conn.execute("ALTER TABLE papers ADD COLUMN embedding BLOB")
                logger.info("Migrated papers table: added 'embedding' column.")
            except Exception:
                pass  # column already exists
            # Migration: add rating columns to professors if absent
            for col, defn in [
                ("rating", "REAL NOT NULL DEFAULT 0.0"),
                ("rating_reasoning", "TEXT NOT NULL DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE professors ADD COLUMN {col} {defn}")
                    logger.info("Migrated professors table: added '%s' column.", col)
                except Exception:
                    pass  # column already exists

    # ==================================================================
    # Papers
    # ==================================================================

    def insert_paper(self, paper: Paper) -> None:
        """Insert a new paper.  Silently ignores duplicate IDs."""
        sql = """
            INSERT OR IGNORE INTO papers (
                id, title, authors, abstract, url, pdf_url,
                published_date, updated_date, categories, source,
                citations, has_code, code_url,
                summary, novelty_score, impact_score, reproducibility_score,
                relevance_score, overall_score,
                method_name, method_description,
                is_breakthrough, breakthrough_reason,
                directions, key_contributions, limitations,
                fetched_at, analyzed_at, is_read, is_starred
            ) VALUES (
                :id, :title, :authors, :abstract, :url, :pdf_url,
                :published_date, :updated_date, :categories, :source,
                :citations, :has_code, :code_url,
                :summary, :novelty_score, :impact_score, :reproducibility_score,
                :relevance_score, :overall_score,
                :method_name, :method_description,
                :is_breakthrough, :breakthrough_reason,
                :directions, :key_contributions, :limitations,
                :fetched_at, :analyzed_at, :is_read, :is_starred
            )
        """
        with self._connect() as conn:
            conn.execute(sql, self._paper_params(paper))

    def update_paper(self, paper: Paper) -> None:
        """Upsert a paper — insert or replace all fields."""
        sql = """
            INSERT OR REPLACE INTO papers (
                id, title, authors, abstract, url, pdf_url,
                published_date, updated_date, categories, source,
                citations, has_code, code_url,
                summary, novelty_score, impact_score, reproducibility_score,
                relevance_score, overall_score,
                method_name, method_description,
                is_breakthrough, breakthrough_reason,
                directions, key_contributions, limitations,
                fetched_at, analyzed_at, is_read, is_starred
            ) VALUES (
                :id, :title, :authors, :abstract, :url, :pdf_url,
                :published_date, :updated_date, :categories, :source,
                :citations, :has_code, :code_url,
                :summary, :novelty_score, :impact_score, :reproducibility_score,
                :relevance_score, :overall_score,
                :method_name, :method_description,
                :is_breakthrough, :breakthrough_reason,
                :directions, :key_contributions, :limitations,
                :fetched_at, :analyzed_at, :is_read, :is_starred
            )
        """
        with self._connect() as conn:
            conn.execute(sql, self._paper_params(paper))

    @staticmethod
    def _paper_params(paper: Paper) -> Dict:
        """Convert a Paper to a flat dict suitable for SQLite binding."""
        d = paper.to_dict()
        d["authors"] = _jdump(d["authors"])
        d["categories"] = _jdump(d["categories"])
        d["directions"] = _jdump(d["directions"])
        d["key_contributions"] = _jdump(d["key_contributions"])
        d["has_code"] = int(d["has_code"])
        d["is_breakthrough"] = int(d["is_breakthrough"])
        d["is_read"] = int(d["is_read"])
        d["is_starred"] = int(d["is_starred"])
        return d

    def get_paper(self, paper_id: str) -> Optional[Paper]:
        """Retrieve a single paper by its arXiv / source ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
        return _row_to_paper(row) if row else None

    def get_papers_by_date(self, target_date: date) -> List[Paper]:
        """Return all papers whose ``published_date`` matches *target_date*."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM papers WHERE published_date = ? ORDER BY overall_score DESC",
                (target_date.isoformat(),),
            ).fetchall()
        return [_row_to_paper(r) for r in rows]

    def get_recent_papers(self, days: int = 7, limit: int = 100) -> List[Paper]:
        """Return papers published within the last *days* days, best first."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM papers
                   WHERE published_date >= ?
                   ORDER BY overall_score DESC, published_date DESC
                   LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
        return [_row_to_paper(r) for r in rows]

    def search_papers(self, query: str, limit: int = 50) -> List[Paper]:
        """Semantic search if embeddings are available, else keyword LIKE search."""
        from arxiv_intel.embedding import is_available as _emb_available
        if _emb_available():
            results = self.search_papers_semantic(query, limit=limit)
            if results:
                return results
        # Fallback: keyword LIKE search
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM papers
                   WHERE title LIKE ? OR abstract LIKE ? OR authors LIKE ?
                   ORDER BY overall_score DESC, published_date DESC
                   LIMIT ?""",
                (pattern, pattern, pattern, limit),
            ).fetchall()
        return [_row_to_paper(r) for r in rows]

    def search_papers_semantic(self, query: str, limit: int = 50) -> List[Paper]:
        """Semantic search using cosine similarity over stored embeddings.

        Returns papers ranked by semantic similarity to the query.
        Falls back to an empty list if no embeddings are stored yet.
        """
        from arxiv_intel.embedding import embed, rank_by_similarity

        # Load all (id, embedding) pairs that have an embedding
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, embedding FROM papers WHERE embedding IS NOT NULL"
            ).fetchall()

        if not rows:
            return []

        candidates = [(r["id"], r["embedding"]) for r in rows]
        query_vec = embed(query)
        ranked = rank_by_similarity(query_vec, candidates, top_k=limit)

        if not ranked:
            return []

        # Fetch full paper rows in ranked order
        id_to_score = {pid: score for pid, score in ranked}
        placeholders = ",".join("?" * len(ranked))
        with self._connect() as conn:
            paper_rows = conn.execute(
                f"SELECT * FROM papers WHERE id IN ({placeholders})",
                [pid for pid, _ in ranked],
            ).fetchall()

        papers = [_row_to_paper(r) for r in paper_rows]
        # Re-sort by semantic similarity (DB may return in arbitrary order)
        papers.sort(key=lambda p: id_to_score.get(p.id, 0.0), reverse=True)
        return papers

    def save_embedding(self, paper_id: str, embedding_blob: bytes) -> None:
        """Store a serialised embedding vector for a paper."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE papers SET embedding = ? WHERE id = ?",
                (embedding_blob, paper_id),
            )

    def get_papers_without_embeddings(self, limit: int = 500) -> List[Paper]:
        """Return papers that have not yet had embeddings computed."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM papers
                   WHERE embedding IS NULL
                   ORDER BY published_date DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [_row_to_paper(r) for r in rows]

    def get_unanalyzed_papers(self, limit: int = 50) -> List[Paper]:
        """Return papers that have not yet been processed by the AI analyser."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM papers
                   WHERE analyzed_at IS NULL
                   ORDER BY published_date DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [_row_to_paper(r) for r in rows]

    def get_breakthrough_papers(self, days: int = 30) -> List[Paper]:
        """Return papers flagged as breakthroughs within the last *days* days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM papers
                   WHERE is_breakthrough = 1 AND published_date >= ?
                   ORDER BY overall_score DESC, published_date DESC""",
                (cutoff,),
            ).fetchall()
        return [_row_to_paper(r) for r in rows]

    def get_papers_by_direction(self, direction: str, limit: int = 50) -> List[Paper]:
        """Return papers tagged with a given direction name."""
        pattern = f'%"{direction}"%'
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM papers
                   WHERE directions LIKE ?
                   ORDER BY overall_score DESC, published_date DESC
                   LIMIT ?""",
                (pattern, limit),
            ).fetchall()
        return [_row_to_paper(r) for r in rows]

    def get_papers_with_code(self, days: int = 7) -> List[Paper]:
        """Return recent papers that have associated code repositories."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).date().isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM papers
                   WHERE has_code = 1 AND published_date >= ?
                   ORDER BY published_date DESC""",
                (cutoff,),
            ).fetchall()
        return [_row_to_paper(r) for r in rows]

    # ==================================================================
    # Directions
    # ==================================================================

    def insert_direction(self, direction: Direction) -> None:
        """Insert a direction record; silently ignores duplicate IDs."""
        sql = """
            INSERT OR IGNORE INTO directions (
                id, name, aliases, overview, status,
                worthiness_score, worthiness_reasoning,
                key_papers, key_authors, open_problems, milestones,
                related_directions, analyzed_at
            ) VALUES (
                :id, :name, :aliases, :overview, :status,
                :worthiness_score, :worthiness_reasoning,
                :key_papers, :key_authors, :open_problems, :milestones,
                :related_directions, :analyzed_at
            )
        """
        with self._connect() as conn:
            conn.execute(sql, self._direction_params(direction))

    def update_direction(self, direction: Direction) -> None:
        """Upsert a direction record — insert or replace all fields."""
        sql = """
            INSERT OR REPLACE INTO directions (
                id, name, aliases, overview, status,
                worthiness_score, worthiness_reasoning,
                key_papers, key_authors, open_problems, milestones,
                related_directions, analyzed_at
            ) VALUES (
                :id, :name, :aliases, :overview, :status,
                :worthiness_score, :worthiness_reasoning,
                :key_papers, :key_authors, :open_problems, :milestones,
                :related_directions, :analyzed_at
            )
        """
        with self._connect() as conn:
            conn.execute(sql, self._direction_params(direction))

    @staticmethod
    def _direction_params(direction: Direction) -> Dict:
        d = direction.to_dict()
        d["aliases"] = _jdump(d["aliases"])
        d["key_papers"] = _jdump(d["key_papers"])
        d["key_authors"] = _jdump(d["key_authors"])
        d["open_problems"] = _jdump(d["open_problems"])
        d["milestones"] = _jdump(d["milestones"])
        d["related_directions"] = _jdump(d["related_directions"])
        return d

    def get_direction(self, name: str) -> Optional[Direction]:
        """Look up a direction by exact name (case-insensitive)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM directions WHERE lower(name) = lower(?)", (name,)
            ).fetchone()
        return _row_to_direction(row) if row else None

    def list_directions(self) -> List[Direction]:
        """Return all known research directions ordered by worthiness score."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM directions ORDER BY worthiness_score DESC, name ASC"
            ).fetchall()
        return [_row_to_direction(r) for r in rows]

    def list_directions_by_status(self, status: str) -> List[Direction]:
        """Return directions filtered by their trend status."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM directions WHERE status = ? ORDER BY worthiness_score DESC",
                (status,),
            ).fetchall()
        return [_row_to_direction(r) for r in rows]

    # ==================================================================
    # Professors
    # ==================================================================

    def insert_professor(self, prof: Professor) -> None:
        """Insert a professor record; silently ignores duplicate IDs."""
        sql = """
            INSERT OR IGNORE INTO professors (
                id, name, institution, email, homepage,
                research_focus, top_papers, h_index, citation_count,
                directions, bio, rating, rating_reasoning, analyzed_at
            ) VALUES (
                :id, :name, :institution, :email, :homepage,
                :research_focus, :top_papers, :h_index, :citation_count,
                :directions, :bio, :rating, :rating_reasoning, :analyzed_at
            )
        """
        with self._connect() as conn:
            conn.execute(sql, self._professor_params(prof))

    def update_professor(self, prof: Professor) -> None:
        """Upsert a professor record — insert or replace all fields."""
        sql = """
            INSERT OR REPLACE INTO professors (
                id, name, institution, email, homepage,
                research_focus, top_papers, h_index, citation_count,
                directions, bio, rating, rating_reasoning, analyzed_at
            ) VALUES (
                :id, :name, :institution, :email, :homepage,
                :research_focus, :top_papers, :h_index, :citation_count,
                :directions, :bio, :rating, :rating_reasoning, :analyzed_at
            )
        """
        with self._connect() as conn:
            conn.execute(sql, self._professor_params(prof))

    @staticmethod
    def _professor_params(prof: Professor) -> Dict:
        d = prof.to_dict()
        d["research_focus"] = _jdump(d["research_focus"])
        d["top_papers"] = _jdump(d["top_papers"])
        d["directions"] = _jdump(d["directions"])
        return d

    def get_professor(self, name: str) -> Optional[Professor]:
        """Look up a professor by name (case-insensitive substring match)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM professors WHERE lower(name) LIKE lower(?)",
                (f"%{name}%",),
            ).fetchone()
        return _row_to_professor(row) if row else None

    def list_professors(self) -> List[Professor]:
        """Return all professor profiles ordered by citation count."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM professors ORDER BY citation_count DESC, name ASC"
            ).fetchall()
        return [_row_to_professor(r) for r in rows]

    # ==================================================================
    # Conferences
    # ==================================================================

    def insert_conference(self, conf: Conference) -> None:
        """Insert a conference; silently ignores duplicate IDs."""
        sql = """
            INSERT OR IGNORE INTO conferences (
                id, name, full_name, website,
                submission_deadline, notification_date, conference_date,
                location, year, field
            ) VALUES (
                :id, :name, :full_name, :website,
                :submission_deadline, :notification_date, :conference_date,
                :location, :year, :field
            )
        """
        with self._connect() as conn:
            conn.execute(sql, conf.to_dict())

    def update_conference(self, conf: Conference) -> None:
        """Upsert a conference record."""
        sql = """
            INSERT OR REPLACE INTO conferences (
                id, name, full_name, website,
                submission_deadline, notification_date, conference_date,
                location, year, field
            ) VALUES (
                :id, :name, :full_name, :website,
                :submission_deadline, :notification_date, :conference_date,
                :location, :year, :field
            )
        """
        with self._connect() as conn:
            conn.execute(sql, conf.to_dict())

    def list_conferences(self) -> List[Conference]:
        """Return all conferences ordered by submission deadline (soonest first)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM conferences
                   ORDER BY submission_deadline ASC NULLS LAST, conference_date ASC NULLS LAST"""
            ).fetchall()
        return [_row_to_conference(r) for r in rows]

    def get_upcoming_conferences(self, days: int = 90) -> List[Conference]:
        """Return conferences with submission deadlines within the next *days* days."""
        today = date.today().isoformat()
        cutoff = (date.today() + timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM conferences
                   WHERE submission_deadline >= ? AND submission_deadline <= ?
                   ORDER BY submission_deadline ASC""",
                (today, cutoff),
            ).fetchall()
        return [_row_to_conference(r) for r in rows]

    # ==================================================================
    # Reports
    # ==================================================================

    def insert_daily_report(self, report: DailyReport) -> None:
        """Persist a DailyReport to the reports table."""
        sql = """
            INSERT OR REPLACE INTO reports (
                id, report_type, date, direction_name,
                papers, breakthrough_paper, trending_topics, new_code_releases,
                related_papers, word_count, html_path, direction_json, created_at
            ) VALUES (
                :id, 'daily', :date, '',
                :papers, :breakthrough_paper, :trending_topics, :new_code_releases,
                '[]', :word_count, :html_path, NULL, :created_at
            )
        """
        d = report.to_dict()
        d["papers"] = _jdump(d["papers"])
        d["trending_topics"] = _jdump(d["trending_topics"])
        d["new_code_releases"] = _jdump(d["new_code_releases"])
        with self._connect() as conn:
            conn.execute(sql, d)

    def insert_direction_report(self, report: DirectionReport) -> None:
        """Persist a DirectionReport to the reports table."""
        sql = """
            INSERT OR REPLACE INTO reports (
                id, report_type, date, direction_name,
                papers, breakthrough_paper, trending_topics, new_code_releases,
                related_papers, word_count, html_path, direction_json, created_at
            ) VALUES (
                :id, 'direction', NULL, :direction_name,
                '[]', NULL, '[]', '[]',
                :related_papers, 0, :html_path, :direction_json, :created_at
            )
        """
        d = report.to_dict()
        d["related_papers"] = _jdump(d["related_papers"])
        d["direction_json"] = (
            json.dumps(d["direction"], ensure_ascii=False)
            if d.get("direction")
            else None
        )
        with self._connect() as conn:
            conn.execute(sql, d)

    def get_latest_daily_report(self) -> Optional[DailyReport]:
        """Return the most recently generated daily report."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM reports
                   WHERE report_type = 'daily'
                   ORDER BY created_at DESC
                   LIMIT 1"""
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["papers"] = _jload(d.get("papers", "[]"))
        d["trending_topics"] = _jload(d.get("trending_topics", "[]"))
        d["new_code_releases"] = _jload(d.get("new_code_releases", "[]"))
        return DailyReport.from_dict(d)

    # ==================================================================
    # Statistics
    # ==================================================================

    def get_stats(self) -> Dict:
        """Return a summary statistics dictionary about the database contents."""
        with self._connect() as conn:
            total_papers = conn.execute(
                "SELECT COUNT(*) FROM papers"
            ).fetchone()[0]

            analyzed_papers = conn.execute(
                "SELECT COUNT(*) FROM papers WHERE analyzed_at IS NOT NULL"
            ).fetchone()[0]

            breakthrough_papers = conn.execute(
                "SELECT COUNT(*) FROM papers WHERE is_breakthrough = 1"
            ).fetchone()[0]

            papers_with_code = conn.execute(
                "SELECT COUNT(*) FROM papers WHERE has_code = 1"
            ).fetchone()[0]

            directions_count = conn.execute(
                "SELECT COUNT(*) FROM directions"
            ).fetchone()[0]

            professors_count = conn.execute(
                "SELECT COUNT(*) FROM professors"
            ).fetchone()[0]

            conferences_count = conn.execute(
                "SELECT COUNT(*) FROM conferences"
            ).fetchone()[0]

            reports_count = conn.execute(
                "SELECT COUNT(*) FROM reports"
            ).fetchone()[0]

            avg_score_row = conn.execute(
                "SELECT AVG(overall_score) FROM papers WHERE analyzed_at IS NOT NULL"
            ).fetchone()
            avg_score = round(float(avg_score_row[0] or 0.0), 2)

            # Most recent paper date
            latest_row = conn.execute(
                "SELECT MAX(published_date) FROM papers"
            ).fetchone()
            latest_paper_date: Optional[str] = latest_row[0] if latest_row else None

            # Source breakdown
            source_rows = conn.execute(
                "SELECT source, COUNT(*) AS cnt FROM papers GROUP BY source"
            ).fetchall()
            sources: Dict[str, int] = {r[0]: r[1] for r in source_rows}

            # Today's papers
            today_str = date.today().isoformat()
            papers_today = conn.execute(
                "SELECT COUNT(*) FROM papers WHERE published_date = ?",
                (today_str,),
            ).fetchone()[0]

            # Emerging directions
            emerging_count = conn.execute(
                "SELECT COUNT(*) FROM directions WHERE status = 'emerging'"
            ).fetchone()[0]

            declining_count = conn.execute(
                "SELECT COUNT(*) FROM directions WHERE status IN ('declining', 'dead')"
            ).fetchone()[0]

        return {
            "total_papers": total_papers,
            "analyzed_papers": analyzed_papers,
            "unanalyzed_papers": total_papers - analyzed_papers,
            "breakthrough_papers": breakthrough_papers,
            "papers_with_code": papers_with_code,
            "papers_today": papers_today,
            "directions_count": directions_count,
            "emerging_directions": emerging_count,
            "declining_directions": declining_count,
            "professors_count": professors_count,
            "conferences_count": conferences_count,
            "reports_count": reports_count,
            "avg_overall_score": avg_score,
            "latest_paper_date": latest_paper_date,
            "sources": sources,
        }
