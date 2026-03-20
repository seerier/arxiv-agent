# Arxiv Intelligence System — User Guide

A comprehensive, AI-powered research monitoring platform for AI, Computer Vision, Graphics, and Event Camera research. Fetches papers automatically, analyzes them with Claude, and delivers a beautiful daily digest — plus an interactive tool for deep research field exploration.

---

## Table of Contents

1. [Setup](#1-setup)
2. [First Run](#2-first-run)
3. [Daily Workflow](#3-daily-workflow)
4. [All Commands](#4-all-commands)
   - [fetch](#arxiv-fetch) — Pull new papers
   - [embed](#arxiv-embed) — Build semantic search index
   - [report](#arxiv-report) — Generate digest (daily / weekly / monthly)
   - [survey](#arxiv-survey) — Deep survey of any research area
   - [search](#arxiv-search) — Semantic search your paper database
   - [direction](#arxiv-direction) — Deep-dive a research direction
   - [ask](#arxiv-ask) — Ask a research question
   - [professor](#arxiv-professor) — Look up a researcher
   - [knowledge](#arxiv-knowledge) — Browse the knowledge base
   - [schedule](#arxiv-schedule) — View scheduler status
   - [stats](#arxiv-stats) — Database statistics
5. [Understanding the Reports](#5-understanding-the-reports)
6. [Automating Daily Digests](#6-automating-daily-digests)
7. [Configuration](#7-configuration)
8. [Tips & Workflows](#8-tips--workflows)

---

## 1. Setup

### Prerequisites
- macOS (tested on macOS 15)
- Conda (`miniconda3` or `anaconda`)
- An Anthropic API key ([get one here](https://console.anthropic.com/))

### Install

The system runs inside the `claudecode` conda environment, which was created during setup. All dependencies are already installed.

**Set your API key** (required for all AI-powered features):

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

To make this permanent, add it to your `~/.zshrc`:

```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
source ~/.zshrc
```

### Activate the environment

```bash
conda activate claudecode
```

After activation, the `arxiv` command is available globally.

### Project location

```
/Users/zhao/AgentBase/CodeRepos/Arxiv/
├── config.yaml          ← All settings live here
├── data/papers.db       ← Your paper database (auto-created)
├── reports/             ← Generated HTML reports
│   ├── 2026-03-20-daily.html
│   ├── directions/
│   └── ask/
└── arxiv_agent/         ← Source code
```

Always run commands from the project root:

```bash
cd /Users/zhao/AgentBase/CodeRepos/Arxiv
arxiv <command>
```

---

## 2. First Run

The very first time, run these two commands to populate your database:

```bash
# Step 1: Fetch papers (takes 2–5 minutes)
arxiv fetch

# Step 2: Generate your first report
arxiv report
```

`fetch` will pull hundreds of recent papers from arxiv (cs.AI, cs.LG, cs.CV, cs.GR, eess.IV) plus event camera papers, analyze each one with Claude, and save everything locally. The HTML report opens automatically in your browser.

---

## 3. Daily Workflow

Your typical day with the system:

```
Morning:
  → System auto-fetches at 8:00 AM and emails/saves a report
  → Open the HTML report in your browser
  → Read 5 top papers + 1 breakthrough highlight (5 minutes)

When curious about a topic:
  → arxiv ask "what is the current state of X"
  → arxiv direction "neural rendering"

When looking up a researcher:
  → arxiv professor "Davide Scaramuzza"

Weekly:
  → arxiv knowledge           ← see all directions at a glance
  → arxiv knowledge --emerging ← what's rising fast?
```

---

## 4. All Commands

### `arxiv fetch`

Fetches latest papers from all sources and analyzes them with Claude.

```bash
# Fetch everything (last 1 day by default)
arxiv fetch

# Fetch since a specific date
arxiv fetch --since 2026-03-01

# Fetch only, skip AI analysis (faster)
arxiv fetch --no-analyze
```

**What it does:**
1. Pulls from arXiv API (cs.AI, cs.LG, cs.CV, cs.GR, eess.IV + event camera queries)
2. Pulls from Papers With Code (for code links and SOTA tracking)
3. Enriches with Semantic Scholar (citation counts)
4. Deduplicates across sources
5. Runs Claude analysis on each new paper: summary, scores, method extraction, breakthrough detection
6. Saves everything to `data/papers.db`
7. Automatically computes **semantic embeddings** for all new papers (enables AI-powered search)

**Terminal output example:**
```
┌──────────────────────────────────────────────┐
│  Fetch Complete                               │
│  New papers:     47                           │
│  Updated:        12                           │
│  Total fetched:  59                           │
│  Sources: arxiv, paperswithcode               │
└──────────────────────────────────────────────┘

Analyzing 47 new papers with Claude...
  ████████████████████ 47/47  Event Camera NeRF [2:34]

✓ Analysis complete.
```

---

### `arxiv embed`

Computes semantic embeddings for all papers in your database, enabling AI-powered (meaning-based) search. Run this once after your first `fetch`, and again after large backfills.

```bash
arxiv embed
```

**How it works:** Uses `sentence-transformers/all-MiniLM-L6-v2` (~90 MB, downloaded once) to embed each paper's title + abstract into a 384-dimensional vector. All future `search`, `survey`, and `ask` commands use cosine similarity over these vectors instead of keyword matching.

**After embedding is active**, queries like `"event based optical flow"` or `"neural path guiding"` find semantically related papers even if none contain those exact words.

> `arxiv fetch` automatically embeds new papers — you only need `arxiv embed` manually to backfill existing papers.

---

### `arxiv report`

Generates a research digest — daily, weekly, or monthly — in the terminal and as a beautiful HTML file.

```bash
# Today's digest (default)
arxiv report

# Last 7 days
arxiv report --period weekly

# Last 30 days
arxiv report --period monthly

# Terminal only, don't open browser
arxiv report --no-open
arxiv report --period weekly --no-open
```

**Saved to:**
- Daily: `reports/YYYY-MM-DD-daily.html`
- Weekly: `reports/YYYY-W12-weekly.html`
- Monthly: `reports/YYYY-MM-monthly.html`

**What you get:**

In the **terminal**: A Rich-formatted summary with score bars, a breakthrough callout, and trending topics.

As an **HTML file** at `reports/YYYY-MM-DD-daily.html`: A premium dark newsletter with:
- Top 5 papers of the day, each with:
  - Color-coded score badge (Novelty / Impact / Reproducibility / Relevance)
  - 2-sentence AI summary
  - Core method name
  - Key contributions
  - Links to paper and code (if available)
- A gold "Breakthrough" callout if a major paper was detected
- Trending topics with paper counts
- New code releases

**Reading time:** ~5 minutes. The report is self-contained — all links work offline for the metadata, and click through to arxiv/GitHub for full papers.

---

### `arxiv survey`

Generate a comprehensive academic-style survey of any research area — free-form, not limited to fixed keywords.

```bash
# Any natural language area description
arxiv survey "event cameras"
arxiv survey "event based optical flow"
arxiv survey "neural path guiding"
arxiv survey "diffusion models for video generation"
arxiv survey "spiking neural networks for robotics"

# Look back further in time
arxiv survey "3D gaussian splatting" --days 180

# Don't open browser
arxiv survey "neural rendering" --no-open
```

**What it does:**
1. Uses semantic search to find all relevant papers in your DB (up to 30 most relevant)
2. Sends them to Claude with a structured survey prompt
3. Claude writes a full survey with sections: Overview · History · Key Methods · Landmark Papers · State of the Art · Open Problems · Emerging Directions · Applications · Worthiness Assessment
4. Saves as `reports/survey-{area}.html`

**Tips:**
- The query is free-form — multi-word phrases and descriptive names all work
- Even with few local papers, Claude draws on its training knowledge to fill the survey
- Use `--days 180` or `--days 365` to widen the paper search window

---

### `arxiv search`

Search your local paper database using **semantic (AI) similarity** — finds conceptually related papers even without exact keyword matches.

```bash
# Semantic search — finds conceptually related papers
arxiv search "event based optical flow"
arxiv search "neural path guiding"
arxiv search "implicit neural representation for video"

# More results
arxiv search "diffusion model" --limit 50

# Only high-scoring papers
arxiv search "neural radiance field" --min-score 7.5
```

> Semantic search activates automatically once you run `arxiv embed`. Falls back to keyword matching otherwise.

**Output:** A Rich table with columns:
- Score bar (visual, e.g. `████████░░`)
- Title (clickable link to arxiv)
- Authors
- Date
- Research directions

---

### `arxiv direction`

Get a comprehensive AI-generated analysis of a research direction.

```bash
# Analyze a direction (generates HTML report)
arxiv direction "event cameras"
arxiv direction "neural rendering"
arxiv direction "diffusion models"
arxiv direction "3D gaussian splatting"

# Force re-analysis (refresh stale data)
arxiv direction "event cameras" --refresh

# Don't open browser
arxiv direction "event cameras" --no-open
```

**The HTML report includes:**
- **Status badge**: EMERGING / STABLE / DECLINING / DEAD (color-coded)
- **Worthiness score** (1–10) with full reasoning: *"Is this direction worth pursuing? Why? What's the ceiling?"*
- **Overview**: 2–3 paragraph description of the field
- **Milestones timeline**: Key papers and breakthroughs in chronological order
- **Key papers**: Top papers with links to arxiv
- **Open problems**: 5–7 unsolved challenges
- **Related directions**: Links to adjacent fields

**Saved to:** `reports/directions/{name}.html`

---

### `arxiv ask`

Ask any research question and get a comprehensive, paper-grounded AI answer.

```bash
# General state of a field
arxiv ask "What is the current state of event cameras for robotics?"

# Comparison questions
arxiv ask "How do 3D Gaussian Splatting and NeRF compare in 2026?"

# Emerging directions
arxiv ask "What are the most promising directions in computer vision for 2026?"

# Technical deep-dives
arxiv ask "What are the main challenges in training large vision-language models?"

# Career/research planning
arxiv ask "Is neuromorphic vision worth pursuing as a PhD topic?"
```

**What it does:**
1. Searches your local paper DB for the 20 most relevant papers
2. Sends them + the question to Claude as context
3. Claude writes a comprehensive, structured answer with paper citations
4. Displays in the terminal as formatted Markdown
5. Saves a beautiful HTML report at `reports/ask/{timestamp}-{slug}.html`

**The HTML report includes:**
- Your question prominently displayed
- Full structured answer with sections and citations like `[Smith et al., 2025]`
- Numbered reference list at the bottom with links to every cited paper

**Tip:** The more papers you have in your DB (from running `arxiv fetch` regularly), the better and more grounded the answers will be.

---

### `arxiv professor`

Look up a researcher's profile from your local database.

```bash
arxiv professor "Davide Scaramuzza"
arxiv professor "Yann LeCun"
arxiv professor "Andreas Geiger"
```

**Shows:**
- Name, institution, homepage
- Research focus areas
- h-index and citation count
- Top papers (with scores)
- Research directions

**Note:** Professor profiles are built automatically from papers in your DB. A researcher will appear here once they've authored papers that were fetched. You can enrich profiles by running `arxiv fetch` regularly.

---

### `arxiv knowledge`

Browse the full research knowledge base — all directions ranked by worthiness.

```bash
# Show all directions
arxiv knowledge

# Only emerging directions
arxiv knowledge --emerging

# Only declining directions
arxiv knowledge --dying
```

**Output:** A Rich table with:
- Direction name
- Status badge (EMERGING / STABLE / DECLINING / DEAD)
- Worthiness score bar
- Number of papers in DB

Use this as your weekly overview to see what's rising, what's stable, and what's dying.

---

### `arxiv schedule`

View the automatic scheduler configuration.

```bash
arxiv schedule
```

**Shows:**
- Configured schedule time (default: 08:00 daily)
- Last run time and result
- Next scheduled run
- Total papers and reports in DB

---

### `arxiv stats`

Show comprehensive database statistics.

```bash
arxiv stats
```

**Shows:**
- Total papers, analyzed papers, breakthrough count
- Papers per source (arxiv, Papers With Code, Semantic Scholar)
- Date range of papers in DB
- Directions and professors count
- Report count

---

## 5. Understanding the Reports

### Paper Scores

Every paper is scored by Claude across 4 dimensions (1–10 each):

| Score | What it measures |
|-------|-----------------|
| **Novelty** | How new/original is the idea? |
| **Impact** | How likely to influence the field? |
| **Reproducibility** | How easy to replicate? (code, clarity) |
| **Relevance** | How relevant to your focus areas? |

**Overall score** = 0.3 × Novelty + 0.3 × Impact + 0.2 × Reproducibility + 0.2 × Relevance

Score bars use block characters: `████████░░` = 8/10

Color coding:
- 🟡 **Gold** (≥ 8.0): Exceptional
- 🟢 **Green** (≥ 6.5): Good
- 🟡 **Yellow** (≥ 5.0): Average
- 🔴 **Red** (< 5.0): Low priority

### Breakthrough Detection

Claude flags papers as breakthroughs when they:
- Claim new SOTA on a major benchmark
- Introduce a paradigm-shifting method
- Open a new subfield
- Achieve a long-sought capability

Breakthrough papers appear in a **gold callout box** in the daily report.

### Direction Status

| Status | Meaning |
|--------|---------|
| 🟢 **EMERGING** | Paper count growing fast, new methods appearing |
| 🔵 **STABLE** | Steady activity, established field |
| 🟡 **DECLINING** | Fewer new papers, attention shifting away |
| 🔴 **DEAD** | Essentially no new work |

### Worthiness Score

The worthiness score (1–10) answers: *"Should you work in this direction?"* It considers:
- Is the field saturated or open?
- What's the ceiling — how much further can it go?
- Is industry/academia both interested?
- Are there clear open problems to work on?

The reasoning paragraph explains the score in detail.

---

## 6. Automating Daily Digests

The system includes a built-in scheduler. To run it as a persistent background daemon:

```bash
# Start the scheduler (runs daily at 08:00 by default)
conda activate claudecode
cd /Users/zhao/AgentBase/CodeRepos/Arxiv
/Users/zhao/miniconda3/envs/claudecode/bin/python -c "
from arxiv_agent.config import get_config
from arxiv_agent.database import Database
from arxiv_agent.fetcher.coordinator import FetchCoordinator
from arxiv_agent.analyzer.paper_analyzer import PaperAnalyzer
from arxiv_agent.reporter.daily_reporter import DailyReporter
from arxiv_agent.knowledge.knowledge_base import KnowledgeBase
from arxiv_agent.scheduler import ArxivScheduler
import pathlib, time

cfg = get_config()
db = Database(cfg.db_path)
coordinator = FetchCoordinator(cfg, db)
analyzer = PaperAnalyzer()
reporter = DailyReporter(cfg.report_dir)

scheduler = ArxivScheduler(cfg, db, coordinator, analyzer, reporter, None)
scheduler.start()
print('Scheduler started. Reports will be generated daily at 08:00.')
while True:
    time.sleep(60)
"
```

### Using launchd (macOS) for true automation

Create `~/Library/LaunchAgents/com.arxiv.intel.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.arxiv.intel</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/zhao/miniconda3/envs/claudecode/bin/python</string>
        <string>/Users/zhao/AgentBase/CodeRepos/Arxiv/run.py</string>
        <string>fetch</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>ANTHROPIC_API_KEY</key>
        <string>sk-ant-YOUR-KEY-HERE</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>/Users/zhao/AgentBase/CodeRepos/Arxiv</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/arxiv-intel.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/arxiv-intel-error.log</string>
</dict>
</plist>
```

Then load it:
```bash
launchctl load ~/Library/LaunchAgents/com.arxiv.intel.plist
```

---

## 7. Configuration

All settings are in `config.yaml`:

```yaml
# Which arxiv categories to track
categories:
  - cs.AI    # Artificial Intelligence
  - cs.LG    # Machine Learning
  - cs.CV    # Computer Vision
  - cs.GR    # Graphics
  - eess.IV  # Image & Video Processing

# Free-text search queries (for event cameras etc.)
custom_queries:
  - "event camera"
  - "neuromorphic"
  - "DVS"
  - "dynamic vision sensor"

# Max papers to fetch per run
max_papers_per_run: 200

# Daily digest schedule
schedule_time: "08:00"

# Claude model for analysis
claude_model: claude-sonnet-4-6

# Where to save HTML reports
report_dir: ./reports

# SQLite database path
db_path: ./data/papers.db

# How many papers in the daily digest
top_papers_in_digest: 5

# Word limit for digest (~800 = 5 min read)
report_max_words: 800

# Which sources to use
sources:
  arxiv: true
  paperswithcode: true
  semantic_scholar: true
```

### Adding new categories

To track additional arxiv categories, add them to `categories`:

```yaml
categories:
  - cs.AI
  - cs.LG
  - cs.CV
  - cs.GR
  - eess.IV
  - cs.RO    # Robotics
  - cs.MM    # Multimedia
```

### Adding new keywords

To track specific topics beyond categories:

```yaml
custom_queries:
  - "event camera"
  - "neuromorphic"
  - "DVS"
  - "dynamic vision sensor"
  - "Mamba vision"       # ← add new topics here
  - "state space model"
```

---

## 8. Tips & Workflows

### Build up your database first

The more papers you have locally, the better `ask` and `direction` work. Run:

```bash
# Fetch the last 30 days of papers
arxiv fetch --since 2026-02-20
```

Then re-run weekly or rely on the daily auto-fetch.

### Research a new field quickly

```bash
# 1. Get the overview
arxiv direction "3D gaussian splatting"

# 2. Ask a specific question
arxiv ask "What are the main limitations of 3D Gaussian Splatting and how are people addressing them?"

# 3. Find top papers
arxiv search "3D gaussian splatting" --min-score 8.0

# 4. Check who's leading the field
arxiv professor "Bernhard Kerbl"
```

### Evaluate whether to pursue a direction

```bash
arxiv direction "event camera SLAM" --refresh
# Read the "Worthiness" section carefully
# It tells you: score, ceiling, open problems, saturation level

arxiv ask "Is event camera SLAM worth pursuing for a PhD? What are the open problems?"
```

### Weekly research review

```bash
# Monday morning
arxiv fetch                          # Get the latest
arxiv knowledge                      # What's the landscape?
arxiv knowledge --emerging           # What should I pay attention to?
arxiv report                         # Read this week's digest
```

### Find papers with code

```bash
# Search and filter by availability
arxiv search "event camera" | grep "code"
# Papers with code links are marked [CODE] in the report
```

### All reports are saved

Every HTML report is saved permanently:
- Daily digests: `reports/YYYY-MM-DD-daily.html`
- Direction analyses: `reports/directions/{name}.html`
- Q&A sessions: `reports/ask/{timestamp}-{query}.html`

Open any past report in your browser:
```bash
open reports/2026-03-20-daily.html
open "reports/directions/event-cameras.html"
```

---

## Quick Reference

```bash
# Setup
conda activate claudecode
cd /Users/zhao/AgentBase/CodeRepos/Arxiv
export ANTHROPIC_API_KEY="sk-ant-..."

# Setup (run once)
arxiv embed              # Build semantic search index

# Daily
arxiv fetch              # Pull new papers + analyze + embed
arxiv report             # Today's digest
arxiv report --period weekly    # Last 7 days
arxiv report --period monthly   # Last 30 days

# Research
arxiv search "query"                     # Semantic paper search
arxiv survey "area name"                 # Full area survey report
arxiv direction "field name"             # Field deep-dive + worthiness
arxiv ask "your question"                # Research Q&A
arxiv professor "Name"                   # Researcher profile

# Overview
arxiv knowledge                    # All directions
arxiv knowledge --emerging         # Rising fields
arxiv stats                        # DB overview

# Help
arxiv --help
arxiv <command> --help
```

---

*Built with Claude Sonnet 4.6 · Python 3.11 · claudecode conda env*
*Source: /Users/zhao/AgentBase/CodeRepos/Arxiv*
