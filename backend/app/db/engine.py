"""Database engine and sessions.

SQLite settings applied on every connection:
- WAL journal: the UI can read while a background run is writing.
- foreign_keys=ON: SQLite ignores foreign keys unless asked.
- busy_timeout: a writer waits briefly for a lock instead of failing immediately.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


def init_db(url: str | None = None) -> Engine:
    """(Re)configure the engine and create tables. Called at startup, and by tests with a temp DB."""
    global _engine, _SessionLocal
    from app.db import models  # noqa: F401  (registers tables on Base.metadata)

    url = url or get_settings().database_url
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        event.listen(_engine, "connect", _sqlite_pragmas)
    models.Base.metadata.create_all(_engine)
    _add_missing_columns(_engine, models.Base.metadata)
    _SessionLocal = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def _add_missing_columns(engine: Engine, metadata) -> list[str]:
    """Forward-only upgrade for an existing database: add new *nullable* columns that create_all can't add to
    existing tables. Anything more (renames, new constraints) is out of scope — that is what Alembic is for in
    production. Returns the columns added."""
    insp = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing and col.nullable:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" '
                                      f'{col.type.compile(engine.dialect)}'))
                    added.append(f"{table.name}.{col.name}")
    return added


def get_engine() -> Engine:
    return _engine or init_db()


@contextmanager
def session_scope() -> Iterator[Session]:
    """One unit of work: commit on success, roll back on any error."""
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
