import subprocess
import uuid
import wave
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from server.core import media_store, project_store
from server.core.database import Job, SessionLocal, apply_migrations, init_database


@pytest.fixture(autouse=True)
def initialize_isolated_catalog():
    # tests/conftest.py supplies MEDIENWERK_DATABASE_URL and MEDIENWERK_WORKSPACE
    # pointing at its disposable per-session directory.
    init_database()


def _wav(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000)
    return path


def _av_video(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "color=c=black:s=160x120:r=24:d=1", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1", "-shortest", "-c:v", "mpeg4",
        "-c:a", "aac", "-y", str(path),
    ], check=True, timeout=20)
    return path


def test_additive_migration_preserves_existing_oauth_tokens(tmp_path):
    target = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        with target.begin() as connection:
            connection.execute(text("""CREATE TABLE oauth_tokens (
                id INTEGER PRIMARY KEY, platform VARCHAR UNIQUE, access_token TEXT,
                refresh_token TEXT, expires_at DATETIME, created_at DATETIME,
                updated_at DATETIME
            )"""))
            connection.execute(text(
                "INSERT INTO oauth_tokens(platform, access_token) VALUES ('youtube', 'keep-me')"
            ))
        apply_migrations(target)
        with target.connect() as connection:
            assert connection.execute(text("SELECT access_token FROM oauth_tokens WHERE platform='youtube'")).scalar_one() == "keep-me"
            assert connection.execute(text("SELECT version FROM schema_migrations")).scalar_one() == 1
            tables = {row[0] for row in connection.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ))}
            assert {"projects", "media", "jobs", "job_steps", "job_events"} <= tables
    finally:
        target.dispose()


def test_duplicate_titles_have_distinct_projects_and_secrets_are_removed():
    first = project_store.create_project("Same title", "quick_creator", {"settings": {"VOICE": "Kore", "API_KEY": "hidden"}})
    second = project_store.create_project("Same title", "quick_creator")

    assert first["id"] != second["id"]
    assert first["config"] == {"settings": {"VOICE": "Kore"}}


def test_media_registration_probes_audio_and_resolves_only_registered_paths(tmp_path):
    project = project_store.create_project("Audio", "tools")
    audio_path = _wav(project_store.project_directory(project["id"]) / "source" / "voice.wav")

    media = media_store.register_media(project["id"], audio_path, role="source", kind="audio")

    assert media["media_type"].startswith("audio/")
    assert media["metadata"]["duration_seconds"] > 0
    assert media_store.resolve_media(media["id"]) == audio_path
    with pytest.raises(FileNotFoundError):
        media_store.resolve_media(str(uuid.uuid4()))


def test_final_audio_is_valid_but_final_video_requires_audio(tmp_path):
    project = project_store.create_project("Final media", "tools")
    audio_path = _wav(project_store.project_directory(project["id"]) / "output" / "final_tts.wav")
    audio = media_store.register_media(project["id"], audio_path, role="final", kind="audio")
    assert audio["media_type"].startswith("audio/")

    silent_video = project_store.project_directory(project["id"]) / "output" / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i",
        "color=c=black:s=160x120:r=24:d=1", "-an", "-c:v", "mpeg4", "-y", str(silent_video),
    ], check=True, timeout=20)
    with pytest.raises(media_store.MediaValidationError, match="audio streams"):
        media_store.register_media(project["id"], silent_video, role="final", kind="video")

    # Browser video generation and silent-source conversion legitimately have
    # no audio; each workflow states its expected streams explicitly.
    silent = media_store.register_media(
        project["id"], silent_video, role="final", kind="video", require_audio=False,
    )
    assert silent["media_type"].startswith("video/")

    with pytest.raises(media_store.MediaValidationError, match="Expected video"):
        media_store.register_media(project["id"], audio_path, role="source", kind="video")


def test_registration_rejects_invalid_files_symlinks_and_paths_outside_project(tmp_path):
    project = project_store.create_project("Boundaries", "tools")
    root = project_store.project_directory(project["id"])
    invalid = root / "source" / "fake.mp4"
    invalid.write_text("not media", encoding="utf-8")
    with pytest.raises(media_store.MediaValidationError):
        media_store.register_media(project["id"], invalid)

    outside = _wav(tmp_path / "outside.wav")
    with pytest.raises(media_store.MediaValidationError):
        media_store.register_media(project["id"], outside)

    link = root / "source" / "linked.wav"
    link.symlink_to(outside)
    with pytest.raises(media_store.MediaValidationError, match="Symlinks"):
        media_store.register_media(project["id"], link)


def test_import_is_idempotent_and_project_delete_keeps_legacy_file(tmp_path):
    legacy_root = tmp_path / "legacy"
    legacy_file = _wav(legacy_root / "existing" / "legacy.wav")
    project = project_store.create_project("Imported", "tools")
    key = "selected-import-file-key"

    first = media_store.register_media(
        project["id"], legacy_file, role="source", kind="audio",
        origin="imported", origin_key=key, import_root=legacy_root,
    )
    second = media_store.register_media(
        project["id"], legacy_file, role="source", kind="audio",
        origin="imported", origin_key=key, import_root=legacy_root,
    )

    assert first["id"] == second["id"]
    assert project_store.delete_project(project["id"]) is True
    assert legacy_file.is_file()


def test_legacy_import_preview_apply_is_idempotent_and_ignores_unknown_outputs(tmp_path):
    legacy_root = tmp_path / "legacy"
    final_file = _av_video(legacy_root / "old-topic" / "final_podcast_video.mp4")
    unknown = legacy_root / "old-topic" / "random_intermediate.mp4"
    unknown.write_bytes(b"not scanned")

    preview = media_store.preview_legacy_import([str(legacy_root)])
    first = media_store.apply_legacy_import([str(legacy_root)])
    second = media_store.apply_legacy_import([str(legacy_root)])

    assert preview["count"] == 1
    assert first["errors"] == [] and len(first["imported"]) == 1
    assert len(second["skipped"]) == 1 and second["errors"] == []
    assert project_store.get_summary()["projects"] >= 1
    assert final_file.is_file()


def test_project_delete_is_blocked_for_active_jobs_and_removes_native_media():
    project = project_store.create_project("Owned files", "tools")
    audio_path = _wav(project_store.project_directory(project["id"]) / "source" / "voice.wav")
    media_store.register_media(project["id"], audio_path)
    with SessionLocal.begin() as db:
        db.add(Job(id=str(uuid.uuid4()), project_id=project["id"], workflow="test", status="running"))

    with pytest.raises(ValueError, match="active job"):
        project_store.delete_project(project["id"])
    with pytest.raises(ValueError, match="active job"):
        media_store.unregister_media(media_store.list_media(project["id"])[0]["id"], project_id=project["id"])

    with SessionLocal.begin() as db:
        for job in db.query(Job).filter(Job.project_id == project["id"]).all():
            job.status = "completed"
    assert project_store.delete_project(project["id"]) is True
    assert not audio_path.exists()


def test_history_and_summary_are_based_on_registered_data():
    project = project_store.create_project("History sample", "quick_creator")
    before = project_store.get_summary()

    history = project_store.get_history()

    assert any(entry["id"] == project["id"] and entry["videos"] == [] and entry["scripts"] == [] for entry in history)
    assert project_store.get_summary()["projects"] == before["projects"]
