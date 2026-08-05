"""Engine and URL factories.

Two credentials, two capabilities: `codeatlas_migrator` owns DDL (Alembic),
`codeatlas_app` gets DML only. Passwords live in Windows Credential Manager
(service `codeatlas/db`) and are fetched via keyring at engine-build time —
never stored in files. `CODEATLAS_DB_URL` / `CODEATLAS_TEST_DB_URL` env vars
override for CI or non-Windows environments.
"""

from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

_HOST = os.environ.get("CODEATLAS_DB_HOST", "127.0.0.1")
_PORT = os.environ.get("CODEATLAS_DB_PORT", "5432")


@lru_cache(maxsize=8)
def _keyring_password(account: str) -> str:
    import keyring

    password = keyring.get_password("codeatlas/db", account)
    if password is None:
        raise RuntimeError(
            f"no password for codeatlas/db/{account} in Windows Credential Manager; "
            "run the PostgreSQL setup from docs/runbooks/setup.md"
        )
    return password


def _url(role: str, database: str) -> str:
    env_override = os.environ.get(
        "CODEATLAS_TEST_DB_URL" if database == "codeatlas_test" else "CODEATLAS_DB_URL"
    )
    if env_override:
        return env_override
    password = _keyring_password(role)
    return f"postgresql+psycopg://{role}:{password}@{_HOST}:{_PORT}/{database}"


def app_engine(test: bool = False) -> Engine:
    db = "codeatlas_test" if test else "codeatlas"
    return create_engine(_url("codeatlas_app", db), pool_pre_ping=True)


def migrator_engine(test: bool = False) -> Engine:
    db = "codeatlas_test" if test else "codeatlas"
    return create_engine(_url("codeatlas_migrator", db), pool_pre_ping=True)


def migrator_url(test: bool = False) -> str:
    return _url("codeatlas_migrator", "codeatlas_test" if test else "codeatlas")


def test_db_available() -> bool:
    """True iff the codeatlas_test database accepts connections."""
    try:
        engine = migrator_engine(test=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False
