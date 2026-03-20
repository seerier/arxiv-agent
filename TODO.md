# Arxiv Intelligence System — Todo List

## Phase 1: Data Ingestion
- [ ] **Arxiv fetcher** — pull papers daily from:
  - `cs.AI`, `cs.LG`, `cs.CV` (computer vision)
  - `cs.GR` (graphics), `eess.IV` (image/video)
  - Custom query: `event camera OR neuromorphic OR DVS`
- [ ] **Web fetcher** — scrape from:
  - Papers With Code (new SOTA, benchmarks)
  - Semantic Scholar (citations, influence)
  - Google Scholar alerts (key authors/topics)
  - Conference sites: CVPR, ICCV, ECCV, SIGGRAPH, NeurIPS, ICLR, ICML
  - Twitter/X research accounts (viral papers)
  - YouTube: talks, lectures, course releases
- [ ] **Deduplication** — merge same paper from multiple sources
- [ ] **Storage** — SQLite DB with: title, authors, abstract, date, URL, source, category, citations, code availability

## Phase 2: Analysis Engine (Claude-powered)
- [ ] **Paper scoring** — rate each paper on: novelty, impact, reproducibility, relevance
- [ ] **Abstract summarizer** — 2-sentence TL;DR per paper
- [ ] **Method extractor** — identify the core technique/contribution
- [ ] **Breakthrough detector** — flag papers with SOTA claims, new benchmarks, paradigm shifts
- [ ] **Direction classifier** — tag each paper to a subfield/direction
- [ ] **Author tracker** — identify key professors, labs, institutions per direction

## Phase 3: Daily 5-Minute Report
- [ ] **Report generator** — structured Markdown/HTML digest:
  - Top 5 must-read papers today (scored + summarized)
  - 1 breakthrough highlight (if any)
  - Trending topics this week
  - New code releases / demos
- [ ] **Read-time enforcer** — keep report under 800 words (~5 min read)
- [ ] **Scheduler** — run every morning at a configurable time (cron)
- [ ] **Output options** — save to file, optionally email or push to Slack

## Phase 4: Knowledge Base (Living Document)
- [ ] **Important works** — curated list of seminal/landmark papers per subfield
- [ ] **Breakthroughs timeline** — chronological log of paradigm-shifting moments
- [ ] **Novel methods registry** — index of new techniques with one-line descriptions
- [ ] **Professor/researcher profiles** — name, institution, research focus, top papers, h-index
- [ ] **Conference calendar** — upcoming deadlines, talk schedules, proceedings links
- [ ] **Talks & courses** — YouTube lectures, Coursera/edX courses, workshop recordings
- [ ] **Direction analysis** — for each subfield (e.g. NeRF, event cameras, diffusion models):
  - What it is + history
  - Key papers + authors
  - Open problems
  - Emerging trend score (rising/stable/declining)
  - **Worthiness rating** — is this worth pursuing? why? what's the ceiling?
- [ ] **Emerging directions radar** — weekly update on what's gaining momentum
- [ ] **Dying directions log** — what's being abandoned and why

## Phase 5: CLI Interface
- [ ] `arxiv fetch` — manual trigger to fetch latest papers
- [ ] `arxiv report` — generate today's digest on demand
- [ ] `arxiv search <query>` — search the local DB
- [ ] `arxiv direction <name>` — pull up full analysis of a subfield
- [ ] `arxiv professor <name>` — profile lookup
- [ ] `arxiv knowledge` — browse the full knowledge base

## Phase 6: Config & Ops
- [ ] `config.yaml` — keywords, categories, schedule, output format, Claude model
- [ ] Incremental fetching — only process new papers since last run
- [ ] Rate limiting — respect arxiv API limits
- [ ] Logging — track fetch errors, analysis failures
