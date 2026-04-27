from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:123@localhost:5432/postgres"


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    database_url: str
    host: str
    port: int
    reload: bool
    log_file: Path
    logger: str = "autoservice"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base_dir = Path(__file__).resolve().parent
    _load_dotenv(base_dir / ".env")
    _load_dotenv(base_dir.parent / ".env")

    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    reload = os.getenv("APP_RELOAD", "false").lower() in {"1", "true", "yes", "on"}
    log_file = Path(os.getenv("APP_LOG_FILE", str(base_dir / "logs" / "app.log")))

    return Settings(
        base_dir=base_dir,
        database_url=database_url,
        host=host,
        port=port,
        reload=reload,
        log_file=log_file,
    )
