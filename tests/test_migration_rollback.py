import sqlite3
from datetime import datetime

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from server.core.database import OAuthToken, apply_migrations, rollback_migrations


def test_migration_rollback_requires_backup_override_preserves_oauth_and_can_upgrade(tmp_path):
    source_path = tmp_path / "migration-source.sqlite"
    backup_path = tmp_path / "migration-backup.sqlite"
    target_engine = create_engine(f"sqlite:///{source_path}")
    OAuthToken.__table__.create(target_engine)
    local_sessions = sessionmaker(bind=target_engine, expire_on_commit=False)
    with local_sessions.begin() as session:
        session.add(OAuthToken(
            platform="youtube",
            access_token="oauth-access-fixture",
            refresh_token="oauth-refresh-fixture",
            expires_at=None,
            created_at=datetime(2026, 10, 11),
            updated_at=datetime(2026, 10, 11),
        ))

    apply_migrations(target_engine)
    with target_engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO projects(id, title, kind, status, config_json, created_at, updated_at) "
            "VALUES ('project-fixture', 'Backup target', 'quick_creator', 'completed', '{}', "
            "'2026-10-11 00:00:00', '2026-10-11 00:00:00')"
        ))

    # Validate a separate SQLite backup before using the explicit data-loss flag.
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("SELECT title FROM projects WHERE id='project-fixture'").fetchone() == ("Backup target",)
        assert backup.execute("SELECT access_token FROM oauth_tokens WHERE platform='youtube'").fetchone() == ("oauth-access-fixture",)

    with pytest.raises(RuntimeError, match="populated table 'projects'"):
        rollback_migrations(target_engine)
    with target_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE version=1")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM projects")).scalar_one() == 1

    assert rollback_migrations(target_engine, allow_data_loss=True) == [1]
    tables_after_down = set(inspect(target_engine).get_table_names())
    assert not {"projects", "media", "jobs", "job_steps", "job_events"} & tables_after_down
    assert "oauth_tokens" in tables_after_down
    with target_engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE version=1")).scalar_one() == 0
        assert connection.execute(text("SELECT access_token FROM oauth_tokens WHERE platform='youtube'")).scalar_one() == "oauth-access-fixture"

    # A subsequent normal startup must see the missing version row and reapply it.
    apply_migrations(target_engine)
    tables_after_up = set(inspect(target_engine).get_table_names())
    assert {"projects", "media", "jobs", "job_steps", "job_events"} <= tables_after_up
    with target_engine.connect() as connection:
        assert connection.execute(text("SELECT version FROM schema_migrations")).scalar_one() == 1
    with local_sessions() as session:
        oauth = session.query(OAuthToken).filter_by(platform="youtube").one()
    assert oauth.access_token == "oauth-access-fixture"

    target_engine.dispose()


def test_empty_migration_schema_can_be_rolled_back_without_override(tmp_path):
    target_engine = create_engine(f"sqlite:///{tmp_path / 'empty-schema.sqlite'}")
    apply_migrations(target_engine)

    assert rollback_migrations(target_engine, target_version=0) == [1]
    assert {"projects", "media", "jobs", "job_steps", "job_events"}.isdisjoint(
        inspect(target_engine).get_table_names()
    )
    target_engine.dispose()
