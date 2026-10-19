"""Runtime settings of the explorer API, read from environment variables.

Units: ``retry_after_s`` is in seconds; the cache sizes are counts of entries.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

DEFAULT_DUCKDB_PATH: Final = ".dbt-local/oap.duckdb"
DEFAULT_WEB_DIST: Final = "apps/web/dist"
DEFAULT_DUCKDB_CONFIG: Final[Mapping[str, str]] = {
    "threads": "2",
    "memory_limit": "512MB",
    "access_mode": "READ_ONLY",
}


def _default_duckdb_config() -> Mapping[str, str]:
    """Return a fresh copy of the default DuckDB connection configuration.

    Returns:
        The ``threads``, ``memory_limit`` and ``access_mode`` settings as strings.
    """
    return dict(DEFAULT_DUCKDB_CONFIG)


@dataclass(frozen=True)
class ApiSettings:
    """Settings of the explorer API.

    Attributes:
        duckdb_path: DuckDB file the gold tables are read from (``OAP_DUCKDB_PATH``).
        web_dist: Directory of the built web app (``OAP_WEB_DIST``).
        retry_after_s: Seconds a client is told to wait when the writer holds the lock.
        quotes_cache: Number of underlyings whose quotes stay in memory.
        session_cache: Number of computed sessions that stay in memory.
        duckdb_config: DuckDB connection configuration; read-only, two threads, 512 MB.
        cors_origins: Allowed CORS origins (``OAP_API_CORS_ORIGINS``, comma separated);
            empty means no CORS middleware.
    """

    duckdb_path: Path = Path(DEFAULT_DUCKDB_PATH)
    web_dist: Path = Path(DEFAULT_WEB_DIST)
    retry_after_s: int = 15
    quotes_cache: int = 3
    session_cache: int = 256
    duckdb_config: Mapping[str, str] = field(default_factory=_default_duckdb_config)
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ApiSettings":
        """Build settings from environment variables.

        Args:
            env: Variables to read; ``os.environ`` when None.

        Returns:
            The settings, with defaults for every unset variable. Blank entries in the
            CORS list are ignored.
        """
        source = os.environ if env is None else env
        raw_origins = source.get("OAP_API_CORS_ORIGINS", "").split(",")
        return cls(
            duckdb_path=Path(source.get("OAP_DUCKDB_PATH", DEFAULT_DUCKDB_PATH)),
            web_dist=Path(source.get("OAP_WEB_DIST", DEFAULT_WEB_DIST)),
            cors_origins=tuple(o.strip() for o in raw_origins if o.strip()),
        )
