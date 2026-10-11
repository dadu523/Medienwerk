"""SQLite persistence for projects, media, and durable jobs.

The database location can be isolated with ``MEDIENWERK_DATABASE_URL`` and
``MEDIENWERK_WORKSPACE``. Schema changes are applied by numbered, additive
migrations in ``server/migrations``; OAuth data remains in its original table.
"""

from __future__ import annotations

import importlib
import os
from datetime import datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


def _configured_workspace() -> Path:
    path = Path(os.environ.get("MEDIENWERK_WORKSPACE", "workspace")).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


WORKSPACE = _configured_workspace()
DATABASE_URL = os.environ.get(
    "MEDIENWERK_DATABASE_URL", f"sqlite:///{(WORKSPACE / 'app.db').as_posix()}"
)
if not DATABASE_URL.startswith("sqlite:"):
    raise RuntimeError("Medienwerk currently supports SQLite database URLs only")

# Create the parent for file-backed SQLite URLs, without changing :memory: URLs.
_sqlite_path = DATABASE_URL.removeprefix("sqlite:///")
if _sqlite_path and _sqlite_path != ":memory:":
    Path(_sqlite_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _enable_sqlite_safety(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
Base = declarative_base()


def utcnow() -> datetime:
    return datetime.utcnow()


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String, unique=True, index=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True)
    title = Column(String(500), nullable=False)
    kind = Column(String(80), nullable=False, index=True)
    status = Column(String(40), nullable=False, default="created", index=True)
    config_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    media = relationship("Media", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("Job", back_populates="project", cascade="all, delete-orphan")


class Media(Base):
    __tablename__ = "media"
    __table_args__ = (
        UniqueConstraint("origin", "origin_key", name="uq_media_origin_key"),
        Index("ix_media_project_created", "project_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(80), nullable=False, default="final", index=True)
    relative_path = Column(Text, nullable=False)
    storage_root = Column(Text, nullable=False)
    media_type = Column(String(80), nullable=False)
    metadata_json = Column(Text, nullable=False, default="{}")
    origin = Column(String(40), nullable=False, default="native", index=True)
    origin_key = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)

    project = relationship("Project", back_populates="media")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("workflow", "idempotency_key", name="uq_jobs_workflow_idempotency"),
        Index("ix_jobs_project_created", "project_id", "created_at"),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    workflow = Column(String(100), nullable=False)
    topic = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    step = Column(Text, nullable=False, default="Waiting in queue...")
    idempotency_key = Column(String(255), nullable=True)
    settings_json = Column(Text, nullable=False, default="{}")
    progress = Column(Float, nullable=False, default=0.0)
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="jobs")
    steps = relationship("JobStep", back_populates="job", cascade="all, delete-orphan")
    events = relationship("JobEvent", back_populates="job", cascade="all, delete-orphan")


class JobStep(Base):
    __tablename__ = "job_steps"
    __table_args__ = (UniqueConstraint("job_id", "step_id", name="uq_job_steps_job_step"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String(120), nullable=False)
    title = Column(String(300), nullable=True)
    status = Column(String(32), nullable=False, default="queued")
    progress = Column(Float, nullable=False, default=0.0)
    result_json = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    job = relationship("Job", back_populates="steps")


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "seq", name="uq_job_events_job_seq"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=utcnow)
    event_type = Column(String(80), nullable=False)
    payload_json = Column(Text, nullable=False, default="{}")

    job = relationship("Job", back_populates="events")


def apply_migrations(target_engine: Engine = engine) -> None:
    """Apply additive, ordered migrations exactly once per database."""
    with target_engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        ))
        applied = {row[0] for row in connection.execute(text("SELECT version FROM schema_migrations"))}
        for version, module_name in ((1, "server.migrations.0001_project_media_jobs"),):
            if version in applied:
                continue
            migration = importlib.import_module(module_name)
            migration.upgrade(connection)
            connection.execute(
                text("INSERT INTO schema_migrations(version, name, applied_at) VALUES (:v, :n, :t)"),
                {"v": version, "n": module_name.rsplit(".", 1)[-1], "t": utcnow().isoformat()},
            )
        # Keep the existing OAuth table available on fresh installs too. create_all
        # only creates a missing table and does not alter an existing one.
        OAuthToken.__table__.create(connection, checkfirst=True)


def rollback_migrations(
    target_engine: Engine = engine,
    target_version: int = 0,
    *,
    allow_data_loss: bool = False,
) -> list[int]:
    """Explicitly downgrade numbered migrations; never called during startup.

    By default, refuse to drop migration-owned tables if they contain rows. Set
    ``allow_data_loss=True`` only after taking and validating a separate backup.
    Existing OAuth storage is not owned by these migrations and is preserved.
    """
    migrations = {
        1: (
            "server.migrations.0001_project_media_jobs",
            ("job_events", "job_steps", "jobs", "media", "projects"),
        ),
    }
    if (
        isinstance(target_version, bool)
        or not isinstance(target_version, int)
        or target_version < 0
        or target_version not in {0, *migrations}
    ):
        raise ValueError(f"Unsupported target migration version: {target_version}")
    if not isinstance(allow_data_loss, bool):
        raise ValueError("allow_data_loss must be an explicit boolean")

    rolled_back: list[int] = []
    with target_engine.begin() as connection:
        has_version_table = connection.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        )).first()
        if not has_version_table:
            return rolled_back
        applied = [row[0] for row in connection.execute(
            text("SELECT version FROM schema_migrations ORDER BY version DESC")
        )]
        unknown = [version for version in applied if version not in migrations]
        if unknown:
            raise RuntimeError(f"Cannot roll back unknown migration version(s): {unknown}")

        for version in applied:
            if version <= target_version:
                continue
            module_name, owned_tables = migrations[version]
            if not allow_data_loss:
                for table in owned_tables:
                    present = connection.execute(text(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:name"
                    ), {"name": table}).first()
                    if present and connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one():
                        raise RuntimeError(
                            f"Migration {version} owns populated table '{table}'; "
                            "make and validate a backup, then pass allow_data_loss=True explicitly"
                        )

            # Delete the version row first so SQLite starts a write transaction
            # before the migration's DDL. A failure rolls both changes back.
            connection.execute(
                text("DELETE FROM schema_migrations WHERE version=:version"),
                {"version": version},
            )
            migration = importlib.import_module(module_name)
            migration.downgrade(connection)
            rolled_back.append(version)

    return rolled_back


def init_database() -> None:
    apply_migrations(engine)


def get_db() -> Iterator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session_scope():
    """Return a fresh context manager session for worker/service calls."""
    return SessionLocal.begin()
