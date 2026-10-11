"""Initial additive project/media/job schema; leaves existing OAuth data intact."""

from sqlalchemy import text


def upgrade(connection):
    statements = (
        """CREATE TABLE IF NOT EXISTS projects (
            id VARCHAR(36) PRIMARY KEY,
            title VARCHAR(500) NOT NULL,
            kind VARCHAR(80) NOT NULL,
            status VARCHAR(40) NOT NULL DEFAULT 'created',
            config_json TEXT NOT NULL DEFAULT '{}',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS ix_projects_kind ON projects(kind)",
        "CREATE INDEX IF NOT EXISTS ix_projects_status ON projects(status)",
        "CREATE INDEX IF NOT EXISTS ix_projects_created_at ON projects(created_at)",
        """CREATE TABLE IF NOT EXISTS media (
            id VARCHAR(36) PRIMARY KEY,
            project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            role VARCHAR(80) NOT NULL DEFAULT 'final',
            relative_path TEXT NOT NULL,
            storage_root TEXT NOT NULL,
            media_type VARCHAR(80) NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            origin VARCHAR(40) NOT NULL DEFAULT 'native',
            origin_key TEXT NOT NULL,
            created_at DATETIME NOT NULL,
            CONSTRAINT uq_media_origin_key UNIQUE(origin, origin_key)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_media_role ON media(role)",
        "CREATE INDEX IF NOT EXISTS ix_media_origin ON media(origin)",
        "CREATE INDEX IF NOT EXISTS ix_media_created_at ON media(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_media_project_created ON media(project_id, created_at)",
        """CREATE TABLE IF NOT EXISTS jobs (
            id VARCHAR(36) PRIMARY KEY,
            project_id VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            workflow VARCHAR(100) NOT NULL,
            topic TEXT,
            status VARCHAR(32) NOT NULL DEFAULT 'queued',
            step TEXT NOT NULL DEFAULT 'Waiting in queue...',
            idempotency_key VARCHAR(255),
            settings_json TEXT NOT NULL DEFAULT '{}',
            progress FLOAT NOT NULL DEFAULT 0,
            result_json TEXT,
            error TEXT,
            created_at DATETIME NOT NULL,
            started_at DATETIME,
            finished_at DATETIME,
            CONSTRAINT uq_jobs_workflow_idempotency UNIQUE(workflow, idempotency_key)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status)",
        "CREATE INDEX IF NOT EXISTS ix_jobs_created_at ON jobs(created_at)",
        "CREATE INDEX IF NOT EXISTS ix_jobs_project_created ON jobs(project_id, created_at)",
        """CREATE TABLE IF NOT EXISTS job_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            step_id VARCHAR(120) NOT NULL,
            title VARCHAR(300),
            status VARCHAR(32) NOT NULL DEFAULT 'queued',
            progress FLOAT NOT NULL DEFAULT 0,
            result_json TEXT,
            error TEXT,
            started_at DATETIME,
            finished_at DATETIME,
            CONSTRAINT uq_job_steps_job_step UNIQUE(job_id, step_id)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_job_steps_job_id ON job_steps(job_id)",
        """CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            occurred_at DATETIME NOT NULL,
            event_type VARCHAR(80) NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            CONSTRAINT uq_job_events_job_seq UNIQUE(job_id, seq)
        )""",
        "CREATE INDEX IF NOT EXISTS ix_job_events_job_id ON job_events(job_id)",
    )
    for statement in statements:
        connection.execute(text(statement))


def downgrade(connection):
    """Drop only tables introduced by this migration; never touch oauth_tokens."""
    for table in ("job_events", "job_steps", "jobs", "media", "projects"):
        connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
