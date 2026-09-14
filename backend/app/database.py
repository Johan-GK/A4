"""
Database engine/session setup.

Uses SQLite by default (zero external dependencies -- the whole system can be
handed to someone as a zip file and just run). The data-access layer is kept
thin (SQLAlchemy Core/ORM) so swapping the SQLALCHEMY_DATABASE_URL environment
variable for a Postgres/MySQL DSN is a configuration change, not a rewrite --
consistent with the specification's stack-agnostic intent (Section 2.2).
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "pcts.db")
os.makedirs(os.path.dirname(DEFAULT_DB_PATH), exist_ok=True)

SQLALCHEMY_DATABASE_URL = os.environ.get(
    "PCTS_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}"
)

connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args, future=True)

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        # Foreign keys off by default in SQLite -- turn them on.
        # WAL mode gives better concurrent read/write behaviour, which matters
        # because Section 25 requires genuine transactional isolation for the
        # reservation/check-and-act sequence, not just a single-writer file lock.
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
