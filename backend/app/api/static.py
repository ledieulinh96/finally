"""Serve the Next.js static export with an SPA fallback.

Mounted last so every ``/api/*`` route wins. Unknown ``/api/*`` paths still 404
as JSON instead of returning ``index.html``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def mount_static(app: FastAPI, static_dir: Path) -> bool:
    """Register the static catch-all route. Returns False if ``static_dir`` is missing."""
    root = static_dir.resolve()
    index = root / "index.html"
    if not root.is_dir() or not index.is_file():
        return False

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_relative_to(root):
                if candidate.is_file():
                    return FileResponse(candidate)
                # Next.js export emits /foo.html or /foo/index.html
                html = candidate.with_name(candidate.name + ".html")
                if html.is_file():
                    return FileResponse(html)
                nested = candidate / "index.html"
                if nested.is_file():
                    return FileResponse(nested)
        return FileResponse(index)

    return True
