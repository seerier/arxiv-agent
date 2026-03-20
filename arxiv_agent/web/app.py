"""FastAPI web application factory for the Arxiv Intelligence System."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from arxiv_agent.database import Database
from arxiv_agent.models import Paper, Direction, Professor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template directory
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Jinja2 filters
# ---------------------------------------------------------------------------

def score_color(score: float) -> str:
    """Return a CSS hex color based on score (0-10)."""
    if score >= 8.0:
        return "#4CAF82"   # green
    elif score >= 6.0:
        return "#4F8EF7"   # blue
    elif score >= 4.0:
        return "#F5A623"   # gold
    else:
        return "#F76464"   # red


def score_bg_color(score: float) -> str:
    """Return a dimmed CSS background color based on score (0-10)."""
    if score >= 8.0:
        return "rgba(76,175,130,0.15)"
    elif score >= 6.0:
        return "rgba(79,142,247,0.15)"
    elif score >= 4.0:
        return "rgba(245,166,35,0.15)"
    else:
        return "rgba(247,100,100,0.15)"


def status_color(status: str) -> str:
    """Return a CSS color for a direction status."""
    return {
        "emerging": "#4CAF82",
        "stable": "#4F8EF7",
        "declining": "#F5A623",
        "dead": "#F76464",
    }.get(status, "#9BA3BF")


def status_bg(status: str) -> str:
    return {
        "emerging": "rgba(76,175,130,0.15)",
        "stable": "rgba(79,142,247,0.15)",
        "declining": "rgba(245,166,35,0.15)",
        "dead": "rgba(247,100,100,0.15)",
    }.get(status, "rgba(155,163,191,0.15)")


def fmt_date(d) -> str:
    if d is None:
        return ""
    try:
        from datetime import date
        if isinstance(d, str):
            from datetime import date as date_cls
            d = date_cls.fromisoformat(d)
        return d.strftime("%b %-d, %Y")
    except Exception:
        return str(d)


def fmt_score(score: float) -> str:
    return f"{score:.1f}"


def clamp_pct(score: float, max_val: float = 10.0) -> float:
    return round(min(max(score / max_val * 100, 0), 100), 1)


def truncate(s: str, length: int = 200) -> str:
    if len(s) <= length:
        return s
    return s[:length].rstrip() + "…"


def nl2br(s: str) -> str:
    """Convert newlines to <br> tags."""
    import markupsafe
    escaped = markupsafe.escape(s)
    return markupsafe.Markup(str(escaped).replace("\n", "<br>"))


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(db: Database, config) -> FastAPI:
    """Create and configure the FastAPI application.

    Parameters
    ----------
    db:
        Initialised Database instance.
    config:
        ConfigLoader instance from arxiv_agent.config.
    """
    app = FastAPI(
        title="Arxiv Intelligence System",
        description="Research paper intelligence dashboard",
        version="1.0.0",
    )

    # Mount static files (if directory exists)
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.filters["score_color"] = score_color
    templates.env.filters["score_bg"] = score_bg_color
    templates.env.filters["status_color"] = status_color
    templates.env.filters["status_bg"] = status_bg
    templates.env.filters["fmt_date"] = fmt_date
    templates.env.filters["fmt_score"] = fmt_score
    templates.env.filters["clamp_pct"] = clamp_pct
    templates.env.filters["truncate_text"] = truncate
    templates.env.filters["nl2br"] = nl2br

    # Shared state stored on app
    app.state.db = db
    app.state.config = config

    # ---------------------------------------------------------------------------
    # Startup
    # ---------------------------------------------------------------------------

    @app.on_event("startup")
    async def startup_event():
        logger.info("Arxiv Intel web app started")

    # ---------------------------------------------------------------------------
    # Helper: get paper count per direction
    # ---------------------------------------------------------------------------

    def _direction_paper_counts(directions: List[Direction]) -> dict:
        counts = {}
        for d in directions:
            papers = db.get_papers_by_direction(d.name, limit=200)
            counts[d.name] = len(papers)
        return counts

    # ---------------------------------------------------------------------------
    # Routes
    # ---------------------------------------------------------------------------

    # ── Dashboard ─────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        stats = db.get_stats()
        top_papers = db.get_recent_papers(days=30, limit=5)
        directions = db.list_directions()

        # Breakthrough papers last 7 days
        breakthroughs = db.get_breakthrough_papers(days=7)

        # Direction paper counts for bar chart
        dir_counts = {}
        for d in directions[:10]:
            papers = db.get_papers_by_direction(d.name, limit=100)
            dir_counts[d.name] = len(papers)

        # Sort by count
        dir_counts_sorted = sorted(dir_counts.items(), key=lambda x: x[1], reverse=True)
        max_count = max((v for v in dir_counts.values()), default=1) or 1

        # Recent reports from filesystem
        recent_reports = []
        try:
            report_dir = Path(config.report_dir)
            if report_dir.exists():
                html_files = sorted(report_dir.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
                recent_reports = html_files[:5]
        except Exception:
            pass

        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "active_page": "dashboard",
            "stats": stats,
            "top_papers": top_papers,
            "directions": directions,
            "breakthroughs": breakthroughs,
            "dir_counts_sorted": dir_counts_sorted,
            "max_count": max_count,
            "recent_reports": recent_reports,
        })

    # ── Papers browser ────────────────────────────────────────────────────────

    @app.get("/papers", response_class=HTMLResponse)
    async def papers_list(
        request: Request,
        q: str = "",
        min_score: float = 0.0,
        page: int = 1,
        limit: int = 20,
    ):
        if q:
            all_papers = db.search_papers(q, limit=500)
        else:
            all_papers = db.get_recent_papers(days=90, limit=500)

        # Filter by min score
        if min_score > 0:
            all_papers = [p for p in all_papers if p.overall_score >= min_score]

        total = len(all_papers)
        total_pages = max(1, (total + limit - 1) // limit)
        page = max(1, min(page, total_pages))
        offset = (page - 1) * limit
        papers = all_papers[offset: offset + limit]

        return templates.TemplateResponse("papers.html", {
            "request": request,
            "active_page": "papers",
            "papers": papers,
            "query": q,
            "min_score": min_score,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        })

    # ── Paper detail ──────────────────────────────────────────────────────────

    @app.get("/papers/{paper_id:path}", response_class=HTMLResponse)
    async def paper_detail(request: Request, paper_id: str):
        paper = db.get_paper(paper_id)
        if not paper:
            return templates.TemplateResponse("404.html", {
                "request": request,
                "active_page": "",
                "message": f"Paper '{paper_id}' not found in database.",
            }, status_code=404)

        return templates.TemplateResponse("paper_detail.html", {
            "request": request,
            "active_page": "papers",
            "paper": paper,
        })

    # ── Directions browser ────────────────────────────────────────────────────

    @app.get("/directions", response_class=HTMLResponse)
    async def directions_list(request: Request, status_filter: str = "all"):
        if status_filter and status_filter != "all":
            directions = db.list_directions_by_status(status_filter)
        else:
            directions = db.list_directions()

        # Paper counts per direction
        dir_counts = {}
        for d in directions:
            papers = db.get_papers_by_direction(d.name, limit=100)
            dir_counts[d.name] = len(papers)

        return templates.TemplateResponse("directions.html", {
            "request": request,
            "active_page": "directions",
            "directions": directions,
            "dir_counts": dir_counts,
            "status_filter": status_filter,
        })

    # ── Direction detail ──────────────────────────────────────────────────────

    @app.get("/directions/{name:path}", response_class=HTMLResponse)
    async def direction_detail(request: Request, name: str):
        direction = db.get_direction(name)
        if not direction:
            return templates.TemplateResponse("404.html", {
                "request": request,
                "active_page": "",
                "message": f"Direction '{name}' not found.",
            }, status_code=404)

        # Get key papers
        key_papers = []
        for pid in direction.key_papers[:8]:
            p = db.get_paper(pid)
            if p:
                key_papers.append(p)

        # If no key papers by ID, search by direction name
        if not key_papers:
            key_papers = db.get_papers_by_direction(direction.name, limit=8)

        paper_count = len(db.get_papers_by_direction(direction.name, limit=200))

        return templates.TemplateResponse("direction_detail.html", {
            "request": request,
            "active_page": "directions",
            "direction": direction,
            "key_papers": key_papers,
            "paper_count": paper_count,
        })

    # ── Ask ───────────────────────────────────────────────────────────────────

    @app.get("/ask", response_class=HTMLResponse)
    async def ask_get(request: Request):
        return templates.TemplateResponse("ask.html", {
            "request": request,
            "active_page": "ask",
            "question": "",
            "answer": None,
            "referenced_papers": [],
            "error": None,
        })

    @app.post("/ask", response_class=HTMLResponse)
    async def ask_post(request: Request):
        form = await request.form()
        question = str(form.get("question", "")).strip()

        if not question:
            return templates.TemplateResponse("ask.html", {
                "request": request,
                "active_page": "ask",
                "question": "",
                "answer": None,
                "referenced_papers": [],
                "error": "Please enter a question.",
            })

        answer_html = ""
        referenced_papers = []
        error = None
        saved_path = None

        try:
            import anthropic

            # Gather context: top papers + directions
            recent_papers = db.get_recent_papers(days=30, limit=30)
            directions = db.list_directions()

            context_parts = []

            if recent_papers:
                context_parts.append("=== RECENT PAPERS (last 30 days) ===")
                for p in recent_papers[:20]:
                    context_parts.append(
                        f"Title: {p.title}\n"
                        f"Authors: {', '.join(p.authors[:3])}\n"
                        f"Score: {p.overall_score:.1f}/10\n"
                        f"Summary: {p.summary}\n"
                        f"Directions: {', '.join(p.directions)}\n"
                        f"URL: {p.url}\n"
                        "---"
                    )

            if directions:
                context_parts.append("\n=== RESEARCH DIRECTIONS ===")
                for d in directions[:10]:
                    context_parts.append(
                        f"Direction: {d.name} ({d.status}, worthiness: {d.worthiness_score:.1f}/10)\n"
                        f"Overview: {d.overview[:300]}\n"
                        "---"
                    )

            context = "\n".join(context_parts)

            system_prompt = (
                "You are a research intelligence assistant for the Arxiv Intelligence System. "
                "You have access to a curated database of AI/ML research papers and research directions. "
                "Answer questions thoroughly and helpfully. Format your response with clear sections using "
                "HTML tags (<h3>, <p>, <ul>, <li>, <strong>, <em>) for readability. "
                "Reference specific papers and authors when relevant."
            )

            client = anthropic.Anthropic(api_key=config.anthropic_api_key)
            message = client.messages.create(
                model=config.claude_model,
                max_tokens=2048,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": f"Based on this research database context:\n\n{context}\n\n"
                                   f"Question: {question}"
                    }
                ]
            )
            answer_html = message.content[0].text if message.content else ""

            # Find referenced papers
            for p in recent_papers[:20]:
                if p.title.lower() in answer_html.lower() or any(a.split()[-1].lower() in answer_html.lower() for a in p.authors[:2]):
                    referenced_papers.append(p)
                    if len(referenced_papers) >= 5:
                        break

            # Save the answer as HTML report
            try:
                from datetime import datetime as dt
                report_dir = Path(config.report_dir)
                report_dir.mkdir(parents=True, exist_ok=True)
                ts = dt.now().strftime("%Y%m%d_%H%M%S")
                safe_q = "".join(c if c.isalnum() or c in " -_" else "" for c in question[:40]).strip().replace(" ", "_")
                filename = f"ask_{ts}_{safe_q}.html"
                saved_path = str(report_dir / filename)

                ask_html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Q&A: {question[:60]}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@700&display=swap" rel="stylesheet">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0F1117; color: #E8EAF6; font-family: Inter, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }}
h1 {{ font-family: 'Playfair Display', serif; color: #F5A623; margin-bottom: 8px; }}
.question {{ background: #1A1D27; border: 1px solid #2D3147; border-left: 4px solid #4F8EF7; padding: 20px; border-radius: 8px; margin: 20px 0; font-size: 18px; }}
.answer {{ background: #1A1D27; border: 1px solid #2D3147; padding: 24px; border-radius: 8px; margin: 20px 0; line-height: 1.7; }}
.answer h3 {{ color: #4F8EF7; margin: 16px 0 8px; }}
.answer p {{ margin: 8px 0; color: #9BA3BF; }}
.answer ul {{ padding-left: 20px; color: #9BA3BF; }}
.answer li {{ margin: 4px 0; }}
.meta {{ color: #5C6480; font-size: 12px; margin-top: 24px; }}
</style>
</head>
<body>
<h1>Research Q&A</h1>
<div class="question"><strong>Q:</strong> {question}</div>
<div class="answer">{answer_html}</div>
<div class="meta">Generated by Arxiv Intel · {dt.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
</body>
</html>"""
                with open(saved_path, "w", encoding="utf-8") as f:
                    f.write(ask_html_content)
            except Exception as save_err:
                logger.warning("Could not save ask report: %s", save_err)
                saved_path = None

        except Exception as e:
            logger.error("Error in /ask POST: %s", e)
            error = f"Failed to get answer: {str(e)}"

        return templates.TemplateResponse("ask.html", {
            "request": request,
            "active_page": "ask",
            "question": question,
            "answer": answer_html,
            "referenced_papers": referenced_papers,
            "error": error,
            "saved_path": saved_path,
        })

    # ── Professors ────────────────────────────────────────────────────────────

    @app.get("/professors", response_class=HTMLResponse)
    async def professors_list(request: Request, q: str = ""):
        if q:
            prof = db.get_professor(q)
            professors = [prof] if prof else []
        else:
            professors = db.list_professors()

        return templates.TemplateResponse("professors.html", {
            "request": request,
            "active_page": "professors",
            "professors": professors,
            "query": q,
        })

    # ---------------------------------------------------------------------------
    # API endpoints
    # ---------------------------------------------------------------------------

    @app.get("/api/stats")
    async def api_stats():
        stats = db.get_stats()
        return JSONResponse(content=stats)

    @app.get("/api/papers")
    async def api_papers(
        q: str = "",
        limit: int = 50,
        min_score: float = 0.0,
    ):
        if q:
            papers = db.search_papers(q, limit=limit)
        else:
            papers = db.get_recent_papers(days=30, limit=limit)

        if min_score > 0:
            papers = [p for p in papers if p.overall_score >= min_score]

        return JSONResponse(content=[p.to_dict() for p in papers])

    @app.get("/api/directions")
    async def api_directions():
        directions = db.list_directions()
        return JSONResponse(content=[d.to_dict() for d in directions])

    # ---------------------------------------------------------------------------
    # 404 handler
    # ---------------------------------------------------------------------------

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return templates.TemplateResponse("404.html", {
            "request": request,
            "active_page": "",
            "message": "The page you're looking for doesn't exist.",
        }, status_code=404)

    return app
