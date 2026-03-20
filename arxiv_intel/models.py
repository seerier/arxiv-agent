"""Data models for the Arxiv Intelligence System.

All models are Python dataclasses with full typing and JSON serialisation
support via ``to_dict()`` / ``from_dict()`` helpers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dt_iso(value: Optional[datetime]) -> Optional[str]:
    """Convert a datetime to an ISO-8601 string, or return None."""
    return value.isoformat() if value is not None else None


def _date_iso(value: Optional[date]) -> Optional[str]:
    """Convert a date to an ISO-8601 string, or return None."""
    return value.isoformat() if value is not None else None


# ---------------------------------------------------------------------------
# Paper
# ---------------------------------------------------------------------------

@dataclass
class Paper:
    """Represents a single research paper from any supported source.

    Scores are floats in the range [0.0, 10.0].
    """

    # ── Identity ──────────────────────────────────────────────────────────
    id: str
    title: str
    authors: List[str] = field(default_factory=list)
    abstract: str = ""
    url: str = ""
    pdf_url: str = ""

    # ── Dates ─────────────────────────────────────────────────────────────
    published_date: Optional[date] = None
    updated_date: Optional[date] = None

    # ── Classification ────────────────────────────────────────────────────
    categories: List[str] = field(default_factory=list)
    source: str = "arxiv"  # arxiv | paperswithcode | semantic_scholar

    # ── Bibliometric data ─────────────────────────────────────────────────
    citations: int = 0
    has_code: bool = False
    code_url: str = ""

    # ── Claude-generated analysis ─────────────────────────────────────────
    summary: str = ""                   # 2-sentence TL;DR
    novelty_score: float = 0.0
    impact_score: float = 0.0
    reproducibility_score: float = 0.0
    relevance_score: float = 0.0
    overall_score: float = 0.0

    method_name: str = ""
    method_description: str = ""

    is_breakthrough: bool = False
    breakthrough_reason: str = ""

    directions: List[str] = field(default_factory=list)     # subfield tags
    key_contributions: List[str] = field(default_factory=list)
    limitations: str = ""

    # ── Bookkeeping ───────────────────────────────────────────────────────
    fetched_at: Optional[datetime] = None
    analyzed_at: Optional[datetime] = None
    is_read: bool = False
    is_starred: bool = False

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "authors": self.authors,
            "abstract": self.abstract,
            "url": self.url,
            "pdf_url": self.pdf_url,
            "published_date": _date_iso(self.published_date),
            "updated_date": _date_iso(self.updated_date),
            "categories": self.categories,
            "source": self.source,
            "citations": self.citations,
            "has_code": self.has_code,
            "code_url": self.code_url,
            "summary": self.summary,
            "novelty_score": self.novelty_score,
            "impact_score": self.impact_score,
            "reproducibility_score": self.reproducibility_score,
            "relevance_score": self.relevance_score,
            "overall_score": self.overall_score,
            "method_name": self.method_name,
            "method_description": self.method_description,
            "is_breakthrough": self.is_breakthrough,
            "breakthrough_reason": self.breakthrough_reason,
            "directions": self.directions,
            "key_contributions": self.key_contributions,
            "limitations": self.limitations,
            "fetched_at": _dt_iso(self.fetched_at),
            "analyzed_at": _dt_iso(self.analyzed_at),
            "is_read": self.is_read,
            "is_starred": self.is_starred,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Paper":
        """Deserialise from a dictionary (e.g. loaded from SQLite JSON cols)."""

        def _parse_date(v: Optional[str]) -> Optional[date]:
            return date.fromisoformat(v) if v else None

        def _parse_dt(v: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(v) if v else None

        def _load_list(v) -> list:
            if isinstance(v, list):
                return v
            if isinstance(v, str) and v:
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    return []
            return []

        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            authors=_load_list(data.get("authors", [])),
            abstract=data.get("abstract", ""),
            url=data.get("url", ""),
            pdf_url=data.get("pdf_url", ""),
            published_date=_parse_date(data.get("published_date")),
            updated_date=_parse_date(data.get("updated_date")),
            categories=_load_list(data.get("categories", [])),
            source=data.get("source", "arxiv"),
            citations=int(data.get("citations", 0)),
            has_code=bool(data.get("has_code", False)),
            code_url=data.get("code_url", ""),
            summary=data.get("summary", ""),
            novelty_score=float(data.get("novelty_score", 0.0)),
            impact_score=float(data.get("impact_score", 0.0)),
            reproducibility_score=float(data.get("reproducibility_score", 0.0)),
            relevance_score=float(data.get("relevance_score", 0.0)),
            overall_score=float(data.get("overall_score", 0.0)),
            method_name=data.get("method_name", ""),
            method_description=data.get("method_description", ""),
            is_breakthrough=bool(data.get("is_breakthrough", False)),
            breakthrough_reason=data.get("breakthrough_reason", ""),
            directions=_load_list(data.get("directions", [])),
            key_contributions=_load_list(data.get("key_contributions", [])),
            limitations=data.get("limitations", ""),
            fetched_at=_parse_dt(data.get("fetched_at")),
            analyzed_at=_parse_dt(data.get("analyzed_at")),
            is_read=bool(data.get("is_read", False)),
            is_starred=bool(data.get("is_starred", False)),
        )


# ---------------------------------------------------------------------------
# Direction
# ---------------------------------------------------------------------------

@dataclass
class Milestone:
    """A chronological event in a research direction's history."""
    date: str       # ISO date string (YYYY-MM-DD or YYYY)
    event: str

    def to_dict(self) -> Dict[str, Any]:
        return {"date": self.date, "event": self.event}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Milestone":
        return cls(date=data.get("date", ""), event=data.get("event", ""))


