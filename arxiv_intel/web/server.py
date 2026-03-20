"""Entry point for the Arxiv Intel web server."""

import uvicorn
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_server(host: str = "127.0.0.1", port: int = 8080, reload: bool = False) -> None:
    """Start the Arxiv Intel web application.

    Parameters
    ----------
    host:
        Hostname to bind to. Defaults to 127.0.0.1 (localhost only).
    port:
        Port to listen on. Defaults to 8080.
    reload:
        Enable auto-reload on code changes (development mode).
    """
    from arxiv_intel.config import get_config
    from arxiv_intel.database import Database
    from arxiv_intel.web.app import create_app

    cfg = get_config()
    db = Database(cfg.db_path)
    app = create_app(db, cfg)
    uvicorn.run(app, host=host, port=port, reload=reload)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Arxiv Intel Web Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port, reload=args.reload)
