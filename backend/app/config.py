"""Application settings.

The repo-root ``.env`` is loaded once at import time with ``override=False`` so
values passed by docker ``--env-file`` (or the shell) always win.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

_TRUE = {"1", "true", "yes", "on"}


def load_env() -> None:
    """Load ``<repo>/.env`` without overriding variables already set."""
    env_file = REPO_ROOT / ".env"
    if env_file.is_file():
        load_dotenv(env_file, override=False)


load_env()


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path
    static_dir: Path
    llm_mock: bool
    openrouter_api_key: str
    opendart_api_key: str
    snapshot_interval: float = 60.0

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            db_path=Path(env.get("DB_PATH") or REPO_ROOT / "db" / "finally.db"),
            static_dir=Path(env.get("STATIC_DIR") or BACKEND_DIR / "static"),
            llm_mock=env.get("LLM_MOCK", "").strip().lower() in _TRUE,
            openrouter_api_key=env.get("OPENROUTER_API_KEY", "").strip(),
            opendart_api_key=env.get("OPENDART_API_KEY", "").strip(),
        )
