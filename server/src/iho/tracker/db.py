"""Database session for the tracker. iho.tracker.service binds the engine to the server's SQLite file;
the routers only take a Session."""
from collections.abc import Iterator

from sqlalchemy.orm import Session, sessionmaker

SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
