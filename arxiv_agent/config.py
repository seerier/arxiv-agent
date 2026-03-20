"""Configuration loader for the Arxiv Intelligence System.

Usage::

    from arxiv_agent.config import get_config

    cfg = get_config()
    print(cfg.claude_model)
    print(cfg.categories)

The config is loaded once and cached as a module-level singleton.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# ---------------------------------------------------------------------------
# Auto-load .env file from project root or ~/.arxiv_agent.env
# This means users never need to manually export ANTHROPIC_API_KEY.
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    """Load API key from .env file if not already set in environment."""
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return  # already set, nothing to do

    # Search locations in priority order
    _project_root = Path(__file__).parent.parent
    candidates = [
        _project_root / ".env",                    # project root .env
        Path.home() / ".arxiv_agent.env",          # user home fallback
    ]
    for env_file in candidates:
        if env_file.exists():
            try:
                with open(env_file) as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = val
            except OSError:
                pass
            break

_load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults — used when config.yaml is absent or a key is missing
# ---------------------------------------------------------------------------

_DEFAULTS: Dict[str, Any] = {
    "categories": ["cs.AI", "cs.LG", "cs.CV", "cs.GR", "eess.IV"],
    "custom_queries": [
        "event camera",
        "neuromorphic",
        "DVS",
        "dynamic vision sensor",
    ],
    "max_papers_per_run": 200,
    "schedule_time": "08:00",
    "claude_model": "claude-sonnet-4-6",
    "report_dir": "./reports",
    "db_path": "./data/papers.db",
    "top_papers_in_digest": 5,
    "report_max_words": 800,
    "sources": {
        "arxiv": True,
        "paperswithcode": True,
        "semantic_scholar": True,
    },
    "log_level": "INFO",
}

# ---------------------------------------------------------------------------
# Config class
# ---------------------------------------------------------------------------


class ConfigLoader:
    """Loads and validates the YAML configuration file.

    Parameters
    ----------
    config_path:
        Path to ``config.yaml``.  Defaults to ``<project_root>/config.yaml``
        where the project root is determined relative to this file's location.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        if config_path is None:
            # Resolve relative to the package directory (one level up from here)
            config_path = Path(__file__).parent.parent / "config.yaml"

        self._config_path = Path(config_path)
        self._raw: Dict[str, Any] = {}
        self._load()
        self._validate()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read YAML file, falling back to defaults on any error."""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as fh:
                    loaded = yaml.safe_load(fh) or {}
                if not isinstance(loaded, dict):
                    logger.warning(
                        "config.yaml did not parse to a dict; using defaults."
                    )
                    loaded = {}
                # Merge: defaults first, then override with file values
                self._raw = {**_DEFAULTS, **loaded}
                # Deep-merge the 'sources' sub-dict
                if "sources" in loaded and isinstance(loaded["sources"], dict):
                    self._raw["sources"] = {
                        **_DEFAULTS["sources"],
                        **loaded["sources"],
                    }
                logger.debug("Loaded config from %s", self._config_path)
            except yaml.YAMLError as exc:
                logger.error(
                    "Failed to parse %s: %s — falling back to defaults.",
                    self._config_path,
                    exc,
                )
                self._raw = dict(_DEFAULTS)
        else:
            logger.warning(
                "Config file not found at %s — using built-in defaults.",
                self._config_path,
            )
            self._raw = dict(_DEFAULTS)

    def _validate(self) -> None:
        """Validate required runtime values.

        Raises
        ------
        EnvironmentError
            If ``ANTHROPIC_API_KEY`` is not set in the environment.
        """
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Please export it before running the Arxiv Intelligence System."
            )

    # ------------------------------------------------------------------
    # Typed accessors
    # ------------------------------------------------------------------

    @property
    def categories(self) -> List[str]:
        """ArXiv category codes to monitor (e.g. ``cs.AI``)."""
        value = self._raw.get("categories", _DEFAULTS["categories"])
        return list(value) if value else list(_DEFAULTS["categories"])

    @property
    def custom_queries(self) -> List[str]:
        """Free-text search queries appended to the arxiv fetch."""
        value = self._raw.get("custom_queries", _DEFAULTS["custom_queries"])
        return list(value) if value else list(_DEFAULTS["custom_queries"])

    @property
    def max_papers_per_run(self) -> int:
        """Maximum number of papers to ingest in a single fetch cycle."""
        return int(self._raw.get("max_papers_per_run", _DEFAULTS["max_papers_per_run"]))

    @property
    def schedule_time(self) -> str:
        """Daily run time in ``HH:MM`` 24-hour format."""
        return str(self._raw.get("schedule_time", _DEFAULTS["schedule_time"]))

    @property
    def schedule_hour(self) -> int:
        """Hour component of ``schedule_time``."""
        return int(self.schedule_time.split(":")[0])

    @property
    def schedule_minute(self) -> int:
        """Minute component of ``schedule_time``."""
        return int(self.schedule_time.split(":")[1])

    @property
    def claude_model(self) -> str:
        """Claude model identifier to use for analysis."""
        return str(self._raw.get("claude_model", _DEFAULTS["claude_model"]))

    @property
    def anthropic_api_key(self) -> str:
        """Anthropic API key from the environment (never stored in config)."""
        return os.environ["ANTHROPIC_API_KEY"].strip()

    @property
    def _project_root(self) -> Path:
        """Absolute path to the project root (directory containing config.yaml)."""
        return self._config_path.parent.resolve()

    def _resolve_path(self, raw: str) -> Path:
        """Resolve a path from config: absolute paths are used as-is,
        relative paths are anchored to the project root (not the CWD)."""
        p = Path(raw).expanduser()
        if p.is_absolute():
            return p
        return (self._project_root / p).resolve()

    @property
    def report_dir(self) -> Path:
        """Directory where HTML reports are written."""
        raw = self._raw.get("report_dir", _DEFAULTS["report_dir"])
        return self._resolve_path(raw)

    @property
    def db_path(self) -> Path:
        """Path to the SQLite database file."""
        raw = self._raw.get("db_path", _DEFAULTS["db_path"])
        return self._resolve_path(raw)

    @property
    def top_papers_in_digest(self) -> int:
        """Number of top papers to feature in the daily digest."""
        return int(self._raw.get("top_papers_in_digest", _DEFAULTS["top_papers_in_digest"]))

    @property
    def report_max_words(self) -> int:
        """Target maximum word count for each generated report."""
        return int(self._raw.get("report_max_words", _DEFAULTS["report_max_words"]))

    @property
    def sources(self) -> Dict[str, bool]:
        """Enabled data sources mapping (name -> bool)."""
        raw = self._raw.get("sources", _DEFAULTS["sources"])
        if not isinstance(raw, dict):
            return dict(_DEFAULTS["sources"])
        return {k: bool(v) for k, v in raw.items()}

    @property
    def source_arxiv(self) -> bool:
        return self.sources.get("arxiv", True)

    @property
    def source_paperswithcode(self) -> bool:
        return self.sources.get("paperswithcode", True)

    @property
    def source_semantic_scholar(self) -> bool:
        return self.sources.get("semantic_scholar", True)

    @property
    def log_level(self) -> str:
        """Python logging level name (e.g. ``INFO``, ``DEBUG``)."""
        return str(self._raw.get("log_level", _DEFAULTS["log_level"])).upper()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """Generic key access with fallback."""
        return self._raw.get(key, default)

    def as_dict(self) -> Dict[str, Any]:
        """Return a copy of the merged configuration as a plain dict."""
        return dict(self._raw)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ConfigLoader(config_path={self._config_path!r}, "
            f"claude_model={self.claude_model!r}, "
            f"categories={self.categories!r})"
        )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_config_instance: Optional[ConfigLoader] = None


def get_config(config_path: Optional[Path] = None) -> ConfigLoader:
    """Return the module-level ``ConfigLoader`` singleton.

    On the first call the config file is read from *config_path* (or the
    default location).  Subsequent calls return the cached instance regardless
    of any *config_path* argument.
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigLoader(config_path=config_path)
    return _config_instance


def reset_config() -> None:
    """Clear the cached config singleton.  Primarily useful in tests."""
    global _config_instance
    _config_instance = None