@dataclass
class Direction:
    """A research direction / subfield with trend analysis and worthiness rating.

    ``status`` is one of: ``emerging`` | ``stable`` | ``declining`` | ``dead``.
    ``worthiness_score`` is a float in [0.0, 10.0].
    """

    id: str
    name: str
    aliases: List[str] = field(default_factory=list)
    overview: str = ""

    status: str = "stable"          # emerging | stable | declining | dead
    worthiness_score: float = 0.0   # 0–10
    worthiness_reasoning: str = ""

    key_papers: List[str] = field(default_factory=list)     # paper IDs
    key_authors: List[str] = field(default_factory=list)    # names
    open_problems: List[str] = field(default_factory=list)
    milestones: List[Milestone] = field(default_factory=list)
    related_directions: List[str] = field(default_factory=list)

    analyzed_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": self.aliases,
            "overview": self.overview,
            "status": self.status,
            "worthiness_score": self.worthiness_score,
            "worthiness_reasoning": self.worthiness_reasoning,
            "key_papers": self.key_papers,
            "key_authors": self.key_authors,
            "open_problems": self.open_problems,
            "milestones": [m.to_dict() for m in self.milestones],
            "related_directions": self.related_directions,
            "analyzed_at": _dt_iso(self.analyzed_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Direction":
        def _load_list(v) -> list:
            if isinstance(v, list):
                return v
            if isinstance(v, str) and v:
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    return []
            return []

        def _parse_dt(v: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(v) if v else None

        raw_milestones = _load_list(data.get("milestones", []))
        milestones = [
            Milestone.from_dict(m) if isinstance(m, dict) else Milestone(date="", event=str(m))
            for m in raw_milestones
        ]

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            aliases=_load_list(data.get("aliases", [])),
            overview=data.get("overview", ""),
            status=data.get("status", "stable"),
            worthiness_score=float(data.get("worthiness_score", 0.0)),
            worthiness_reasoning=data.get("worthiness_reasoning", ""),
            key_papers=_load_list(data.get("key_papers", [])),
            key_authors=_load_list(data.get("key_authors", [])),
            open_problems=_load_list(data.get("open_problems", [])),
            milestones=milestones,
            related_directions=_load_list(data.get("related_directions", [])),
            analyzed_at=_parse_dt(data.get("analyzed_at")),
        )


# ---------------------------------------------------------------------------
# Professor / Researcher
# ---------------------------------------------------------------------------

@dataclass
class Professor:
    """Profile for an academic researcher or professor."""

    id: str
    name: str
    institution: str = ""
    email: str = ""
    homepage: str = ""

    research_focus: List[str] = field(default_factory=list)
    top_papers: List[str] = field(default_factory=list)    # paper IDs or titles
    h_index: int = 0
    citation_count: int = 0
    directions: List[str] = field(default_factory=list)    # direction names

    bio: str = ""
    rating: float = 0.0                 # 1–10 researcher impact/worthiness score
    rating_reasoning: str = ""          # Claude's explanation of the rating
    analyzed_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "institution": self.institution,
            "email": self.email,
            "homepage": self.homepage,
            "research_focus": self.research_focus,
            "top_papers": self.top_papers,
            "h_index": self.h_index,
            "citation_count": self.citation_count,
            "directions": self.directions,
            "bio": self.bio,
            "rating": self.rating,
            "rating_reasoning": self.rating_reasoning,
            "analyzed_at": _dt_iso(self.analyzed_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Professor":
        def _load_list(v) -> list:
            if isinstance(v, list):
                return v
            if isinstance(v, str) and v:
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    return []
            return []

        def _parse_dt(v: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(v) if v else None

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            institution=data.get("institution", ""),
            email=data.get("email", ""),
            homepage=data.get("homepage", ""),
            research_focus=_load_list(data.get("research_focus", [])),
            top_papers=_load_list(data.get("top_papers", [])),
            h_index=int(data.get("h_index", 0)),
            citation_count=int(data.get("citation_count", 0)),
            directions=_load_list(data.get("directions", [])),
            bio=data.get("bio", ""),
            rating=float(data.get("rating", 0.0)),
            rating_reasoning=data.get("rating_reasoning", ""),
            analyzed_at=_parse_dt(data.get("analyzed_at")),
        )


# ---------------------------------------------------------------------------
# Conference
# ---------------------------------------------------------------------------

@dataclass
class Conference:
    """An academic conference with deadline and schedule information."""

    id: str
    name: str           # Short name, e.g. "CVPR"
    full_name: str = ""
    website: str = ""

    submission_deadline: Optional[date] = None
    notification_date: Optional[date] = None
    conference_date: Optional[date] = None

    location: str = ""
    year: int = 0
    field: str = ""     # e.g. "Computer Vision"

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "full_name": self.full_name,
            "website": self.website,
            "submission_deadline": _date_iso(self.submission_deadline),
            "notification_date": _date_iso(self.notification_date),
            "conference_date": _date_iso(self.conference_date),
            "location": self.location,
            "year": self.year,
            "field": self.field,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conference":
        def _parse_date(v: Optional[str]) -> Optional[date]:
            return date.fromisoformat(v) if v else None

        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            full_name=data.get("full_name", ""),
            website=data.get("website", ""),
            submission_deadline=_parse_date(data.get("submission_deadline")),
            notification_date=_parse_date(data.get("notification_date")),
            conference_date=_parse_date(data.get("conference_date")),
            location=data.get("location", ""),
            year=int(data.get("year", 0)),
            field=data.get("field", ""),
        )


# ---------------------------------------------------------------------------
# DailyReport
# ---------------------------------------------------------------------------

@dataclass
class DailyReport:
    """A generated daily digest report.

    ``papers`` holds the IDs of the top papers featured in the report.
    ``breakthrough_paper`` is the ID of the single breakthrough paper (if any).
    """

    id: str
    date: date

    papers: List[str] = field(default_factory=list)            # top paper IDs
    breakthrough_paper: Optional[str] = None                   # paper ID
    trending_topics: List[str] = field(default_factory=list)
    new_code_releases: List[str] = field(default_factory=list) # paper IDs / URLs

    word_count: int = 0
    html_path: str = ""

    created_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "date": _date_iso(self.date),
            "papers": self.papers,
            "breakthrough_paper": self.breakthrough_paper,
            "trending_topics": self.trending_topics,
            "new_code_releases": self.new_code_releases,
            "word_count": self.word_count,
            "html_path": self.html_path,
            "created_at": _dt_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DailyReport":
        def _load_list(v) -> list:
            if isinstance(v, list):
                return v
            if isinstance(v, str) and v:
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    return []
            return []

        def _parse_date(v: Optional[str]) -> Optional[date]:
            return date.fromisoformat(v) if v else None

        def _parse_dt(v: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(v) if v else None

        return cls(
            id=data.get("id", ""),
            date=_parse_date(data.get("date")) or date.today(),
            papers=_load_list(data.get("papers", [])),
            breakthrough_paper=data.get("breakthrough_paper"),
            trending_topics=_load_list(data.get("trending_topics", [])),
            new_code_releases=_load_list(data.get("new_code_releases", [])),
            word_count=int(data.get("word_count", 0)),
            html_path=data.get("html_path", ""),
            created_at=_parse_dt(data.get("created_at")),
        )


# ---------------------------------------------------------------------------
# DirectionReport
# ---------------------------------------------------------------------------

@dataclass
class DirectionReport:
    """A full deep-dive analysis report for a single research direction.

    ``related_papers`` holds paper IDs cited in the report.
    """

    id: str
    direction_name: str
    direction: Optional[Direction] = None

    related_papers: List[str] = field(default_factory=list)   # paper IDs
    html_path: str = ""

    created_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "direction_name": self.direction_name,
            "direction": self.direction.to_dict() if self.direction else None,
            "related_papers": self.related_papers,
            "html_path": self.html_path,
            "created_at": _dt_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DirectionReport":
        def _load_list(v) -> list:
            if isinstance(v, list):
                return v
            if isinstance(v, str) and v:
                try:
                    return json.loads(v)
                except json.JSONDecodeError:
                    return []
            return []

        def _parse_dt(v: Optional[str]) -> Optional[datetime]:
            return datetime.fromisoformat(v) if v else None

        raw_direction = data.get("direction")
        direction: Optional[Direction] = None
        if isinstance(raw_direction, dict):
            direction = Direction.from_dict(raw_direction)
        elif isinstance(raw_direction, str) and raw_direction:
            try:
                direction = Direction.from_dict(json.loads(raw_direction))
            except (json.JSONDecodeError, TypeError):
                direction = None

        return cls(
            id=data.get("id", ""),
            direction_name=data.get("direction_name", ""),
            direction=direction,
            related_papers=_load_list(data.get("related_papers", [])),
            html_path=data.get("html_path", ""),
            created_at=_parse_dt(data.get("created_at")),
        )
